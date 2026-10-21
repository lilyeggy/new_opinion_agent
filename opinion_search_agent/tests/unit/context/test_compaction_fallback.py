"""A long run must not die because a required-but-compactable section grew.

The findings section used to be marked required and un-compactable; at 89
findings it pushed the locked total over the budget and the compiler raised,
ending the run. Required now only means "drop me last", never "fail instead".
"""

from __future__ import annotations

import pytest

from opinion_search.context.compactor import compact_context_sections
from opinion_search.context.models import (
    CompactionMode,
    ContextSection,
    RequiredContextOverflow,
)


class CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _section(section_id: str, content: str, *, priority: int, required: bool = False,
             compaction: CompactionMode = CompactionMode.DROP,
             layer: str = "l2_memory", origin: str = "runtime") -> ContextSection:
    return ContextSection(
        section_id=section_id, layer=layer, title=section_id, content=content,
        priority=priority, required=required, trust="trusted", origin=origin,
        compaction=compaction, provenance_refs=(section_id,),
    )


def _instructions(content: str) -> ContextSection:
    return _section(
        "instructions.core", content, priority=100, required=True,
        compaction=CompactionMode.NEVER, layer="l0_instructions", origin="app_config",
    )


def test_required_but_compactable_sections_are_dropped_instead_of_failing():
    sections = (
        _instructions("instructions"),
        _section("memory.findings", "x" * 500, priority=100, required=True),
        _section("memory.progress", "y" * 500, priority=90),
    )

    result = compact_context_sections(sections, input_token_limit=200, estimator=CharacterEstimator())

    assert "memory.findings" in result.dropped_section_ids
    assert result.estimated_input_tokens <= 200
    kept = [section.section_id for section in result.sections]
    assert "instructions.core" in kept


def test_irreducible_core_over_budget_still_fails_loudly():
    sections = (
        _instructions("z" * 500),
    )

    with pytest.raises(RequiredContextOverflow):
        compact_context_sections(sections, input_token_limit=100, estimator=CharacterEstimator())
