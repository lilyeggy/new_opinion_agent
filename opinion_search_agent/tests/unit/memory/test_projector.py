import pytest
from pydantic import ValidationError

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Evidence,
    GapStatus,
    InvestigationGap,
    Narrative,
    NarrativeKind,
    OpinionSearchState,
    Source,
)
from opinion_search.memory.models import WorkingMemory
from opinion_search.memory.projector import project_working_memory


OFFICIAL = "https://example.org/official"
REPORT = "https://news.example/report"
ANALYSIS = "https://research.example/analysis"


def _state(*, no_open_gaps: bool = False) -> OpinionSearchState:
    open_status = GapStatus.RESOLVED if no_open_gaps else GapStatus.OPEN
    open_note = "Resolved for the fixture." if no_open_gaps else None
    gaps = (
        InvestigationGap(
            gap_id="gap-primary",
            question="Find the primary account.",
            priority=5,
            status=open_status,
            evidence_ids=("evidence-official",) if no_open_gaps else (),
            resolution_note=open_note,
        ),
        InvestigationGap(
            gap_id="gap-source",
            question="Find independent attribution.",
            priority=4,
            status=open_status,
            evidence_ids=("evidence-official",) if no_open_gaps else (),
            resolution_note=open_note,
        ),
        InvestigationGap(
            gap_id="gap-timeline",
            question="Establish the timeline.",
            status=GapStatus.RESOLVED,
            evidence_ids=("evidence-official",),
            resolution_note="The timeline is established.",
        ),
    )
    candidates = tuple(
        CandidateSource(
            source_id=url,
            url=url,
            title=title,
            snippet=f"Candidate snippet for {title}.",
            discovered_for_gap_ids=("gap-primary",),
        )
        for url, title in (
            (OFFICIAL, "Official"),
            (REPORT, "Report"),
            (ANALYSIS, "Analysis"),
        )
    )
    sources = (
        Source(source_id=OFFICIAL, url=OFFICIAL, title="Official"),
        Source(source_id=ANALYSIS, url=ANALYSIS, title="Analysis"),
    )
    evidence = (
        Evidence(
            evidence_id="evidence-official",
            source_id=OFFICIAL,
            acquired_for_gap_id="gap-primary",
            excerpt="The official source provides the timeline.",
            locator="Timeline paragraph.",
        ),
    )
    return OpinionSearchState(
        request=SearchRequest(
            question="What happened and how is it being described?",
            topic="Example event",
            time_range="2026-08-01/2026-08-20",
            focus="Compare the official and independent accounts.",
            language="en",
            include_domains=("example.org",),
            exclude_domains=("spam.example",),
        ),
        gaps=gaps,
        candidates=candidates,
        sources=sources,
        evidence=evidence,
        reflections=(
            "The timeline is established.",
            "Independent attribution is still missing.",
        ),
        revision=7,
    )


def test_projector_builds_compact_rich_view_from_committed_state() -> None:
    memory = project_working_memory(_state())

    assert memory.state_revision == 7
    assert memory.goal.question == ("What happened and how is it being described?")
    assert memory.current_gap_id == "gap-primary"
    assert memory.current_focus == ("Compare the official and independent accounts.")
    assert memory.open_gap_ids == ("gap-primary", "gap-source")
    assert memory.resolved_gap_ids == ("gap-timeline",)
    assert memory.blocked_gap_ids == ()
    assert memory.pending_candidate_source_ids == (REPORT,)
    assert memory.read_source_ids == (OFFICIAL, ANALYSIS)
    assert memory.evidence[0].evidence_id == "evidence-official"
    assert memory.opinion_coverage[2].evidence_ids == ("evidence-official",)
    assert tuple(item.source_id for item in memory.candidates) == (REPORT,)


def test_projection_is_deterministic_and_rebuildable() -> None:
    state = _state()
    first = project_working_memory(state)
    rebuilt = project_working_memory(
        OpinionSearchState.model_validate_json(state.model_dump_json())
    )

    assert rebuilt.model_dump_json() == first.model_dump_json()
    assert WorkingMemory.model_validate_json(first.model_dump_json()) == rebuilt


def test_projection_uses_no_process_local_cursor_or_mutable_alias() -> None:
    payload = _state().model_dump(mode="json")
    state = OpinionSearchState.model_validate(payload)
    memory = project_working_memory(state)

    payload["gaps"].clear()
    payload["candidates"].clear()

    assert memory.current_gap_id == "gap-primary"
    assert memory.pending_candidate_source_ids == (REPORT,)


def test_projector_has_no_focus_gap_when_no_gap_remains_open() -> None:
    memory = project_working_memory(_state(no_open_gaps=True))

    assert memory.current_gap_id is None
    assert memory.open_gap_ids == ()


def test_memory_models_are_frozen_strict_and_exclude_runtime_feedback() -> None:
    memory = project_working_memory(_state())

    with pytest.raises(ValidationError):
        memory.state_revision = 8
    with pytest.raises(ValidationError):
        WorkingMemory.model_validate(
            {
                **memory.model_dump(mode="json"),
                "last_tool_feedback": "Recent interaction owns this.",
            }
        )


def test_goal_preserves_optional_absence_without_inventing_defaults() -> None:
    state = OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Find the primary account.",
            ),
        ),
    )

    goal = project_working_memory(state).goal

    assert goal.topic is None
    assert goal.time_range is None
    assert goal.focus is None
    assert goal.language == "zh"


def test_projector_prefers_committed_reflect_focus_over_request_focus() -> None:
    state = _state().model_copy(
        update={"current_focus": "Investigate the alternative account."}
    )

    memory = project_working_memory(state)

    assert memory.goal.focus == ("Compare the official and independent accounts.")
    assert memory.current_focus == "Investigate the alternative account."


def test_projector_selects_highest_priority_open_gap_not_tuple_order() -> None:
    state = OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-low",
                question="Low priority.",
                priority=1,
            ),
            InvestigationGap(
                gap_id="gap-high",
                question="High priority.",
                priority=5,
            ),
        ),
    )

    memory = project_working_memory(state)

    assert memory.open_gap_ids == ("gap-low", "gap-high")
    assert memory.current_gap_id == "gap-high"


def _semantic_state() -> OpinionSearchState:
    gaps = (
        InvestigationGap(
            gap_id="gap-factual",
            question="Establish the factual baseline.",
            priority=5,
        ),
        InvestigationGap(
            gap_id="gap-counter",
            question="Map counter narratives.",
            priority=4,
            status=GapStatus.RESOLVED,
            evidence_ids=("evidence-source",),
            resolution_note="Counter framing committed.",
        ),
    )
    candidates = (
        CandidateSource(
            source_id=OFFICIAL,
            url=OFFICIAL,
            title="Official",
            snippet="Official.",
            discovered_for_gap_ids=("gap-factual",),
        ),
    )
    sources = (Source(source_id=OFFICIAL, url=OFFICIAL, title="Official"),)
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=gaps,
        candidates=candidates,
        sources=sources,
        evidence=(
            Evidence(
                evidence_id="evidence-source",
                source_id=OFFICIAL,
                acquired_for_gap_id="gap-factual",
                excerpt="A source describing the event.",
                locator="1.",
            ),
        ),
        narratives=(
            Narrative(
                narrative_id="narrative-counter",
                summary="A counter frame.",
                kind=NarrativeKind.COUNTER,
                evidence_ids=("evidence-source",),
            ),
        ),
    )


def test_evidence_semantic_gap_projection_is_separate_from_acquisition() -> None:
    memory = project_working_memory(_semantic_state())

    evidence = memory.evidence[0]
    assert evidence.acquired_for_gap_id == "gap-factual"
    assert evidence.semantic_gap_ids == ("gap-counter",)
    assert evidence.narrative_ids == ("narrative-counter",)
    # coverage for the semantic gap cites the source even though acquisition
    # was for the factual baseline
    counter_cell = next(
        cell for cell in memory.opinion_coverage if cell.gap_id == "gap-counter"
    )
    assert counter_cell.source_ids == (OFFICIAL,)
    assert counter_cell.evidence_ids == ("evidence-source",)


def test_working_memory_json_round_trip_preserves_semantic_fields() -> None:
    memory = project_working_memory(_semantic_state())

    restored = WorkingMemory.model_validate_json(memory.model_dump_json())

    assert restored == memory
    assert restored.evidence[0].semantic_gap_ids == ("gap-counter",)


def test_deleting_and_reprojecting_memory_returns_equality() -> None:
    state = _semantic_state()
    first = project_working_memory(state)

    rebuilt = project_working_memory(
        OpinionSearchState.model_validate_json(state.model_dump_json())
    )

    assert rebuilt.model_dump_json() == first.model_dump_json()


def test_projector_does_not_mutate_state() -> None:
    state = _semantic_state()
    before = state.model_dump(mode="json")

    project_working_memory(state)

    assert state.model_dump(mode="json") == before
