from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Callable

from opinion_search.tools.contracts import ToolErrorKind


MonotonicClock = Callable[[], float]


class CircuitStatus(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# These kinds poison provider health and can trip a circuit. Authentication
# and permission failures are usually configuration-specific and must remain
# visible on the next run instead of permanently opening a breaker.
_POISONING_KINDS = frozenset(
    {
        ToolErrorKind.TIMEOUT,
        ToolErrorKind.RATE_LIMITED,
        ToolErrorKind.SERVER_ERROR,
        ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
    }
)


@dataclass(frozen=True)
class ProviderCircuitKey:
    tool_name: str
    provider_id: str


@dataclass
class ProviderCircuitRecord:
    consecutive_failures: int = 0
    opened_at_monotonic: float | None = None
    probe_in_flight: bool = False


class ProviderCircuitBreaker:
    """Per tool/provider in-memory circuit state with an injected clock.

    State is intentionally in-memory: it resets on process restart and is
    execution health, not Domain State or checkpoint data.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least one")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._records: dict[ProviderCircuitKey, ProviderCircuitRecord] = {}

    def status(self, key: ProviderCircuitKey) -> CircuitStatus:
        record = self._records.get(key)
        if record is None or record.opened_at_monotonic is None:
            return CircuitStatus.CLOSED
        if self._clock() - record.opened_at_monotonic < self._cooldown_seconds:
            return CircuitStatus.OPEN
        return CircuitStatus.HALF_OPEN

    def allow_request(self, key: ProviderCircuitKey) -> bool:
        status = self.status(key)
        if status is CircuitStatus.CLOSED:
            return True
        if status is CircuitStatus.OPEN:
            return False
        record = self._records[key]
        if record.probe_in_flight:
            return False
        record.probe_in_flight = True
        return True

    def record_success(self, key: ProviderCircuitKey) -> None:
        self._records[key] = ProviderCircuitRecord(consecutive_failures=0)

    def record_failure(
        self,
        key: ProviderCircuitKey,
        kind: ToolErrorKind,
    ) -> None:
        record = self._records.get(key)
        if record is None:
            if kind in _POISONING_KINDS:
                self._records[key] = ProviderCircuitRecord(
                    consecutive_failures=1
                )
            return

        if record.probe_in_flight:
            # A probe outcome must always release the probe. A poisoning
            # failure reopens the circuit at cooldown; a non-poisoning outcome
            # (auth/permission/not-found) closes it because it is a request or
            # configuration result, not provider-health evidence.
            if kind in _POISONING_KINDS:
                self._records[key] = ProviderCircuitRecord(
                    consecutive_failures=self._failure_threshold,
                    opened_at_monotonic=self._clock(),
                    probe_in_flight=False,
                )
            else:
                self._records[key] = ProviderCircuitRecord(
                    consecutive_failures=0
                )
            return

        if kind not in _POISONING_KINDS:
            return
        failures = record.consecutive_failures + 1
        if failures >= self._failure_threshold:
            self._records[key] = ProviderCircuitRecord(
                consecutive_failures=self._failure_threshold,
                opened_at_monotonic=self._clock(),
            )
        else:
            self._records[key] = ProviderCircuitRecord(
                consecutive_failures=failures,
            )
