from typing import Annotated, Generic, Self, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from opinion_search.runtime.lifecycle import StepPhase
from opinion_search.runtime.errors import RuntimeFailure


DecisionT = TypeVar("DecisionT")
ActionT = TypeVar("ActionT")
ObservationT = TypeVar("ObservationT")
DeltaT = TypeVar("DeltaT")

NonEmptyId = Annotated[str, Field(min_length=1)]
AttemptNumber = Annotated[int, Field(ge=1)]


class DecisionEnvelope(BaseModel, Generic[DecisionT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyId
    step_id: NonEmptyId
    attempt: AttemptNumber
    decision: DecisionT


class ActionRequest(BaseModel, Generic[ActionT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyId
    step_id: NonEmptyId
    attempt: AttemptNumber
    action_id: NonEmptyId
    action: ActionT


class ObservationEnvelope(BaseModel, Generic[ObservationT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyId
    step_id: NonEmptyId
    attempt: AttemptNumber
    action_id: NonEmptyId
    observation: ObservationT


class StateDelta(BaseModel, Generic[DeltaT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyId
    step_id: NonEmptyId
    attempt: AttemptNumber
    action_id: NonEmptyId
    delta: DeltaT


_STEP_PAYLOAD_FIELDS_BY_PHASE = {
    StepPhase.OPENED: frozenset(),
    StepPhase.DECIDING: frozenset(),
    StepPhase.DECISION_ACCEPTED: frozenset({"decision"}),
    StepPhase.ACTION_RUNNING: frozenset({"decision", "action"}),
    StepPhase.OBSERVATION_READY: frozenset({"decision", "action", "observation"}),
    StepPhase.REDUCING: frozenset({"decision", "action", "observation"}),
    StepPhase.COMMITTED: frozenset({"decision", "action", "observation"}),
}


class StepRecord(
    BaseModel,
    Generic[DecisionT, ActionT, ObservationT],
):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyId
    step_id: NonEmptyId
    attempt: AttemptNumber
    phase: StepPhase
    decision: DecisionEnvelope[DecisionT] | None = None
    action: ActionRequest[ActionT] | None = None
    observation: ObservationEnvelope[ObservationT] | None = None
    failures: tuple[RuntimeFailure, ...] = ()

    @model_validator(mode="after")
    def validate_recovery_invariants(self) -> Self:
        expected_fields = _STEP_PAYLOAD_FIELDS_BY_PHASE[self.phase]

        actual_fields = {
            field_name
            for field_name in {"decision", "action", "observation"}
            if getattr(self, field_name) is not None
        }

        if actual_fields != expected_fields:
            missing_fields = expected_fields - actual_fields
            premature_fields = actual_fields - expected_fields

            raise ValueError(
                "step payloads do not match phase "
                f"{self.phase.value}: "
                f"missing={sorted(missing_fields)}, "
                f"premature={sorted(premature_fields)}"
            )

        expected_correlation = (
            self.run_id,
            self.step_id,
            self.attempt,
        )

        for field_name in expected_fields:
            envelope = getattr(self, field_name)
            actual_correlation = (
                envelope.run_id,
                envelope.step_id,
                envelope.attempt,
            )

            if actual_correlation != expected_correlation:
                raise ValueError(f"{field_name} correlation does not match step record")

        if (
            self.action is not None
            and self.observation is not None
            and self.action.action_id != self.observation.action_id
        ):
            raise ValueError("observation action_id does not match action request")

        return self
