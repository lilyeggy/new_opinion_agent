import pytest

from opinion_search.tools.circuit import (
    CircuitStatus,
    ProviderCircuitBreaker,
    ProviderCircuitKey,
)
from opinion_search.tools.contracts import ToolErrorKind


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _key(tool: str = "search.web", provider: str = "primary") -> ProviderCircuitKey:
    return ProviderCircuitKey(tool_name=tool, provider_id=provider)


def test_threshold_transition_opens_circuit() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=3,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()

    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.CLOSED
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.CLOSED
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.OPEN
    assert breaker.allow_request(key) is False


def test_open_skips_requests_before_cooldown() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.TIMEOUT)
    breaker.record_failure(key, ToolErrorKind.TIMEOUT)
    assert breaker.status(key) is CircuitStatus.OPEN

    assert breaker.allow_request(key) is False
    clock.advance(29)
    assert breaker.allow_request(key) is False
    clock.advance(2)
    assert breaker.status(key) is CircuitStatus.HALF_OPEN


def test_half_open_allows_single_probe() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    clock.advance(31)

    assert breaker.status(key) is CircuitStatus.HALF_OPEN
    assert breaker.allow_request(key) is True
    assert breaker.allow_request(key) is False  # concurrent probe skipped


def test_probe_success_closes_and_resets() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    clock.advance(31)
    breaker.allow_request(key)

    breaker.record_success(key)

    assert breaker.status(key) is CircuitStatus.CLOSED
    assert breaker.allow_request(key) is True


def test_probe_failure_reopens_and_resets_open_time() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    clock.advance(31)
    breaker.allow_request(key)

    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.OPEN

    clock.advance(29)
    assert breaker.status(key) is CircuitStatus.OPEN
    clock.advance(2)
    assert breaker.status(key) is CircuitStatus.HALF_OPEN


def test_records_are_independent_by_tool_and_provider() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    breaker.record_failure(
        _key(tool="search.web", provider="a"),
        ToolErrorKind.SERVER_ERROR,
    )
    breaker.record_failure(
        _key(tool="search.web", provider="a"),
        ToolErrorKind.SERVER_ERROR,
    )
    assert breaker.status(_key(tool="search.web", provider="a")) is CircuitStatus.OPEN
    assert breaker.status(_key(tool="search.web", provider="b")) is CircuitStatus.CLOSED
    assert breaker.status(_key(tool="read.web", provider="a")) is CircuitStatus.CLOSED


def test_non_poisoning_error_does_not_open_circuit() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()

    breaker.record_failure(key, ToolErrorKind.AUTHENTICATION)
    breaker.record_failure(key, ToolErrorKind.PERMISSION)

    assert breaker.status(key) is CircuitStatus.CLOSED
    assert breaker.allow_request(key) is True


def test_success_resets_accumulated_failures_before_threshold() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=3,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.RATE_LIMITED)
    breaker.record_failure(key, ToolErrorKind.RATE_LIMITED)

    breaker.record_success(key)

    breaker.record_failure(key, ToolErrorKind.RATE_LIMITED)
    assert breaker.status(key) is CircuitStatus.CLOSED


def test_configuration_validation() -> None:
    with pytest.raises(ValueError):
        ProviderCircuitBreaker(failure_threshold=0)
    with pytest.raises(ValueError):
        ProviderCircuitBreaker(cooldown_seconds=0)


@pytest.mark.parametrize("kind", [ToolErrorKind.AUTHENTICATION, ToolErrorKind.PERMISSION])
def test_non_poisoning_probe_failure_releases_the_probe(kind) -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.OPEN
    clock.advance(31)
    assert breaker.allow_request(key) is True  # half-open probe allowed

    breaker.record_failure(key, kind)

    # The non-poisoning outcome must release the probe and close the circuit,
    # so a later request is allowed again.
    assert breaker.allow_request(key) is True
    assert breaker.status(key) is CircuitStatus.CLOSED


def test_non_poisoning_probe_does_not_increment_poisoning_failures() -> None:
    clock = FakeClock()
    breaker = ProviderCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    key = _key()
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    clock.advance(31)
    breaker.allow_request(key)
    breaker.record_failure(key, ToolErrorKind.AUTHENTICATION)

    # A fresh poisoning sequence must need the full threshold again, proving
    # the auth outcome did not count toward health.
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.CLOSED
    breaker.record_failure(key, ToolErrorKind.SERVER_ERROR)
    assert breaker.status(key) is CircuitStatus.OPEN
