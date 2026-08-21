import asyncio
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from opinion_search.tools.cache import (
    InMemoryActionResultCache,
    ToolResultCache,
)
from opinion_search.tools.circuit import (
    ProviderCircuitBreaker,
    ProviderCircuitKey,
)
from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolAdapterError,
    ToolAdapterResponse,
    ToolCall,
    ToolError,
    ToolErrorKind,
    ToolInvocation,
    ToolOutcome,
    ToolResult,
)
from opinion_search.tools.registry import ToolRegistry, UnknownToolError


Sleep = Callable[[float], Awaitable[None]]

_RETRYABLE_KINDS = frozenset(
    {
        ToolErrorKind.TIMEOUT,
        ToolErrorKind.RATE_LIMITED,
        ToolErrorKind.SERVER_ERROR,
    }
)

_STOP_IMMEDIATE_KINDS = frozenset(
    {
        ToolErrorKind.INVALID_ARGUMENTS,
        ToolErrorKind.UNKNOWN_TOOL,
        ToolErrorKind.CANCELLED,
    }
)

_FALLBACKABLE_KINDS = _RETRYABLE_KINDS | frozenset(
    {
        ToolErrorKind.AUTHENTICATION,
        ToolErrorKind.PERMISSION,
        ToolErrorKind.NOT_FOUND,
        ToolErrorKind.UNREADABLE_CONTENT,
        ToolErrorKind.CONTENT_TOO_LARGE,
        ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
    }
)


class ToolExecutor:
    """Execute one validated ToolCall across ordered provider bindings.

    Ownership: argument validation, success cache, same-provider retry,
    cross-provider fallback, timeout, and safe error construction all live
    here. Each adapter performs exactly one provider invocation and never
    builds its own retry loop.

    ``asyncio.CancelledError`` is never caught; it propagates to the AgentLoop
    cancellation handling. Any other unexpected exception is normalized into a
    safe ``UNKNOWN_PROVIDER_ERROR``. A cache identity conflict is a programming
    failure and is allowed to propagate rather than being turned into a
    ToolError.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        retry_policy: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        result_cache: ToolResultCache | None = None,
        circuit_breaker: ProviderCircuitBreaker | None = None,
    ) -> None:
        self._registry = registry
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._result_cache = result_cache or InMemoryActionResultCache()
        self._circuit = circuit_breaker or ProviderCircuitBreaker()

    async def execute(self, call: ToolCall) -> ToolOutcome:
        try:
            registered = self._registry.resolve(call.tool_name)
        except UnknownToolError:
            return self._error(
                call,
                ToolErrorKind.UNKNOWN_TOOL,
                f"Tool is not registered: {call.tool_name}.",
                attempts=0,
            )

        try:
            arguments = registered.definition.input_model.model_validate(
                call.arguments
            )
        except ValidationError:
            return self._error(
                call,
                ToolErrorKind.INVALID_ARGUMENTS,
                f"Arguments are invalid for tool {call.tool_name}.",
                attempts=0,
            )

        cached = await self._result_cache.get(call)
        if cached is not None:
            return cached

        global_attempt = 0
        final_kind: ToolErrorKind | None = None
        final_message: str | None = None
        attempted_any: bool = False

        for binding in registered.providers:
            key = ProviderCircuitKey(
                call.tool_name,
                binding.provider_id,
            )
            if not self._circuit.allow_request(key):
                continue
            attempted_any = True
            for local_attempt in range(
                1,
                self._retry_policy.max_attempts_per_provider + 1,
            ):
                global_attempt += 1
                invocation = ToolInvocation(
                    action_id=call.action_id,
                    tool_name=call.tool_name,
                    attempt=global_attempt,
                    arguments=arguments,
                )
                retry_after: float | None = None
                try:
                    async with asyncio.timeout(self._retry_policy.timeout_seconds):
                        response = await binding.adapter.invoke(invocation)
                    if not isinstance(response, ToolAdapterResponse):
                        raise TypeError(
                            "tool adapter returned an invalid response type"
                        )
                except TimeoutError:
                    kind = ToolErrorKind.TIMEOUT
                    message = "Tool execution timed out."
                except ToolAdapterError as exc:
                    kind = exc.kind
                    message = exc.safe_message
                    retry_after = exc.retry_after_seconds
                except Exception:
                    kind = ToolErrorKind.UNKNOWN_PROVIDER_ERROR
                    message = "Tool provider returned an unexpected error."
                else:
                    self._circuit.record_success(key)
                    result = ToolResult(
                        action_id=call.action_id,
                        tool_name=call.tool_name,
                        payload=response.payload,
                        artifact_refs=response.artifact_refs,
                        attempts=global_attempt,
                    )
                    await self._result_cache.put(call, result)
                    return result

                self._circuit.record_failure(key, kind)
                if (
                    kind in _RETRYABLE_KINDS
                    and local_attempt < self._retry_policy.max_attempts_per_provider
                ):
                    delay = self._retry_policy.backoff_after(
                        local_attempt,
                        retry_after_seconds=retry_after,
                    )
                    if delay > 0:
                        await self._sleep(delay)
                    continue

                if kind in _STOP_IMMEDIATE_KINDS:
                    return self._error(
                        call,
                        kind,
                        message,
                        attempts=global_attempt,
                    )

                if kind in _FALLBACKABLE_KINDS:
                    final_kind = kind
                    final_message = message
                    break

                return self._error(call, kind, message, attempts=global_attempt)

        if not attempted_any:
            return self._error(
                call,
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "All configured providers are currently unavailable.",
                attempts=0,
            )
        if final_kind is None or final_message is None:
            raise RuntimeError("tool retry loop exited without an outcome")
        return self._error(
            call,
            final_kind,
            final_message,
            attempts=global_attempt,
        )

    @staticmethod
    def _error(
        call: ToolCall,
        kind: ToolErrorKind,
        message: str,
        *,
        attempts: int,
    ) -> ToolError:
        return ToolError(
            action_id=call.action_id,
            tool_name=call.tool_name,
            kind=kind,
            message=message,
            attempts=attempts,
        )
