import pytest

from opinion_search.runtime.lifecycle import (
    InvalidLifecycleTransition,
    RunStatus,
    StepPhase,
    validate_run_transition,
    validate_step_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.CREATED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.PARTIAL),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLED),
    ],
)
def test_accepts_legal_run_transitions(
    current: RunStatus,
    target: RunStatus,
) -> None:
    assert validate_run_transition(current, target) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.CREATED, RunStatus.COMPLETED),
        (RunStatus.CREATED, RunStatus.PARTIAL),
        (RunStatus.CREATED, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CREATED),
        (RunStatus.RUNNING, RunStatus.RUNNING),
    ],
)
def test_rejects_illegal_run_transitions(
    current: RunStatus,
    target: RunStatus,
) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validate_run_transition(current, target)


@pytest.mark.parametrize(
    "terminal_status",
    [
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ],
)
@pytest.mark.parametrize("target", list(RunStatus))
def test_terminal_run_status_cannot_transition(
    terminal_status: RunStatus,
    target: RunStatus,
) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validate_run_transition(terminal_status, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StepPhase.OPENED, StepPhase.DECIDING),
        (StepPhase.DECIDING, StepPhase.DECISION_ACCEPTED),
        (StepPhase.DECISION_ACCEPTED, StepPhase.ACTION_RUNNING),
        (StepPhase.ACTION_RUNNING, StepPhase.OBSERVATION_READY),
        (StepPhase.OBSERVATION_READY, StepPhase.REDUCING),
        (StepPhase.REDUCING, StepPhase.COMMITTED),
    ],
)
def test_accepts_legal_step_transitions(
    current: StepPhase,
    target: StepPhase,
) -> None:
    assert validate_step_transition(current, target) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StepPhase.OPENED, StepPhase.OPENED),
        (StepPhase.OPENED, StepPhase.DECISION_ACCEPTED),
        (StepPhase.DECIDING, StepPhase.OPENED),
        (StepPhase.ACTION_RUNNING, StepPhase.DECISION_ACCEPTED),
        (StepPhase.OBSERVATION_READY, StepPhase.COMMITTED),
    ],
)
def test_rejects_step_repetition_skips_and_regressions(
    current: StepPhase,
    target: StepPhase,
) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validate_step_transition(current, target)


@pytest.mark.parametrize("target", list(StepPhase))
def test_committed_step_cannot_transition(target: StepPhase) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validate_step_transition(StepPhase.COMMITTED, target)
