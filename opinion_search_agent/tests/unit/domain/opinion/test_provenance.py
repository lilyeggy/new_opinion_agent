import pytest
from pydantic import ValidationError

from opinion_search.domain.opinion.provenance import (
    ProvenanceIndex,
    ProvenanceInvariantError,
    build_provenance_index,
)
from opinion_search.domain.opinion.state import (
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
    StakeholderPosition,
)
from opinion_search.app.contracts import SearchRequest


def _base_state() -> OpinionSearchState:
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(gap_id="gap-a", question="A.", priority=5),
            InvestigationGap(gap_id="gap-b", question="B.", priority=4),
        ),
    )


def _state_with_evidence(*, unlinked: bool = False) -> OpinionSearchState:
    source_a = Source(
        source_id="https://example.com/a",
        url="https://example.com/a",
        title="A",
    )
    source_b = Source(
        source_id="https://example.com/b",
        url="https://example.com/b",
        title="B",
    )
    evidence_a = Evidence(
        evidence_id="evidence-a",
        source_id=source_a.source_id,
        acquired_for_gap_id="gap-a",
        excerpt="A says X.",
        locator="1.",
    )
    evidence_b = Evidence(
        evidence_id="evidence-b",
        source_id=source_b.source_id,
        acquired_for_gap_id="gap-b",
        excerpt="B says Y.",
        locator="1.",
    )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-a",
                question="A.",
                priority=5,
                status=GapStatus.RESOLVED,
                evidence_ids=("evidence-a",),
                resolution_note="resolved by a",
            ),
            InvestigationGap(
                gap_id="gap-b",
                question="B.",
                priority=4,
                status=GapStatus.OPEN,
                evidence_ids=() if unlinked else ("evidence-b",),
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=source_a.source_id,
                url=source_a.url,
                title="A",
                snippet="A.",
                discovered_for_gap_ids=("gap-a",),
            ),
            CandidateSource(
                source_id=source_b.source_id,
                url=source_b.url,
                title="B",
                snippet="B.",
                discovered_for_gap_ids=("gap-b",),
            ),
        ),
        sources=(source_a, source_b),
        evidence=(evidence_a, evidence_b),
        claims=(
            Claim(
                claim_id="claim-1",
                text="X occurred.",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=("evidence-a",),
                status=ClaimStatus.SUPPORTED,
            ),
        ),
        stakeholder_positions=(
            StakeholderPosition(
                position_id="position-1",
                stakeholder="A",
                statement="We did X.",
                evidence_ids=("evidence-a",),
            ),
        ),
        narratives=(
            Narrative(
                narrative_id="narrative-1",
                summary="Counter framing.",
                kind=NarrativeKind.COUNTER,
                evidence_ids=("evidence-a",),
            ),
        ),
    )


def test_one_evidence_linked_through_every_relation_type() -> None:
    index = build_provenance_index(_state_with_evidence())
    record = index.record("evidence-a")

    assert record.evidence_id == "evidence-a"
    assert record.source_id == "https://example.com/a"
    assert record.acquired_for_gap_id == "gap-a"
    assert record.semantic_gap_ids == ("gap-a",)
    assert record.supporting_claim_ids == ("claim-1",)
    assert record.contradicting_claim_ids == ()
    assert record.position_ids == ("position-1",)
    assert record.narrative_ids == ("narrative-1",)


def test_supporting_and_contradicting_claim_links_remain_distinct() -> None:
    state = _state_with_evidence()
    state = state.model_copy(
        update={
            "claims": (
                Claim(
                    claim_id="claim-support",
                    text="Supports X.",
                    kind=ClaimKind.FACT,
                    supporting_evidence_ids=("evidence-a",),
                    status=ClaimStatus.SUPPORTED,
                ),
                Claim(
                    claim_id="claim-contra",
                    text="Contradicts X.",
                    kind=ClaimKind.FACT,
                    contradicting_evidence_ids=("evidence-a",),
                    status=ClaimStatus.CONTESTED,
                ),
            ),
        }
    )
    index = build_provenance_index(state)
    record = index.record("evidence-a")
    assert record.supporting_claim_ids == ("claim-support",)
    assert record.contradicting_claim_ids == ("claim-contra",)


def test_one_evidence_can_cover_multiple_gaps() -> None:
    state = _state_with_evidence()
    state = state.model_copy(
        update={
            "gaps": (
                InvestigationGap(
                    gap_id="gap-a",
                    question="A.",
                    priority=5,
                    status=GapStatus.RESOLVED,
                    evidence_ids=("evidence-a",),
                    resolution_note="r",
                ),
                InvestigationGap(
                    gap_id="gap-b",
                    question="B.",
                    priority=4,
                    status=GapStatus.RESOLVED,
                    evidence_ids=("evidence-a", "evidence-b"),
                    resolution_note="r2",
                ),
            )
        }
    )
    index = build_provenance_index(state)
    record = index.record("evidence-a")
    assert record.semantic_gap_ids == ("gap-a", "gap-b")


def test_acquisition_gap_differs_from_semantic_gap() -> None:
    # evidence-b acquired for gap-b but covers gap-a semantically which is NOT
    # allowed here (evidence-b not in gap-a.evidence_ids); instead assert
    # acquisition is preserved separately from semantic in the same record.
    state = _state_with_evidence()
    state = state.model_copy(
        update={
            "gaps": (
                InvestigationGap(
                    gap_id="gap-a",
                    question="A.",
                    priority=5,
                    status=GapStatus.RESOLVED,
                    evidence_ids=("evidence-b",),
                    resolution_note="r",
                ),
                InvestigationGap(
                    gap_id="gap-b",
                    question="B.",
                    priority=4,
                    status=GapStatus.OPEN,
                ),
            )
        }
    )
    index = build_provenance_index(state)
    record = index.record("evidence-b")
    assert record.acquired_for_gap_id == "gap-b"
    assert record.semantic_gap_ids == ("gap-a",)


def test_unlinked_evidence_detection() -> None:
    index = build_provenance_index(_state_with_evidence(unlinked=True))
    # evidence-b has no semantic gap (gap-b has no evidence_ids), no claim,
    # position or narrative reference.
    assert index.unlinked_evidence_ids() == ("evidence-b",)
    assert index.evidence_ids_for_gap("gap-b") == ()


def test_evidence_ids_and_source_ids_for_gap() -> None:
    index = build_provenance_index(_state_with_evidence())
    assert index.evidence_ids_for_gap("gap-a") == ("evidence-a",)
    # gap-b semantically references evidence-b
    assert index.evidence_ids_for_gap("gap-b") == ("evidence-b",)
    assert index.source_ids_for_gap("gap-a") == ("https://example.com/a",)
    assert index.source_ids_for_gap("gap-b") == ("https://example.com/b",)


def test_duplicate_free_deterministic_order() -> None:
    index = build_provenance_index(_state_with_evidence())
    assert len(index.evidence) == 2
    assert [r.evidence_id for r in index.evidence] == ["evidence-a", "evidence-b"]


def test_model_json_round_trip() -> None:
    index = build_provenance_index(_state_with_evidence())
    restored = ProvenanceIndex.model_validate_json(index.model_dump_json())
    assert restored == index
    assert restored.record("evidence-a") == index.record("evidence-a")


def test_unknown_link_fails_closed() -> None:
    state = _base_state()
    state = state.model_copy(
        update={
            "candidates": (
                CandidateSource(
                    source_id="https://example.com/a",
                    url="https://example.com/a",
                    title="A",
                    snippet="A.",
                    discovered_for_gap_ids=("gap-a",),
                ),
            ),
            "sources": (
                Source(
                    source_id="https://example.com/a",
                    url="https://example.com/a",
                    title="A",
                ),
            ),
            "evidence": (),
            "gaps": (
                InvestigationGap(
                    gap_id="gap-a",
                    question="A.",
                    priority=5,
                    status=GapStatus.RESOLVED,
                    evidence_ids=("evidence-missing",),
                    resolution_note="r",
                ),
            ),
        }
    )
    # build_provenance_index must not expose dict insertion order as a contract;
    # the gap references an unknown evidence id and must fail closed.
    with pytest.raises(ProvenanceInvariantError):
        build_provenance_index(state)


def test_unknown_record_lookup_fails_closed() -> None:
    index = build_provenance_index(_state_with_evidence())
    with pytest.raises(ProvenanceInvariantError):
        index.record("evidence-does-not-exist")


def test_index_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProvenanceIndex.model_validate({"evidence": [], "extra": 1})
