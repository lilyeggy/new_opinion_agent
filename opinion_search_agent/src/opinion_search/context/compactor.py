from dataclasses import dataclass

from opinion_search.context.models import (
    CompactionMode,
    ContextSection,
    RequiredContextOverflow,
    TokenEstimator,
    TrustBoundary,
    render_sections,
)


_MIN_COMPACTED_CHARACTERS = 96
_COMPACTION_MARKER = "\n[content compacted]"


@dataclass(frozen=True)
class CompactionResult:
    sections: tuple[ContextSection, ...]
    dropped_section_ids: tuple[str, ...]
    compacted_section_ids: tuple[str, ...]
    estimated_input_tokens: int


def compact_context_sections(
    sections: tuple[ContextSection, ...],
    *,
    input_token_limit: int,
    estimator: TokenEstimator,
) -> CompactionResult:
    if input_token_limit < 1:
        raise ValueError("input_token_limit must be positive")

    working = list(sections)
    compacted: list[str] = []

    locked = tuple(
        section
        for section in sections
        if section.required or section.compaction is CompactionMode.NEVER
    )
    if _measure(locked, estimator) > input_token_limit:
        raise RequiredContextOverflow(
            "required context exceeds the available input budget"
        )

    if _measure(tuple(working), estimator) <= input_token_limit:
        return _result(working, sections, compacted, estimator)

    truncation_candidates = sorted(
        (
            section
            for section in working
            if section.compaction is CompactionMode.TRUNCATE
            and len(section.content) > _MIN_COMPACTED_CHARACTERS
        ),
        key=_degradation_rank,
    )
    for original in truncation_candidates:
        index = _index_for_id(working, original.section_id)
        if _measure(tuple(working), estimator) <= input_token_limit:
            break
        current = working[index]
        content = (
            current.content[:_MIN_COMPACTED_CHARACTERS].rstrip() + _COMPACTION_MARKER
        )
        working[index] = ContextSection.model_validate(
            {**current.model_dump(mode="json"), "content": content}
        )
        compacted.append(original.section_id)

    if _measure(tuple(working), estimator) > input_token_limit:
        droppable = sorted(
            (
                section
                for section in working
                if not section.required
                and section.compaction is not CompactionMode.NEVER
            ),
            key=_degradation_rank,
        )
        for section in droppable:
            if _measure(tuple(working), estimator) <= input_token_limit:
                break
            index = _index_for_id(working, section.section_id)
            working.pop(index)

    measured = _measure(tuple(working), estimator)
    if measured > input_token_limit:
        raise RequiredContextOverflow(
            "non-removable context exceeds the available input budget"
        )

    compacted = [
        section_id
        for section_id in compacted
        if any(item.section_id == section_id for item in working)
    ]
    return _result(working, sections, compacted, estimator)


def _degradation_rank(section: ContextSection) -> tuple[int, int, int, str]:
    return (
        0 if section.trust is TrustBoundary.UNTRUSTED else 1,
        0 if section.layer.value == "l3_recent" else 1,
        section.priority,
        section.section_id,
    )


def _index_for_id(sections: list[ContextSection], section_id: str) -> int:
    return next(
        index
        for index, section in enumerate(sections)
        if section.section_id == section_id
    )


def _measure(
    sections: tuple[ContextSection, ...],
    estimator: TokenEstimator,
) -> int:
    return estimator.estimate(render_sections(sections))


def _result(
    working: list[ContextSection],
    original: tuple[ContextSection, ...],
    compacted: list[str],
    estimator: TokenEstimator,
) -> CompactionResult:
    selected_ids = {section.section_id for section in working}
    dropped = tuple(
        section.section_id
        for section in original
        if section.section_id not in selected_ids
    )
    final = tuple(working)
    return CompactionResult(
        sections=final,
        dropped_section_ids=dropped,
        compacted_section_ids=tuple(compacted),
        estimated_input_tokens=_measure(final, estimator),
    )
