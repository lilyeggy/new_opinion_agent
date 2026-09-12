"""Targeted follow-up: references validated against the parent, idempotent creation."""

from __future__ import annotations

import pytest

from opinion_search.investigation.storage import read_json


def test_update_rejects_unknown_issue_reference(manager, run_offline):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    with pytest.raises(ValueError, match="parent version"):
        manager.create({"issue_ids": ["issue-nope"]}, parent_id=parent["run_id"])


def test_update_rejects_unknown_finding_reference(manager, run_offline):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    with pytest.raises(ValueError, match="parent version"):
        manager.create({"finding_ids": ["finding-nope"]}, parent_id=parent["run_id"])


def test_update_rejects_unexpected_fields(manager, run_offline):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    with pytest.raises(ValueError, match="targeted references"):
        manager.create({"focus": "x", "evil": 1}, parent_id=parent["run_id"])


def test_client_request_id_is_idempotent_for_same_content(manager, run_offline):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    first = manager.create({"focus": "补充", "client_request_id": "key-1"}, parent_id=parent["run_id"])
    again = manager.create({"focus": "补充", "client_request_id": "key-1"}, parent_id=parent["run_id"])
    assert again["run_id"] == first["run_id"]
    with pytest.raises(ValueError, match="reused"):
        manager.create({"focus": "不同内容", "client_request_id": "key-1"}, parent_id=parent["run_id"])


def test_followup_intent_is_persisted_on_the_child_draft(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    issue_id = parent["report"]["issues"][0]["issue_id"]
    finding_id = parent["report"]["findings"][0]["finding_id"]
    child = manager.create({"focus": "补充", "issue_ids": [issue_id], "finding_ids": [finding_id],
                            "client_request_id": "key-persist"}, parent_id=parent["run_id"])
    data = manager.load(child["run_id"])
    assert data["followup"]["issue_ids"] == [issue_id]
    assert data["followup"]["finding_ids"] == [finding_id]
    registry = read_json(manager.root / "cases" / parent["case_id"] / "requests.json")
    assert registry["key-persist"]["run_id"] == child["run_id"]
    wait_for_terminal(manager, child["run_id"])


def test_search_attempt_records_task_identity_and_gap():
    from opinion_search.domain.investigation.engine import reduce_state
    from opinion_search.domain.investigation.models import (
        Delta, InvestigationRequest, Issue, Observation, SearchDecision, State, utcnow,
    )
    from opinion_search.tools.contracts import ToolError, ToolErrorKind

    state = State(request=InvestigationRequest(question="某市公交夜班车调整"), subject="夜班调整",
        cutoff=utcnow(), issues=(Issue(issue_id="i1", question="q1"), Issue(issue_id="i2", question="q2"),
                                 Issue(issue_id="i3", question="q3")))
    decision = SearchDecision(issue_id="i1", query="查询", purpose="official_response", target_gap="机构回应未找到")
    error = ToolError(action_id="a", tool_name="search.web", kind=ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                      message="x", attempts=1, retryable=False)
    reduced = reduce_state(state, Delta(decision=decision, observation=Observation(action="search", outcome=error)))
    attempt = reduced.searches[-1]
    assert attempt.task_id.startswith("search-task-")
    assert attempt.target_gap == "机构回应未找到"
    assert attempt.discovery_mode == "targeted"
    assert attempt.outcome == "error"


def test_compiler_exposes_search_coverage_to_the_model(tmp_path):
    import json
    from types import SimpleNamespace

    from opinion_search.domain.investigation.models import (
        InvestigationRequest, Issue, SearchAttempt, State, utcnow,
    )
    from opinion_search.investigation.context import Compiler
    from opinion_search.investigation.storage import Budget

    issues = tuple(Issue(issue_id=f"i{i}", question=f"q{i}") for i in range(3))
    state = State(request=InvestigationRequest(question="某市公交夜班车调整"), subject="夜班调整",
        cutoff=utcnow(), issues=issues,
        searches=(SearchAttempt(issue_id="i1", query="q", purpose="original", page=0,
                                outcome="candidates", count=1, task_id="t1",
                                target_gap="需要原始公告", discovery_mode="targeted"),))
    compiler = Compiler(Budget(tmp_path / "budget.json"))
    run = SimpleNamespace(run_id="r", domain_state=state, next_step_index=1, committed_steps=(),
                          active_step=SimpleNamespace(step_id="s", failures=()))
    context = compiler.compile(run)
    section = next(s for s in context.sections if s.section_id == "memory.coverage")
    payload = json.loads(section.content)
    assert payload["search_coverage"]["i1"]["attempts"] == 1
    assert "需要原始公告" in payload["recent_target_gaps"]


def test_provisional_workbench_written_during_run_and_served_before_report(manager, run_offline):
    created = manager.create({"mode": "offline", "question": "某市公交夜班车调整的争议与回应"})
    run_id = created["run_id"]
    import time
    saw_provisional = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(run_id)
        if snapshot["status"] in {"completed", "partial", "failed", "cancelled"}:
            break
        try:
            projection = manager.workbench(run_id)
        except FileNotFoundError:
            time.sleep(0.01)
            continue
        if projection["publication_state"] == "running":
            saw_provisional = True
            assert all(m["state"] in {"provisional", "insufficient"} for m in projection["modules"])
            break
        time.sleep(0.01)
    snapshot = manager.snapshot(run_id)
    if snapshot["status"] not in {"failed", "cancelled"}:
        assert saw_provisional, "running projection never became visible before the terminal report"
        deadline = time.monotonic() + 20
        while manager.snapshot(run_id)["status"] not in {"completed", "partial", "failed", "cancelled"}:
            if time.monotonic() > deadline:
                raise AssertionError("run did not terminate")
            time.sleep(0.01)
        projection = manager.workbench(run_id)
        assert projection["publication_state"] in {"completed", "partial"}
