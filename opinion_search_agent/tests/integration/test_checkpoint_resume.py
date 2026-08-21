import asyncio

import pytest

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    InvestigationGap,
    OpinionSearchState,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeActionExecutor,
    FakeActionResolver,
    FakeCompletionEvaluator,
    FakeDecisionValidator,
    FakeObservationProcessor,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    OpinionRunState,
    ScriptedModelClient,
    default_script,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.lifecycle import RunStatus, StepPhase
from opinion_search.runtime.loop import (
    AgentLoop,
    CheckpointBoundary,
    RuntimeState,
)


class InjectedCrash(RuntimeError):
    pass


class CrashAtBoundary:
    def __init__(
        self,
        boundary: CheckpointBoundary,
        occurrence: int = 1,
    ) -> None:
        self._boundary = boundary
        self._occurrence = occurrence
        self._seen = 0

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        if boundary is not self._boundary:
            return
        self._seen += 1
        if self._seen == self._occurrence:
            raise InjectedCrash(boundary.value)


def _initial_state() -> OpinionRunState:
    return OpinionRunState(
        run_id="run-resume",
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


def _build_loop(path, *, hook=None):
    executor = FakeActionExecutor()
    store = JsonCheckpointStore(path, OpinionRunState)
    loop = AgentLoop(
        model=ScriptedModelClient(default_script()),
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=FakeActionResolver(MinimalOpinionCompletionPolicy()),
        action_executor=executor,
        observation_processor=FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=store,
        id_factory=DeterministicIdFactory(),
        max_steps=10,
        hook=hook,
    )
    return loop, executor, store


def test_resume_from_action_running_reuses_stable_action_id(tmp_path) -> None:
    path = tmp_path / "run.json"
    crashing_loop, _, store = _build_loop(
        path,
        hook=CrashAtBoundary(CheckpointBoundary.ACTION_RUNNING),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(crashing_loop.run(_initial_state()))

    crashed = asyncio.run(store.load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.ACTION_RUNNING
    action_id = crashed.active_step.action.action_id

    resumed_loop, resumed_executor, _ = _build_loop(path)
    result = asyncio.run(resumed_loop.resume())

    assert result.status is RunStatus.COMPLETED
    assert resumed_executor.execution_counts[action_id] == 1


def test_resume_from_observation_does_not_execute_action_again(
    tmp_path,
) -> None:
    path = tmp_path / "run.json"
    crashing_loop, _, store = _build_loop(
        path,
        hook=CrashAtBoundary(CheckpointBoundary.OBSERVATION_READY),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(crashing_loop.run(_initial_state()))

    crashed = asyncio.run(store.load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.OBSERVATION_READY
    action_id = crashed.active_step.action.action_id

    resumed_loop, resumed_executor, _ = _build_loop(path)
    result = asyncio.run(resumed_loop.resume())

    assert result.status is RunStatus.COMPLETED
    assert resumed_executor.execution_counts[action_id] == 0


def test_resume_after_final_commit_does_not_repeat_state_effect(
    tmp_path,
) -> None:
    path = tmp_path / "run.json"
    crashing_loop, _, store = _build_loop(
        path,
        hook=CrashAtBoundary(
            CheckpointBoundary.STEP_COMMITTED,
            occurrence=5,
        ),
    )

    with pytest.raises(InjectedCrash):
        asyncio.run(crashing_loop.run(_initial_state()))

    crashed = asyncio.run(store.load())
    assert crashed.active_step is None
    assert crashed.continuation_pending is True
    assert crashed.domain_state.revision == 3
    assert len(crashed.committed_steps) == 5

    resumed_loop, resumed_executor, _ = _build_loop(path)
    result = asyncio.run(resumed_loop.resume())

    assert result.status is RunStatus.COMPLETED
    assert result.domain_state.revision == 3
    assert sum(resumed_executor.execution_counts.values()) == 0
