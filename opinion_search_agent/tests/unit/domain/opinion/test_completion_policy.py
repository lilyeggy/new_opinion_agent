from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.completion import OpinionSearchCompletionPolicy
from opinion_search.domain.opinion.decisions import FinishDecision
from opinion_search.domain.opinion.state import (
    COUNTER_NARRATIVES_GAP_ID,
    DOMINANT_NARRATIVES_GAP_ID,
    FACTUAL_BASELINE_GAP_ID,
    STAKEHOLDER_POSITIONS_GAP_ID,
    CandidateSource,
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    GapStatus,
    InvestigationGap,
    Narrative,
    NarrativeKind,
    OpinionSearchState,
    Source,
    SourceKind,
    StakeholderPosition,
)
from opinion_search.runtime.completion import CompletionDisposition


OFFICIAL_URL = "https://example.com/official"
REPORT_URL = "https://news.example.com/report"


def _state(
    *,
    counter_status: GapStatus = GapStatus.RESOLVED,
    with_claim: bool = True,
) -> OpinionSearchState:
    evidence = (
        Evidence(
            evidence_id="evidence-baseline",
            source_id=OFFICIAL_URL,
            acquired_for_gap_id=FACTUAL_BASELINE_GAP_ID,
            excerpt="The organization confirms the event.",
            locator="Official opening paragraph.",
        ),
        Evidence(
            evidence_id="evidence-narrative",
            source_id=REPORT_URL,
            acquired_for_gap_id=DOMINANT_NARRATIVES_GAP_ID,
            excerpt="Coverage frames the event as a major policy change.",
            locator="Report paragraph 2.",
        ),
        Evidence(
            evidence_id="evidence-counter",
            source_id=REPORT_URL,
            acquired_for_gap_id=COUNTER_NARRATIVES_GAP_ID,
            excerpt="Critics dispute whether the change is material.",
            locator="Report paragraph 4.",
        ),
    )
    gaps = (
        InvestigationGap(
            gap_id=FACTUAL_BASELINE_GAP_ID,
            question="Establish the factual baseline.",
            status=GapStatus.RESOLVED,
            evidence_ids=("evidence-baseline",),
            resolution_note="The event is established.",
        ),
        InvestigationGap(
            gap_id=STAKEHOLDER_POSITIONS_GAP_ID,
            question="Map stakeholder positions.",
            status=GapStatus.RESOLVED,
            evidence_ids=("evidence-baseline",),
            resolution_note="The organization position is recorded.",
        ),
        InvestigationGap(
            gap_id=DOMINANT_NARRATIVES_GAP_ID,
            question="Map dominant narratives.",
            status=GapStatus.RESOLVED,
            evidence_ids=("evidence-narrative",),
            resolution_note="A dominant framing is recorded.",
        ),
        InvestigationGap(
            gap_id=COUNTER_NARRATIVES_GAP_ID,
            question="Map counter-narratives.",
            status=counter_status,
            evidence_ids=(
                ("evidence-counter",) if counter_status is not GapStatus.BLOCKED else ()
            ),
            resolution_note=(
                "A counter-frame is recorded."
                if counter_status is GapStatus.RESOLVED
                else "No accessible counter-frame was found."
                if counter_status is GapStatus.BLOCKED
                else None
            ),
        ),
    )
    claims = (
        (
            Claim(
                claim_id="claim-event",
                text="The event occurred.",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=("evidence-baseline",),
                status=ClaimStatus.SUPPORTED,
            ),
        )
        if with_claim
        else ()
    )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=gaps,
        candidates=tuple(
            CandidateSource(
                source_id=url,
                url=url,
                title=title,
                snippet="Public account.",
                discovered_for_gap_ids=(FACTUAL_BASELINE_GAP_ID,),
            )
            for url, title in (
                (OFFICIAL_URL, "Official"),
                (REPORT_URL, "Independent report"),
            )
        ),
        sources=(
            Source(
                source_id=OFFICIAL_URL,
                url=OFFICIAL_URL,
                title="Official",
                source_kind=SourceKind.PRIMARY,
            ),
            Source(
                source_id=REPORT_URL,
                url=REPORT_URL,
                title="Independent report",
                source_kind=SourceKind.REPORTING,
            ),
        ),
        evidence=evidence,
        claims=claims,
        stakeholder_positions=(
            StakeholderPosition(
                position_id="position-organization",
                stakeholder="The organization",
                statement="The event is a major policy change.",
                evidence_ids=("evidence-baseline",),
            ),
        ),
        narratives=(
            Narrative(
                narrative_id="narrative-dominant",
                summary="The event is framed as a major policy change.",
                kind=NarrativeKind.DOMINANT,
                evidence_ids=("evidence-narrative",),
            ),
            Narrative(
                narrative_id="narrative-counter",
                summary="Critics frame the change as incremental.",
                kind=NarrativeKind.COUNTER,
                evidence_ids=("evidence-counter",),
            ),
        ),
    )


def _proposal(state: OpinionSearchState) -> FinishDecision:
    return FinishDecision(
        action="finish",
        answer_candidate="Proposed answer.",
        resolved_gap_ids=state.resolved_gap_ids,
        unresolved_gap_ids=state.open_gap_ids,
    )


def test_completion_accepts_opinion_specific_coverage() -> None:
    state = _state()

    verdict = OpinionSearchCompletionPolicy().evaluate(state, _proposal(state))

    assert verdict.disposition is CompletionDisposition.ACCEPT_COMPLETE


def test_completion_rejects_open_dimension_and_mismatched_proposal() -> None:
    original = _state()
    state = OpinionSearchState.model_validate(
        original.model_copy(
            update={
                "gaps": original.gaps[:-1]
                + (
                    original.gaps[-1].model_copy(
                        update={"status": GapStatus.OPEN, "resolution_note": None}
                    ),
                )
            }
        ).model_dump()
    )

    open_verdict = OpinionSearchCompletionPolicy().evaluate(
        state,
        _proposal(state),
    )
    mismatch = OpinionSearchCompletionPolicy().evaluate(
        state,
        FinishDecision(
            action="finish",
            answer_candidate="Incorrect accounting.",
            resolved_gap_ids=tuple(gap.gap_id for gap in state.gaps),
            unresolved_gap_ids=(),
        ),
    )

    assert open_verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert mismatch.disposition is CompletionDisposition.REJECT_AND_CONTINUE


def test_completion_returns_partial_for_blocked_or_uninterpreted_evidence() -> None:
    blocked = _state(counter_status=GapStatus.BLOCKED)
    no_claim = _state(with_claim=False)

    assert (
        OpinionSearchCompletionPolicy()
        .evaluate(blocked, _proposal(blocked))
        .disposition
        is CompletionDisposition.ACCEPT_PARTIAL
    )
    assert (
        OpinionSearchCompletionPolicy()
        .evaluate(no_claim, _proposal(no_claim))
        .disposition
        is CompletionDisposition.ACCEPT_PARTIAL
    )


def test_completion_uses_linked_source_records_not_model_source_labels() -> None:
    original = _state()
    arbitrary_labels = OpinionSearchState.model_validate(
        original.model_copy(
            update={
                "sources": tuple(
                    source.model_copy(update={"source_kind": SourceKind.OTHER})
                    for source in original.sources
                )
            }
        ).model_dump()
    )
    unlinked_second_source = OpinionSearchState.model_validate(
        original.model_copy(
            update={
                "evidence": tuple(
                    item.model_copy(update={"source_id": OFFICIAL_URL})
                    for item in original.evidence
                )
            }
        ).model_dump()
    )

    label_verdict = OpinionSearchCompletionPolicy().evaluate(
        arbitrary_labels,
        _proposal(arbitrary_labels),
    )
    unlinked_verdict = OpinionSearchCompletionPolicy().evaluate(
        unlinked_second_source,
        _proposal(unlinked_second_source),
    )

    assert label_verdict.disposition is CompletionDisposition.ACCEPT_COMPLETE
    assert unlinked_verdict.disposition is CompletionDisposition.ACCEPT_PARTIAL
    assert "distinct" in unlinked_verdict.reason
