from enum import StrEnum


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepPhase(StrEnum):
    OPENED = "opened"
    DECIDING = "deciding"
    DECISION_ACCEPTED = "decision_accepted"
    ACTION_RUNNING = "action_running"
    OBSERVATION_READY = "observation_ready"
    REDUCING = "reducing"
    COMMITTED = "committed"


class InvalidLifecycleTransition(ValueError):
    """Raised when a runtime lifecycle transition is not allowed."""


_ALLOWED_RUN_TRANSITIONS = frozenset(
    {
        (RunStatus.CREATED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.PARTIAL),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLED),
    }
)

_ALLOWED_STEP_TRANSITIONS = frozenset(
    {
        (StepPhase.OPENED, StepPhase.DECIDING),
        (StepPhase.DECIDING, StepPhase.DECISION_ACCEPTED),
        (StepPhase.DECISION_ACCEPTED, StepPhase.ACTION_RUNNING),
        (StepPhase.ACTION_RUNNING, StepPhase.OBSERVATION_READY),
        (StepPhase.OBSERVATION_READY, StepPhase.REDUCING),
        (StepPhase.REDUCING, StepPhase.COMMITTED),
    }
)


def validate_run_transition(
    current: RunStatus,
    target: RunStatus,
) -> None:
    transition = (current, target)
    if transition not in _ALLOWED_RUN_TRANSITIONS:
        raise InvalidLifecycleTransition(
            f"Invalid run transition: {current.value} -> {target.value}"
        )


def validate_step_transition(
    current: StepPhase,
    target: StepPhase,
) -> None:
    transition = (current, target)
    if transition not in _ALLOWED_STEP_TRANSITIONS:
        raise InvalidLifecycleTransition(
            f"Invalid step transition: {current.value} -> {target.value}"
        )
