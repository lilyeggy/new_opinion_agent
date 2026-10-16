"""Read-decision validation: normalization, feedback quality, recoverability.

The live run 73e84650… recorded five `read requires an allowed discovered
candidate` failures that cost a decision attempt each; these tests pin the
repaired contract (normalization + actionable feedback).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opinion_search.domain.investigation.engine import Validator
from opinion_search.domain.investigation.models import (
    ComponentAssessment, Evidence, Finding, FindingProposal, InvestigationRequest, Issue,
    IssueAssessment, QuestionComponent, ReadDecision, ReflectDecision, SearchAttempt,
    SearchDecision, SourceVersion, State, utcnow,
)


def _state(read_attempts: tuple[str, ...] = ()) -> State:
    issues = tuple(Issue(issue_id=f"issue-{i}", question=f"问题{i}", status="open") for i in range(3))
    return State(request=InvestigationRequest(question="某市公交夜班车调整的争议"), subject="夜班调整",
        cutoff=utcnow(), issues=issues,
        candidates=({"url": "https://a.example/1", "title": "公告", "issue_id": "issue-0"},
                    {"url": "https://b.example/2", "title": "报道", "issue_id": "issue-1"}),
        read_attempts=read_attempts)


def test_read_accepts_a_reformatted_known_candidate_url() -> None:
    state = _state()
    # same page, reformatted by the model (trailing slash): normalization must
    # match it against the candidate instead of burning a decision attempt
    Validator().validate(state, ReadDecision(action="read", issue_id="issue-0",
        url="https://a.example/1/", focus="核对原文"))


def test_read_rejection_names_the_rule_and_points_at_legal_candidates() -> None:
    with pytest.raises(ValueError) as captured:
        Validator().validate(_state(), ReadDecision(action="read", issue_id="issue-0",
            url="https://invented.example/page", focus="读一个没见过的链接"))
    message = str(captured.value)
    assert "not a discovered candidate" in message
    assert "https://a.example/1" in message, "feedback must list a legal candidate"
    assert "https://b.example/2" in message


def test_read_rejection_without_candidates_says_to_search_first() -> None:
    state = _state().model_copy(update={"candidates": ()})
    with pytest.raises(ValueError) as captured:
        Validator().validate(state, ReadDecision(action="read", issue_id="issue-0",
            url="https://a.example/1", focus="没有任何候选"))
    assert "run search first" in str(captured.value)


def test_already_read_url_points_at_retrieve() -> None:
    with pytest.raises(ValueError) as captured:
        Validator().validate(_state(read_attempts=("https://a.example/1",)),
            ReadDecision(action="read", issue_id="issue-0", url="https://a.example/1", focus="重读"))
    assert "retrieve" in str(captured.value)


def _evidence_state(*, source_count: int = 4, duplicate_searches: int = 0,
                    with_finding: bool = False) -> State:
    state = _state()
    sources = tuple(SourceVersion(
        version_id=f"source-{index}", url=f"https://source{index}.example/doc",
        final_url=f"https://source{index}.example/doc", title=f"材料{index}",
        fetched_at=utcnow(), artifact_ref=f"artifact://{index}", content_hash=str(index) * 64,
    ) for index in range(source_count))
    evidence = tuple(Evidence(
        evidence_id=f"evidence-{index}", version_id=source.version_id,
        excerpt="可核查原文", start=0, end=5, locator="chars 0:5",
    ) for index, source in enumerate(sources))
    searches = tuple(SearchAttempt(
        issue_id="issue-0", query=f"查询{index}", purpose="independent", page=0,
        outcome="duplicate",
    ) for index in range(duplicate_searches))
    findings = ()
    if with_finding:
        findings = (Finding(
            finding_id="finding-0", issue_id="issue-0", text="已有初步判断",
            kind="fact", evidence_ids=(evidence[0].evidence_id,),
        ),)
    return state.model_copy(update={
        "sources": sources, "evidence": evidence, "searches": searches,
        "findings": findings,
    })


def test_first_reflection_gate_rejects_more_acquisition_after_enough_evidence() -> None:
    state = _evidence_state()
    with pytest.raises(ValueError, match="reflect is required"):
        Validator().validate(state, SearchDecision(
            issue_id="issue-0", query="继续搜索", purpose="independent"))

    Validator().validate(state, ReflectDecision(
        findings=(FindingProposal(
            issue_id="issue-0", text="已有原文支持一项初步判断。", kind="fact",
            evidence_ids=("evidence-0",),
        ),),
        assessments=(IssueAssessment(
            issue_id="issue-0", status="answered", reason="已有原文支持。",
            evidence_ids=("evidence-0",),
        ),),
        reason="先整理已有证据",
    ))


def test_first_reflection_gate_rejects_empty_reflection() -> None:
    with pytest.raises(ValueError, match="must create at least one evidence-linked finding"):
        Validator().validate(_evidence_state(), ReflectDecision(reason="稍后再说"))


def test_first_reflection_requires_a_finding_instead_of_assessment_only() -> None:
    with pytest.raises(ValueError, match="leave assessments empty"):
        Validator().validate(_evidence_state(), ReflectDecision(
            assessments=(IssueAssessment(
                issue_id="issue-0", status="answered", reason="已有原文支持。",
                evidence_ids=("evidence-0",),
            ),),
            reason="只处置问题但没有形成报告判断",
        ))


def test_partial_reflection_can_keep_uncovered_components_open() -> None:
    state = _evidence_state().model_copy(update={
        "issues": (
            _evidence_state().issues[0].model_copy(update={
                "components": (
                    QuestionComponent(text="监管认定"),
                    QuestionComponent(text="独立核验"),
                ),
            }),
            *_evidence_state().issues[1:],
        ),
    })
    Validator().validate(state, ReflectDecision(
        findings=(FindingProposal(
            issue_id="issue-0", text="现有材料记录了一项监管认定。", kind="fact",
            evidence_ids=("evidence-0",),
        ),),
        assessments=(IssueAssessment(
            issue_id="issue-0", status="open", reason="独立核验仍缺材料。",
            evidence_ids=("evidence-0",),
            components=(
                ComponentAssessment(text="监管认定", status="answered", evidence_ids=("evidence-0",)),
                ComponentAssessment(text="独立核验", status="open"),
            ),
        ),),
        reason="先提交已覆盖部分",
    ))


def test_duplicate_search_streak_drains_unread_candidates_before_reflection() -> None:
    state = _evidence_state(source_count=1, duplicate_searches=2)
    with pytest.raises(ValueError, match="read is required"):
        Validator().validate(state, SearchDecision(
            issue_id="issue-0", query="第三次换词", purpose="independent"))
    Validator().validate(state, ReadDecision(
        issue_id="issue-0", url="https://a.example/1", focus="读取已知候选"))


def test_duplicate_search_streak_requires_reflection_when_no_candidates_remain() -> None:
    state = _evidence_state(source_count=1, duplicate_searches=2).model_copy(update={
        "read_attempts": ("https://a.example/1", "https://b.example/2"),
    })
    with pytest.raises(ValueError, match="reflect is required"):
        Validator().validate(state, SearchDecision(
            issue_id="issue-0", query="第三次换词", purpose="independent"))


def test_ongoing_synthesis_gate_redirects_acquisition_when_undisposed_piles_up() -> None:
    """After the first finding, undisposed evidence must not pile up.

    A 2026-09-23 live run converted only 4 of 8 read sources into findings;
    once 8+ excerpts sit undisposed, acquisition is redirected into synthesis.
    Unlike the first reflection, ongoing synthesis accepts assessment-only
    reflections: linking evidence to an issue disposes it too.
    """
    state = _evidence_state(source_count=10, with_finding=True)
    with pytest.raises(ValueError, match="reflect is required"):
        Validator().validate(state, SearchDecision(
            issue_id="issue-0", query="继续搜索", purpose="independent"))

    # Assessment-only synthesis is legal for the ongoing gate.
    Validator().validate(state, ReflectDecision(
        assessments=(IssueAssessment(
            issue_id="issue-0", status="answered", reason="已有原文支持。",
            evidence_ids=("evidence-1", "evidence-2"),
        ),),
        reason="处置堆积证据",
    ))

    # An empty reflection still disposes nothing.
    with pytest.raises(ValueError, match="must dispose evidence"):
        Validator().validate(state, ReflectDecision(reason="什么都不做"))


def test_ongoing_synthesis_gate_stays_open_below_threshold() -> None:
    state = _evidence_state(source_count=8, with_finding=True)
    Validator().validate(state, SearchDecision(
        issue_id="issue-0", query="继续搜索", purpose="independent"))


def test_first_reflection_gate_releases_after_a_finding_exists() -> None:
    state = _evidence_state(with_finding=True)
    Validator().validate(state, SearchDecision(
        issue_id="issue-0", query="针对剩余缺口继续搜索", purpose="followup"))


def test_compiler_exposes_first_reflection_as_a_protected_runtime_constraint(tmp_path) -> None:
    from opinion_search.investigation.context import Compiler
    from opinion_search.investigation.storage import Budget

    state = _evidence_state()
    run = SimpleNamespace(
        run_id="run", domain_state=state, next_step_index=9, committed_steps=(),
        active_step=SimpleNamespace(step_id="step", failures=()),
    )
    context = Compiler(Budget(tmp_path / "budget.json")).compile(run)
    constraint = next(
        section for section in context.sections
        if section.section_id == "memory.next_action_constraint"
    )
    payload = json.loads(constraint.content)
    assert payload["required_action"] == "reflect"
    assert "Prefer assessments=[]" in payload["minimum_result"]
    assert payload["allowed_issue_ids"] == ["issue-0", "issue-1", "issue-2"]
    assert payload["allowed_evidence_ids"] == [
        "evidence-0", "evidence-1", "evidence-2", "evidence-3"
    ]
    assert constraint.required is False
    assert constraint.compaction.value == "never"
    assert "memory.next_action_constraint" not in context.plan.dropped_section_ids
