import asyncio
from typing import TypeAlias

import pytest

from opinion_search.app.action_executor import OpinionActionExecutor
from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.action_resolver import (
    OpinionSearchActionResolver,
)
from opinion_search.domain.opinion.actions import OpinionAction, ToolAction
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    GapAssessmentProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.processor import (
    OpinionObservation,
    OpinionSearchCompletionEvaluator,
    OpinionSearchObservationProcessor,
    ToolObservation,
)
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    CandidateSource,
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    stable_domain_id,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeDecisionValidator,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    ScriptedModelClient,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.lifecycle import RunStatus, StepPhase
from opinion_search.runtime.loop import (
    AgentLoop,
    CheckpointBoundary,
    RuntimeState,
)
from opinion_search.runtime.transaction import RunState
from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
    fake_reader_definition,
    fake_search_definition,
)
from opinion_search.tools.capabilities.web import SearchHit
from opinion_search.tools.contracts import RetryPolicy, ToolResult
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.registry import ToolRegistry


CANDIDATE_URL = "https://example.com/primary"

OpinionToolRunState: TypeAlias = RunState[
    OpinionSearchState,
    AgentDecision,
    OpinionAction,
    OpinionObservation,
]


class InjectedCrash(RuntimeError):
    pass


class CrashAtBoundary:
    def __init__(self, boundary: CheckpointBoundary) -> None:
        self._boundary = boundary

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        if boundary is self._boundary:
            raise InjectedCrash(boundary.value)


def _script() -> tuple[AgentDecision, ...]:
    evidence_id = stable_domain_id(
        "evidence",
        CANDIDATE_URL,
        "gap-primary",
        "The complete official event description.",
    )
    return (
        SearchDecision(
            action="search",
            query="official announcement",
            target_gap_id="gap-primary",
            purpose="Find the primary source.",
        ),
        FinishDecision(
            action="finish",
            answer_candidate="Not ready.",
            resolved_gap_ids=(),
            unresolved_gap_ids=("gap-primary",),
        ),
        ReadDecision(
            action="read",
            candidate_source_id=CANDIDATE_URL,
            target_gap_id="gap-primary",
            focus="Read the primary source.",
        ),
        ReflectDecision(
            action="reflect",
            assessment="The primary source resolves the gap.",
            next_focus="Prepare the answer.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id="gap-primary",
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(evidence_id,),
                    rationale="The primary source resolves the gap.",
                ),
            ),
        ),
        FinishDecision(
            action="finish",
            answer_candidate="Complete.",
            resolved_gap_ids=("gap-primary",),
            unresolved_gap_ids=(),
        ),
    )


def _initial_state() -> OpinionToolRunState:
    return OpinionToolRunState(
        run_id="run-with-tools",
        domain_state=OpinionSearchState(
            request=SearchRequest(question="What happened?"),
            gaps=(
                InvestigationGap(
                    gap_id="gap-primary",
                    question="Find the primary account.",
                    priority=5,
                ),
            ),
        ),
    )


def _build_loop(
    path,
    *,
    hook=None,
    decisions=None,
    reader_pages=None,
    max_steps: int = 10,
):
    search_adapter = FakeSearchAdapter(
        {
            "official announcement": (
                SearchHit(
                    title="Primary source",
                    url=CANDIDATE_URL,
                    snippet="Official event facts.",
                ),
            )
        }
    )
    reader_adapter = FakeReaderAdapter(
        pages=reader_pages
        if reader_pages is not None
        else {
            CANDIDATE_URL: FakePage(
                title="Primary source",
                content="The complete official event description.",
                artifact_ref="artifact-primary",
            )
        },
    )
    registry = ToolRegistry()
    registry.register(fake_search_definition(), search_adapter)
    registry.register(fake_reader_definition(), reader_adapter)
    tool_executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=2, timeout_seconds=1),
    )
    policy = MinimalOpinionCompletionPolicy()
    model = ScriptedModelClient(decisions or _script())
    store = JsonCheckpointStore(path, OpinionToolRunState)
    loop = AgentLoop(
        model=model,
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=OpinionSearchActionResolver(policy),
        action_executor=OpinionActionExecutor(tool_executor),
        observation_processor=OpinionSearchObservationProcessor(),
        completion_evaluator=OpinionSearchCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=store,
        id_factory=DeterministicIdFactory(),
        max_steps=max_steps,
        hook=hook,
    )
    return loop, model, search_adapter, reader_adapter, store


def test_loop_executes_search_and_read_through_tool_runtime(tmp_path) -> None:
    loop, model, search_adapter, reader_adapter, store = _build_loop(
        tmp_path / "run.json"
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.domain_state.candidate_source_ids == (CANDIDATE_URL,)
    assert result.domain_state.read_source_ids == (CANDIDATE_URL,)
    assert result.domain_state.resolved_gap_ids == ("gap-primary",)
    assert result.domain_state.revision == 3
    assert len(checkpoint.committed_steps) == 5
    assert len(search_adapter.invocations) == 1
    assert len(reader_adapter.invocations) == 1
    assert model.calls[2].last_completion_feedback is not None

    search_step = checkpoint.committed_steps[0]
    assert search_step.action is not None
    assert isinstance(search_step.action.action, ToolAction)
    assert search_step.observation is not None
    assert isinstance(
        search_step.observation.observation,
        ToolObservation,
    )
    outcome = search_step.observation.observation.outcome
    assert isinstance(outcome, ToolResult)
    assert outcome.action_id == search_step.action.action_id
    assert search_adapter.invocations[0].action_id == outcome.action_id


def test_action_running_resume_reuses_tool_action_id(tmp_path) -> None:
    path = tmp_path / "run.json"
    crashing_loop, _, _, _, store = _build_loop(
        path,
        hook=CrashAtBoundary(CheckpointBoundary.ACTION_RUNNING),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(crashing_loop.run(_initial_state()))

    crashed = asyncio.run(store.load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.ACTION_RUNNING
    stable_action_id = crashed.active_step.action.action_id

    resumed_loop, _, search_adapter, _, _ = _build_loop(path)
    result = asyncio.run(resumed_loop.resume())

    assert result.status is RunStatus.COMPLETED
    assert search_adapter.invocations[0].action_id == stable_action_id


def test_observation_ready_resume_does_not_repeat_tool_call(tmp_path) -> None:
    path = tmp_path / "run.json"
    crashing_loop, _, first_search_adapter, _, store = _build_loop(
        path,
        hook=CrashAtBoundary(CheckpointBoundary.OBSERVATION_READY),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(crashing_loop.run(_initial_state()))

    crashed = asyncio.run(store.load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.OBSERVATION_READY
    assert len(first_search_adapter.invocations) == 1

    resumed_loop, _, resumed_search_adapter, reader_adapter, _ = _build_loop(path)
    result = asyncio.run(resumed_loop.resume())

    assert result.status is RunStatus.COMPLETED
    assert resumed_search_adapter.invocations == []
    assert len(reader_adapter.invocations) == 1


def test_tool_error_is_committed_and_visible_to_the_next_decision(
    tmp_path,
) -> None:
    missing_url = "https://example.com/missing"
    decisions: tuple[AgentDecision, ...] = (
        ReadDecision(
            action="read",
            candidate_source_id=missing_url,
            target_gap_id="gap-primary",
            focus="Read the missing source.",
        ),
        SearchDecision(
            action="search",
            query="official announcement",
            target_gap_id="gap-primary",
            purpose="Recover by finding another source.",
        ),
    )
    initial = OpinionToolRunState(
        run_id="run-tool-error",
        domain_state=OpinionSearchState(
            request=SearchRequest(question="What happened?"),
            gaps=(
                InvestigationGap(
                    gap_id="gap-primary",
                    question="Find the primary account.",
                    priority=5,
                ),
            ),
            candidates=(
                CandidateSource(
                    source_id=missing_url,
                    url=missing_url,
                    title="Missing page",
                    snippet="Candidate page.",
                    discovered_for_gap_ids=("gap-primary",),
                ),
            ),
        ),
    )
    loop, model, _, reader_adapter, store = _build_loop(
        tmp_path / "run.json",
        decisions=decisions,
        reader_pages={},
        max_steps=2,
    )

    result = asyncio.run(loop.run(initial))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.PARTIAL
    assert len(reader_adapter.invocations) == 1
    assert model.calls[1].last_tool_feedback == ("The requested page was not found.")
    assert checkpoint.committed_steps[0].observation is not None
    observation = checkpoint.committed_steps[0].observation.observation
    assert isinstance(observation, ToolObservation)
    assert not isinstance(observation.outcome, ToolResult)
    assert result.domain_state.reflections == ()
