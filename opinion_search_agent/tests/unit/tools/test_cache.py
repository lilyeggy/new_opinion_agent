import asyncio

import pytest

from opinion_search.tools.cache import (
    InMemoryActionResultCache,
    ToolCacheConflictError,
)
from opinion_search.tools.contracts import ToolCall, ToolResult


def _call(*, query: str = "topic") -> ToolCall:
    return ToolCall(
        action_id="action-1",
        tool_name="search.web",
        arguments={"query": query},
    )


def _result() -> ToolResult:
    return ToolResult(
        action_id="action-1",
        tool_name="search.web",
        payload={"items": []},
        attempts=1,
    )


def test_cache_returns_success_for_the_same_complete_call() -> None:
    async def scenario() -> None:
        cache = InMemoryActionResultCache()
        await cache.put(_call(), _result())

        assert await cache.get(_call()) == _result()

    asyncio.run(scenario())


def test_cache_rejects_action_identity_reuse_with_different_call() -> None:
    async def scenario() -> None:
        cache = InMemoryActionResultCache()
        await cache.put(_call(), _result())

        with pytest.raises(ToolCacheConflictError):
            await cache.get(_call(query="different"))

    asyncio.run(scenario())


def test_cache_rejects_result_identity_mismatch() -> None:
    mismatched = ToolResult(
        action_id="different-action",
        tool_name="search.web",
        payload={"items": []},
        attempts=1,
    )

    async def scenario() -> None:
        with pytest.raises(ToolCacheConflictError):
            await InMemoryActionResultCache().put(_call(), mismatched)

    asyncio.run(scenario())
