"""C: attribution, response coverage, and source independence are enforced."""

from __future__ import annotations

import pytest

from opinion_search.domain.investigation.engine import Validator, response_search_complete
from opinion_search.domain.investigation.models import (
    Evidence, FindingProposal, InvestigationRequest, Issue, ReflectDecision, SearchAttempt,
    SourceVersion, State, uid, utcnow,
)
from opinion_search.investigation.report import build_report

TEXTS = ("发生了什么", "争议是什么", "回应如何")


def _base_state(**extra) -> State:
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in TEXTS)
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="公告", fetched_at=utcnow(), artifact_ref="artifact://sha256/" + "3" * 64,
                           content_hash="3" * 64)
    excerpt = "官方称已解决。"
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt=excerpt, start=0, end=len(excerpt), locator="chars 0:6")
    return State(request=InvestigationRequest(question="公交夜班调整的争议"), subject="公交夜班调整",
                 cutoff=utcnow(), issues=issues, sources=(source,), evidence=(evidence,), **extra)


def _proposal(**overrides) -> FindingProposal:
    base = dict(issue_id=uid("issue", "回应如何"), text="机构称已解决。", kind="fact", evidence_ids=("e1",))
    base.update(overrides)
    return FindingProposal(**base)


def test_attributed_claim_requires_an_identified_speaker():
    with pytest.raises(ValueError):
        Validator().validate(_base_state(), ReflectDecision(findings=(_proposal(kind="attributed"),), reason="r"))


def test_partial_response_must_name_the_uncovered_component():
    proposal = _proposal(response="partial", coverage_reason="只回应了周末")
    with pytest.raises(ValueError):
        Validator().validate(_base_state(), ReflectDecision(findings=(proposal,), reason="r"))
    named = _proposal(response="partial", coverage_reason="只回应了周末", uncovered=("工作日替代出行",))
    Validator().validate(_base_state(), ReflectDecision(findings=(named,), reason="r"))


def test_full_response_cannot_leave_a_component_uncovered():
    proposal = _proposal(response="direct", coverage_reason="逐项回应", uncovered=("票价",))
    with pytest.raises(ValueError):
        Validator().validate(_base_state(), ReflectDecision(findings=(proposal,), reason="r"))


def test_response_judgement_requires_a_coverage_reason():
    with pytest.raises(ValueError):
        Validator().validate(_base_state(), ReflectDecision(findings=(_proposal(response="non_substantive"),), reason="r"))


def test_not_found_requires_finished_scoped_searching():
    issue_id = uid("issue", "回应如何")
    incomplete = _base_state(searches=(SearchAttempt(issue_id=issue_id, query="q", purpose="official_response", page=0, outcome="filtered", count=0),))
    assert response_search_complete(incomplete, issue_id) is False

    finished = _base_state(searches=tuple(
        SearchAttempt(issue_id=issue_id, query=f"q-{purpose}", purpose=purpose, page=0, outcome="empty", count=0)
        for purpose in ("official_response", "event_response", "followup")
    ))
    assert response_search_complete(finished, issue_id) is True

    # A discovered but unread candidate means the search is not finished.
    pending = _base_state(
        searches=finished.searches,
        candidates=({"url": "https://example.org/response", "title": "t", "snippet": "s", "issue_id": issue_id},),
    )
    assert response_search_complete(pending, issue_id) is False


def test_duplicate_reprints_are_not_independent_sources():
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in TEXTS)
    sources = tuple(
        SourceVersion(version_id=f"v{i}", url=f"https://site{i}.example/a", final_url=f"https://site{i}.example/a",
                      title=f"转载 {i}", fetched_at=utcnow(), artifact_ref="artifact://sha256/" + "4" * 64,
                      content_hash="4" * 64, duplicate_of=None if i == 0 else "v0")
        for i in range(3)
    )
    state = State(request=InvestigationRequest(question="通稿转载"), subject="通稿", cutoff=utcnow(), issues=issues, sources=sources)
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r")
    assert report["independent_source_count"] == 1
    assert [s["independent"] for s in report["sources"]] == [True, False, False]


def test_coverage_failures_name_the_field_the_model_must_fix():
    from opinion_search.investigation.context import INSTRUCTIONS

    partial = _proposal(response="partial", coverage_reason="只回应了周末")
    with pytest.raises(ValueError, match="uncovered"):
        Validator().validate(_base_state(), ReflectDecision(findings=(partial,), reason="r"))
    full = _proposal(response="direct", coverage_reason="逐项回应", uncovered=("票价",))
    with pytest.raises(ValueError, match="uncovered"):
        Validator().validate(_base_state(), ReflectDecision(findings=(full,), reason="r"))
    with pytest.raises(ValueError, match="coverage_reason"):
        Validator().validate(_base_state(), ReflectDecision(findings=(_proposal(response="non_substantive"),), reason="r"))

    assert "uncovered" in INSTRUCTIONS and "coverage_reason" in INSTRUCTIONS


def _compound_state(*, component_status="open", issue_status="open", with_review=True):
    from opinion_search.domain.investigation.engine import reduce_state
    from opinion_search.domain.investigation.models import (
        ComponentAssessment, Delta, Finding, Observation, QuestionComponent, ReviewRecord,
        accepted_review, finding_hash,
    )

    question = "用户范围、退费标准、执行时间"
    components = (
        QuestionComponent(text="用户范围", status=component_status, evidence_ids=("e1",) if component_status != "open" else ()),
        QuestionComponent(text="退费标准", status="answered" if component_status == "answered" else "open"),
        QuestionComponent(text="执行时间", status="answered" if component_status == "answered" else "open"),
    )
    compound = Issue(issue_id="compound", question=question, required=True, status=issue_status,
                    note="测试复合问题", components=components)
    filler_a = Issue(issue_id="filler-a", question="发生了什么", status="answered")
    filler_b = Issue(issue_id="filler-b", question="回应如何", status="answered")
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="公告", fetched_at=utcnow(), artifact_ref="artifact://sha256/" + "5" * 64,
                           content_hash="5" * 64)
    excerpt = "官方称相关安排已经执行。"
    evidence = Evidence(evidence_id="e1", version_id="v1", excerpt=excerpt, start=0, end=len(excerpt), locator="chars 0:12")
    proposal = FindingProposal(issue_id="compound", text=excerpt, kind="fact", evidence_ids=("e1",))
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", "compound"))
    reviews = ()
    if with_review:
        reviews = (ReviewRecord(finding_id=finding.finding_id, verdict="supported", reason="测试",
                                finding_hash=finding_hash(finding), model="test", reviewed_at=utcnow()),)
    return State(request=InvestigationRequest(question="复合问题测试"), subject="复合问题测试",
                 cutoff=utcnow(), issues=(compound, filler_a, filler_b), sources=(source,),
                 evidence=(evidence,), findings=(finding,), reviews=reviews)


def test_compound_issue_requires_every_component_disposition():
    from opinion_search.domain.investigation.models import ComponentAssessment, IssueAssessment
    state = _compound_state()
    decision = ReflectDecision(assessments=(IssueAssessment(
        issue_id="compound", status="answered", reason="已逐项回答", evidence_ids=("e1",),
        components=(ComponentAssessment(text="用户范围", status="answered", evidence_ids=("e1",)),
                    ComponentAssessment(text="退费标准", status="answered", evidence_ids=("e1",))),
    ),), reason="测试")
    with pytest.raises(ValueError, match="every component"):
        Validator().validate(state, decision)


def test_answered_issue_cannot_keep_an_unavailable_component():
    from opinion_search.domain.investigation.models import ComponentAssessment, IssueAssessment
    state = _compound_state()
    decision = ReflectDecision(assessments=(IssueAssessment(
        issue_id="compound", status="answered", reason="回答", evidence_ids=("e1",),
        components=(ComponentAssessment(text="用户范围", status="answered", evidence_ids=("e1",)),
                    ComponentAssessment(text="退费标准", status="unavailable", note="范围内未取得"),
                    ComponentAssessment(text="执行时间", status="answered", evidence_ids=("e1",))),
    ),), reason="测试")
    with pytest.raises(ValueError, match="non-answered component"):
        Validator().validate(state, decision)


def test_compound_issue_reducer_and_workbench_expose_component_status():
    from opinion_search.domain.investigation.engine import reduce_state
    from opinion_search.domain.investigation.models import (
        ComponentAssessment, Delta, IssueAssessment, Observation,
    )
    from opinion_search.investigation.workbench import build_workbench

    state = _compound_state()
    decision = ReflectDecision(assessments=(IssueAssessment(
        issue_id="compound", status="answered", reason="已逐项回答", evidence_ids=("e1",),
        components=(ComponentAssessment(text="用户范围", status="answered", evidence_ids=("e1",)),
                    ComponentAssessment(text="退费标准", status="answered", evidence_ids=("e1",)),
                    ComponentAssessment(text="执行时间", status="answered", evidence_ids=("e1",))),
    ),), reason="测试")
    reduced = reduce_state(state, Delta(decision=decision, observation=Observation(action="reflect")))
    issue = next(item for item in reduced.issues if item.issue_id == "compound")
    assert [component.status for component in issue.components] == ["answered", "answered", "answered"]

    report = build_report(reduced, "completed", "完成", case_id="c", run_id="compound")
    component_view = next(item for item in build_workbench(report)["views"]["issues"]["issues"]
                          if item["issue_id"] == "compound")
    assert [component["text"] for component in component_view["components"]] == ["用户范围", "退费标准", "执行时间"]
    assert all(component["status"] == "answered" for component in component_view["components"])


def test_completion_stays_partial_when_an_answered_issue_has_an_open_component():
    from opinion_search.domain.investigation.engine import CompletionEvaluator, completion
    from opinion_search.runtime.completion import CompletionDisposition

    state = _compound_state(component_status="open", issue_status="answered")
    verdict = completion(state)
    assert verdict.disposition == CompletionDisposition.ACCEPT_PARTIAL


def test_unbacked_numeric_specifics_are_detected_for_review_downgrade():
    from opinion_search.domain.investigation.models import (
        Evidence, Finding, FindingProposal,
    )
    from opinion_search.investigation.service import REVIEW_INSTRUCTIONS, unbacked_specifics

    finding = Finding(**FindingProposal(issue_id="i", text="末班提前至22时，涉及10条线路，补贴30%。",
                                        kind="fact", evidence_ids=("e1",)).model_dump(),
                      finding_id="f1")
    evidence = (Evidence(evidence_id="e1", version_id="v1", excerpt="末班提前至22时，补贴30%。",
                         start=0, end=12, locator="chars 0:12"),)
    assert unbacked_specifics(finding, evidence) == ("10",)
    assert "named measure" in REVIEW_INSTRUCTIONS
