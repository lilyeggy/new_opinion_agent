from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.domain.opinion.state import OpinionSearchState


NonEmptyText = Annotated[str, Field(min_length=1)]


class ProvenanceInvariantError(ValueError):
    """Raised when a provenance relation contradicts the committed State."""


class _ProvenanceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class EvidenceProvenance(_ProvenanceModel):
    evidence_id: NonEmptyText
    source_id: NonEmptyText
    acquired_for_gap_id: NonEmptyText
    semantic_gap_ids: tuple[NonEmptyText, ...]
    supporting_claim_ids: tuple[NonEmptyText, ...]
    contradicting_claim_ids: tuple[NonEmptyText, ...]
    position_ids: tuple[NonEmptyText, ...]
    narrative_ids: tuple[NonEmptyText, ...]

    @property
    def unlinked(self) -> bool:
        return not (
            self.semantic_gap_ids
            or self.supporting_claim_ids
            or self.contradicting_claim_ids
            or self.position_ids
            or self.narrative_ids
        )


class ProvenanceIndex(_ProvenanceModel):
    """Deterministic, pure projection of every Evidence relation in a State.

    Record order equals committed ``state.evidence`` order so the tail is the
    most recently acquired evidence. Acquisition intent (``acquired_for_gap_id``)
    is kept separate from semantic relations; acquisition alone does not link
    an Evidence.
    """

    evidence: tuple[EvidenceProvenance, ...]

    def record(self, evidence_id: str) -> EvidenceProvenance:
        for record in self.evidence:
            if record.evidence_id == evidence_id:
                return record
        raise ProvenanceInvariantError(f"unknown evidence id: {evidence_id}")

    def evidence_ids_for_gap(self, gap_id: str) -> tuple[str, ...]:
        return tuple(
            record.evidence_id
            for record in self.evidence
            if gap_id in record.semantic_gap_ids
        )

    def source_ids_for_gap(self, gap_id: str) -> tuple[str, ...]:
        source_ids: list[str] = []
        for record in self.evidence:
            if gap_id in record.semantic_gap_ids and record.source_id not in source_ids:
                source_ids.append(record.source_id)
        return tuple(source_ids)

    def unlinked_evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            record.evidence_id for record in self.evidence if record.unlinked
        )


def build_provenance_index(state: OpinionSearchState) -> ProvenanceIndex:
    evidence_ids = {item.evidence_id for item in state.evidence}

    for gap in state.gaps:
        _require_known(gap.evidence_ids, evidence_ids, "gap", gap.gap_id)
    for claim in state.claims:
        _require_known(
            claim.supporting_evidence_ids,
            evidence_ids,
            "claim",
            claim.claim_id,
        )
        _require_known(
            claim.contradicting_evidence_ids,
            evidence_ids,
            "claim",
            claim.claim_id,
        )
    for position in state.stakeholder_positions:
        _require_known(
            position.evidence_ids,
            evidence_ids,
            "stakeholder position",
            position.position_id,
        )
    for narrative in state.narratives:
        _require_known(
            narrative.evidence_ids,
            evidence_ids,
            "narrative",
            narrative.narrative_id,
        )

    semantic_gap_ids: dict[str, list[str]] = {}
    for gap in state.gaps:
        for evidence_id in gap.evidence_ids:
            semantic_gap_ids.setdefault(evidence_id, []).append(gap.gap_id)

    supporting_claims: dict[str, list[str]] = {}
    contradicting_claims: dict[str, list[str]] = {}
    for claim in state.claims:
        for evidence_id in claim.supporting_evidence_ids:
            supporting_claims.setdefault(evidence_id, []).append(claim.claim_id)
        for evidence_id in claim.contradicting_evidence_ids:
            contradicting_claims.setdefault(evidence_id, []).append(claim.claim_id)

    position_ids: dict[str, list[str]] = {}
    for position in state.stakeholder_positions:
        for evidence_id in position.evidence_ids:
            position_ids.setdefault(evidence_id, []).append(position.position_id)

    narrative_ids: dict[str, list[str]] = {}
    for narrative in state.narratives:
        for evidence_id in narrative.evidence_ids:
            narrative_ids.setdefault(evidence_id, []).append(narrative.narrative_id)

    records = tuple(
        EvidenceProvenance(
            evidence_id=item.evidence_id,
            source_id=item.source_id,
            acquired_for_gap_id=item.acquired_for_gap_id,
            semantic_gap_ids=tuple(semantic_gap_ids.get(item.evidence_id, ())),
            supporting_claim_ids=tuple(supporting_claims.get(item.evidence_id, ())),
            contradicting_claim_ids=tuple(
                contradicting_claims.get(item.evidence_id, ())
            ),
            position_ids=tuple(position_ids.get(item.evidence_id, ())),
            narrative_ids=tuple(narrative_ids.get(item.evidence_id, ())),
        )
        for item in state.evidence
    )
    return ProvenanceIndex(evidence=records)


def _require_known(
    evidence_ids: tuple[str, ...],
    known: set[str],
    owner: str,
    owner_id: str,
) -> None:
    unknown = tuple(evidence_id for evidence_id in evidence_ids if evidence_id not in known)
    if unknown:
        raise ProvenanceInvariantError(
            f"{owner} {owner_id} references unknown evidence: {list(unknown)}"
        )
