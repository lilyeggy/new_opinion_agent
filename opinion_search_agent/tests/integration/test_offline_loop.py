import asyncio

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
from opinion_search.runtime.cancellation import EventCancellationSignal
from opinion_search.runtime.completion import CompletionDisposition
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.loop import (
    AgentLoop,
    CheckpointBoundary,
    RuntimeState,
)


def _initial_state() -> OpinionRunState:
    return OpinionRunState(
        run_id="run-offline",
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
    checkpoint_path,
    *,
    max_steps: int = 10,
    cancellation_signal=None,
    hook=None,
):
    model = ScriptedModelClient(default_script())
    executor = FakeActionExecutor()
    store = JsonCheckpointStore(checkpoint_path, OpinionRunState)
    loop = AgentLoop(
        model=model,
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=FakeActionResolver(MinimalOpinionCompletionPolicy()),
        action_executor=executor,
        observation_processor=FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=store,
        id_factory=DeterministicIdFactory(),
        max_steps=max_steps,
        cancellation_signal=cancellation_signal,
        hook=hook,
    )
    return loop, model, executor, store


def test_offline_loop_completes_five_step_investigation(tmp_path) -> None:
    loop, model, executor, store = _build_loop(tmp_path / "run.json")

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.domain_state.open_gap_ids == ()
    assert result.domain_state.resolved_gap_ids == ("gap-primary",)
    assert result.domain_state.candidate_source_ids == (
        "https://example.test/gap-primary",
    )
    assert result.domain_state.read_source_ids == ("https://example.test/gap-primary",)
    assert result.domain_state.revision == 3
    assert len(checkpoint.committed_steps) == 5
    assert len(executor.execution_counts) == 5
    assert len(model.calls) == 5


def test_premature_finish_is_persisted_feedback_not_domain_evidence(
    tmp_path,
) -> None:
    loop, model, _, store = _build_loop(tmp_path / "run.json")

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())
    finish_observation = checkpoint.committed_steps[1].observation

    assert finish_observation is not None
    verdict = finish_observation.observation.completion_verdict
    assert verdict is not None
    assert verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
    assert model.calls[2].last_completion_feedback == verdict.reason
    assert verdict.reason not in result.domain_state.reflections


def test_step_limit_returns_partial_with_committed_state(tmp_path) -> None:
    loop, _, _, store = _build_loop(
        tmp_path / "run.json",
        max_steps=2,
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.PARTIAL
    assert result.domain_state.candidate_source_ids == (
        "https://example.test/gap-primary",
    )
    assert result.domain_state.open_gap_ids == ("gap-primary",)
    assert len(checkpoint.committed_steps) == 2


class CancelAfterFirstCommit:
    def __init__(self, signal: EventCancellationSignal) -> None:
        self._signal = signal
        self._committed = 0

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        if boundary is CheckpointBoundary.STEP_COMMITTED:
            self._committed += 1
            if self._committed == 1:
                self._signal.cancel()


def test_cancellation_preserves_committed_state(tmp_path) -> None:
    signal = EventCancellationSignal()
    loop, _, _, store = _build_loop(
        tmp_path / "run.json",
        cancellation_signal=signal,
        hook=CancelAfterFirstCommit(signal),
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.CANCELLED
    assert result.domain_state.candidate_source_ids == (
        "https://example.test/gap-primary",
    )
    assert len(checkpoint.committed_steps) == 1
    assert checkpoint.active_step is None
