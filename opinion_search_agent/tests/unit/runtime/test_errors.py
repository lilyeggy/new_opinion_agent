import pytest
from pydantic import ValidationError

from opinion_search.runtime.errors import (
    RecoveryDirective,
    RuntimeFailure,
    RuntimeFailureKind,
    recovery_directive_for,
)


@pytest.mark.parametrize(
    ("kind", "expected_directive"),
    [
        (
            RuntimeFailureKind.MODEL_MALFORMED_RESPONSE,
            RecoveryDirective.RETRY_ATTEMPT,
        ),
        (
            RuntimeFailureKind.MODEL_EMPTY_RESPONSE,
            RecoveryDirective.RETRY_ATTEMPT,
        ),
        (
            RuntimeFailureKind.MODEL_REFUSAL,
            RecoveryDirective.RETRY_ATTEMPT,
        ),
        (
            RuntimeFailureKind.INVALID_DECISION,
            RecoveryDirective.FEEDBACK_AND_CONTINUE,
        ),
        (
            RuntimeFailureKind.INVALID_ACTION,
            RecoveryDirective.FEEDBACK_AND_CONTINUE,
        ),
        (
            RuntimeFailureKind.TOOL_ERROR,
            RecoveryDirective.FEEDBACK_AND_CONTINUE,
        ),
        (
            RuntimeFailureKind.TOOL_CONFIGURATION_ERROR,
            RecoveryDirective.FAIL_RUN,
        ),
        (
            RuntimeFailureKind.REDUCER_INVARIANT,
            RecoveryDirective.FAIL_RUN,
        ),
        (
            RuntimeFailureKind.CHECKPOINT_READ,
            RecoveryDirective.FAIL_RUN,
        ),
        (
            RuntimeFailureKind.CHECKPOINT_WRITE,
            RecoveryDirective.FAIL_RUN,
        ),
        (
            RuntimeFailureKind.CHECKPOINT_VERSION,
            RecoveryDirective.FAIL_RUN,
        ),
        (
            RuntimeFailureKind.CONTEXT_OVERFLOW,
            RecoveryDirective.PARTIAL_STOP,
        ),
        (
            RuntimeFailureKind.REPEATED_ACTION,
            RecoveryDirective.PARTIAL_STOP,
        ),
        (
            RuntimeFailureKind.CANCELLED,
            RecoveryDirective.CANCEL_RUN,
        ),
        (
            RuntimeFailureKind.SAFETY_LIMIT,
            RecoveryDirective.PARTIAL_STOP,
        ),
    ],
)
def test_runtime_failure_kind_has_deterministic_recovery_directive(
    kind: RuntimeFailureKind,
    expected_directive: RecoveryDirective,
) -> None:
    assert recovery_directive_for(kind) is expected_directive


def test_recovery_policy_covers_every_runtime_failure_kind() -> None:
    mapped_kinds = {
        kind
        for kind in RuntimeFailureKind
        if recovery_directive_for(kind) in RecoveryDirective
    }

    assert mapped_kinds == set(RuntimeFailureKind)


def test_runtime_failure_round_trips_stable_payload() -> None:
    payload = {
        "kind": "invalid_decision",
        "message": "The target gap does not exist in the current state.",
    }

    failure = RuntimeFailure.model_validate(payload)

    assert failure.kind is RuntimeFailureKind.INVALID_DECISION
    assert failure.directive is RecoveryDirective.FEEDBACK_AND_CONTINUE
    assert failure.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "invalid_decision", "message": ""},
        {"kind": "invalid_decision", "message": "   "},
        {"kind": "unknown_failure", "message": "Something happened."},
    ],
)
def test_runtime_failure_rejects_blank_message_and_unknown_kind(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RuntimeFailure.model_validate(payload)


def test_runtime_failure_rejects_caller_supplied_directive() -> None:
    payload = {
        "kind": "reducer_invariant",
        "message": "Reducer rejected an invalid delta.",
        "directive": "retry_attempt",
    }

    with pytest.raises(ValidationError):
        RuntimeFailure.model_validate(payload)


def test_runtime_failure_is_immutable() -> None:
    failure = RuntimeFailure(
        kind=RuntimeFailureKind.SAFETY_LIMIT,
        message="The maximum number of steps was reached.",
    )

    with pytest.raises(ValidationError):
        failure.kind = RuntimeFailureKind.INVALID_DECISION
