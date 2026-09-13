"""Frozen-material replay harness: manifest, adapters and loop wiring."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opinion_search.domain.investigation.models import (
    Evidence, FinishDecision, FindingProposal, InvestigationRequest, Issue, IssueAssessment,
    ReadDecision, ReflectDecision, ReviewDecision, ReviewItem, ReviewResult, SearchDecision,
    State, utcnow,
)
from opinion_search.investigation.replay import (
    ReplayReaderAdapter, ReplaySearchAdapter, load_replay_case,
)
from opinion_search.investigation.service import InvestigationRun, build_loop
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
