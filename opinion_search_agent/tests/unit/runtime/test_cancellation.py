import asyncio

from opinion_search.app.action_executor import OpinionActionExecutor
from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.action_resolver import (
    OpinionSearchActionResolver,
)
from opinion_search.domain.opinion.actions import OpinionAction
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
)
from opinion_search.domain.opinion.processor import (
    OpinionObservation,
    OpinionSearchCompletionEvaluator,
    OpinionSearchObservationProcessor,
)
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    InvestigationGap,
    OpinionSearchState,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeAction,
    FakeActionExecutor,
    FakeActionResolver,
    FakeCompletionEvaluator,
    FakeDecisionValidator,
    FakeObservation,
    FakeObservationProcessor,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    ScriptedModelClient,
    default_script,
)
from opinion_search.runtime.cancellation import (
    CancellationSignal,
    EventCancellationSignal,
    NeverCancelledSignal,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.loop import AgentLoop
from opinion_search.runtime.transaction import RunState
from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
    fake_reader_definition,
    fake_search_definition,
)
from opinion_search.tools.capabilities.web import SearchHit
from opinion_search.tools.contracts import RetryPolicy, ToolInvocation
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.registry import ToolRegistry


FakeRunState = RunState[
    OpinionSearchState,
    AgentDecision,
    FakeAction,
    FakeObservation,
]


CANDIDATE_URL = "https://example.com/primary"


class BlockingModel:
    async def decide(self, context) -> AgentDecision:
        await asyncio.Event().wait()


class BlockingSearchAdapter(FakeSearchAdapter):
    async def invoke(self, invocation: ToolInvocation):
        await asyncio.Event().wait()


def _initial_state() -> RunState:
    return RunState(
        run_id="run-cancel",
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


def _build_fake_loop(
    path,
    *,
    model=None,
    signal: CancellationSignal | None = None,
    hook=None,
):
    model = model or ScriptedModelClient(default_script())
    executor = FakeActionExecutor()
    store = JsonCheckpointStore(path, FakeRunState)
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
        max_steps=10,
        cancellation_signal=signal,
        hook=hook,
    )
    return loop, model, executor, store


def _build_tool_loop(path, *, signal: CancellationSignal | None = None):
    search_adapter = BlockingSearchAdapter(
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
        pages={
            CANDIDATE_URL: FakePage(
                title="Primary source",
                content="The complete official event description.",
                artifact_ref="artifact-primary",
            )
        }
    )
    registry = ToolRegistry()
    registry.register(fake_search_definition(), search_adapter)
    registry.register(fake_reader_definition(), reader_adapter)
    tool_executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=1, timeout_seconds=30),
    )
    policy = MinimalOpinionCompletionPolicy()
    tool_run_state = RunState[
        OpinionSearchState,
        AgentDecision,
        OpinionAction,
        OpinionObservation,
    ]
    store = JsonCheckpointStore(path, tool_run_state)
    loop = AgentLoop(
        model=ScriptedModelClient(default_script()),
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=OpinionSearchActionResolver(policy),
        action_executor=OpinionActionExecutor(tool_executor),
        observation_processor=OpinionSearchObservationProcessor(),
        completion_evaluator=OpinionSearchCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=store,
        id_factory=DeterministicIdFactory(),
        max_steps=10,
        cancellation_signal=signal,
    )
    return loop, search_adapter, store


def test_event_signal_cancel_is_idempotent() -> None:
    signal = EventCancellationSignal()
    assert signal.is_cancelled() is False
    signal.cancel()
    signal.cancel()
    assert signal.is_cancelled() is True


def test_never_cancelled_signal_is_not_cancelled() -> None:
    signal = NeverCancelledSignal()
    assert signal.is_cancelled() is False


def test_cancellation_before_model_call_skips_the_model(tmp_path) -> None:
    signal = EventCancellationSignal()
    signal.cancel()
    loop, model, executor, store = _build_fake_loop(
        tmp_path / "run.json",
        signal=signal,
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.CANCELLED
    assert result.stop_reason == "The run was cancelled."
    assert model.calls == []
    assert len(executor.execution_counts) == 0
    assert checkpoint.status is RunStatus.CANCELLED
    assert checkpoint.stop_reason == "The run was cancelled."


def test_cancellation_while_model_blocked_cancels_model_task(tmp_path) -> None:
    signal = EventCancellationSignal()
    loop, model, executor, store = _build_fake_loop(
        tmp_path / "run.json",
        model=BlockingModel(),
        signal=signal,
    )

    async def scenario():
        task = asyncio.create_task(loop.run(_initial_state()))
        await asyncio.sleep(0.05)
        signal.cancel()
        return await task

    result = asyncio.run(scenario())
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.CANCELLED
    assert checkpoint.active_step is None
    assert not checkpoint.committed_steps
    assert result.domain_state.revision == 0


def test_cancellation_while_tool_adapter_blocked_cancels_adapter(
    tmp_path,
) -> None:
    signal = EventCancellationSignal()
    loop, search_adapter, store = _build_tool_loop(
        tmp_path / "run.json",
        signal=signal,
    )

    async def scenario():
        task = asyncio.create_task(loop.run(_initial_state()))
        await asyncio.sleep(0.05)
        signal.cancel()
        return await task

    result = asyncio.run(scenario())
    checkpoint = asyncio.run(store.load())

    assert result.status is RunStatus.CANCELLED
    assert not result.domain_state.candidate_source_ids
    assert not checkpoint.committed_steps
    assert checkpoint.active_step is None
    assert result.domain_state.revision == 0


def test_normal_completion_when_cancellation_never_fires(tmp_path) -> None:
    loop, model, executor, store = _build_fake_loop(tmp_path / "run.json")

    result = asyncio.run(loop.run(_initial_state()))

    assert result.status is RunStatus.COMPLETED
    assert len(model.calls) == 5


class CancelAtBoundary:
    def __init__(
        self,
        signal: EventCancellationSignal,
        boundary,
        occurrence: int = 1,
    ) -> None:
        self._signal = signal
        self._boundary = boundary
        self._occurrence = occurrence
        self._seen = 0

    async def after_checkpoint(self, boundary, state) -> None:
        if boundary is self._boundary:
            self._seen += 1
            if self._seen == self._occurrence:
                self._signal.cancel()


def test_cancellation_after_observation_ready_commits_exactly_once(
    tmp_path,
) -> None:
    from opinion_search.runtime.loop import CheckpointBoundary

    signal = EventCancellationSignal()
    loop, model, executor, store = _build_fake_loop(
        tmp_path / "run.json",
        signal=signal,
        hook=CancelAtBoundary(signal, CheckpointBoundary.OBSERVATION_READY),
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    first_action_id = checkpoint.committed_action_ids[0]
    assert result.status is RunStatus.CANCELLED
    assert len(checkpoint.committed_steps) == 1
    assert checkpoint.active_step is None
    assert checkpoint.domain_state.revision == 1
    assert checkpoint.committed_action_ids == (first_action_id,)
    assert executor.execution_counts.get(first_action_id, 0) == 1
    assert sum(executor.execution_counts.values()) == 1
    # reload reflects the same committed domain state
    reloaded = asyncio.run(
        JsonCheckpointStore(tmp_path / "run.json", FakeRunState).load()
    )
    assert reloaded.domain_state == checkpoint.domain_state


def test_cancellation_after_reducing_commits_exactly_once(tmp_path) -> None:
    from opinion_search.runtime.loop import CheckpointBoundary

    signal = EventCancellationSignal()
    loop, model, executor, store = _build_fake_loop(
        tmp_path / "run.json",
        signal=signal,
        hook=CancelAtBoundary(signal, CheckpointBoundary.REDUCING),
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(store.load())

    first_action_id = checkpoint.committed_action_ids[0]
    assert result.status is RunStatus.CANCELLED
    assert len(checkpoint.committed_steps) == 1
    assert checkpoint.active_step is None
    assert checkpoint.domain_state.revision == 1
    assert checkpoint.committed_action_ids == (first_action_id,)
    assert executor.execution_counts.get(first_action_id, 0) == 1
    assert sum(executor.execution_counts.values()) == 1
