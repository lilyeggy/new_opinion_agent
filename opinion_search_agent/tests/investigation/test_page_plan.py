"""PagePlan binds event-specific search requirements to safe Web sections."""

from __future__ import annotations

import json
from types import SimpleNamespace

from opinion_search.domain.investigation.models import (
    Evidence,
    EventProfile,
    Finding,
    FindingProposal,
    InvestigationRequest,
    Issue,
    ModuleField,
    ReviewRecord,
    SourceVersion,
    State,
    finding_hash,
    uid,
    utcnow,
)
from opinion_search.investigation.page_plan import FORMAT, build_page_plan


def _issues():
    return (
        Issue(issue_id="i-rule", question="新规则何时生效并适用于谁？", status="open"),
        Issue(issue_id="i-voices", question="各方有哪些争议和诉求？", status="open"),
        Issue(issue_id="i-response", question="机构回应覆盖了什么？", status="open"),
    )


def test_general_plan_keeps_the_trust_framework_without_an_empty_focus_view():
    plan = build_page_plan(None, _issues())

    assert plan["format"] == FORMAT
    assert plan["event_facets"] == ["general"]
    assert [section["view"] for section in plan["sections"]] == [
        "overview", "issues", "coverage", "citations", "diagnostics",
    ]
    assert plan["module_requirements"] == []
    assert plan["search_targets"] == []


def test_event_facet_changes_page_composition_and_creates_bounded_search_targets():
    profile = EventProfile(facets=("rule_change",), rationale="涉及规则调整",
                           question_refs=("i-rule",))
    plan = build_page_plan(profile, _issues())

    assert [section["view"] for section in plan["sections"]][:3] == ["overview", "focus", "issues"]
    focus = next(section for section in plan["sections"] if section["view"] == "focus")
    assert focus["title"] == "规则与适用影响"
    assert focus["module_types"] == ["rule-comparison"]
    assert {target["field"] for target in plan["search_targets"]} == {
        "new_value", "applies_to", "effective_time",
    }
    assert all(target["issue_id"] == "i-rule" for target in plan["search_targets"])
    assert all(target["target_gap"].startswith("新旧规则对照缺少") for target in plan["search_targets"])


def test_existing_structured_fields_close_targets_without_changing_section_identity():
    profile = EventProfile(facets=("rule_change",), question_refs=("i-rule",))
    proposal = FindingProposal(
        issue_id="i-rule", text="公告列明新规则、范围和生效时间。", kind="attributed",
        stakeholder="机构", evidence_ids=("e1",),
        module_fields=(
            ModuleField(module="rule-comparison", field="new_value", value="末班调整至22时"),
            ModuleField(module="rule-comparison", field="applies_to", value="工作日线路"),
            ModuleField(module="rule-comparison", field="effective_time", value="2026-01-10"),
        ),
    )
    finding = Finding(**proposal.model_dump(), finding_id="f1")
    missing = build_page_plan(profile, _issues())
    ready = build_page_plan(profile, _issues(), (finding,))

    assert missing["sections"] == ready["sections"]
    assert missing["plan_id"] != ready["plan_id"]
    assert ready["search_targets"] == []
    assert ready["module_requirements"][0]["state"] == "ready"


def test_narrow_question_requires_only_the_module_anchor_field():
    issues = (
        Issue(issue_id="i-rule", question="新规则是什么？"),
        Issue(issue_id="i-voices", question="各方有哪些争议和诉求？"),
        Issue(issue_id="i-response", question="机构回应覆盖了什么？"),
    )
    profile = EventProfile(facets=("rule_change",), question_refs=("i-rule",))
    proposal = FindingProposal(
        issue_id="i-rule", text="公告列明新规则。", kind="attributed",
        stakeholder="机构", evidence_ids=("e1",),
        module_fields=(ModuleField(module="rule-comparison", field="new_value", value="末班调整至22时"),),
    )
    finding = Finding(**proposal.model_dump(), finding_id="f-narrow")

    plan = build_page_plan(profile, issues, (finding,))

    requirement = plan["module_requirements"][0]
    assert requirement["required_fields"] == ["new_value"]
    assert requirement["state"] == "ready"
    assert plan["search_targets"] == []


def test_field_from_an_unrelated_issue_does_not_close_a_required_module_gap():
    profile = EventProfile(facets=("rule_change",), question_refs=("i-rule",))
    proposal = FindingProposal(
        issue_id="i-voices", text="评论提到一个生效日期。", kind="attributed",
        stakeholder="评论者", evidence_ids=("e1",),
        module_fields=(ModuleField(module="rule-comparison", field="effective_time", value="2026-01-10"),),
    )
    finding = Finding(**proposal.model_dump(), finding_id="f-unrelated")

    plan = build_page_plan(profile, _issues(), (finding,))

    assert "effective_time" in plan["module_requirements"][0]["missing_fields"]
    assert any(target["field"] == "effective_time" for target in plan["search_targets"])


def test_unlinked_facet_is_visible_but_does_not_create_required_work():
    profile = EventProfile(facets=("billing_remedy",), rationale="候选侧重")
    plan = build_page_plan(profile, _issues())

    assert plan["module_requirements"][0]["state"] == "optional_incomplete"
    assert plan["module_requirements"][0]["required"] is False
    assert plan["search_targets"] == []


def test_multiple_facets_bind_targets_to_their_own_questions():
    issues = (
        Issue(issue_id="i-rule", question="新规则何时生效并适用于谁？"),
        Issue(issue_id="i-billing", question="费用如何复核和办理退费？"),
        Issue(issue_id="i-response", question="机构回应覆盖了什么？"),
    )
    profile = EventProfile(facets=("rule_change", "billing_remedy"),
                           question_refs=("i-rule", "i-billing"))
    plan = build_page_plan(profile, issues)
    targets = {item["module_type"]: item["issue_id"] for item in plan["search_targets"]}

    assert targets["rule-comparison"] == "i-rule"
    assert targets["billing-remedy"] == "i-billing"


def test_compiler_exposes_the_same_page_plan_to_the_search_loop(tmp_path):
    from opinion_search.investigation.context import Compiler
    from opinion_search.investigation.storage import Budget

    profile = EventProfile(facets=("rule_change",), question_refs=("i-rule",))
    state = State(request=InvestigationRequest(question="某市夜班规则调整"), subject="夜班规则调整",
                  cutoff=utcnow(), issues=_issues(), profile=profile)
    compiler = Compiler(Budget(tmp_path / "budget.json"))
    run = SimpleNamespace(run_id="r", domain_state=state, next_step_index=1, committed_steps=(),
                          active_step=SimpleNamespace(step_id="s", failures=()))

    context = compiler.compile(run)
    section = next(item for item in context.sections if item.section_id == "memory.page_plan")
    payload = json.loads(section.content)
    assert payload == build_page_plan(profile, state.issues, state.findings)
    assert payload["search_targets"][0]["issue_id"] == "i-rule"


def _completion_state(*, include_effective_time: bool) -> State:
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="公告", fetched_at=utcnow(), artifact_ref="artifacts/a", content_hash="h")
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt="公告内容", start=0, end=4,
                        locator="Reader text chars 0:4")
    fields = [
        ModuleField(module="rule-comparison", field="new_value", value="22时"),
        ModuleField(module="rule-comparison", field="applies_to", value="工作日线路"),
    ]
    if include_effective_time:
        fields.append(ModuleField(module="rule-comparison", field="effective_time", value="2026-01-10"))
    proposal = FindingProposal(issue_id="i-rule", text="公告说明规则调整。", kind="attributed",
                               stakeholder="机构", evidence_ids=("e1",), module_fields=tuple(fields))
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", "page-plan-completion"))
    review = ReviewRecord(finding_id=finding.finding_id, verdict="supported", reason="原文支持",
                          finding_hash=finding_hash(finding), model="test", reviewed_at=utcnow())
    issues = (
        Issue(issue_id="i-rule", question="新规则何时生效并适用于谁？", status="answered", evidence_ids=("e1",)),
        Issue(issue_id="i-voices", question="各方诉求？", status="not_found", note="范围内未发现"),
        Issue(issue_id="i-response", question="回应如何？", status="not_found", note="范围内未发现"),
    )
    return State(request=InvestigationRequest(question="规则调整"), subject="规则调整", cutoff=utcnow(),
                 issues=issues, sources=(source,), evidence=(evidence,), findings=(finding,), reviews=(review,),
                 profile=EventProfile(facets=("rule_change",), question_refs=("i-rule",)))


def test_required_page_module_gap_downgrades_completion_to_partial():
    from opinion_search.domain.investigation.engine import completion
    from opinion_search.runtime.completion import CompletionDisposition

    incomplete = completion(_completion_state(include_effective_time=False))
    complete = completion(_completion_state(include_effective_time=True))

    assert incomplete.disposition == CompletionDisposition.ACCEPT_PARTIAL
    assert complete.disposition == CompletionDisposition.ACCEPT_COMPLETE


def test_required_page_module_gap_is_visible_in_chain_diagnostics():
    from opinion_search.investigation.diagnostics import build_chain_diagnostics

    diagnostics = build_chain_diagnostics(_completion_state(include_effective_time=False),
                                          publication_status="partial")
    signal = next(item for item in diagnostics["signals"]
                  if item["code"] == "required_page_modules_incomplete")

    assert signal["severity"] == "critical"
    assert signal["details"]["targets"][0]["field"] == "effective_time"
    assert diagnostics["stages"][5]["status"] == "blocked"
