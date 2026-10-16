from datetime import date

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.framing import (
    TemporalScopeProvenance,
    build_task_frame,
)


def test_relative_chinese_time_in_question_becomes_a_persistable_window() -> None:
    frame = build_task_frame(
        SearchRequest(question="过去一周公众对 Codex 额度的反映如何？"),
        anchor_date=date(2026, 8, 23),
    )

    assert frame.temporal_scope.start_date == date(2026, 8, 17)
    assert frame.temporal_scope.end_date == date(2026, 8, 23)
    assert frame.temporal_scope.anchor_date == date(2026, 8, 23)
    assert (
        frame.temporal_scope.provenance
        is TemporalScopeProvenance.INFERRED_FROM_QUESTION
    )


def test_explicit_request_time_range_overrides_question_inference() -> None:
    frame = build_task_frame(
        SearchRequest(
            question="过去一周公众对 Codex 额度的反映如何？",
            time_range="2026-06-01 至 2026-06-07",
        ),
        anchor_date=date(2026, 8, 23),
    )

    assert frame.temporal_scope.start_date == date(2026, 6, 1)
    assert frame.temporal_scope.end_date == date(2026, 6, 7)
    assert (
        frame.temporal_scope.provenance
        is TemporalScopeProvenance.EXPLICIT_REQUEST
    )


def test_ui_placeholder_time_range_with_inner_spaces_is_bounded() -> None:
    """Regression: the web placeholder literally shows "过去 30 天"; users who
    copy it verbatim must get a bounded window, not a silent unspecified."""
    for expression in ("过去 30 天", "过去 30天", "过去30 天", "过去  30  天"):
        frame = build_task_frame(
            SearchRequest(question="某事件始末如何？", time_range=expression),
            anchor_date=date(2026, 9, 21),
        )

        assert frame.temporal_scope.is_bounded, expression
        assert frame.temporal_scope.start_date == date(2026, 8, 23)
        assert frame.temporal_scope.end_date == date(2026, 9, 21)
        assert (
            frame.temporal_scope.provenance
            is TemporalScopeProvenance.EXPLICIT_REQUEST
        )


def test_unsupported_time_language_remains_explicitly_unspecified() -> None:
    frame = build_task_frame(
        SearchRequest(question="前年秋天的公众反映如何？"),
        anchor_date=date(2026, 8, 23),
    )

    assert frame.temporal_scope.provenance is TemporalScopeProvenance.UNSPECIFIED
    assert frame.temporal_scope.start_date is None
    assert frame.temporal_scope.end_date is None


def test_slash_separated_iso_range_from_cli_documentation_is_bounded() -> None:
    frame = build_task_frame(
        SearchRequest(question="q", time_range="2026-08-01/2026-08-20"),
        anchor_date=date(2026, 8, 25),
    )

    assert frame.temporal_scope.start_date == date(2026, 8, 1)
    assert frame.temporal_scope.end_date == date(2026, 8, 20)
