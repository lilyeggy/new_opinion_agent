from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.domain.opinion.state import ClaimStatus, NarrativeKind
from opinion_search.memory.models import WorkingEvidence, WorkingMemory


class EvidenceCatalogPolicy(BaseModel):
    """Bounded Evidence catalog partitioning rules for one compiler config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_evidence_limit: Annotated[int, Field(ge=8)] = 64
    history_chunk_size: Annotated[int, Field(ge=8)] = 64
    coverage_sample_limit_per_gap: Annotated[int, Field(ge=1)] = 16


@dataclass(frozen=True)
class EvidenceCatalogEntry:
    evidence_id: str
    source_id: str
    acquired_for_gap_id: str
    semantic_gap_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceCatalogPartition:
    required: tuple[EvidenceCatalogEntry, ...]
    history: tuple[tuple[EvidenceCatalogEntry, ...], ...]
    state_order_ids: tuple[str, ...]
    current_gap_relevance_ids: tuple[str, ...]


def partition_evidence_catalog(
    memory: WorkingMemory,
    *,
    policy: EvidenceCatalogPolicy,
    current_gap_id: str | None,
) -> EvidenceCatalogPartition:
    evidence = memory.evidence
    entries_by_id = {
        item.evidence_id: _entry(item) for item in evidence
    }
    all_ids = tuple(item.evidence_id for item in evidence)

    if current_gap_id is None:
        contested_ids = _contested_evidence_ids(memory)
        required_selected = [
            evidence_id for evidence_id in all_ids if evidence_id in contested_ids
        ][: policy.required_evidence_limit]
        relevance_ids: tuple[str, ...] = ()
    else:
        ranked = _rank_current_gap(evidence, current_gap_id, memory)
        required_selected = ranked[: policy.required_evidence_limit]
        relevance_ids = tuple(required_selected)

    required_set = set(required_selected)
    required_committed = tuple(
        evidence_id for evidence_id in all_ids if evidence_id in required_set
    )
    remaining = tuple(
        evidence_id for evidence_id in all_ids if evidence_id not in required_set
    )
    history = tuple(
        tuple(entries_by_id[evidence_id] for evidence_id in remaining[offset : offset + policy.history_chunk_size])
        for offset in range(0, len(remaining), policy.history_chunk_size)
    )

    return EvidenceCatalogPartition(
        required=tuple(
            entries_by_id[evidence_id] for evidence_id in required_committed
        ),
        history=history,
        state_order_ids=all_ids,
        current_gap_relevance_ids=relevance_ids,
    )


def _rank_current_gap(
    evidence: tuple[WorkingEvidence, ...],
    current_gap_id: str,
    memory: WorkingMemory,
) -> list[str]:
    contested_ids = _contested_evidence_ids(memory)
    newest_first = list(reversed(evidence))

    def group(item: WorkingEvidence) -> int:
        if current_gap_id in item.semantic_gap_ids:
            return 1
        if not (
            item.semantic_gap_ids
            or item.supporting_claim_ids
            or item.contradicting_claim_ids
            or item.position_ids
            or item.narrative_ids
        ):
            return 2
        if item.acquired_for_gap_id == current_gap_id:
            return 3
        if item.evidence_id in contested_ids:
            return 4
        return 5

    ordered: list[str] = []
    seen: set[str] = set()
    for current_group in (1, 2, 3, 4, 5):
        for item in newest_first:
            if item.evidence_id in seen:
                continue
            if group(item) == current_group:
                ordered.append(item.evidence_id)
                seen.add(item.evidence_id)
    return ordered


def _contested_evidence_ids(memory: WorkingMemory) -> set[str]:
    contested: set[str] = set()
    for claim in memory.claims:
        if claim.status is not ClaimStatus.SUPPORTED:
            contested.update(claim.supporting_evidence_ids)
            contested.update(claim.contradicting_evidence_ids)
    for narrative in memory.narratives:
        if narrative.kind is NarrativeKind.COUNTER:
            contested.update(narrative.evidence_ids)
    return contested


def _entry(item: WorkingEvidence) -> EvidenceCatalogEntry:
    return EvidenceCatalogEntry(
        evidence_id=item.evidence_id,
        source_id=item.source_id,
        acquired_for_gap_id=item.acquired_for_gap_id,
        semantic_gap_ids=item.semantic_gap_ids,
    )
