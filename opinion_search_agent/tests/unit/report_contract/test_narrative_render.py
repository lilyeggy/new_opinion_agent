"""The dossier renders prose above the cards, and still renders without it."""

from __future__ import annotations

from opinion_search.report_contract.contracts import (
    NarrativeClause, NarrativeParagraph, NarrativeSection, PresentationPlan,
)
from opinion_search.report_contract.renderer import render_html


def _plan(narrative=None) -> PresentationPlan:
    return PresentationPlan(
        source_content_revision=1, report_id="run-1", subject="事件", status="partial",
        generated_at="2026-10-20", sections=(), narrative=narrative,
    )


def test_narrative_renders_above_the_cards_with_proof_chips():
    narrative = NarrativeSection(
        headline="营销越界，而非口味分歧",
        headline_finding_ids=("f-a", "f-b"),
        paragraphs=(NarrativeParagraph(role="定性", clauses=(
            NarrativeClause(text="争议核心是文案对节日情感的冒犯。", finding_ids=("f-a",)),
        )),),
    )
    html = render_html(_plan(narrative))
    assert "营销越界，而非口味分歧" in html
    assert "争议核心是文案对节日情感的冒犯" in html
    assert html.count("narrative-chip") == 2
    assert html.index("narrative-block") < html.index("<nav")


def test_card_only_output_still_renders():
    html = render_html(_plan(None))
    assert "narrative-block" not in html
    assert "事件" in html
