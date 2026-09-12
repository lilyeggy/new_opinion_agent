"""Facet-driven module selection: one workbench, different event content."""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    EventProfile, Finding, FindingProposal, InvestigationRequest, Issue, SourceVersion,
    State, Evidence, uid, utcnow,
)
from opinion_search.investigation.presentation import HIGHLIGHT_LIMIT, confirmed_profile, highlights
from opinion_search.investigation.report import build_report
from opinion_search.investigation.workbench import build_workbench


def _state(facets=("rule_change",), with_findings=True) -> State:
    issues = tuple(Issue(issue_id=f"issue-{i}", question=f"问题{i}", status="answered") for i in range(3))
    evidence = ()
    findings = ()
    sources = ()
    if with_findings:
        sources = (SourceVersion(version_id="v1", url="https://a.example/1", final_url="https://a.example/1",
            title="来源v1", fetched_at=utcnow(), artifact_ref="artifacts/x", content_hash="h1"),)
        evidence = (Evidence(evidence_id="e1", version_id="v1", excerpt="末班提前至22时", start=0, end=8,
            locator="Reader text chars 0:8"),)
        proposal = FindingProposal(issue_id="issue-0", text="公告称末班提前。", kind="attributed",
            stakeholder="交通部门", evidence_ids=("e1",))
        findings = (Finding(**proposal.model_dump(), finding_id=uid("finding", "f1")),)
    return State(request=InvestigationRequest(question="某市公交夜班车调整的争议与回应"), subject="夜班调整",
        cutoff=utcnow(), issues=issues, sources=sources, evidence=evidence, findings=findings,
        profile=EventProfile(facets=facets, rationale="测试用侧重") if facets else None)


def _findings_by_issue(report):
    return {issue["issue_id"]: {"question": issue["question"],
            "findings": [f for f in report["findings"] if f["issue_id"] == issue["issue_id"]]}
            for issue in report["issues"]}


def test_confirmation_drops_unknown_facets_and_keeps_user_questions():
    from opinion_search.domain.investigation.models import PlanProposal, QuestionProposal

    questions = (QuestionProposal(question="q1"), QuestionProposal(question="q2"), QuestionProposal(question="q3"))
    plan = PlanProposal(subject="s", facets=("rule_change", "made_up_facet"), facet_rationale="r", questions=questions)
    profile = confirmed_profile(plan, _state().issues)
    assert profile is not None and profile.facets == ("rule_change",)

    plain = PlanProposal(subject="s", questions=questions)
    assert confirmed_profile(plain, _state().issues) is None
    general = PlanProposal(subject="s", facets=("general",), questions=plain.questions)
    assert confirmed_profile(general, _state().issues) is None


def test_two_facets_produce_different_modules_and_general_falls_back():
    rule = build_workbench(build_report(_state(("rule_change",)), "completed", "完成", case_id="c", run_id="r1"))
    billing = build_workbench(build_report(_state(("billing_remedy",)), "completed", "完成", case_id="c", run_id="r2"))
    general = build_workbench(build_report(_state((), with_findings=False), "completed", "完成", case_id="c", run_id="r3"))

    rule_types = {m["module_type"] for m in rule["modules"]}
    billing_types = {m["module_type"] for m in billing["modules"]}
    assert "rule-comparison" in rule_types and "rule-comparison" not in billing_types
    assert "billing-remedy" in billing_types and "billing-remedy" not in rule_types
    assert general["profile"]["facets"] == ["general"]
    assert not any(m.get("facet") for m in general["modules"])
    assert rule["views"]["overview"]["highlights"][0]["module_type"] == "rule-comparison"
    assert len(rule["views"]["overview"]["highlights"]) <= HIGHLIGHT_LIMIT


def test_facet_module_without_findings_is_insufficient_with_gap():
    workbench = build_workbench(build_report(_state(("billing_remedy",), with_findings=False), "partial", "无判断", case_id="c", run_id="r4"))
    module = next(m for m in workbench["modules"] if m["module_type"] == "billing-remedy")
    assert module["state"] == "insufficient"
    assert "受理渠道不等于已退费" in module["gap"]
    assert module["items"] == []
    assert module["selection_rationale"].startswith("事件侧重点 billing_remedy")


def test_in_run_projection_marks_data_backed_modules_provisional():
    workbench = build_workbench(build_report(_state(("rule_change",)), "running", "阶段投影", case_id="c", run_id="r5"))
    states = {m["module_type"]: m["state"] for m in workbench["modules"]}
    assert states["rule-comparison"] == "provisional"
    assert states["issues-review"] == "provisional"
    assert states["publication-distribution"] == "insufficient"


def test_highlights_prefer_ready_modules_and_cap_at_three():
    modules = [{"module_type": f"m{i}", "facet": True, "state": state, "title": t}
               for i, (state, t) in enumerate([("insufficient", "a"), ("ready", "b"), ("provisional", "c"),
                                               ("ready", "d"), ("ready", "e")])]
    picks = highlights(modules)
    assert len(picks) == HIGHLIGHT_LIMIT
    assert [m["state"] for m in picks] == ["ready", "provisional", "ready"]


def test_update_run_inherits_the_parent_event_emphasis(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车时间调整的争议与回应"})
    assert parent["report"]["profile"]["facets"] == ["rule_change"]
    child = manager.create({"focus": "补充执行情况"}, parent_id=parent["run_id"])
    child = wait_for_terminal(manager, child["run_id"])
    assert child["report"]["profile"]["facets"] == ["rule_change"], "an update must not drop the event emphasis"
    workbench = manager.workbench(child["run_id"])
    assert any(module["module_type"] == "rule-comparison" for module in workbench["modules"])
