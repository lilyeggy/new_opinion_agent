import pytest
from pydantic import ValidationError

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    Source,
)


URL = "https://example.com/official"


def _valid_state() -> OpinionSearchState:
    gap = InvestigationGap(
        gap_id="gap-primary",
        question="What does the primary source say?",
        priority=5,
        status=GapStatus.RESOLVED,
        attempted_queries=("official announcement",),
        attempted_source_ids=(URL,),
        evidence_ids=("evidence-official",),
        resolution_note="The source was read.",
    )
    candidate = CandidateSource(
        source_id=URL,
        url=URL,
        title="Official announcement",
        snippet="The organization published an announcement.",
        discovered_for_gap_ids=(gap.gap_id,),
    )
    source = Source(
        source_id=URL,
        url=URL,
        title=candidate.title,
        artifact_ref="artifact-official",
    )
    evidence = Evidence(
        evidence_id="evidence-official",
        source_id=URL,
        acquired_for_gap_id=gap.gap_id,
        excerpt="The announcement states the event date.",
        locator="Reader excerpt focused on the event date.",
    )
    claim = Claim(
        claim_id="claim-date",
        text="The event occurred on the announced date.",
        kind=ClaimKind.FACT,
        supporting_evidence_ids=(evidence.evidence_id,),
        status=ClaimStatus.SUPPORTED,
    )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(gap,),
        candidates=(candidate,),
        sources=(source,),
        evidence=(evidence,),
        claims=(claim,),
        reflections=("The primary account is available.",),
        revision=4,
    )


def test_opinion_search_state_round_trips_rich_domain_json() -> None:
    state = _valid_state()

    restored = OpinionSearchState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert restored.open_gap_ids == ()
    assert restored.resolved_gap_ids == ("gap-primary",)
    assert restored.candidate_source_ids == (URL,)
    assert restored.read_source_ids == (URL,)


@pytest.mark.parametrize(
    ("field_name", "duplicate"),
    [
        ("gaps", lambda state: state.gaps + state.gaps),
        ("candidates", lambda state: state.candidates + state.candidates),
        ("sources", lambda state: state.sources + state.sources),
        ("evidence", lambda state: state.evidence + state.evidence),
        ("claims", lambda state: state.claims + state.claims),
        ("reflections", lambda state: state.reflections + state.reflections),
    ],
)
def test_state_rejects_duplicate_stable_objects(
    field_name: str,
    duplicate,
) -> None:
    state = _valid_state()
    payload = state.model_dump(mode="python")
    payload[field_name] = duplicate(state)

    with pytest.raises(ValidationError, match="must be unique"):
        OpinionSearchState.model_validate(payload)


def test_state_rejects_dangling_source_evidence_and_claim_links() -> None:
    state = _valid_state()

    with pytest.raises(ValidationError, match="originate from a candidate"):
        OpinionSearchState.model_validate(
            state.model_copy(update={"candidates": ()}).model_dump()
        )

    with pytest.raises(ValidationError, match="unknown source"):
        bad_evidence = state.evidence[0].model_copy(
            update={"source_id": "https://example.com/missing"}
        )
        OpinionSearchState.model_validate(
            state.model_copy(update={"evidence": (bad_evidence,)}).model_dump()
        )

    with pytest.raises(ValidationError, match="unknown evidence"):
        bad_claim = Claim(
            claim_id="claim-missing",
            text="Unsupported claim.",
            kind=ClaimKind.FACT,
            supporting_evidence_ids=("evidence-missing",),
            status=ClaimStatus.SUPPORTED,
        )
        OpinionSearchState.model_validate(
            state.model_copy(update={"claims": (bad_claim,)}).model_dump()
        )


def test_claim_status_is_derived_from_evidence_relationships() -> None:
    with pytest.raises(ValidationError, match="requires at least one"):
        Claim(
            claim_id="claim-unlinked",
            text="An unlinked claim.",
            kind=ClaimKind.INTERPRETATION,
            status=ClaimStatus.UNRESOLVED,
        )

    with pytest.raises(ValidationError, match="must be derived"):
        Claim(
            claim_id="claim-invalid",
            text="A claim.",
            kind=ClaimKind.FACT,
            supporting_evidence_ids=("evidence-1",),
            status=ClaimStatus.UNRESOLVED,
        )

    with pytest.raises(ValidationError, match="both support and contradict"):
        Claim(
            claim_id="claim-overlap",
            text="A contested claim.",
            kind=ClaimKind.FACT,
            supporting_evidence_ids=("evidence-1",),
            contradicting_evidence_ids=("evidence-1",),
            status=ClaimStatus.CONTESTED,
        )


def test_closed_gap_requires_a_reason_and_state_is_immutable() -> None:
    with pytest.raises(ValidationError, match="requires a resolution note"):
        InvestigationGap(
            gap_id="gap-closed",
            question="Was it resolved?",
            status=GapStatus.RESOLVED,
        )

    state = _valid_state()
    with pytest.raises(ValidationError):
        state.revision = 5
