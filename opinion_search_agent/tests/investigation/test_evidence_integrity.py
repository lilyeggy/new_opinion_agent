"""R08: evidence must be re-verifiable against the immutable source artifact."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from opinion_search.domain.investigation.models import Evidence
from opinion_search.investigation.service import PROFILE, InvestigationRun
from opinion_search.investigation.storage import Corpus, verify_evidence, verify_state_integrity
from opinion_search.runtime.checkpoint import JsonCheckpointStore


def test_verify_evidence_rejects_forged_locator():
    verify_evidence(Evidence(evidence_id="e", version_id="v", excerpt="abc", start=2, end=5, locator="x"), "xxabcxx")
    with pytest.raises(ValueError):
        verify_evidence(Evidence(evidence_id="e", version_id="v", excerpt="abd", start=2, end=5, locator="x"), "xxabcxx")
    with pytest.raises(ValueError):
        verify_evidence(Evidence(evidence_id="e", version_id="v", excerpt="abc", start=2, end=6, locator="x"), "xxabcxx")


def test_corpus_locate_matches_source_text(tmp_path: Path):
    corpus = Corpus(tmp_path)
    content = ("开头无关内容。" * 50) + "\n\n夜班接驳车安排在工作日23时运行，涉及运营时段调整。\n\n" + ("结尾。")
    ref = asyncio.run(corpus.artifacts.put_text(content))
    from opinion_search.domain.investigation.models import SourceVersion, utcnow
    from hashlib import sha256
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="长文", fetched_at=utcnow(), artifact_ref=ref,
                           content_hash=sha256(content.encode()).hexdigest())
    evidence = asyncio.run(corpus.retrieve((source,), "接驳车 23时"))
    assert evidence
    for item in evidence:
        assert content[item.start:item.end] == item.excerpt


def test_committed_state_reverifies_against_artifacts(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    run_id = snapshot["run_id"]
    case_id = manager.load(run_id)["case_id"]
    run_root = manager.path(run_id)
    case_root = manager.root / "cases" / case_id

    checkpoint = JsonCheckpointStore(run_root / "run.json", InvestigationRun, execution_profile=PROFILE)
    state = asyncio.run(checkpoint.load()).domain_state
    corpus = Corpus(case_root)
    asyncio.run(verify_state_integrity(state, corpus))  # committed evidence is intact

    source = state.sources[0]
    digest = source.content_hash
    artifact = corpus.artifacts._root / f"{digest}.txt"  # noqa: SLF001 - integrity fixture
    artifact.write_text("被篡改的正文", encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(verify_state_integrity(state, corpus))


def test_unverifiable_read_degrades_to_a_tool_error_instead_of_crashing(tmp_path, monkeypatch):
    from pathlib import Path

    from opinion_search.domain.investigation.models import (
        Action, InvestigationRequest, Issue, ReadDecision, State, uid, utcnow,
    )
    from opinion_search.investigation.service import Executor
    from opinion_search.runtime.protocols import ActionRequest
    from opinion_search.tools.contracts import ToolResult

    url = "https://example.org/notice"
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("发生了什么", "争议是什么", "回应如何"))
    state = State(
        request=InvestigationRequest(question="某市公交夜班调整的争议"),
        subject="公交夜班调整",
        cutoff=utcnow(),
        issues=issues,
        candidates=({"url": url, "title": "公告", "issue_id": issues[0].issue_id},),
    )

    class _Checkpoint:
        path = tmp_path / "run.json"

        async def load(self):
            return type("Run", (), {"domain_state": state})()

    class _Tools:
        async def execute(self, call):
            return ToolResult(action_id=call.action_id, tool_name=call.tool_name, attempts=1,
                              payload={"url": url, "final_url": url, "title": "公告", "content": "正文内容。" * 40})

    executor = Executor(_Tools(), _Checkpoint(), None, None, "test-model")

    async def _boom(*args, **kwargs):
        raise ValueError("evidence excerpt does not match the stored source text")

    monkeypatch.setattr(Executor, "_read_material", _boom)

    decision = ReadDecision(issue_id=uid("issue", "发生了什么"), url=url, focus="起因", role="original")
    request = ActionRequest(run_id="r1", step_id="s1", attempt=1, action=Action(decision=decision, tool_name="read.web", arguments={"url": url}), action_id="a1")

    import asyncio

    observation = asyncio.run(executor.execute(request))

    assert observation.outcome is not None
    assert observation.outcome.kind is not None
    assert observation.evidence == ()


def test_evidence_positioning_survives_emoji_and_combining_marks():
    """W11: char offsets are Python code points, so astral/combining text must
    slice, verify and reassemble exactly; the page only renders pre-cut
    before/excerpt/after and never converts offsets to UTF-16 indices."""

    content = "公告🙂发布于广场前，e\u0301clair 仍在出售，末班车时间提前至22时，居民🌙表示关注。"
    excerpt = "末班车时间提前至22时"
    start = content.index(excerpt)
    item = Evidence(evidence_id="e", version_id="v", excerpt=excerpt,
                    start=start, end=start + len(excerpt), locator=f"Reader text chars {start}:{start + len(excerpt)}")
    verify_evidence(item, content)  # must not raise

    # the manager/export context cut reassembles the original text exactly
    before = content[max(0, item.start - 240):item.start]
    after = content[item.end:item.end + 240]
    assert before + item.excerpt + after == content
    assert "🙂" in before and "🌙" in after

    # a byte-flawed copy (emoji dropped) can never pass verification
    import pytest
    mangled = content.replace("🙂", "")
    with pytest.raises(ValueError):
        verify_evidence(item, mangled)


def test_evidence_endpoint_and_export_report_a_verification_failure(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    run_id = snapshot["run_id"]
    item = snapshot["report"]["evidence"][0]
    evidence_id = item["evidence_id"]
    source = next(source for source in snapshot["report"]["sources"]
                  if source["version_id"] == item["version_id"])

    located = manager.evidence(run_id, evidence_id)
    assert located["verification"]["status"] == "verified"

    case_root = manager.root / "cases" / manager.load(run_id)["case_id"]
    digest = source["artifact_ref"].rsplit("/", 1)[-1]
    artifact = case_root / "artifacts" / f"{digest}.txt"
    artifact.write_text("被替换的归档正文", encoding="utf-8")

    located = manager.evidence(run_id, evidence_id)
    assert located["verification"]["status"] == "unverified"
    assert located["verification"]["reason"]
    assert located["excerpt"] == item["excerpt"], "the saved report excerpt stays available for provenance"

    contexts = manager._evidence_context(run_id)  # noqa: SLF001 - export contract
    assert contexts[evidence_id]["status"] == "unverified"
    page = manager.page(run_id)
    start = page.find('id="cite-1"')
    end = page.find("</li>", start)
    entry = page[start:end]
    assert "未与归档正文比对" in entry
    assert "<mark>" not in entry
