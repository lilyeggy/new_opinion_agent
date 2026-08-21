from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.app.contracts import SearchRequest


NonEmptyText = Annotated[str, Field(min_length=1)]
PublicUrl = Annotated[str, Field(pattern=r"^https?://")]
Revision = Annotated[int, Field(ge=0)]

FACTUAL_BASELINE_GAP_ID = "gap-factual-baseline"
STAKEHOLDER_POSITIONS_GAP_ID = "gap-stakeholder-positions"
DOMINANT_NARRATIVES_GAP_ID = "gap-dominant-narratives"
COUNTER_NARRATIVES_GAP_ID = "gap-counter-narratives"


class GapStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


class SourceKind(StrEnum):
    PRIMARY = "primary"
    REPORTING = "reporting"
    ANALYSIS = "analysis"
    OTHER = "other"


class ClaimKind(StrEnum):
    FACT = "fact"
    ATTRIBUTED_STATEMENT = "attributed_statement"
    INTERPRETATION = "interpretation"


class ClaimStatus(StrEnum):
    UNRESOLVED = "unresolved"
    SUPPORTED = "supported"
    CONTESTED = "contested"


class NarrativeKind(StrEnum):
    DOMINANT = "dominant"
    COUNTER = "counter"
    EMERGING = "emerging"


class _DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class InvestigationGap(_DomainModel):
    gap_id: NonEmptyText
    question: NonEmptyText
    priority: Annotated[int, Field(ge=1, le=5)] = 3
    status: GapStatus = GapStatus.OPEN
    attempted_queries: tuple[NonEmptyText, ...] = ()
    attempted_source_ids: tuple[NonEmptyText, ...] = ()
    evidence_ids: tuple[NonEmptyText, ...] = ()
    resolution_note: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.status is GapStatus.OPEN and self.resolution_note is not None:
            raise ValueError("open gap cannot have a resolution note")
        if self.status is not GapStatus.OPEN and self.resolution_note is None:
            raise ValueError("closed gap requires a resolution note")
        if self.status is GapStatus.RESOLVED and not self.evidence_ids:
            raise ValueError("resolved gap requires evidence")
        _require_unique(self.attempted_queries, "attempted queries")
        _require_unique(self.attempted_source_ids, "attempted source IDs")
        _require_unique(self.evidence_ids, "gap evidence IDs")
        return self


class CandidateSource(_DomainModel):
    source_id: NonEmptyText
    url: PublicUrl
    title: NonEmptyText
    snippet: NonEmptyText
    discovered_for_gap_ids: tuple[NonEmptyText, ...]
    source_kind: SourceKind = SourceKind.OTHER

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.source_id != self.url:
            raise ValueError("candidate source_id must equal its canonical URL")
        if not self.discovered_for_gap_ids:
            raise ValueError("candidate must be associated with a gap")
        _require_unique(self.discovered_for_gap_ids, "candidate gap IDs")
        return self


class Source(_DomainModel):
    source_id: NonEmptyText
    url: PublicUrl
    final_url: PublicUrl | None = None
    title: NonEmptyText
    source_kind: SourceKind = SourceKind.OTHER
    artifact_ref: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.source_id != self.url:
            raise ValueError("source_id must equal the requested canonical URL")
        return self


class Evidence(_DomainModel):
    evidence_id: NonEmptyText
    source_id: NonEmptyText
    acquired_for_gap_id: NonEmptyText
    excerpt: NonEmptyText
    locator: NonEmptyText


class Claim(_DomainModel):
    claim_id: NonEmptyText
    text: NonEmptyText
    kind: ClaimKind
    supporting_evidence_ids: tuple[NonEmptyText, ...] = ()
    contradicting_evidence_ids: tuple[NonEmptyText, ...] = ()
    status: ClaimStatus

    @model_validator(mode="after")
    def validate_evidence_status(self) -> Self:
        _require_unique(self.supporting_evidence_ids, "supporting evidence IDs")
        _require_unique(
            self.contradicting_evidence_ids,
            "contradicting evidence IDs",
        )
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("claim evidence cannot both support and contradict")
        if not (self.supporting_evidence_ids or self.contradicting_evidence_ids):
            raise ValueError("claim requires at least one evidence reference")
        expected = claim_status_for(
            self.supporting_evidence_ids,
            self.contradicting_evidence_ids,
        )
        if self.status is not expected:
            raise ValueError(
                f"claim status must be derived from evidence: {expected.value}"
            )
        return self


class StakeholderPosition(_DomainModel):
    position_id: NonEmptyText
    stakeholder: NonEmptyText
    statement: NonEmptyText
    evidence_ids: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if not self.evidence_ids:
            raise ValueError("stakeholder position requires evidence")
        _require_unique(self.evidence_ids, "position evidence IDs")
        return self


class Narrative(_DomainModel):
    narrative_id: NonEmptyText
    summary: NonEmptyText
    kind: NarrativeKind
    stakeholder_names: tuple[NonEmptyText, ...] = ()
    evidence_ids: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if not self.evidence_ids:
            raise ValueError("narrative requires evidence")
        _require_unique(self.stakeholder_names, "narrative stakeholders")
        _require_unique(self.evidence_ids, "narrative evidence IDs")
        return self


class GapAssessment(_DomainModel):
    gap_id: NonEmptyText
    outcome: GapStatus
    evidence_ids: tuple[NonEmptyText, ...] = ()
    rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is GapStatus.RESOLVED and not self.evidence_ids:
            raise ValueError("resolved gap assessment requires evidence")
        _require_unique(self.evidence_ids, "gap assessment evidence IDs")
        return self


class OpinionSearchState(_DomainModel):
    request: SearchRequest
    gaps: tuple[InvestigationGap, ...]
    current_focus: NonEmptyText | None = None
    candidates: tuple[CandidateSource, ...] = ()
    sources: tuple[Source, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    claims: tuple[Claim, ...] = ()
    stakeholder_positions: tuple[StakeholderPosition, ...] = ()
    narratives: tuple[Narrative, ...] = ()
    reflections: tuple[NonEmptyText, ...] = ()
    revision: Revision = 0

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        _require_unique_by(self.gaps, "gap_id", "gap IDs")
        _require_unique_by(self.candidates, "source_id", "candidate IDs")
        _require_unique_by(self.sources, "source_id", "source IDs")
        _require_unique_by(self.evidence, "evidence_id", "evidence IDs")
        _require_unique_by(self.claims, "claim_id", "claim IDs")
        _require_unique_by(
            self.stakeholder_positions,
            "position_id",
            "position IDs",
        )
        _require_unique_by(self.narratives, "narrative_id", "narrative IDs")
        _require_unique(self.reflections, "reflections")

        gap_ids = {gap.gap_id for gap in self.gaps}
        candidate_ids = {candidate.source_id for candidate in self.candidates}
        source_ids = {source.source_id for source in self.sources}
        evidence_ids = {item.evidence_id for item in self.evidence}

        if not source_ids.issubset(candidate_ids):
            raise ValueError("every source must originate from a candidate")
        for candidate in self.candidates:
            if not set(candidate.discovered_for_gap_ids).issubset(gap_ids):
                raise ValueError("candidate references an unknown gap")
        for item in self.evidence:
            if item.source_id not in source_ids:
                raise ValueError("evidence references an unknown source")
            if item.acquired_for_gap_id not in gap_ids:
                raise ValueError("evidence acquisition references an unknown gap")
        for gap in self.gaps:
            if not set(gap.evidence_ids).issubset(evidence_ids):
                raise ValueError("gap references unknown evidence")
        for claim in self.claims:
            linked = set(claim.supporting_evidence_ids) | set(
                claim.contradicting_evidence_ids
            )
            if not linked.issubset(evidence_ids):
                raise ValueError("claim references unknown evidence")
        for position in self.stakeholder_positions:
            if not set(position.evidence_ids).issubset(evidence_ids):
                raise ValueError("stakeholder position references unknown evidence")
        for narrative in self.narratives:
            if not set(narrative.evidence_ids).issubset(evidence_ids):
                raise ValueError("narrative references unknown evidence")
        return self

    @property
    def open_gap_ids(self) -> tuple[str, ...]:
        return tuple(gap.gap_id for gap in self.gaps if gap.status is GapStatus.OPEN)

    @property
    def resolved_gap_ids(self) -> tuple[str, ...]:
        return tuple(
            gap.gap_id for gap in self.gaps if gap.status is GapStatus.RESOLVED
        )

    @property
    def blocked_gap_ids(self) -> tuple[str, ...]:
        return tuple(gap.gap_id for gap in self.gaps if gap.status is GapStatus.BLOCKED)

    @property
    def candidate_source_ids(self) -> tuple[str, ...]:
        return tuple(candidate.source_id for candidate in self.candidates)

    @property
    def read_source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self.sources)


class OpinionSearchDelta(_DomainModel):
    add_candidates: tuple[CandidateSource, ...] = ()
    add_sources: tuple[Source, ...] = ()
    add_evidence: tuple[Evidence, ...] = ()
    upsert_claims: tuple[Claim, ...] = ()
    add_stakeholder_positions: tuple[StakeholderPosition, ...] = ()
    upsert_narratives: tuple[Narrative, ...] = ()
    record_query_by_gap: tuple[tuple[NonEmptyText, NonEmptyText], ...] = ()
    record_source_attempt_by_gap: tuple[tuple[NonEmptyText, NonEmptyText], ...] = ()
    gap_assessments: tuple[GapAssessment, ...] = ()
    append_reflections: tuple[NonEmptyText, ...] = ()
    set_current_focus: NonEmptyText | None = None


def claim_status_for(
    supporting_evidence_ids: tuple[str, ...],
    contradicting_evidence_ids: tuple[str, ...],
) -> ClaimStatus:
    if supporting_evidence_ids and not contradicting_evidence_ids:
        return ClaimStatus.SUPPORTED
    if supporting_evidence_ids or contradicting_evidence_ids:
        return ClaimStatus.CONTESTED
    return ClaimStatus.UNRESOLVED


def stable_domain_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(part.strip() for part in parts)
    digest = sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def _require_unique_by(
    values: tuple[BaseModel, ...],
    field_name: str,
    label: str,
) -> None:
    identifiers = tuple(getattr(item, field_name) for item in values)
    _require_unique(identifiers, label)
