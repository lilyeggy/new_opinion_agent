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
    assert payload["search_coverage"]["i1"]["purposes"]["original"]["candidates"] == 1
    assert "positions" in payload["search_coverage"]["i1"]["unattempted_directions"]
    assert payload["search_coverage"]["i2"]["attempts"] == 0
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


def test_targeted_update_uses_selected_issue_and_keeps_other_findings(manager, run_offline,
                                                                       wait_for_terminal, tmp_path):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    issues = parent["report"]["issues"]
    target = issues[0]
    child = manager.create({"issue_ids": [target["issue_id"]], "client_request_id": "target-a"},
                           parent_id=parent["run_id"])
    child = wait_for_terminal(manager, child["run_id"])
    state = manager._domain_state(child["run_id"])  # noqa: SLF001 - contract assertion

    assert state.update_intent is not None
    assert state.update_intent.issue_ids == (target["issue_id"],)
    assert state.issues[0].issue_id == target["issue_id"], "the selected target must lead the next action"
    old_findings = {finding["finding_id"]: finding for finding in parent["report"]["findings"]}
    carried = [finding for finding in state.findings if finding.finding_id in old_findings]
    for finding in carried:
        if finding.issue_id == target["issue_id"]:
            assert finding.active is False, "the selected issue is opened for fresh evidence"
        else:
            assert finding.active is True, "unselected findings must not be reopened or retired by default"


def test_targeted_update_compilation_distinguishes_issue_a_from_issue_b(manager, run_offline,
                                                                         wait_for_terminal, tmp_path):
    import asyncio
    import json
    from types import SimpleNamespace

    from opinion_search.investigation.context import Compiler
    from opinion_search.investigation.offline import OfflineModel
    from opinion_search.investigation.storage import Budget

    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    issues = parent["report"]["issues"]
    children = {}
    for key, issue in (("A", issues[0]), ("B", issues[2])):
        child = manager.create({"issue_ids": [issue["issue_id"]], "client_request_id": "target-" + key},
                               parent_id=parent["run_id"])
        children[key] = (issue["issue_id"], wait_for_terminal(manager, child["run_id"]))

    sections = {}
    for key, (issue_id, snapshot) in children.items():
        state = manager._domain_state(snapshot["run_id"])  # noqa: SLF001 - contract assertion
        probe_state = state.model_copy(update={"searches": ()})
        compiler = Compiler(Budget(tmp_path / f"budget-{key}.json"))
        run = SimpleNamespace(run_id="r", domain_state=probe_state, next_step_index=1,
                              committed_steps=(), active_step=SimpleNamespace(step_id="s", failures=()))
        context = compiler.compile(run)
        section = next(item for item in context.sections if item.section_id == "memory.update_intent")
        payload = json.loads(section.content)
        sections[key] = payload
        assert payload["issue_ids"] == [issue_id]
        assert probe_state.issues[0].issue_id == issue_id
        first_decision = asyncio.run(OfflineModel(compiler, Budget(tmp_path / f"model-{key}.json"),
                                                  fixture="bus").decide(context))
        assert first_decision.issue_id == issue_id, "the first action must target the selected issue"

    assert sections["A"]["issue_ids"] != sections["B"]["issue_ids"]
    assert children["A"][0] in sections["A"]["issue_ids"]


def test_update_inherits_parent_aliases(monkeypatch, manager, run_offline, wait_for_terminal):
    from opinion_search.investigation import offline

    real_plan = offline.offline_plan

    def plan_with_aliases(request):
        return real_plan(request).model_copy(update={"aliases": ("演示城市公交", "夜班公交")})

    monkeypatch.setattr(offline, "offline_plan", plan_with_aliases)
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    assert manager._domain_state(parent["run_id"]).aliases == ("演示城市公交", "夜班公交")  # noqa: SLF001

    created = manager.create({"focus": "补充执行情况"}, parent_id=parent["run_id"])
    child = wait_for_terminal(manager, created["run_id"])
    state = manager._domain_state(child["run_id"])  # noqa: SLF001
    assert state.aliases == ("演示城市公交", "夜班公交")


def test_selected_finding_maps_to_issue_and_evidence(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    finding = parent["report"]["findings"][0]
    child = manager.create({"finding_ids": [finding["finding_id"]], "client_request_id": "target-finding"},
                           parent_id=parent["run_id"])
    child = wait_for_terminal(manager, child["run_id"])
    state = manager._domain_state(child["run_id"])  # noqa: SLF001

    assert state.update_intent is not None
    assert state.update_intent.finding_ids == (finding["finding_id"],)
    assert state.update_intent.targets
    target = state.update_intent.targets[0]
    assert target.finding_id == finding["finding_id"]
    assert target.issue_id == finding["issue_id"]
    assert target.evidence_ids == tuple(finding["evidence_ids"])
    assert state.issues[0].issue_id == finding["issue_id"]


def test_evidence_api_marks_inactive_relations_as_history(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    target = next(issue for issue in parent["report"]["issues"] if "具体发生" in issue["question"])
    parent_finding = next(finding for finding in parent["report"]["findings"] if finding["issue_id"] == target["issue_id"])
    evidence_id = parent_finding["evidence_ids"][0]

    created = manager.create({"issue_ids": [target["issue_id"]], "client_request_id": "history-relation"},
                             parent_id=parent["run_id"])
    child = wait_for_terminal(manager, created["run_id"])
    located = manager.evidence(child["run_id"], evidence_id)
    history = [relation for relation in located["relations"] if relation["active"] is False]
    assert history, "targeted reopening must expose the old finding as history"
    assert any(relation["finding_text"] == parent_finding["text"] for relation in history)
    assert any(relation["issue_question"] for relation in history)
