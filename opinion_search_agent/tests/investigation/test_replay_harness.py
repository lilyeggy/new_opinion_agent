"""Frozen-material replay harness: manifest, adapters and loop wiring."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opinion_search.domain.investigation.models import (
    Decision, Evidence, FinishDecision, FindingProposal, InvestigationRequest, Issue, IssueAssessment,
    ReadDecision, ReflectDecision, ReviewDecision, ReviewItem, ReviewResult, SearchDecision,
    State, utcnow,
)
from opinion_search.domain.investigation.engine import Validator
from opinion_search.investigation.replay import (
    ReplayReaderAdapter, ReplaySearchAdapter, load_replay_case, run_replay_case,
    run_replay_update_case,
)
from opinion_search.investigation.service import ConsolidationValidator, InvestigationRun, build_loop
from opinion_search.investigation.storage import Budget
from opinion_search.runtime.cancellation import EventCancellationSignal
from opinion_search.runtime.loop import NoopLoopHook


class _FrozenModel:
    def __init__(self):
        self.calls = 0

    async def decide(self, context):
        self.calls += 1
        sections = {section.section_id: section.content for section in context.sections}
        questions = json.loads(sections.get("memory.questions", "{}"))
        progress = json.loads(sections.get("memory.progress", "{}"))
        findings = json.loads(sections.get("memory.findings", "[]"))
        issues = questions.get("issues", [])
        issue_ids = [issue["issue_id"] for issue in issues]
        searches = progress.get("searches", [])
        read_attempts = progress.get("read_attempts", [])

        if not searches:
            return SearchDecision(issue_id=issue_ids[0], query="事件 调整", purpose="original")
        urls = ["https://example.org/frozen-official", "https://example.org/frozen-report"]
        unread = [url for url in urls if url not in read_attempts]
        if unread:
            return ReadDecision(issue_id=issue_ids[0], url=unread[0], focus="事件 回应", role="original")

        active = [finding for finding in findings if finding.get("active", True)]
        if not active:
            evidence = [json.loads(content) for section_id, content in sections.items()
                        if section_id.startswith("evidence.")]
            proposals = []
            assessments = []
            for index, issue_id in enumerate(issue_ids):
                evidence_id = evidence[index % len(evidence)]["evidence_id"]
                proposals.append(FindingProposal(issue_id=issue_id,
                                                 text="根据冻结材料，该问题已有可核查说明。",
                                                 kind="fact", evidence_ids=(evidence_id,)))
                assessments.append(IssueAssessment(issue_id=issue_id, status="answered",
                                                   reason="冻结材料已说明。", evidence_ids=(evidence_id,)))
            return ReflectDecision(findings=tuple(proposals), assessments=tuple(assessments), reason="冻结材料整理")

        pending = [finding["finding_id"] for finding in active if finding.get("review") != "supported"]
        if pending:
            return ReviewDecision(finding_ids=tuple(pending))
        return FinishDecision(conclusion_ids=tuple(finding["finding_id"] for finding in active))


class _FrozenReviewer:
    async def decide(self, context):
        sections = {section.section_id: section.content for section in context.sections}
        payload = json.loads(sections["input.material"])
        return ReviewResult(items=tuple(ReviewItem(finding_id=finding["finding_id"], verdict="supported",
                                                   reason="测试审查：冻结材料支持该说明。")
                                         for finding in payload["findings"]))


def _manifest(root: Path) -> Path:
    content = "官方公告：事件已经作出调整，并提供工作日替代安排。\n\n报道采访：受影响人员希望保留晚班时段，回应仍在补充。"
    snapshot = root / "official.txt"
    snapshot.write_text(content, encoding="utf-8")
    manifest = {
        "case_id": "harness-case",
        "request_question": "冻结材料事件调查",
        "materials": [
            {"url": "https://example.org/frozen-official", "title": "冻结公告", "snapshot_path": "official.txt",
             "sha256": sha256(content.encode("utf-8")).hexdigest(), "role": "original",
             "published_at": "2026-01-01T00:00:00+00:00"},
            {"url": "https://example.org/frozen-report", "title": "冻结报道", "content": "报道采访：受影响人员希望保留晚班时段。",
             "role": "reporting"},
        ],
    }
    path = root / "case.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_replay_case_checks_snapshot_hash(tmp_path):
    manifest = _manifest(tmp_path)
    case = load_replay_case(manifest)
    assert case.case_id == "harness-case"
    assert len(case.materials) == 2
    assert "替代安排" in case.materials[0].content

    broken = json.loads(manifest.read_text(encoding="utf-8"))
    broken["materials"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_replay_case(manifest)


def test_model_replay_requires_every_material_to_be_a_hashed_snapshot(tmp_path):
    manifest = _manifest(tmp_path)
    with pytest.raises(ValueError, match="snapshot_path and sha256"):
        load_replay_case(manifest, require_snapshot_hashes=True)


def test_model_replay_cancels_the_background_run_on_timeout(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for index, item in enumerate(data["materials"]):
        content = item.pop("content", None)
        if content is not None:
            snapshot = tmp_path / f"material-{index}.txt"
            snapshot.write_text(content, encoding="utf-8")
            item["snapshot_path"] = snapshot.name
            item["sha256"] = sha256(content.encode("utf-8")).hexdigest()
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    class HangingManager:
        instance = None

        def __init__(self, *_args, **_kwargs):
            self.cancelled = False
            self.workers = {}
            HangingManager.instance = self

        def create(self, _payload):
            return {"run_id": "a" * 32, "status": "running"}

        def snapshot(self, _run_id):
            return {"run_id": "a" * 32, "status": "running"}

        def cancel(self, _run_id):
            self.cancelled = True
            return {"run_id": "a" * 32, "status": "cancelled"}

    monkeypatch.setattr("opinion_search.investigation.replay.Manager", HangingManager)
    with pytest.raises(TimeoutError, match="terminal state"):
        run_replay_case(tmp_path / "run", manifest, config=SimpleNamespace(), timeout_seconds=0)
    assert HangingManager.instance.cancelled is True


def test_model_replay_update_uses_parent_path_and_cancels_on_timeout(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for index, item in enumerate(data["materials"]):
        content = item.pop("content", None)
        if content is not None:
            snapshot = tmp_path / f"update-material-{index}.txt"
            snapshot.write_text(content, encoding="utf-8")
            item["snapshot_path"] = snapshot.name
            item["sha256"] = sha256(content.encode("utf-8")).hexdigest()
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    class HangingManager:
        instance = None

        def __init__(self, *_args, **_kwargs):
            self.cancelled = False
            self.workers = {}
            self.created = None
            HangingManager.instance = self

        def create(self, payload, parent_id=None):
            self.created = (payload, parent_id)
            return {"run_id": "b" * 32, "status": "running"}

        def snapshot(self, _run_id):
            return {"run_id": "b" * 32, "status": "running"}

        def cancel(self, _run_id):
            self.cancelled = True
            return {"run_id": "b" * 32, "status": "cancelled"}

    monkeypatch.setattr("opinion_search.investigation.replay.Manager", HangingManager)
    with pytest.raises(TimeoutError, match="terminal state"):
        run_replay_update_case(tmp_path / "run", "a" * 32, manifest,
                               focus="只补查执行进展", config=SimpleNamespace(), timeout_seconds=0)
    assert HangingManager.instance.created == ({
        "focus": "只补查执行进展", "issue_ids": [], "finding_ids": []}, "a" * 32)
    assert HangingManager.instance.cancelled is True


def test_replay_adapters_only_serve_frozen_materials(tmp_path):
    case = load_replay_case(_manifest(tmp_path))
    search = ReplaySearchAdapter(case)
    reader = ReplayReaderAdapter(case)
    search_payload = asyncio.run(search.invoke(SimpleNamespace(arguments=SimpleNamespace(query="任意查询"))))
    assert len(search_payload.payload["items"]) == 2
    assert search_payload.payload["items"][0]["url"] == "https://example.org/frozen-official"

    read_payload = asyncio.run(reader.invoke(SimpleNamespace(arguments=SimpleNamespace(url=case.materials[0].url))))
    assert read_payload.payload["content"] == case.materials[0].content
    assert read_payload.payload["published_at"] == case.materials[0].published_at
    with pytest.raises(ValueError, match="only serves frozen case URLs"):
        asyncio.run(reader.invoke(SimpleNamespace(arguments=SimpleNamespace(url="https://example.org/other"))))


def test_build_loop_can_run_on_frozen_adapters_with_a_scripted_model(tmp_path):
    case = load_replay_case(_manifest(tmp_path))
    issues = tuple(Issue(issue_id=f"issue-{index}", question=question) for index, question in
                   enumerate(("发生了什么", "有哪些争议", "回应覆盖什么")))
    state = State(request=InvestigationRequest(question=case.request_question), subject="冻结材料事件",
                  cutoff=utcnow(), issues=issues)
    loop = build_loop(tmp_path / "run", tmp_path / "case", "offline", Budget(tmp_path / "budget.json"),
                      NoopLoopHook(), EventCancellationSignal(), config=None,
                      search_adapter=ReplaySearchAdapter(case), reader_adapter=ReplayReaderAdapter(case),
                      model=_FrozenModel(), reviewer=_FrozenReviewer(), model_name="frozen-test")
    result = asyncio.run(loop.run(InvestigationRun(run_id="frozen-run", domain_state=state)))
    assert result.status.value == "completed", result.stop_reason
    assert len(result.domain_state.sources) == 2
    assert len(result.domain_state.evidence) >= 1
    assert all(finding.active for finding in result.domain_state.findings)
    conclusion_ids = set(result.domain_state.conclusion_ids)
    assert conclusion_ids == {finding.finding_id for finding in result.domain_state.findings}
    assert {source.url for source in result.domain_state.sources} == {
        "https://example.org/frozen-official", "https://example.org/frozen-report"}


def test_live_config_controls_loop_limits_and_model_output_cap(tmp_path):
    from opinion_search.config import LiveConfig
    from opinion_search.investigation.service import live_model

    config = LiveConfig(
        model_api_key="model-key", brave_search_api_key="brave-key",
        max_steps=17, max_decision_attempts=3, model_max_output_tokens=16384,
    )
    budget = Budget(tmp_path / "budget.json")
    client = live_model(config, budget, Decision)
    assert client._max_output_tokens == 16384

    case = load_replay_case(_manifest(tmp_path))
    loop = build_loop(
        tmp_path / "configured-run", tmp_path / "configured-case", "offline", budget,
        NoopLoopHook(), EventCancellationSignal(), config=config,
        search_adapter=ReplaySearchAdapter(case), reader_adapter=ReplayReaderAdapter(case),
        model=_FrozenModel(), reviewer=_FrozenReviewer(), model_name="configured-test",
    )
    assert loop._max_steps == 17
    assert loop._max_decision_attempts == 3


def test_consolidation_validator_reserves_actions_for_review_then_finish(tmp_path):
    from opinion_search.domain.investigation.models import Finding, ReviewRecord, SourceVersion, finding_hash, uid

    source = SourceVersion(version_id="v1", url="https://example.org/rule",
                           final_url="https://example.org/rule", title="规则原文",
                           fetched_at=utcnow(), artifact_ref="artifact://rule", content_hash="hash")
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt="规则生效", start=0, end=4,
                        locator="Reader text chars 0:4")
    proposal = FindingProposal(issue_id="issue-0", text="规则已生效。", kind="fact",
                               evidence_ids=("e1",))
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", "reserve"))
    issues = tuple(Issue(issue_id=f"issue-{index}", question=f"问题{index}") for index in range(3))
    state = State(request=InvestigationRequest(question="规则调查"), subject="规则",
                  cutoff=utcnow(), issues=issues,
                  sources=(source,), evidence=(evidence,), findings=(finding,))
    budget = Budget(tmp_path / "reserve-budget.json", {"model": 6})
    for _ in range(4):
        budget.charge("model")
    guarded = ConsolidationValidator(Validator(), budget)

    empty = state.model_copy(update={"findings": ()})
    with pytest.raises(ValueError, match="requires synthesizing"):
        guarded.validate(empty, FinishDecision(conclusion_ids=()))
    guarded.validate(empty, ReflectDecision(findings=(proposal,), reason="先整理现有证据"))

    with pytest.raises(ValueError, match="requires reviewing"):
        guarded.validate(state, SearchDecision(issue_id="issue-0", query="继续搜索", purpose="original"))
    guarded.validate(state, ReviewDecision(finding_ids=(finding.finding_id,)))

    review = ReviewRecord(finding_id=finding.finding_id, verdict="supported", reason="原文支持",
                          finding_hash=finding_hash(finding), model="test", reviewed_at=utcnow())
    reviewed = state.model_copy(update={"reviews": (review,)})
    with pytest.raises(ValueError, match="finish now"):
        guarded.validate(reviewed, SearchDecision(issue_id="issue-0", query="再搜索", purpose="followup"))
    guarded.validate(reviewed, FinishDecision(conclusion_ids=(finding.finding_id,)))
