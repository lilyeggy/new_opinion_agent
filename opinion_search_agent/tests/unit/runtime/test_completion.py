import pytest
from pydantic import ValidationError

from opinion_search.runtime.completion import (
    CompletionDisposition,
    CompletionVerdict,
    RunResult,
    result_from_state,
    status_for_completion,
)
from opinion_search.runtime.errors import (
    RuntimeFailure,
    RuntimeFailureKind,
)
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.transaction import RunState, start_run, terminate_run


@pytest.mark.parametrize(
    ("disposition", "expected_status"),
    [
        (CompletionDisposition.ACCEPT_COMPLETE, RunStatus.COMPLETED),
        (CompletionDisposition.REJECT_AND_CONTINUE, RunStatus.RUNNING),
        (CompletionDisposition.ACCEPT_PARTIAL, RunStatus.PARTIAL),
        (CompletionDisposition.SAFETY_STOP, RunStatus.PARTIAL),
    ],
)
def test_completion_disposition_maps_to_runtime_status(
    disposition: CompletionDisposition,
    expected_status: RunStatus,
) -> None:
    verdict = CompletionVerdict(
        disposition=disposition,
        reason="Deterministic completion decision.",
    )

    assert status_for_completion(verdict) is expected_status


def test_completion_verdict_rejects_blank_reason_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CompletionVerdict(
            disposition=CompletionDisposition.ACCEPT_COMPLETE,
            reason="   ",
        )

    with pytest.raises(ValidationError):
        CompletionVerdict.model_validate(
            {
                "disposition": "accept_complete",
                "reason": "Done.",
                "provider": "private",
            }
        )


def test_run_result_requires_terminal_status() -> None:
    with pytest.raises(ValidationError, match="terminal"):
        RunResult(
            run_id="run-1",
            status=RunStatus.RUNNING,
            domain_state="domain",
            stop_reason="Not actually stopped.",
        )


def test_failed_run_result_requires_typed_failure() -> None:
    with pytest.raises(ValidationError):
        RunResult(
            run_id="run-1",
            status=RunStatus.FAILED,
            domain_state="domain",
            stop_reason="Reducer failed.",
        )


def test_result_is_built_from_terminal_run_state() -> None:
    state = start_run(
        RunState[str, str, str, str](
            run_id="run-1",
            domain_state="domain",
        )
    )
    failure = RuntimeFailure(
        kind=RuntimeFailureKind.REDUCER_INVARIANT,
        message="Reducer rejected the delta.",
    )
    failed = terminate_run(
        state,
        target_status=RunStatus.FAILED,
        reason="Reducer failed.",
        failure=failure,
    )

    result = result_from_state(failed)

    assert result.status is RunStatus.FAILED
    assert result.failure == failure
    assert result.domain_state == "domain"
