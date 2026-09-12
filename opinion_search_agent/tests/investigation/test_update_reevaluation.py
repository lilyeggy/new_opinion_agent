"""R03: an update must expose 'not yet re-evaluated', never a false withdrawal."""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    Evidence, Finding, InvestigationRequest, Issue, RetiredFinding, SourceVersion, State, uid, utcnow,
)
from opinion_search.investigation.report import build_report


def _state(*, findings, retired=()) -> State:
    request = InvestigationRequest(question="公交夜班调整的争议")
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="公告", fetched_at=utcnow(), artifact_ref="artifact://sha256/" + "1" * 64,
                           content_hash="1" * 64)
    excerpt = "工作日末班提前至22时。"
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt=excerpt, start=0, end=len(excerpt), locator="chars 0:10")
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("发生了什么", "争议是什么", "回应如何"))
    return State(request=request, subject="公交夜班调整", cutoff=utcnow(), issues=issues,
                 sources=(source,), evidence=(evidence,), findings=findings, retired=retired)


def _finding(*, active=True) -> Finding:
    return Finding(issue_id=uid("issue", "发生了什么"), text="公告称工作日末班提前至22时。", kind="attributed",
                   stakeholder="交通部门", evidence_ids=("e1",), finding_id=uid("finding", "f1"), active=active)


def test_absent_finding_without_retirement_is_pending_not_withdrawn():
    parent = build_report(_state(findings=(_finding(),)), "completed", "ok", case_id="c", run_id="parent")
    child = _state(findings=(_finding(active=False),))
    report = build_report(child, "partial", "needs re-evaluation", case_id="c", run_id="child", parent_id="parent", parent=parent)
    kinds = {change["issue_id"]: change["kind"] for change in report["changes"]}
    assert "withdrawn" not in kinds.values()
    assert kinds[uid("issue", "发生了什么")] == "pending_reevaluation"
    assert report["retired"] == []


def test_explicit_retirement_is_reported_as_withdrawn():
    finding = _finding(active=False)
    parent = build_report(_state(findings=(_finding(),)), "completed", "ok", case_id="c", run_id="parent")
    child = _state(findings=(finding,), retired=(RetiredFinding(finding_id=finding.finding_id, reason="新证据表明公告已作废。", retired_at=utcnow()),))
    report = build_report(child, "partial", "retracted", case_id="c", run_id="child", parent_id="parent", parent=parent)
    change = next(c for c in report["changes"] if c["issue_id"] == finding.issue_id)
    assert change["kind"] == "withdrawn"
    assert finding.finding_id in change["retired_reasons"]


def test_update_run_never_reports_false_withdrawal(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    parent_report_path = manager.path(parent["run_id"]) / "report.json"
    before = parent_report_path.read_bytes()

    created = manager.create({"focus": "补充机构最新回应"}, parent_id=parent["run_id"])
    child = wait_for_terminal(manager, created["run_id"])

    assert child["status"] in {"completed", "partial"}
    report = child["report"]
    assert report["parent_id"] == parent["run_id"]
    kinds = {change["kind"] for change in report["changes"]}
    assert "pending_reevaluation" not in kinds  # the update did re-evaluate every issue
    # The published parent version is immutable.
    assert parent_report_path.read_bytes() == before


def test_reduce_state_records_an_explicit_retirement():
    from opinion_search.domain.investigation.engine import reduce_state
    from opinion_search.domain.investigation.models import Delta, Observation, ReflectDecision, Retirement

    finding = _finding()
    delta = Delta(
        decision=ReflectDecision(retirements=(Retirement(finding_id=finding.finding_id, reason="公告已作废。"),), reason="复核后撤回"),
        observation=Observation(action="reflect"),
    )

    reduced = reduce_state(_state(findings=(finding,)), delta)

    assert [record.finding_id for record in reduced.retired] == [finding.finding_id]
    assert reduced.retired[0].retired_at is not None
    assert reduced.retired[0].reason == "公告已作废。"


def test_reduce_state_does_not_duplicate_a_retirement():
    from opinion_search.domain.investigation.engine import reduce_state
    from opinion_search.domain.investigation.models import Delta, Observation, ReflectDecision, Retirement

    finding = _finding()
    retirement = Retirement(finding_id=finding.finding_id, reason="公告已作废。")
    once = reduce_state(_state(findings=(finding,)), Delta(decision=ReflectDecision(retirements=(retirement,), reason="撤回"), observation=Observation(action="reflect")))
    twice = reduce_state(once, Delta(decision=ReflectDecision(retirements=(retirement,), reason="再次撤回"), observation=Observation(action="reflect")))

    assert len(twice.retired) == 1
