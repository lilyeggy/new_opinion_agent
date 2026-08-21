import asyncio
from collections.abc import Awaitable

from pydantic import BaseModel, ConfigDict

from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolAdapterError,
    ToolAdapterResponse,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolErrorKind,
    ToolInvocation,
    ToolResult,
)
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.registry import ToolRegistry
from opinion_search.tools.circuit import (
    CircuitStatus,
    ProviderCircuitBreaker,
    ProviderCircuitKey,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str


Outcome = ToolAdapterResponse | BaseException


class ScriptedAdapter:
    def __init__(self, outcomes: list[Outcome]) -> None:
        self.outcomes = outcomes
        self.invocations: list[ToolInvocation[Arguments]] = []

    async def invoke(
        self,
        invocation: ToolInvocation[Arguments],
    ) -> ToolAdapterResponse:
        self.invocations.append(invocation)
        outcome = self.outcomes[len(self.invocations) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BlockingAdapter:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.invocations = 0

    async def invoke(
        self,
        invocation: ToolInvocation[Arguments],
    ) -> ToolAdapterResponse:
        self.invocations += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class SlowAdapter:
    def __init__(self) -> None:
        self.invocations = 0

    async def invoke(
        self,
        invocation: ToolInvocation[Arguments],
    ) -> ToolAdapterResponse:
        self.invocations += 1
        await asyncio.sleep(1)
        return ToolAdapterResponse(payload={"unreachable": True})


def _definition() -> ToolDefinition:
    return ToolDefinition(
        name="search.web",
        description="Search the public web.",
        capability="search",
        input_model=Arguments,
    )


def _registry(adapter: object) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="search.web",
            description="Search the public web.",
            capability="search",
            input_model=Arguments,
        ),
        adapter,  # type: ignore[arg-type]
    )
    return registry


def _call(**arguments: object) -> ToolCall:
    return ToolCall(
        action_id="action-stable",
        tool_name="search.web",
        arguments=arguments,
    )


def _multi_registry(primary: object, fallback: object) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_provider(_definition(), "primary", primary)
    registry.register_provider(_definition(), "fallback", fallback)
    return registry


def _run(awaitable: Awaitable[object]) -> object:
    return asyncio.run(awaitable)


def test_primary_exhausts_retryable_then_fallback_succeeds() -> None:
    primary = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "Primary failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "Primary failed."),
        ]
    )
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    executor = ToolExecutor(
        _multi_registry(primary, fallback),
        retry_policy=RetryPolicy(max_attempts_per_provider=2, timeout_seconds=1),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolResult)
    assert outcome.attempts == 3
    assert [item.attempt for item in primary.invocations] == [1, 2]
    assert [item.attempt for item in fallback.invocations] == [3]


def test_primary_authentication_fallback_succeeds_without_retrying_primary(
) -> None:
    primary = ScriptedAdapter(
        [ToolAdapterError(ToolErrorKind.AUTHENTICATION, "Denied.")]
    )
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    executor = ToolExecutor(
        _multi_registry(primary, fallback),
        retry_policy=RetryPolicy(max_attempts_per_provider=3, timeout_seconds=1),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolResult)
    assert len(primary.invocations) == 1
    assert len(fallback.invocations) == 1
    assert outcome.attempts == 2


def test_cancelled_primary_calls_no_fallback() -> None:
    primary = ScriptedAdapter(
        [ToolAdapterError(ToolErrorKind.CANCELLED, "Cancelled.")]
    )
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    executor = ToolExecutor(_multi_registry(primary, fallback))

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.CANCELLED
    assert fallback.invocations == []
    assert outcome.attempts == 1


def test_all_providers_fail_returns_final_safe_error_with_total_attempts() -> None:
    primary = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "A failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "A failed."),
        ]
    )
    fallback = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "B failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "B failed."),
        ]
    )
    executor = ToolExecutor(
        _multi_registry(primary, fallback),
        retry_policy=RetryPolicy(max_attempts_per_provider=2, timeout_seconds=1),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.SERVER_ERROR
    assert outcome.retryable is True
    assert outcome.attempts == 4
    assert outcome.message == "B failed."


def test_cache_hit_calls_no_provider() -> None:
    primary = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    executor = ToolExecutor(_multi_registry(primary, fallback))
    call = _call(query="topic")
    _run(executor.execute(call))

    second = _run(executor.execute(call))

    assert isinstance(second, ToolResult)
    assert len(primary.invocations) == 1
    assert fallback.invocations == []


def test_retry_after_dominates_smaller_exponential_and_is_capped() -> None:
    policy = RetryPolicy(
        backoff_seconds=0.1,
        max_backoff_seconds=5,
    )
    assert policy.backoff_after(1, retry_after_seconds=2) == 2.0
    assert policy.backoff_after(1, retry_after_seconds=8) == 5.0

    large_exponential = RetryPolicy(
        backoff_seconds=10,
        max_backoff_seconds=5,
    )
    assert large_exponential.backoff_after(1, retry_after_seconds=2) == 5.0


def test_no_provider_id_appears_in_result_or_error_dump() -> None:
    primary = ScriptedAdapter([ToolAdapterResponse(payload={"items": []})])
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"items": []})])
    result_executor = ToolExecutor(_multi_registry(primary, fallback))
    outcome = _run(result_executor.execute(_call(query="topic")))
    assert isinstance(outcome, ToolResult)
    assert "primary" not in outcome.model_dump_json()
    assert "fallback" not in outcome.model_dump_json()

    failing_primary = ScriptedAdapter(
        [ToolAdapterError(ToolErrorKind.AUTHENTICATION, "Denied.")]
    )
    failing_fallback = ScriptedAdapter(
        [ToolAdapterError(ToolErrorKind.AUTHENTICATION, "Denied.")]
    )
    err_executor = ToolExecutor(_multi_registry(failing_primary, failing_fallback))
    err_outcome = _run(err_executor.execute(_call(query="topic")))
    assert isinstance(err_outcome, ToolError)
    assert "primary" not in err_outcome.model_dump_json()
    assert "fallback" not in err_outcome.model_dump_json()


def test_circuit_open_provider_is_skipped_in_favor_of_fallback() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    primary = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "A failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "A failed."),
        ]
    )
    fallback = ScriptedAdapter(
        [ToolAdapterResponse(payload={"ok": True}),
         ToolAdapterResponse(payload={"ok": True})]
    )
    executor = ToolExecutor(
        _multi_registry(primary, fallback),
        retry_policy=RetryPolicy(max_attempts_per_provider=2, timeout_seconds=1),
        circuit_breaker=breaker,
    )

    first = _run(
        executor.execute(ToolCall(action_id="action-1", tool_name="search.web", arguments={"query": "topic"}))
    )
    second = _run(
        executor.execute(ToolCall(action_id="action-2", tool_name="search.web", arguments={"query": "topic"}))
    )

    assert isinstance(first, ToolResult)
    assert isinstance(second, ToolResult)
    assert len(primary.invocations) == 2
    assert len(fallback.invocations) == 2


def test_cache_hit_calls_no_provider_even_when_circuit_open() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=30,
        clock=clock,
    )
    primary = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    fallback = ScriptedAdapter([ToolAdapterResponse(payload={"ok": True})])
    executor = ToolExecutor(
        _multi_registry(primary, fallback),
        retry_policy=RetryPolicy(max_attempts_per_provider=2, timeout_seconds=1),
        circuit_breaker=breaker,
    )
    call = ToolCall(
        action_id="action-cached",
        tool_name="search.web",
        arguments={"query": "topic"},
    )

    _run(executor.execute(call))
    # force the primary circuit open
    breaker.record_failure(
        ProviderCircuitKey("search.web", "primary"),
        ToolErrorKind.SERVER_ERROR,
    )
    assert breaker.status(ProviderCircuitKey("search.web", "primary")) is CircuitStatus.OPEN

    second = _run(executor.execute(call))

    assert isinstance(second, ToolResult)
    assert len(primary.invocations) == 1
    assert fallback.invocations == []


def test_executor_validates_arguments_before_adapter_invocation() -> None:
    adapter = ScriptedAdapter([ToolAdapterResponse(payload={"should_not_run": True})])
    executor = ToolExecutor(_registry(adapter))

    outcome = _run(executor.execute(_call(unknown="value")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.INVALID_ARGUMENTS
    assert outcome.attempts == 0
    assert adapter.invocations == []


def test_executor_returns_unknown_tool_without_invocation() -> None:
    executor = ToolExecutor(ToolRegistry())
    call = ToolCall(
        action_id="action-1",
        tool_name="missing.tool",
        arguments={},
    )

    outcome = _run(executor.execute(call))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNKNOWN_TOOL
    assert outcome.attempts == 0


def test_executor_normalizes_successful_adapter_response() -> None:
    adapter = ScriptedAdapter(
        [
            ToolAdapterResponse(
                payload={"items": [{"url": "https://example.com"}]},
                artifact_refs=("artifact-1",),
            )
        ]
    )
    executor = ToolExecutor(_registry(adapter))

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolResult)
    assert outcome.action_id == "action-stable"
    assert outcome.tool_name == "search.web"
    assert outcome.attempts == 1
    assert outcome.artifact_refs == ("artifact-1",)


def test_executor_reuses_cached_success_for_the_same_action() -> None:
    adapter = ScriptedAdapter([ToolAdapterResponse(payload={"items": []})])
    executor = ToolExecutor(_registry(adapter))
    call = _call(query="topic")

    first = _run(executor.execute(call))
    second = _run(executor.execute(call))

    assert isinstance(first, ToolResult)
    assert second == first
    assert len(adapter.invocations) == 1


def test_executor_retries_retryable_error_with_stable_action_id() -> None:
    adapter = ScriptedAdapter(
        [
            ToolAdapterError(
                ToolErrorKind.RATE_LIMITED,
                "Rate limited.",
            ),
            ToolAdapterResponse(payload={"items": []}),
        ]
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    executor = ToolExecutor(
        _registry(adapter),
        retry_policy=RetryPolicy(
            max_attempts_per_provider=3,
            timeout_seconds=1,
            backoff_seconds=0.25,
        ),
        sleep=record_sleep,
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolResult)
    assert outcome.attempts == 2
    assert [item.attempt for item in adapter.invocations] == [1, 2]
    assert {item.action_id for item in adapter.invocations} == {"action-stable"}
    assert delays == [0.25]


def test_executor_returns_last_retryable_error_when_exhausted() -> None:
    adapter = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "Server failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "Server failed."),
            ToolAdapterError(ToolErrorKind.SERVER_ERROR, "Server failed."),
        ]
    )
    executor = ToolExecutor(
        _registry(adapter),
        retry_policy=RetryPolicy(max_attempts_per_provider=3, timeout_seconds=1),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.SERVER_ERROR
    assert outcome.retryable is True
    assert outcome.attempts == 3
    assert len(adapter.invocations) == 3


def test_executor_does_not_retry_non_retryable_adapter_error() -> None:
    adapter = ScriptedAdapter(
        [
            ToolAdapterError(
                ToolErrorKind.AUTHENTICATION,
                "Authentication failed.",
            )
        ]
    )
    executor = ToolExecutor(
        _registry(adapter),
        retry_policy=RetryPolicy(max_attempts_per_provider=3, timeout_seconds=1),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.AUTHENTICATION
    assert outcome.attempts == 1
    assert len(adapter.invocations) == 1


def test_executor_retries_timeout_then_reports_exhaustion() -> None:
    adapter = SlowAdapter()
    executor = ToolExecutor(
        _registry(adapter),
        retry_policy=RetryPolicy(
            max_attempts_per_provider=2,
            timeout_seconds=0.001,
        ),
    )

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.TIMEOUT
    assert outcome.attempts == 2
    assert adapter.invocations == 2


def test_executor_converts_unexpected_provider_exception_safely() -> None:
    adapter = ScriptedAdapter([RuntimeError("secret provider detail")])
    executor = ToolExecutor(_registry(adapter))

    outcome = _run(executor.execute(_call(query="topic")))

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNKNOWN_PROVIDER_ERROR
    assert "secret provider detail" not in outcome.message
    assert outcome.attempts == 1


def test_async_task_cancellation_propagates_and_stops_retries() -> None:
    async def scenario() -> None:
        adapter = BlockingAdapter()
        executor = ToolExecutor(
            _registry(adapter),
            retry_policy=RetryPolicy(max_attempts_per_provider=3, timeout_seconds=10),
        )
        task = asyncio.create_task(executor.execute(_call(query="topic")))
        await adapter.started.wait()
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation must propagate")

        assert adapter.invocations == 1

    asyncio.run(scenario())


def test_non_poisoning_probe_release_allows_later_call_to_reach_provider() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = ProviderCircuitKey("search.web", "default")
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    clock.advance(31)

    primary = ScriptedAdapter(
        [
            ToolAdapterError(ToolErrorKind.AUTHENTICATION, "Denied."),
            ToolAdapterError(ToolErrorKind.AUTHENTICATION, "Denied."),
        ]
    )
    executor = ToolExecutor(
        _registry(primary),
        retry_policy=RetryPolicy(max_attempts_per_provider=1, timeout_seconds=1),
        circuit_breaker=breaker,
    )

    first = _run(
        executor.execute(
            ToolCall(action_id="action-a", tool_name="search.web", arguments={"query": "topic"})
        )
    )
    second = _run(
        executor.execute(
            ToolCall(action_id="action-b", tool_name="search.web", arguments={"query": "topic"})
        )
    )

    # Without the fix the half-open probe is never released, so the second call
    # returns "all providers unavailable" with attempts == 0 instead of reaching
    # the provider again.
    assert isinstance(first, ToolError)
    assert isinstance(second, ToolError)
    assert second.attempts == 1
    assert second.kind is ToolErrorKind.AUTHENTICATION
    assert "unavailable" not in second.message
