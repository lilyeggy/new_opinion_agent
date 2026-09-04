import pytest

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.reducer import (
    ReducerInvariantError,
    reduce_opinion_state,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    FinalSynthesis,
    GapAssessment,
    GapStatus,
    InvestigationGap,
    OpinionSearchDelta,
    OpinionSearchState,
    Source,
    StakeholderPosition,
)


URL = "https://example.com/official"


def _state() -> OpinionSearchState:
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Find the primary account.",
                priority=5,
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=URL,
                url=URL,
                title="Official",
                snippet="Official announcement.",
                discovered_for_gap_ids=("gap-primary",),
            ),
        ),
    )


def _source_evidence() -> tuple[Source, Evidence]:
    return (
        Source(source_id=URL, url=URL, title="Official"),
        Evidence(
            evidence_id="evidence-official",
            source_id=URL,
            acquired_for_gap_id="gap-primary",
            excerpt="The official announcement confirms the date.",
            locator="Reader excerpt focused on date.",
        ),
    )


def test_reducer_applies_source_evidence_claim_and_resolution_atomically() -> None:
    source, evidence = _source_evidence()
    claim = Claim(
        claim_id="claim-date",
        text="The event date is confirmed.",
        kind=ClaimKind.FACT,
        supporting_evidence_ids=(evidence.evidence_id,),
        status=ClaimStatus.SUPPORTED,
    )
    delta = OpinionSearchDelta(
        add_sources=(source,),
        add_evidence=(evidence,),
        upsert_claims=(claim,),
        record_query_by_gap=(("gap-primary", "official announcement"),),
        record_source_attempt_by_gap=(("gap-primary", URL),),
        gap_assessments=(
            GapAssessment(
                gap_id="gap-primary",
                outcome=GapStatus.RESOLVED,
                evidence_ids=(evidence.evidence_id,),
                rationale="The primary account was verified.",
            ),
        ),
        append_reflections=("The primary account was verified.",),
        set_current_focus="Find independent confirmation.",
    )

    new_state = reduce_opinion_state(_state(), delta)

    assert new_state.read_source_ids == (URL,)
    assert tuple(item.evidence_id for item in new_state.evidence) == (
        "evidence-official",
    )
    assert new_state.claims == (claim,)
    assert new_state.resolved_gap_ids == ("gap-primary",)
    assert new_state.gaps[0].attempted_queries == ("official announcement",)
    assert new_state.current_focus == "Find independent confirmation."
    assert new_state.revision == 1
    assert reduce_opinion_state(new_state, delta) is new_state


def test_reducer_is_immutable_deterministic_and_semantically_idempotent() -> None:
    old_state = _state()
    delta = OpinionSearchDelta(
        record_query_by_gap=(("gap-primary", "official announcement"),)
    )

    first = reduce_opinion_state(old_state, delta)
    second = reduce_opinion_state(old_state, delta)
    replay = reduce_opinion_state(first, delta)

    assert old_state.gaps[0].attempted_queries == ()
    assert first == second
    assert replay is first
    assert replay.revision == 1


def test_reducer_commits_final_synthesis_once_and_rejects_overwrite() -> None:
    source, evidence = _source_evidence()
    state = reduce_opinion_state(
        _state(),
        OpinionSearchDelta(add_sources=(source,), add_evidence=(evidence,)),
    )
    synthesis = FinalSynthesis(
        summary="The official account confirms the date.",
        evidence_ids=(evidence.evidence_id,),
    )

    committed = reduce_opinion_state(
        state,
        OpinionSearchDelta(set_final_synthesis=synthesis),
    )

    assert committed.final_synthesis == synthesis
    assert reduce_opinion_state(
        committed,
        OpinionSearchDelta(set_final_synthesis=synthesis),
    ) is committed
    with pytest.raises(ReducerInvariantError, match="cannot be overwritten"):
        reduce_opinion_state(
            committed,
            OpinionSearchDelta(
                set_final_synthesis=FinalSynthesis(
                    summary="A different conclusion.",
                    evidence_ids=(evidence.evidence_id,),
                )
            ),
        )


def test_reducer_merges_claim_evidence_without_replacing_stable_identity() -> None:
    source, evidence = _source_evidence()
    second_evidence = Evidence(
        evidence_id="evidence-contradiction",
        source_id=URL,
        acquired_for_gap_id="gap-primary",
        excerpt="A correction disputes the original date.",
        locator="Correction paragraph.",
    )
    supported = Claim(
        claim_id="claim-date",
        text="The event date is confirmed.",
        kind=ClaimKind.FACT,
        supporting_evidence_ids=(evidence.evidence_id,),
        status=ClaimStatus.SUPPORTED,
    )
    state = reduce_opinion_state(
        _state(),
        OpinionSearchDelta(
            add_sources=(source,),
            add_evidence=(evidence, second_evidence),
            upsert_claims=(supported,),
        ),
    )
    contested = Claim(
        claim_id=supported.claim_id,
        text=supported.text,
        kind=supported.kind,
        contradicting_evidence_ids=(second_evidence.evidence_id,),
        status=ClaimStatus.CONTESTED,
    )

    updated = reduce_opinion_state(
        state,
        OpinionSearchDelta(upsert_claims=(contested,)),
    )

    assert updated.claims[0].status is ClaimStatus.CONTESTED
    assert updated.claims[0].supporting_evidence_ids == (evidence.evidence_id,)
    assert updated.claims[0].contradicting_evidence_ids == (
        second_evidence.evidence_id,
    )


def test_reducer_merges_position_evidence_for_stable_identity() -> None:
    source, evidence = _source_evidence()
    second_evidence = Evidence(
        evidence_id="evidence-position-second",
        source_id=URL,
        acquired_for_gap_id="gap-primary",
        excerpt="The organization repeats the same position.",
        locator="Follow-up paragraph.",
    )
    first = StakeholderPosition(
        position_id="position-organization",
        stakeholder="The organization",
        statement="The event date is confirmed.",
        evidence_ids=(evidence.evidence_id,),
    )
    state = reduce_opinion_state(
        _state(),
        OpinionSearchDelta(
            add_sources=(source,),
            add_evidence=(evidence, second_evidence),
            add_stakeholder_positions=(first,),
        ),
    )
    enriched = first.model_copy(update={"evidence_ids": (second_evidence.evidence_id,)})

    updated = reduce_opinion_state(
        state,
        OpinionSearchDelta(add_stakeholder_positions=(enriched,)),
    )

    assert updated.stakeholder_positions[0].evidence_ids == (
        evidence.evidence_id,
        second_evidence.evidence_id,
    )


def test_reducer_rejects_dangling_facts_and_unsupported_resolution() -> None:
    source, evidence = _source_evidence()

    with pytest.raises(ReducerInvariantError, match="without a candidate"):
        reduce_opinion_state(
            OpinionSearchState(
                request=SearchRequest(question="What happened?"),
                gaps=_state().gaps,
            ),
            OpinionSearchDelta(add_sources=(source,)),
        )

    with pytest.raises(ReducerInvariantError, match="unknown evidence"):
        reduce_opinion_state(
            _state(),
            OpinionSearchDelta(
                gap_assessments=(
                    GapAssessment(
                        gap_id="gap-primary",
                        outcome=GapStatus.RESOLVED,
                        evidence_ids=("evidence-missing",),
                        rationale="Resolved with missing evidence.",
                    ),
                ),
            ),
        )

    with pytest.raises(ReducerInvariantError, match="unknown source"):
        reduce_opinion_state(
            _state(),
            OpinionSearchDelta(add_evidence=(evidence,)),
        )


def test_blocked_gap_preserves_missing_evidence_as_an_explicit_outcome() -> None:
    blocked = reduce_opinion_state(
        _state(),
        OpinionSearchDelta(
            gap_assessments=(
                GapAssessment(
                    gap_id="gap-primary",
                    outcome=GapStatus.BLOCKED,
                    rationale="No accessible primary source was found.",
                ),
            ),
        ),
    )

    assert blocked.gaps[0].status is GapStatus.BLOCKED
    assert blocked.blocked_gap_ids == ("gap-primary",)
