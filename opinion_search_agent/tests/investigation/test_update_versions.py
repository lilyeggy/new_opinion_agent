"""D: version provenance, exclusion, recovery, and provider-failure honesty."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from opinion_search.domain.investigation.models import InvestigationRequest, Issue, SearchAttempt, State, uid, utcnow
from opinion_search.investigation.report import build_report, markdown
from opinion_search.investigation.service import PROFILE, InvestigationRun
from opinion_search.investigation.storage import CaseBusy, CaseLock, Corpus
from opinion_search.investigation.storage import verify_state_integrity
from opinion_search.runtime.checkpoint import JsonCheckpointStore


def _state(sources, evidence=(), *, searches=(), read_errors=()) -> State:
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("发生了什么", "争议是什么", "回应如何"))
    return State(request=InvestigationRequest(question="公交夜班调整的争议"), subject="公交夜班调整",
                 cutoff=utcnow(), issues=issues, sources=sources, evidence=evidence,
                 searches=searches, read_errors=read_errors)


def test_same_url_changed_text_adds_a_version_and_keeps_the_old_one(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    parent_state = asyncio.run(JsonCheckpointStore(
        manager.path(parent["run_id"]) / "run.json", InvestigationRun, execution_profile=PROFILE).load()).domain_state
    official = next(s for s in parent_state.sources if "notice" in s.url)
    original_hash = official.content_hash

    created = manager.create({"focus": "补充机构最新回应"}, parent_id=parent["run_id"])
    child = wait_for_terminal(manager, created["run_id"])
    child_state = asyncio.run(JsonCheckpointStore(
        manager.path(child["run_id"]) / "run.json", InvestigationRun, execution_profile=PROFILE).load()).domain_state

    versions = [s for s in child_state.sources if s.url == official.url]
    assert len(versions) == 2, "the changed page must be a new version, not an overwrite"
    assert len({s.content_hash for s in versions}) == 2
    assert original_hash in {s.content_hash for s in versions}
    # The parent's immutable artifact and references still verify against the old text.
    asyncio.run(verify_state_integrity(parent_state, Corpus(manager.root / "cases" / manager.load(parent["run_id"])["case_id"])))

    checks = {c["url"]: c for c in child["report"]["checks"]}
    assert checks[official.url]["changed"] is True
    assert any(s["discovery"] == "changed_page" for s in child["report"]["sources"])


def test_case_lock_excludes_a_second_update(manager, run_offline):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    case_root = manager.root / "cases" / manager.load(parent["run_id"])["case_id"]
    held = CaseLock(case_root / "active.lock")
    try:
        with pytest.raises(CaseBusy):
            manager.create({"focus": "另一路更新"}, parent_id=parent["run_id"])
    finally:
        held.close()
    # Releasing the lock lets the same case proceed.
    created = manager.create({"focus": "另一路更新"}, parent_id=parent["run_id"])
    assert created["status"] in {"planning", "running"}


def test_case_lock_excludes_a_second_process(manager, run_offline):
    import os
    import subprocess
    import sys

    import opinion_search

    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    case_root = manager.root / "cases" / manager.load(parent["run_id"])["case_id"]
    source_root = Path(opinion_search.__file__).resolve().parents[1]
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from opinion_search.investigation.storage import CaseLock\n"
        f"lock = CaseLock(Path({str(case_root)!r}) / 'active.lock')\n"
        "print('HELD', flush=True)\n"
        "sys.stdin.readline()\n"
        "lock.close()\n"
    )
    env = {**os.environ, "PYTHONPATH": str(source_root)}
    process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    try:
        assert process.stdout.readline().strip() == "HELD"
        with pytest.raises(CaseBusy):
            manager.create({"focus": "另一路更新"}, parent_id=parent["run_id"])
    finally:
        process.stdin.write("\n")
        process.stdin.flush()
        process.wait(timeout=10)


def test_resume_does_not_replay_committed_tool_actions(manager, run_offline, monkeypatch):
    calls = {"count": 0}
    from opinion_search.tools import executor as executor_module

    original = executor_module.ToolExecutor.execute

    async def counting(self, call):
        calls["count"] += 1
        return await original(self, call)

    monkeypatch.setattr(executor_module.ToolExecutor, "execute", counting)

    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    run_id = snapshot["run_id"]
    after_run = calls["count"]
    assert after_run > 0

    data = manager.load(run_id)
    data.pop("published", None)
    manager.save(data, status="finalizing", phase="正在写入报告与版本")
    manager.resume(run_id)

    import time
    deadline = time.monotonic() + 20
    while manager.snapshot(run_id)["status"] not in {"completed", "partial", "failed", "cancelled"}:
        if time.monotonic() > deadline:
            raise AssertionError("resume did not finish")
        time.sleep(0.02)

    assert calls["count"] == after_run, "a resume must not re-execute committed tool actions"


def test_provider_failure_is_never_reported_as_no_progress():
    issue_id = uid("issue", "发生了什么")
    failed = _state(
        sources=(),
        searches=(SearchAttempt(issue_id=issue_id, query="q", purpose="original", page=0, outcome="error", count=0),),
        read_errors=("https://example.org/failed",),
    )
    report = build_report(failed, "partial", "provider unavailable", case_id="c", run_id="r")
    assert report["search_failures"] == 1 and report["read_failures"] == 1
    assert report["no_material_change"] is False
    assert "不代表没有新进展" in markdown(report)
