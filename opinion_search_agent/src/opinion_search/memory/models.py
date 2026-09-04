from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.domain.opinion.state import (
    ClaimKind,
    ClaimStatus,
    GapStatus,
    NarrativeKind,
    SourceKind,
    SourcePublicationStatus,
)
from opinion_search.domain.opinion.framing import TaskFrame


NonEmptyText = Annotated[str, Field(min_length=1)]


class _MemoryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class WorkingGoal(_MemoryModel):
    question: NonEmptyText
    topic: NonEmptyText | None = None
    time_range: NonEmptyText | None = None
    focus: NonEmptyText | None = None
    language: NonEmptyText
    include_domains: tuple[NonEmptyText, ...] = ()
    exclude_domains: tuple[NonEmptyText, ...] = ()
    task_frame: TaskFrame | None = None


class WorkingGap(_MemoryModel):
    gap_id: NonEmptyText
    question: NonEmptyText
    priority: int
    status: GapStatus
    attempted_queries: tuple[NonEmptyText, ...]
    attempted_source_ids: tuple[NonEmptyText, ...]
    resolution_note: NonEmptyText | None = None


class WorkingCandidate(_MemoryModel):
    source_id: NonEmptyText
    title: NonEmptyText
    snippet: NonEmptyText
    gap_ids: tuple[NonEmptyText, ...]


class WorkingEvidence(_MemoryModel):
    evidence_id: NonEmptyText
    source_id: NonEmptyText
    acquired_for_gap_id: NonEmptyText
    semantic_gap_ids: tuple[NonEmptyText, ...]
    supporting_claim_ids: tuple[NonEmptyText, ...]
    contradicting_claim_ids: tuple[NonEmptyText, ...]
    position_ids: tuple[NonEmptyText, ...]
    narrative_ids: tuple[NonEmptyText, ...]
    excerpt: NonEmptyText
    locator: NonEmptyText


class WorkingClaim(_MemoryModel):
    claim_id: NonEmptyText
    text: NonEmptyText
    kind: ClaimKind
    status: ClaimStatus
    supporting_evidence_ids: tuple[NonEmptyText, ...]
    contradicting_evidence_ids: tuple[NonEmptyText, ...]


class WorkingPosition(_MemoryModel):
    position_id: NonEmptyText
    stakeholder: NonEmptyText
    statement: NonEmptyText
    evidence_ids: tuple[NonEmptyText, ...]


class WorkingSource(_MemoryModel):
    source_id: NonEmptyText
    title: NonEmptyText
    url: NonEmptyText
    source_kind: SourceKind
    published_at: datetime | None
    publication_status: SourcePublicationStatus


class WorkingNarrative(_MemoryModel):
    narrative_id: NonEmptyText
    summary: NonEmptyText
    kind: NarrativeKind
    stakeholder_names: tuple[NonEmptyText, ...]
    evidence_ids: tuple[NonEmptyText, ...]


class OpinionCoverageCell(_MemoryModel):
    gap_id: NonEmptyText
    question: NonEmptyText
    status: GapStatus
    evidence_ids: tuple[NonEmptyText, ...]
    source_ids: tuple[NonEmptyText, ...]


class WorkingMemory(_MemoryModel):
    state_revision: Annotated[int, Field(ge=0)]
    goal: WorkingGoal
    current_focus: NonEmptyText | None = None
    current_gap_id: NonEmptyText | None = None
    open_gap_ids: tuple[NonEmptyText, ...]
    resolved_gap_ids: tuple[NonEmptyText, ...]
    blocked_gap_ids: tuple[NonEmptyText, ...]
    pending_candidate_source_ids: tuple[NonEmptyText, ...]
    read_source_ids: tuple[NonEmptyText, ...]
    gaps: tuple[WorkingGap, ...]
    opinion_coverage: tuple[OpinionCoverageCell, ...]
    candidates: tuple[WorkingCandidate, ...]
    sources: tuple[WorkingSource, ...]
    evidence: tuple[WorkingEvidence, ...]
    claims: tuple[WorkingClaim, ...]
    stakeholder_positions: tuple[WorkingPosition, ...]
    narratives: tuple[WorkingNarrative, ...]
    reflections: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_projection_invariants(self) -> "WorkingMemory":
        ordered_fields = (
            self.open_gap_ids,
            self.resolved_gap_ids,
            self.blocked_gap_ids,
            self.pending_candidate_source_ids,
            self.read_source_ids,
            self.reflections,
        )
        if any(len(values) != len(set(values)) for values in ordered_fields):
            raise ValueError("working memory sequences must be unique")
        open_gaps = tuple(gap for gap in self.gaps if gap.status is GapStatus.OPEN)
        expected_focus = (
            max(open_gaps, key=lambda gap: gap.priority).gap_id if open_gaps else None
        )
        if self.current_gap_id != expected_focus:
            raise ValueError("current gap must be the highest-priority open gap")
        if set(self.pending_candidate_source_ids) & set(self.read_source_ids):
            raise ValueError("pending and read sources must not overlap")
        if set(self.open_gap_ids) & (
            set(self.resolved_gap_ids) | set(self.blocked_gap_ids)
        ):
            raise ValueError("working gap status projections must not overlap")
        gap_ids = tuple(gap.gap_id for gap in self.gaps)
        coverage_ids = tuple(cell.gap_id for cell in self.opinion_coverage)
        if coverage_ids != gap_ids:
            raise ValueError("opinion coverage must contain one cell per gap")
        return self
