import re

from opinion_search.context.models import (
    ContextContentOrigin,
    ContextLayer,
    ContextSection,
    TrustBoundary,
)


class ContextSelectionError(ValueError):
    """Raised when collected sections disagree on one stable identity."""


_LAYER_ORDER = {
    ContextLayer.IMMUTABLE_INSTRUCTIONS: 0,
    ContextLayer.STABLE_TASK: 1,
    ContextLayer.WORKING_MEMORY: 2,
    ContextLayer.RECENT_INTERACTION: 3,
}


def select_context_sections(
    sections: tuple[ContextSection, ...],
    *,
    current_gap_id: str | None,
) -> tuple[ContextSection, ...]:
    by_id: dict[str, ContextSection] = {}
    for section in sections:
        existing = by_id.get(section.section_id)
        if existing is not None and existing != section:
            raise ContextSelectionError(
                f"section ID has conflicting content: {section.section_id}"
            )
        by_id[section.section_id] = section

    best_by_content: dict[
        tuple[TrustBoundary, ContextContentOrigin, ContextLayer, str],
        ContextSection,
    ] = {}
    for section in by_id.values():
        semantic_key = (
            section.trust,
            section.origin,
            section.layer,
            _normalize_content(section.content),
        )
        existing = best_by_content.get(semantic_key)
        if existing is None:
            best_by_content[semantic_key] = section
            continue
        winner, other = sorted(
            (existing, section),
            key=lambda item: _rank(
                item,
                current_gap_id=current_gap_id,
            ),
        )
        merged_refs = tuple(
            dict.fromkeys(winner.provenance_refs + other.provenance_refs)
        )
        best_by_content[semantic_key] = ContextSection.model_validate(
            {
                **winner.model_dump(mode="json"),
                "provenance_refs": merged_refs,
            }
        )

    return tuple(
        sorted(
            best_by_content.values(),
            key=lambda section: _rank(
                section,
                current_gap_id=current_gap_id,
            ),
        )
    )


def _rank(
    section: ContextSection,
    *,
    current_gap_id: str | None,
) -> tuple[int, int, int, int, str]:
    gap_relevant = (
        current_gap_id is not None and current_gap_id in section.provenance_refs
    )
    return (
        _LAYER_ORDER[section.layer],
        0 if section.required else 1,
        0 if gap_relevant else 1,
        -section.priority,
        section.section_id,
    )


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().casefold()
