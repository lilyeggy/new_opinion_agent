"""A bounded investigation must be able to close as partial instead of spinning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from opinion_search.domain.investigation.engine import (
    completion,
    partial_finish_allowed,
    required_next_action,
)
from opinion_search.domain.investigation.models import (
    Evidence,
    Finding,
    FindingProposal,
    FinishDecision,
    InvestigationRequest,
    Issue,
    ReviewRecord,
    SearchAttempt,
    SourceVersion,
    State,
    finding_hash,
    uid,
    utcnow,
)
from opinion_search.investigation.service import ConsolidationValidator, Validator
from opinion_search.investigation.storage import Budget, atomic_json
from opinion_search.runtime.completion import CompletionDisposition


def _source(index: int) -> SourceVersion:
    url = f"https://example.org/{index}"
    return SourceVersion(
        version_id=f"v{index}",
        url=url,
        final_url=url,
        title="报道",
        fetched_at=utcnow(),
        artifact_ref="artifact://sha256/" + str(index) * 64,
        content_hash=str(index) * 64,
    )


def _progressive_state() -> State:
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("起因", "回应", "后续"))
    excerpt = "品牌方表示会持续改进。"
    evidence = Evidence(
        evidence_id="e1", version_id="v1", excerpt=excerpt,
        start=0, end=len(excerpt), locator=f"Reader text chars 0:{len(excerpt)}",
    )
    proposal = FindingProposal(
        issue_id=issues[1].issue_id,
        text="品牌方表示会持续改进。",
        kind="fact",
        evidence_ids=("e1",),
    )
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", "closeout"))
    review = ReviewRecord(
        finding_id=finding.finding_id,
        verdict="supported",
        reason="原文支持",
        finding_hash=finding_hash(finding),
        model="test",
        reviewed_at=utcnow(),
    )
    searches = tuple(
        SearchAttempt(
            issue_id=issues[1].issue_id,
            query=f"q-{index}",
            purpose=purpose,
            page=0,
            outcome="empty",
            count=0,
        )
        for index, purpose in enumerate(("official_response", "event_response", "followup"))
    )
    return State(
        request=InvestigationRequest(question="事件调查"),
        subject="事件调查",
        cutoff=utcnow(),
        issues=issues,
        sources=(_source(1), _source(2)),
        evidence=(evidence,),
        findings=(finding,),
        reviews=(review,),
        searches=searches,
        read_attempts=("https://example.org/1", "https://example.org/2", "https://example.org/3"),
    )


def test_completion_accepts_a_bounded_partial_with_open_required_questions():
    state = _progressive_state()

    assert partial_finish_allowed(state) is True
    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.ACCEPT_PARTIAL
    assert "partial report" in verdict.reason
    assert "后续" in verdict.reason


def test_unreviewed_findings_keep_the_bounded_partial_gate_closed():
    state = _progressive_state().model_copy(update={"reviews": ()})

    assert partial_finish_allowed(state) is False
    verdict = completion(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE


def test_stale_negative_finding_prevents_a_bounded_partial_finish():
    state = _progressive_state()
    issue_id = state.issues[0].issue_id
    stale = Finding(
        issue_id=issue_id,
        text="品牌方尚未公开回应事件。",
        kind="fact",
        evidence_ids=("e1",),
        response="not_found",
        finding_id="finding-stale-closeout",
    )
    stale_review = ReviewRecord(
        finding_id=stale.finding_id,
        verdict="supported",
        reason="构造的当前审查",
        finding_hash=finding_hash(stale),
        model="test",
        reviewed_at=utcnow(),
    )
    response_evidence = Evidence(
        evidence_id="e2",
        version_id="v2",
        excerpt="品牌方已发布声明回应事件。",
        start=0,
        end=15,
        locator="Reader text chars 0:15",
    )
    state = state.model_copy(update={
        "findings": (*state.findings, stale),
        "reviews": (*state.reviews, stale_review),
        "evidence": (*state.evidence, response_evidence),
    })

    assert partial_finish_allowed(state) is False
    verdict = completion(state)
    next_action = required_next_action(state)

    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert stale.finding_id in verdict.reason
    assert next_action is not None
    assert next_action["required_action"] == "reflect"
    assert next_action["finding_ids"] == [stale.finding_id]


def test_consolidation_requires_finish_once_partial_closeout_is_allowed(tmp_path):
    state = _progressive_state()
    budget_path = tmp_path / "budget.json"
    atomic_json(budget_path, {
        "started_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
        "accumulated_seconds": 0.0,
        "search": 0,
        "read": 0,
        "model": 0,
        "limits": {"search": 20, "read": 24, "model": 120, "seconds": 2400, "consolidate_seconds": 1},
    })
    guarded = ConsolidationValidator(Validator(), Budget(budget_path))

    try:
        guarded.validate(state, _search_decision(state))
    except ValueError as exc:
        assert "finish now with a partial report" in str(exc)
    else:
        raise AssertionError("consolidation must reject further acquisition")

    try:
        guarded.validate(state, _search_decision_with_unknown_issue())
    except ValueError as exc:
        assert "finish now with a partial report" in str(exc)
    else:
        raise AssertionError("closeout must take precedence over inner validation")

    finding_id = state.findings[0].finding_id
    guarded.validate(state, FinishDecision(conclusion_ids=(finding_id,)))


def _search_decision(state: State):
    from opinion_search.domain.investigation.models import SearchDecision

    return SearchDecision(issue_id=state.issues[0].issue_id, query="另一种搜索方向", purpose="original")


def _search_decision_with_unknown_issue():
    from opinion_search.domain.investigation.models import SearchDecision

    return SearchDecision(issue_id="unknown-issue", query="无效新搜索", purpose="original")
