from opinion_search.domain.opinion.provenance import ProvenanceIndex, build_provenance_index
from opinion_search.domain.opinion.state import (
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
)
from opinion_search.memory.models import (
    OpinionCoverageCell,
    WorkingCandidate,
    WorkingClaim,
    WorkingEvidence,
    WorkingGap,
    WorkingGoal,
    WorkingMemory,
    WorkingNarrative,
    WorkingPosition,
    WorkingSource,
)


def project_working_memory(state: OpinionSearchState) -> WorkingMemory:
    provenance = build_provenance_index(state)
    read_source_ids = frozenset(state.read_source_ids)
    pending_candidate_source_ids = tuple(
        source_id
        for source_id in state.candidate_source_ids
        if source_id not in read_source_ids
    )

    request = state.request
    evidence_by_id = {item.evidence_id: item for item in state.evidence}
    return WorkingMemory(
        state_revision=state.revision,
        goal=WorkingGoal(
            question=request.question,
            topic=request.topic,
            time_range=request.time_range,
            focus=request.focus,
            language=request.language,
            include_domains=request.include_domains,
            exclude_domains=request.exclude_domains,
        ),
        current_focus=state.current_focus or request.focus,
        current_gap_id=_highest_priority_open_gap_id(state),
        open_gap_ids=state.open_gap_ids,
        resolved_gap_ids=state.resolved_gap_ids,
        blocked_gap_ids=state.blocked_gap_ids,
        pending_candidate_source_ids=pending_candidate_source_ids,
        read_source_ids=state.read_source_ids,
        gaps=tuple(
            WorkingGap(
                gap_id=gap.gap_id,
                question=gap.question,
                priority=gap.priority,
                status=gap.status,
                attempted_queries=gap.attempted_queries,
                attempted_source_ids=gap.attempted_source_ids,
                resolution_note=gap.resolution_note,
            )
            for gap in state.gaps
        ),
        opinion_coverage=tuple(
            _coverage_cell(gap, provenance) for gap in state.gaps
        ),
        candidates=tuple(
            WorkingCandidate(
                source_id=item.source_id,
                title=item.title,
                snippet=item.snippet,
                gap_ids=item.discovered_for_gap_ids,
            )
            for item in state.candidates
            if item.source_id not in read_source_ids
        ),
        sources=tuple(
            WorkingSource(
                source_id=item.source_id,
                title=item.title,
                url=item.final_url or item.url,
                source_kind=item.source_kind,
            )
            for item in state.sources
        ),
        evidence=tuple(
            _working_evidence(record, evidence_by_id[record.evidence_id])
            for record in provenance.evidence
        ),
        claims=tuple(
            WorkingClaim(
                claim_id=item.claim_id,
                text=item.text,
                kind=item.kind,
                status=item.status,
                supporting_evidence_ids=item.supporting_evidence_ids,
                contradicting_evidence_ids=item.contradicting_evidence_ids,
            )
            for item in state.claims
        ),
        stakeholder_positions=tuple(
            WorkingPosition(
                position_id=item.position_id,
                stakeholder=item.stakeholder,
                statement=item.statement,
                evidence_ids=item.evidence_ids,
            )
            for item in state.stakeholder_positions
        ),
        narratives=tuple(
            WorkingNarrative(
                narrative_id=item.narrative_id,
                summary=item.summary,
                kind=item.kind,
                stakeholder_names=item.stakeholder_names,
                evidence_ids=item.evidence_ids,
            )
            for item in state.narratives
        ),
        reflections=state.reflections,
    )


def _working_evidence(
    record,
    item,
) -> WorkingEvidence:
    return WorkingEvidence(
        evidence_id=record.evidence_id,
        source_id=record.source_id,
        acquired_for_gap_id=record.acquired_for_gap_id,
        semantic_gap_ids=record.semantic_gap_ids,
        supporting_claim_ids=record.supporting_claim_ids,
        contradicting_claim_ids=record.contradicting_claim_ids,
        position_ids=record.position_ids,
        narrative_ids=record.narrative_ids,
        excerpt=item.excerpt,
        locator=item.locator,
    )


def _coverage_cell(
    gap: InvestigationGap,
    provenance: ProvenanceIndex,
) -> OpinionCoverageCell:
    return OpinionCoverageCell(
        gap_id=gap.gap_id,
        question=gap.question,
        status=gap.status,
        evidence_ids=gap.evidence_ids,
        source_ids=provenance.source_ids_for_gap(gap.gap_id),
    )


def _highest_priority_open_gap_id(state: OpinionSearchState) -> str | None:
    open_gaps = tuple(gap for gap in state.gaps if gap.status is GapStatus.OPEN)
    if not open_gaps:
        return None
    return max(open_gaps, key=lambda gap: gap.priority).gap_id
