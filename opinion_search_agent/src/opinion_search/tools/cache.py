import asyncio
from dataclasses import dataclass
from typing import Protocol

from opinion_search.tools.contracts import ToolCall, ToolResult


class ToolCacheConflictError(RuntimeError):
    """Raised when one action identity is reused for different data."""


class ToolResultCache(Protocol):
    async def get(self, call: ToolCall) -> ToolResult | None: ...

    async def put(self, call: ToolCall, result: ToolResult) -> None: ...


@dataclass(frozen=True)
class _CacheEntry:
    call: ToolCall
    result: ToolResult


class InMemoryActionResultCache:
    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, call: ToolCall) -> ToolResult | None:
        async with self._lock:
            entry = self._entries.get(call.action_id)
            if entry is None:
                return None
            if entry.call != call:
                raise ToolCacheConflictError(
                    "action ID was reused for a different ToolCall"
                )
            return entry.result

    async def put(self, call: ToolCall, result: ToolResult) -> None:
        if result.action_id != call.action_id or result.tool_name != call.tool_name:
            raise ToolCacheConflictError(
                "cached result identity does not match ToolCall"
            )

        async with self._lock:
            existing = self._entries.get(call.action_id)
            entry = _CacheEntry(call=call, result=result)
            if existing is not None and existing != entry:
                raise ToolCacheConflictError(
                    "action ID already has a different cached result"
                )
            self._entries[call.action_id] = entry
