from enum import StrEnum
from typing import Annotated, Any, Callable, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.runtime.errors import RuntimeFailure
from opinion_search.runtime.lifecycle import (
    RunStatus,
    StepPhase,
    validate_run_transition,
    validate_step_transition,
)
from opinion_search.runtime.protocols import (
    ActionRequest,
    DecisionEnvelope,
    ObservationEnvelope,
    StateDelta,
    StepRecord,
)


DomainStateT = TypeVar("DomainStateT")
DecisionT = TypeVar("DecisionT")
ActionT = TypeVar("ActionT")
ObservationT = TypeVar("ObservationT")
ModelT = TypeVar("ModelT", bound=BaseModel)

NonEmptyText = Annotated[str, Field(min_length=1)]
StepIndex = Annotated[int, Field(ge=1)]

_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class InvalidTransactionState(ValueError):
    """Raised when a transaction operation is not valid."""


class ResumeAction(StrEnum):
    START_RUN = "start_run"
    RETURN_RESULT = "return_result"
    EVALUATE_CONTINUATION = "evaluate_continuation"
    OPEN_STEP = "open_step"
    REQUEST_DECISION = "request_decision"
    RESOLVE_ACTION = "resolve_action"
    EXECUTE_ACTION = "execute_action"
    REDUCE_OBSERVATION = "reduce_observation"


class RunState(
    BaseModel,
    Generic[DomainStateT, DecisionT, ActionT, ObservationT],
):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyText
    status: RunStatus = RunStatus.CREATED
    domain_state: DomainStateT
    next_step_index: StepIndex = 1
    active_step: StepRecord[DecisionT, ActionT, ObservationT] | None = None
    committed_steps: tuple[
        StepRecord[DecisionT, ActionT, ObservationT],
        ...,
    ] = ()
    committed_action_ids: tuple[NonEmptyText, ...] = ()
    continuation_pending: bool = False
    stop_reason: NonEmptyText | None = None
    failure: RuntimeFailure | None = None

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        if (
            self.active_step is not None
            and self.active_step.phase is StepPhase.COMMITTED
        ):
            raise ValueError("active_step cannot already be committed")

        invalid_committed_step_ids = tuple(
            step.step_id
            for step in self.committed_steps
            if step.phase is not StepPhase.COMMITTED
        )
        if invalid_committed_step_ids:
            raise ValueError(
                "committed_steps contains non-committed steps: "
                f"{list(invalid_committed_step_ids)}"
            )

        all_steps = self.committed_steps
        if self.active_step is not None:
            all_steps = all_steps + (self.active_step,)

        foreign_step_ids = tuple(
            step.step_id for step in all_steps if step.run_id != self.run_id
        )
        if foreign_step_ids:
            raise ValueError(
                f"step run_id does not match RunState: {list(foreign_step_ids)}"
            )

        all_step_ids = tuple(step.step_id for step in all_steps)
        if len(all_step_ids) != len(set(all_step_ids)):
            raise ValueError("step IDs must be unique within a run")

        if len(self.committed_action_ids) != len(set(self.committed_action_ids)):
            raise ValueError("committed_action_ids must contain unique values")

        expected_committed_action_ids = tuple(
            step.action.action_id
            for step in self.committed_steps
            if step.action is not None
        )
        if self.committed_action_ids != expected_committed_action_ids:
            raise ValueError("committed_action_ids do not match committed steps")

        expected_next_step_index = len(self.committed_steps) + 1
        if self.next_step_index != expected_next_step_index:
            raise ValueError("next_step_index must equal committed step count plus one")

        if self.continuation_pending:
            if self.status is not RunStatus.RUNNING:
                raise ValueError("only a running run can have pending continuation")
            if self.active_step is not None:
                raise ValueError("pending continuation cannot coexist with active_step")
            if not self.committed_steps:
                raise ValueError("pending continuation requires a committed step")

        if self.status is RunStatus.CREATED and (
            self.next_step_index != 1
            or self.active_step is not None
            or self.committed_steps
            or self.committed_action_ids
            or self.continuation_pending
        ):
            raise ValueError("created run must have an empty runtime history")

        is_terminal = self.status in _TERMINAL_RUN_STATUSES
        if is_terminal:
            if self.active_step is not None:
                raise ValueError("terminal run cannot have an active step")
            if self.continuation_pending:
                raise ValueError("terminal run cannot have pending continuation")
            if self.stop_reason is None:
                raise ValueError("terminal run requires stop_reason")
        elif self.stop_reason is not None:
            raise ValueError("non-terminal run cannot have stop_reason")

        if self.status is RunStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed run requires RuntimeFailure")
        elif self.failure is not None:
            raise ValueError("only failed run can contain RuntimeFailure")

        return self


def _validated_copy(model: ModelT, **changes: object) -> ModelT:
    values = {
        field_name: getattr(model, field_name)
        for field_name in type(model).model_fields
    }
    values.update(changes)
    return type(model).model_validate(values)


def _require_active_step(
    state: RunState[Any, Any, Any, Any],
    expected_phase: StepPhase,
) -> StepRecord[Any, Any, Any]:
    if state.status is not RunStatus.RUNNING:
        raise InvalidTransactionState("transaction operation requires a running run")
    if state.active_step is None:
        raise InvalidTransactionState("transaction operation requires an active step")
    if state.active_step.phase is not expected_phase:
        raise InvalidTransactionState(
            "active step phase must be "
            f"{expected_phase.value}, got {state.active_step.phase.value}"
        )
    return state.active_step


def _validate_correlation(
    step: StepRecord[Any, Any, Any],
    envelope: Any,
) -> None:
    expected = (step.run_id, step.step_id, step.attempt)
    actual = (envelope.run_id, envelope.step_id, envelope.attempt)
    if actual != expected:
        raise InvalidTransactionState("envelope correlation does not match step")


def start_run(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    validate_run_transition(state.status, RunStatus.RUNNING)
    return _validated_copy(state, status=RunStatus.RUNNING)


def open_step(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    *,
    step_id: str,
    attempt: int = 1,
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    if state.status is not RunStatus.RUNNING:
        raise InvalidTransactionState("only a running run can open a step")
    if state.active_step is not None:
        raise InvalidTransactionState("cannot open a step while another step is active")
    if state.continuation_pending:
        raise InvalidTransactionState(
            "continuation must be evaluated before opening a step"
        )

    step = StepRecord[DecisionT, ActionT, ObservationT](
        run_id=state.run_id,
        step_id=step_id,
        attempt=attempt,
        phase=StepPhase.OPENED,
    )
    return _validated_copy(state, active_step=step)


def mark_deciding(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.OPENED)
    validate_step_transition(step.phase, StepPhase.DECIDING)
    next_step = _validated_copy(step, phase=StepPhase.DECIDING)
    return _validated_copy(state, active_step=next_step)


def accept_decision(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    decision: DecisionEnvelope[DecisionT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.DECIDING)
    _validate_correlation(step, decision)
    validate_step_transition(step.phase, StepPhase.DECISION_ACCEPTED)
    next_step = _validated_copy(
        step,
        phase=StepPhase.DECISION_ACCEPTED,
        decision=decision,
    )
    return _validated_copy(state, active_step=next_step)


def retry_decision(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    failure: RuntimeFailure,
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.DECIDING)
    next_step = StepRecord[DecisionT, ActionT, ObservationT](
        run_id=step.run_id,
        step_id=step.step_id,
        attempt=step.attempt + 1,
        phase=StepPhase.DECIDING,
        failures=step.failures + (failure,),
    )
    return _validated_copy(state, active_step=next_step)


def repair_accepted_decision(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    failure: RuntimeFailure,
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    """Rewind an accepted Decision to deciding after ActionResolver failure.

    No external action has started for this step, so the same step can be
    retried instead of terminating the run. The active StepRecord is rebuilt
    from scratch (not mutated) so the rejected Decision and any partial
    payload are discarded while prior failures are preserved in order.
    """
    step = _require_active_step(state, StepPhase.DECISION_ACCEPTED)
    next_step = StepRecord[DecisionT, ActionT, ObservationT](
        run_id=step.run_id,
        step_id=step.step_id,
        attempt=step.attempt + 1,
        phase=StepPhase.DECIDING,
        failures=step.failures + (failure,),
    )
    return _validated_copy(state, active_step=next_step)


def start_action(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    action: ActionRequest[ActionT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.DECISION_ACCEPTED)
    _validate_correlation(step, action)
    validate_step_transition(step.phase, StepPhase.ACTION_RUNNING)
    next_step = _validated_copy(
        step,
        phase=StepPhase.ACTION_RUNNING,
        action=action,
    )
    return _validated_copy(state, active_step=next_step)


def record_observation(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    observation: ObservationEnvelope[ObservationT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.ACTION_RUNNING)
    _validate_correlation(step, observation)
    if step.action is None or step.action.action_id != observation.action_id:
        raise InvalidTransactionState(
            "observation action_id does not match active action"
        )

    validate_step_transition(step.phase, StepPhase.OBSERVATION_READY)
    next_step = _validated_copy(
        step,
        phase=StepPhase.OBSERVATION_READY,
        observation=observation,
    )
    return _validated_copy(state, active_step=next_step)


def mark_reducing(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    step = _require_active_step(state, StepPhase.OBSERVATION_READY)
    validate_step_transition(step.phase, StepPhase.REDUCING)
    next_step = _validated_copy(step, phase=StepPhase.REDUCING)
    return _validated_copy(state, active_step=next_step)


def commit_step(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    state_delta: StateDelta[Any],
    reducer: Callable[[DomainStateT, Any], DomainStateT],
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    if state_delta.action_id in state.committed_action_ids:
        if state.active_step is not None:
            raise InvalidTransactionState(
                "cannot replay committed delta during another active step"
            )
        committed_step = next(
            (
                step
                for step in state.committed_steps
                if step.action is not None
                and step.action.action_id == state_delta.action_id
            ),
            None,
        )
        if committed_step is None:
            raise InvalidTransactionState(
                "committed action has no matching committed step"
            )
        _validate_correlation(committed_step, state_delta)
        return state

    step = _require_active_step(state, StepPhase.REDUCING)
    _validate_correlation(step, state_delta)
    if step.action is None:
        raise InvalidTransactionState("reducing step has no accepted action")
    if step.action.action_id != state_delta.action_id:
        raise InvalidTransactionState(
            "StateDelta action_id does not match active action"
        )

    new_domain_state = reducer(state.domain_state, state_delta.delta)
    validate_step_transition(step.phase, StepPhase.COMMITTED)
    committed_step = _validated_copy(step, phase=StepPhase.COMMITTED)

    return _validated_copy(
        state,
        domain_state=new_domain_state,
        active_step=None,
        committed_steps=state.committed_steps + (committed_step,),
        committed_action_ids=(state.committed_action_ids + (state_delta.action_id,)),
        next_step_index=state.next_step_index + 1,
        continuation_pending=True,
    )


def apply_continuation(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    *,
    target_status: RunStatus,
    reason: str | None = None,
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    if state.status is not RunStatus.RUNNING:
        raise InvalidTransactionState("continuation requires a running run")
    if not state.continuation_pending:
        raise InvalidTransactionState("run has no pending continuation")

    if target_status is RunStatus.RUNNING:
        if reason is not None:
            raise InvalidTransactionState("continuing run cannot set stop_reason")
        return _validated_copy(state, continuation_pending=False)

    if target_status not in {RunStatus.COMPLETED, RunStatus.PARTIAL}:
        raise InvalidTransactionState("invalid completion target status")
    if reason is None or not reason.strip():
        raise InvalidTransactionState("terminal continuation requires a reason")

    validate_run_transition(state.status, target_status)
    return _validated_copy(
        state,
        status=target_status,
        continuation_pending=False,
        stop_reason=reason,
    )


def terminate_run(
    state: RunState[DomainStateT, DecisionT, ActionT, ObservationT],
    *,
    target_status: RunStatus,
    reason: str,
    failure: RuntimeFailure | None = None,
) -> RunState[DomainStateT, DecisionT, ActionT, ObservationT]:
    if state.status is not RunStatus.RUNNING:
        raise InvalidTransactionState("only a running run can terminate")
    if target_status not in {
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }:
        raise InvalidTransactionState("invalid termination target status")
    if not reason.strip():
        raise InvalidTransactionState("termination requires a reason")
    if target_status is RunStatus.FAILED and failure is None:
        raise InvalidTransactionState("failed termination requires RuntimeFailure")
    if target_status is not RunStatus.FAILED and failure is not None:
        raise InvalidTransactionState(
            "only failed termination can contain RuntimeFailure"
        )

    validate_run_transition(state.status, target_status)
    return _validated_copy(
        state,
        status=target_status,
        active_step=None,
        continuation_pending=False,
        stop_reason=reason,
        failure=failure,
    )


def classify_resume(
    state: RunState[Any, Any, Any, Any],
) -> ResumeAction:
    if state.status is RunStatus.CREATED:
        return ResumeAction.START_RUN
    if state.status in _TERMINAL_RUN_STATUSES:
        return ResumeAction.RETURN_RESULT
    if state.continuation_pending:
        return ResumeAction.EVALUATE_CONTINUATION
    if state.active_step is None:
        return ResumeAction.OPEN_STEP

    phase = state.active_step.phase
    if phase in {StepPhase.OPENED, StepPhase.DECIDING}:
        return ResumeAction.REQUEST_DECISION
    if phase is StepPhase.DECISION_ACCEPTED:
        return ResumeAction.RESOLVE_ACTION
    if phase is StepPhase.ACTION_RUNNING:
        return ResumeAction.EXECUTE_ACTION
    if phase in {StepPhase.OBSERVATION_READY, StepPhase.REDUCING}:
        return ResumeAction.REDUCE_OBSERVATION

    raise InvalidTransactionState(f"cannot resume active step in phase {phase.value}")
