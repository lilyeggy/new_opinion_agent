import asyncio
from collections.abc import Awaitable
from typing import Protocol


class CancellationSignal(Protocol):
    """Async cancellation contract used across model and tool awaits."""

    def is_cancelled(self) -> bool: ...

    def wait_cancelled(self) -> Awaitable[None]: ...


class NeverCancelledSignal:
    """A cancellation signal that never fires."""

    def is_cancelled(self) -> bool:
        return False

    async def wait_cancelled(self) -> None:
        await asyncio.Event().wait()


class EventCancellationSignal:
    """A cancellable signal backed by one asyncio.Event."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait_cancelled(self) -> None:
        await self._event.wait()
