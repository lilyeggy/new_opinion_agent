from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    GapAssessment,
    GapStatus,
    InvestigationGap,
    FinalSynthesis,
    Narrative,
    OpinionSearchDelta,
    OpinionSearchState,
    StakeholderPosition,
    claim_status_for,
)


class ReducerInvariantError(ValueError):
    """Raised when an accepted delta conflicts with domain state."""


ModelT = TypeVar("ModelT", bound=BaseModel)


def reduce_opinion_state(
    old_state: OpinionSearchState,
    accepted_delta: OpinionSearchDelta,
) -> OpinionSearchState:
    gaps_by_id = {gap.gap_id: gap for gap in old_state.gaps}
    assessments_by_gap = {
        assessment.gap_id: assessment for assessment in accepted_delta.gap_assessments
    }
    if len(assessments_by_gap) != len(accepted_delta.gap_assessments):
        raise ReducerInvariantError("gap assessments must be unique")
    affected_gap_ids = (
        {gap_id for gap_id, _ in accepted_delta.record_query_by_gap}
        | {gap_id for gap_id, _ in accepted_delta.record_source_attempt_by_gap}
        | set(assessments_by_gap)
    )
    unknown_gap_ids = affected_gap_ids - set(gaps_by_id)
    if unknown_gap_ids:
        raise ReducerInvariantError(
            f"delta references unknown gaps: {sorted(unknown_gap_ids)}"
        )
    query_additions = _pairs_by_key(accepted_delta.record_query_by_gap)
    source_additions = _pairs_by_key(accepted_delta.record_source_attempt_by_gap)
    invalid_closed_gap_ids = {
        gap_id
        for gap_id in affected_gap_ids
        if gaps_by_id[gap_id].status is not GapStatus.OPEN
        and not _is_exact_closed_gap_replay(
            gaps_by_id[gap_id],
            queries=query_additions.get(gap_id, ()),
            source_ids=source_additions.get(gap_id, ()),
            assessment=assessments_by_gap.get(gap_id),
        )
    }
    if invalid_closed_gap_ids:
        raise ReducerInvariantError(
            f"delta changes non-open gaps: {sorted(invalid_closed_gap_ids)}"
        )
    candidates = _merge_candidates(
        old_state.candidates,
        accepted_delta.add_candidates,
        set(gaps_by_id),
    )
    candidate_ids = {item.source_id for item in candidates}
    sources = _append_models(
        old_state.sources,
        accepted_delta.add_sources,
        key="source_id",
        label="source",
    )
    if not {source.source_id for source in sources}.issubset(candidate_ids):
        raise ReducerInvariantError("cannot add a source without a candidate")

    evidence = _append_models(
        old_state.evidence,
        accepted_delta.add_evidence,
        key="evidence_id",
        label="evidence",
    )
    source_ids = {source.source_id for source in sources}
    for item in evidence:
        if item.source_id not in source_ids:
            raise ReducerInvariantError("evidence references an unknown source")
        if item.acquired_for_gap_id not in gaps_by_id:
            raise ReducerInvariantError(
                "evidence acquisition references an unknown gap"
            )

    evidence_ids = {item.evidence_id for item in evidence}
    claims = _merge_claims(
        old_state.claims,
        accepted_delta.upsert_claims,
        evidence_ids,
    )
    positions = _merge_positions(
        old_state.stakeholder_positions,
        accepted_delta.add_stakeholder_positions,
        evidence_ids,
    )
    for position in positions:
        if not set(position.evidence_ids).issubset(evidence_ids):
            raise ReducerInvariantError(
                "stakeholder position references unknown evidence"
            )
    narratives = _merge_narratives(
        old_state.narratives,
        accepted_delta.upsert_narratives,
        evidence_ids,
    )
    for assessment in assessments_by_gap.values():
        unknown_evidence_ids = set(assessment.evidence_ids) - evidence_ids
        if unknown_evidence_ids:
            raise ReducerInvariantError(
                "gap assessment references unknown evidence IDs: "
                f"{sorted(unknown_evidence_ids)}"
            )
    gaps = tuple(
        _updated_gap(
            gap,
            queries=query_additions.get(gap.gap_id, ()),
            source_ids=source_additions.get(gap.gap_id, ()),
            assessment=assessments_by_gap.get(gap.gap_id),
        )
        for gap in old_state.gaps
    )
    reflections = _append_unique(
        old_state.reflections,
        accepted_delta.append_reflections,
    )
    final_synthesis = _reduce_final_synthesis(
        old_state.final_synthesis,
        accepted_delta.set_final_synthesis,
        evidence_ids=evidence_ids,
        gap_ids=set(gaps_by_id),
    )

    values = {
        "request": old_state.request,
        "gaps": gaps,
        "task_frame": old_state.task_frame,
        "current_focus": (accepted_delta.set_current_focus or old_state.current_focus),
        "candidates": candidates,
        "sources": sources,
        "evidence": evidence,
        "claims": claims,
        "stakeholder_positions": positions,
        "narratives": narratives,
        "final_synthesis": final_synthesis,
        "reflections": reflections,
    }
    if all(getattr(old_state, key) == value for key, value in values.items()):
        return old_state
    return OpinionSearchState(
        **values,
        revision=old_state.revision + 1,
    )


def _reduce_final_synthesis(
    existing: FinalSynthesis | None,
    proposed: FinalSynthesis | None,
    *,
    evidence_ids: set[str],
    gap_ids: set[str],
) -> FinalSynthesis | None:
    if proposed is None:
        return existing
    if not set(proposed.evidence_ids).issubset(evidence_ids):
        raise ReducerInvariantError("final synthesis references unknown evidence")
    if not set(proposed.limitation_gap_ids).issubset(gap_ids):
        raise ReducerInvariantError("final synthesis references unknown limitation gap")
    if existing is None or existing == proposed:
        return proposed
    raise ReducerInvariantError("final synthesis cannot be overwritten")


def _merge_candidates(
    existing: tuple[CandidateSource, ...],
    additions: tuple[CandidateSource, ...],
    known_gap_ids: set[str],
) -> tuple[CandidateSource, ...]:
    result = list(existing)
    index = {item.source_id: position for position, item in enumerate(result)}
    for item in additions:
        if not set(item.discovered_for_gap_ids).issubset(known_gap_ids):
            raise ReducerInvariantError("candidate references an unknown gap")
        position = index.get(item.source_id)
        if position is None:
            index[item.source_id] = len(result)
            result.append(item)
            continue
        current = result[position]
        if (current.url, current.title) != (item.url, item.title):
            raise ReducerInvariantError("candidate identity conflict")
        merged_gaps = _append_unique(
            current.discovered_for_gap_ids,
            item.discovered_for_gap_ids,
        )
        if merged_gaps != current.discovered_for_gap_ids:
            result[position] = current.model_copy(
                update={"discovered_for_gap_ids": merged_gaps}
            )
    return tuple(result)


def _append_models(
    existing: tuple[ModelT, ...],
    additions: tuple[ModelT, ...],
    *,
    key: str,
    label: str,
) -> tuple[ModelT, ...]:
    result = list(existing)
    by_id = {getattr(item, key): item for item in existing}
    for item in additions:
        identifier = getattr(item, key)
        current = by_id.get(identifier)
        if current is None:
            result.append(item)
            by_id[identifier] = item
        elif current != item:
            raise ReducerInvariantError(f"{label} identity conflict")
    return tuple(result)


def _merge_claims(
    existing: tuple[Claim, ...],
    additions: tuple[Claim, ...],
    evidence_ids: set[str],
) -> tuple[Claim, ...]:
    result = list(existing)
    index = {item.claim_id: position for position, item in enumerate(result)}
    for item in additions:
        linked = set(item.supporting_evidence_ids) | set(
            item.contradicting_evidence_ids
        )
        if not linked.issubset(evidence_ids):
            raise ReducerInvariantError("claim references unknown evidence")
        position = index.get(item.claim_id)
        if position is None:
            index[item.claim_id] = len(result)
            result.append(item)
            continue
        current = result[position]
        if (current.text, current.kind) != (item.text, item.kind):
            raise ReducerInvariantError("claim identity conflict")
        supporting = _append_unique(
            current.supporting_evidence_ids,
            item.supporting_evidence_ids,
        )
        contradicting = _append_unique(
            current.contradicting_evidence_ids,
            item.contradicting_evidence_ids,
        )
        if set(supporting) & set(contradicting):
            raise ReducerInvariantError(
                "claim evidence cannot both support and contradict"
            )
        result[position] = Claim(
            claim_id=current.claim_id,
            text=current.text,
            kind=current.kind,
            supporting_evidence_ids=supporting,
            contradicting_evidence_ids=contradicting,
            status=claim_status_for(supporting, contradicting),
        )
    return tuple(result)


def _merge_positions(
    existing: tuple[StakeholderPosition, ...],
    additions: tuple[StakeholderPosition, ...],
    evidence_ids: set[str],
) -> tuple[StakeholderPosition, ...]:
    result = list(existing)
    index = {item.position_id: position for position, item in enumerate(result)}
    for item in additions:
        if not set(item.evidence_ids).issubset(evidence_ids):
            raise ReducerInvariantError(
                "stakeholder position references unknown evidence"
            )
        position = index.get(item.position_id)
        if position is None:
            index[item.position_id] = len(result)
            result.append(item)
            continue
        current = result[position]
        if (current.stakeholder, current.statement) != (
            item.stakeholder,
            item.statement,
        ):
            raise ReducerInvariantError("stakeholder position identity conflict")
        result[position] = StakeholderPosition(
            position_id=current.position_id,
            stakeholder=current.stakeholder,
            statement=current.statement,
            evidence_ids=_append_unique(current.evidence_ids, item.evidence_ids),
        )
    return tuple(result)


def _merge_narratives(
    existing: tuple[Narrative, ...],
    additions: tuple[Narrative, ...],
    evidence_ids: set[str],
) -> tuple[Narrative, ...]:
    result = list(existing)
    index = {item.narrative_id: position for position, item in enumerate(result)}
    for item in additions:
        if not set(item.evidence_ids).issubset(evidence_ids):
            raise ReducerInvariantError("narrative references unknown evidence")
        position = index.get(item.narrative_id)
        if position is None:
            index[item.narrative_id] = len(result)
            result.append(item)
            continue
        current = result[position]
        if (current.summary, current.kind) != (item.summary, item.kind):
            raise ReducerInvariantError("narrative identity conflict")
        result[position] = Narrative(
            narrative_id=current.narrative_id,
            summary=current.summary,
            kind=current.kind,
            stakeholder_names=_append_unique(
                current.stakeholder_names,
                item.stakeholder_names,
            ),
            evidence_ids=_append_unique(
                current.evidence_ids,
                item.evidence_ids,
            ),
        )
    return tuple(result)


def _updated_gap(
    gap: InvestigationGap,
    *,
    queries: tuple[str, ...],
    source_ids: tuple[str, ...],
    assessment: GapAssessment | None,
) -> InvestigationGap:
    target_status = assessment.outcome if assessment is not None else gap.status
    return InvestigationGap(
        gap_id=gap.gap_id,
        question=gap.question,
        priority=gap.priority,
        status=target_status or gap.status,
        attempted_queries=_append_unique(gap.attempted_queries, queries),
        attempted_source_ids=_append_unique(
            gap.attempted_source_ids,
            source_ids,
        ),
        evidence_ids=_append_unique(
            gap.evidence_ids,
            assessment.evidence_ids if assessment is not None else (),
        ),
        resolution_note=(
            assessment.rationale
            if assessment is not None and assessment.outcome is not GapStatus.OPEN
            else gap.resolution_note
        ),
    )


def _is_exact_closed_gap_replay(
    gap: InvestigationGap,
    *,
    queries: tuple[str, ...],
    source_ids: tuple[str, ...],
    assessment: GapAssessment | None,
) -> bool:
    if not set(queries).issubset(gap.attempted_queries):
        return False
    if not set(source_ids).issubset(gap.attempted_source_ids):
        return False
    if assessment is not None:
        return (
            assessment.outcome is gap.status
            and assessment.rationale == gap.resolution_note
            and set(assessment.evidence_ids).issubset(gap.evidence_ids)
        )
    return not queries and not source_ids


def _pairs_by_key(
    pairs: tuple[tuple[str, str], ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for key, value in pairs:
        result[key] = _append_unique(result.get(key, ()), (value,))
    return result


def _append_unique(
    existing: tuple[str, ...],
    additions: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(existing + additions))
