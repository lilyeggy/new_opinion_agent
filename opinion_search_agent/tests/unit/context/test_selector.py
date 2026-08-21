import pytest

from opinion_search.context.models import (
    CompactionMode,
    ContextContentOrigin,
    ContextLayer,
    ContextSection,
    TrustBoundary,
)
from opinion_search.context.selector import (
    ContextSelectionError,
    select_context_sections,
)


def _section(
    section_id: str,
    *,
    layer: ContextLayer = ContextLayer.WORKING_MEMORY,
    content: str | None = None,
    priority: int = 50,
    provenance_refs: tuple[str, ...] = (),
    trust: TrustBoundary = TrustBoundary.TRUSTED,
    origin: ContextContentOrigin = ContextContentOrigin.APP_CONFIG,
) -> ContextSection:
    required = layer in {
        ContextLayer.IMMUTABLE_INSTRUCTIONS,
        ContextLayer.STABLE_TASK,
    }
    return ContextSection(
        section_id=section_id,
        layer=layer,
        title=section_id,
        content=content or section_id,
        priority=priority,
        required=required,
        trust=trust,
        origin=origin,
        provenance_refs=provenance_refs,
        compaction=(CompactionMode.NEVER if required else CompactionMode.DROP),
    )


def test_selector_orders_layers_and_prioritizes_current_gap_within_memory() -> None:
    sections = (
        _section("recent.last", layer=ContextLayer.RECENT_INTERACTION),
        _section("memory.other", priority=90),
        _section(
            "memory.current",
            priority=40,
            provenance_refs=("gap-primary",),
        ),
        _section("task.question", layer=ContextLayer.STABLE_TASK),
        _section("instructions.core", layer=ContextLayer.IMMUTABLE_INSTRUCTIONS),
    )

    selected = select_context_sections(
        sections,
        current_gap_id="gap-primary",
    )

    assert tuple(section.section_id for section in selected) == (
        "instructions.core",
        "task.question",
        "memory.current",
        "memory.other",
        "recent.last",
    )


def test_selector_deduplicates_normalized_content_but_not_trust_boundaries() -> None:
    selected = select_context_sections(
        (
            _section(
                "memory.first",
                content="Same   fact",
                priority=80,
                provenance_refs=("source-1",),
            ),
            _section(
                "memory.second",
                content=" same fact ",
                priority=40,
                provenance_refs=("source-2",),
            ),
            _section(
                "recent.external",
                layer=ContextLayer.RECENT_INTERACTION,
                content="Same fact",
                trust=TrustBoundary.UNTRUSTED,
            ),
        ),
        current_gap_id=None,
    )

    assert tuple(section.section_id for section in selected) == (
        "memory.first",
        "recent.external",
    )
    assert selected[0].provenance_refs == ("source-1", "source-2")


def test_selector_is_deterministic_for_reordered_input() -> None:
    sections = (
        _section("memory.b"),
        _section("memory.a"),
        _section("recent.z", layer=ContextLayer.RECENT_INTERACTION),
    )

    forward = select_context_sections(sections, current_gap_id=None)
    reverse = select_context_sections(tuple(reversed(sections)), current_gap_id=None)

    assert forward == reverse


def test_selector_rejects_conflicting_stable_identity() -> None:
    with pytest.raises(ContextSelectionError, match="conflicting"):
        select_context_sections(
            (
                _section("memory.fact", content="first"),
                _section("memory.fact", content="different"),
            ),
            current_gap_id=None,
        )


def test_dedup_never_merges_different_origins() -> None:
    sections = (
        _section(
            "a.model",
            layer=ContextLayer.RECENT_INTERACTION,
            content="identical untrusted text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.MODEL,
            provenance_refs=("ref-a",),
        ),
        _section(
            "b.tool",
            layer=ContextLayer.RECENT_INTERACTION,
            content="identical untrusted text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.TOOL,
            provenance_refs=("ref-b",),
        ),
    )

    selected = select_context_sections(sections, current_gap_id=None)

    assert [section.section_id for section in selected] == ["a.model", "b.tool"]
    by_id = {section.section_id: section for section in selected}
    assert by_id["a.model"].origin is ContextContentOrigin.MODEL
    assert by_id["a.model"].provenance_refs == ("ref-a",)
    assert by_id["b.tool"].origin is ContextContentOrigin.TOOL
    assert by_id["b.tool"].provenance_refs == ("ref-b",)


def test_provider_and_tool_origins_do_not_merge() -> None:
    sections = (
        _section(
            "p.provider",
            layer=ContextLayer.RECENT_INTERACTION,
            content="same failure message text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.PROVIDER,
            provenance_refs=("p",),
        ),
        _section(
            "t.tool",
            layer=ContextLayer.RECENT_INTERACTION,
            content="same failure message text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.TOOL,
            provenance_refs=("t",),
        ),
    )

    selected = select_context_sections(sections, current_gap_id=None)

    assert {section.section_id for section in selected} == {
        "p.provider",
        "t.tool",
    }


def test_same_origin_identical_sections_still_deduplicate() -> None:
    sections = (
        _section(
            "a",
            layer=ContextLayer.WORKING_MEMORY,
            content="same text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.MODEL,
            provenance_refs=("a",),
        ),
        _section(
            "b",
            layer=ContextLayer.WORKING_MEMORY,
            content="same text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.MODEL,
            provenance_refs=("b",),
        ),
    )

    selected = select_context_sections(sections, current_gap_id=None)

    assert len(selected) == 1
    assert selected[0].provenance_refs == ("a", "b")


def test_json_roundtrip_does_not_change_selection() -> None:
    sections = (
        _section(
            "a.model",
            layer=ContextLayer.RECENT_INTERACTION,
            content="same text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.MODEL,
            provenance_refs=("a",),
        ),
        _section(
            "b.tool",
            layer=ContextLayer.RECENT_INTERACTION,
            content="same text",
            trust=TrustBoundary.UNTRUSTED,
            origin=ContextContentOrigin.TOOL,
            provenance_refs=("b",),
        ),
    )
    restored = tuple(
        ContextSection.model_validate_json(section.model_dump_json())
        for section in sections
    )

    selected = select_context_sections(restored, current_gap_id=None)

    assert [section.section_id for section in selected] == ["a.model", "b.tool"]
