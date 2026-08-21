from enum import StrEnum
from typing import Annotated, Any, Generic, Protocol, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.runtime.errors import RuntimeFailure
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.transaction import RunState


DomainStateT = TypeVar("DomainStateT")
DecisionT = TypeVar("DecisionT")
ObservationT = TypeVar("ObservationT")
FinishProposalT = TypeVar("FinishProposalT")

NonEmptyText = Annotated[str, Field(min_length=1)]

_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class CompletionDisposition(StrEnum):
    ACCEPT_COMPLETE = "accept_complete"
    REJECT_AND_CONTINUE = "reject_and_continue"
    ACCEPT_PARTIAL = "accept_partial"
    SAFETY_STOP = "safety_stop"


class CompletionVerdict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    disposition: CompletionDisposition
    reason: NonEmptyText


class CompletionPolicy(Protocol[DomainStateT, FinishProposalT]):
    def evaluate(
        self,
        state: DomainStateT,
        proposal: FinishProposalT,
    ) -> CompletionVerdict: ...


class CompletionEvaluator(Protocol[DomainStateT, DecisionT, ObservationT]):
    def evaluate(
        self,
        state: DomainStateT,
        decision: DecisionT,
        observation: ObservationT,
    ) -> CompletionVerdict | None: ...


class RunResult(BaseModel, Generic[DomainStateT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyText
    status: RunStatus
    domain_state: DomainStateT
    stop_reason: NonEmptyText
    failure: RuntimeFailure | None = None

    @model_validator(mode="after")
    def validate_terminal_result(self) -> Self:
        if self.status not in _TERMINAL_RUN_STATUSES:
            raise ValueError("RunResult requires a terminal run status")
        if self.status is RunStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed RunResult requires RuntimeFailure")
        elif self.failure is not None:
            raise ValueError("only failed RunResult can contain RuntimeFailure")
        return self


def status_for_completion(verdict: CompletionVerdict) -> RunStatus:
    if verdict.disposition is CompletionDisposition.ACCEPT_COMPLETE:
        return RunStatus.COMPLETED
    if verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE:
        return RunStatus.RUNNING
    return RunStatus.PARTIAL


def result_from_state(
    state: RunState[DomainStateT, Any, Any, Any],
) -> RunResult[DomainStateT]:
    if state.status not in _TERMINAL_RUN_STATUSES:
        raise ValueError("cannot create RunResult from non-terminal state")
    if state.stop_reason is None:
        raise ValueError("terminal RunState has no stop_reason")
    return RunResult(
        run_id=state.run_id,
        status=state.status,
        domain_state=state.domain_state,
        stop_reason=state.stop_reason,
        failure=state.failure,
    )
