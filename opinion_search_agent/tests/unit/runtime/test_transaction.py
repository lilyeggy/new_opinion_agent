from collections.abc import Callable

import pytest
from pydantic import ValidationError

from opinion_search.runtime.errors import (
    RuntimeFailure,
    RuntimeFailureKind,
)
from opinion_search.runtime.lifecycle import RunStatus, StepPhase
from opinion_search.runtime.protocols import (
    ActionRequest,
    DecisionEnvelope,
    ObservationEnvelope,
    StateDelta,
)
from opinion_search.runtime.transaction import (
    InvalidTransactionState,
    ResumeAction,
    RunState,
    accept_decision,
    apply_continuation,
    classify_resume,
    commit_step,
    mark_deciding,
    mark_reducing,
    open_step,
    record_observation,
    repair_accepted_decision,
    retry_decision,
    start_action,
    start_run,
    terminate_run,
)


RuntimeStateFixture = RunState[str, str, str, str]


def _created_run() -> RuntimeStateFixture:
    return RuntimeStateFixture(run_id="run-1", domain_state="domain-v0")


def _action_running_run() -> RuntimeStateFixture:
    state = start_run(_created_run())
    state = open_step(state, step_id="step-1")
    state = mark_deciding(state)
    state = accept_decision(
        state,
        DecisionEnvelope(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            decision="search",
        ),
    )
    return start_action(
        state,
        ActionRequest(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            action_id="action-1",
            action="search-tool",
        ),
    )


def _reducing_run() -> RuntimeStateFixture:
    state = _action_running_run()
    state = record_observation(
        state,
        ObservationEnvelope(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            action_id="action-1",
            observation="candidate-found",
        ),
    )
    return mark_reducing(state)


def _delta(
    *,
    run_id: str = "run-1",
    step_id: str = "step-1",
    action_id: str = "action-1",
) -> StateDelta[str]:
    return StateDelta(
        run_id=run_id,
        step_id=step_id,
        attempt=1,
        action_id=action_id,
        delta="domain-v1",
    )


def _commit(
    state: RuntimeStateFixture,
    reducer: Callable[[str, str], str] | None = None,
) -> RuntimeStateFixture:
    reducer = reducer or (lambda _old, new: new)
    return commit_step(state, _delta(), reducer)


def test_transaction_advances_the_complete_step_lifecycle() -> None:
    state = start_run(_created_run())
    state = open_step(state, step_id="step-1")
    assert state.active_step is not None
    assert state.active_step.phase is StepPhase.OPENED

    state = mark_deciding(state)
    state = accept_decision(
        state,
        DecisionEnvelope(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            decision="search",
        ),
    )
    state = start_action(
        state,
        ActionRequest(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            action_id="action-1",
            action="search-tool",
        ),
    )
    state = record_observation(
        state,
        ObservationEnvelope(
            run_id="run-1",
            step_id="step-1",
            attempt=1,
            action_id="action-1",
            observation="candidate-found",
        ),
    )
    state = mark_reducing(state)
    state = _commit(state)

    assert state.active_step is None
    assert state.committed_steps[0].phase is StepPhase.COMMITTED
    assert state.committed_action_ids == ("action-1",)
    assert state.domain_state == "domain-v1"
    assert state.next_step_index == 2
    assert state.continuation_pending is True


def test_transaction_rejects_out_of_order_phase_change() -> None:
    state = start_run(_created_run())
    state = open_step(state, step_id="step-1")

    with pytest.raises(InvalidTransactionState):
        accept_decision(
            state,
            DecisionEnvelope(
                run_id="run-1",
                step_id="step-1",
                attempt=1,
                decision="search",
            ),
        )


def test_transaction_rejects_mismatched_envelope_correlation() -> None:
    state = start_run(_created_run())
    state = mark_deciding(open_step(state, step_id="step-1"))

    with pytest.raises(
        InvalidTransactionState,
        match="correlation does not match",
    ):
        accept_decision(
            state,
            DecisionEnvelope(
                run_id="different-run",
                step_id="step-1",
                attempt=1,
                decision="search",
            ),
        )


def _accepted_decision_run(
    *,
    decision: str = "search",
    prior_failures: tuple[RuntimeFailure, ...] = (),
) -> RuntimeStateFixture:
    state = start_run(_created_run())
    state = open_step(state, step_id="step-1")
    state = mark_deciding(state)
    for failure in prior_failures:
        state = retry_decision(state, failure)
    return accept_decision(
        state,
        DecisionEnvelope(
            run_id="run-1",
            step_id="step-1",
            attempt=state.active_step.attempt,
            decision=decision,
        ),
    )


def test_repair_accepted_decision_rewinds_same_step_to_deciding() -> None:
    prior = RuntimeFailure(
        kind=RuntimeFailureKind.INVALID_DECISION,
        message="The model proposed an invalid candidate.",
    )
    repair_failure = RuntimeFailure(
        kind=RuntimeFailureKind.INVALID_ACTION,
        message="Action resolution rejected the decision.",
    )
    state = _accepted_decision_run(prior_failures=(prior,))
    original_domain = state.domain_state
    original_committed = state.committed_steps
    original_action_ids = state.committed_action_ids

    repaired = repair_accepted_decision(state, repair_failure)

    assert repaired.run_id == state.run_id
    assert repaired.active_step is not None
    assert repaired.active_step.step_id == state.active_step.step_id
    assert repaired.active_step.attempt == state.active_step.attempt + 1
    assert repaired.active_step.phase is StepPhase.DECIDING
    assert repaired.active_step.decision is None
    assert repaired.active_step.action is None
    assert repaired.active_step.observation is None
    assert repaired.active_step.failures == (prior, repair_failure)
    assert repaired.domain_state == original_domain
    assert repaired.committed_steps == original_committed
    assert repaired.committed_action_ids == original_action_ids
    assert classify_resume(repaired) is ResumeAction.REQUEST_DECISION


def test_repair_accepted_decision_clears_decision_by_reconstruction() -> None:
    state = _accepted_decision_run(decision="search")

    repaired = repair_accepted_decision(
        state,
        RuntimeFailure(
            kind=RuntimeFailureKind.INVALID_ACTION,
            message="Action resolution rejected the decision.",
        ),
    )

    assert repaired.active_step is not None
    assert repaired.active_step is not state.active_step
    assert repaired.active_step.decision is None
    assert repaired.active_step.failures[0].kind is RuntimeFailureKind.INVALID_ACTION


@pytest.mark.parametrize(
    "state_factory",
    [
        lambda: start_run(_created_run()),
        lambda: mark_deciding(open_step(start_run(_created_run()), step_id="step-1")),
        _action_running_run,
        lambda: _commit(_reducing_run()),
        lambda: terminate_run(
            start_run(_created_run()),
            target_status=RunStatus.FAILED,
            reason="Reducer failed.",
            failure=RuntimeFailure(
                kind=RuntimeFailureKind.REDUCER_INVARIANT,
                message="The reducer rejected an invalid delta.",
            ),
        ),
    ],
)
def test_repair_accepted_decision_rejects_wrong_phase_or_terminal_state(
    state_factory,
) -> None:
    failure = RuntimeFailure(
        kind=RuntimeFailureKind.INVALID_ACTION,
        message="Action resolution rejected the decision.",
    )

    with pytest.raises(InvalidTransactionState):
        repair_accepted_decision(state_factory(), failure)


def test_observation_must_match_active_action_id() -> None:
    with pytest.raises(
        InvalidTransactionState,
        match="action_id does not match",
    ):
        record_observation(
            _action_running_run(),
            ObservationEnvelope(
                run_id="run-1",
                step_id="step-1",
                attempt=1,
                action_id="different-action",
                observation="candidate-found",
            ),
        )


def test_duplicate_commit_has_effectively_once_state_effect() -> None:
    calls = 0

    def reducer(_old: str, new: str) -> str:
        nonlocal calls
        calls += 1
        return new

    committed = _commit(_reducing_run(), reducer)
    replayed = commit_step(committed, _delta(), reducer)

    assert replayed is committed
    assert calls == 1
    assert replayed.next_step_index == 2
    assert replayed.committed_action_ids == ("action-1",)


def test_duplicate_commit_rejects_different_correlation() -> None:
    committed = _commit(_reducing_run())

    with pytest.raises(InvalidTransactionState):
        commit_step(
            committed,
            _delta(step_id="different-step"),
            lambda _old, new: new,
        )


def test_continuation_must_be_applied_before_opening_next_step() -> None:
    committed = _commit(_reducing_run())

    with pytest.raises(InvalidTransactionState):
        open_step(committed, step_id="step-2")

    continued = apply_continuation(
        committed,
        target_status=RunStatus.RUNNING,
    )
    next_state = open_step(continued, step_id="step-2")

    assert next_state.active_step is not None
    assert next_state.active_step.step_id == "step-2"


def test_completion_continuation_creates_terminal_state() -> None:
    committed = _commit(_reducing_run())

    completed = apply_continuation(
        committed,
        target_status=RunStatus.COMPLETED,
        reason="Completion policy accepted the finish proposal.",
    )

    assert completed.status is RunStatus.COMPLETED
    assert completed.continuation_pending is False
    assert completed.stop_reason is not None
    assert classify_resume(completed) is ResumeAction.RETURN_RESULT


def test_termination_discards_active_step_and_preserves_committed_state() -> None:
    committed = _commit(_reducing_run())
    continued = apply_continuation(
        committed,
        target_status=RunStatus.RUNNING,
    )
    with_active = open_step(continued, step_id="step-2")

    cancelled = terminate_run(
        with_active,
        target_status=RunStatus.CANCELLED,
        reason="The caller cancelled the run.",
    )

    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.active_step is None
    assert cancelled.domain_state == "domain-v1"
    assert cancelled.committed_action_ids == ("action-1",)


def test_failed_termination_requires_typed_failure() -> None:
    state = start_run(_created_run())

    with pytest.raises(InvalidTransactionState):
        terminate_run(
            state,
            target_status=RunStatus.FAILED,
            reason="Reducer failed.",
        )

    failed = terminate_run(
        state,
        target_status=RunStatus.FAILED,
        reason="Reducer failed.",
        failure=RuntimeFailure(
            kind=RuntimeFailureKind.REDUCER_INVARIANT,
            message="The reducer rejected an invalid delta.",
        ),
    )
    assert failed.status is RunStatus.FAILED


@pytest.mark.parametrize(
    ("state_factory", "expected"),
    [
        (_created_run, ResumeAction.START_RUN),
        (lambda: start_run(_created_run()), ResumeAction.OPEN_STEP),
        (
            lambda: open_step(
                start_run(_created_run()),
                step_id="step-1",
            ),
            ResumeAction.REQUEST_DECISION,
        ),
        (_action_running_run, ResumeAction.EXECUTE_ACTION),
        (_reducing_run, ResumeAction.REDUCE_OBSERVATION),
        (
            lambda: _commit(_reducing_run()),
            ResumeAction.EVALUATE_CONTINUATION,
        ),
    ],
)
def test_resume_classification(
    state_factory: Callable[[], RuntimeStateFixture],
    expected: ResumeAction,
) -> None:
    assert classify_resume(state_factory()) is expected


def test_run_state_rejects_inconsistent_step_cursor() -> None:
    with pytest.raises(ValidationError, match="next_step_index"):
        RuntimeStateFixture(
            run_id="run-1",
            domain_state="domain-v0",
            next_step_index=2,
        )


def test_run_state_round_trips_json_checkpoint_payload() -> None:
    committed = _commit(_reducing_run())

    payload = committed.model_dump(mode="json")
    restored = RuntimeStateFixture.model_validate(payload)

    assert restored == committed
    assert classify_resume(restored) is ResumeAction.EVALUATE_CONTINUATION
