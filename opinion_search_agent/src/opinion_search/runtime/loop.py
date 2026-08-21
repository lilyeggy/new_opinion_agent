import asyncio
from enum import StrEnum
from typing import Any, Callable, Protocol

from opinion_search.models.contracts import ModelClient
from opinion_search.models.contracts import (
    ModelClientError,
    ModelErrorKind,
)
from opinion_search.runtime.checkpoint import CheckpointStore
from opinion_search.runtime.cancellation import (
    CancellationSignal,
    NeverCancelledSignal,
)
from opinion_search.runtime.completion import (
    CompletionEvaluator,
    RunResult,
    result_from_state,
    status_for_completion,
)
from opinion_search.runtime.lifecycle import RunStatus, StepPhase
from opinion_search.runtime.errors import (
    ContextOverflowError,
    DecisionValidationError,
    RuntimeFailure,
    RuntimeFailureKind,
)
from opinion_search.runtime.protocols import (
    ActionRequest,
    DecisionEnvelope,
    ObservationEnvelope,
    StateDelta,
)
from opinion_search.runtime.transaction import (
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


RuntimeState = RunState[Any, Any, Any, Any]


class _RunCancelled(Exception):
    """Internal marker for a cancellation that won an in-flight await race."""


class CheckpointBoundary(StrEnum):
    RUN_STARTED = "run_started"
    STEP_OPENED = "step_opened"
    DECIDING = "deciding"
    DECISION_ACCEPTED = "decision_accepted"
    ACTION_RUNNING = "action_running"
    OBSERVATION_READY = "observation_ready"
    REDUCING = "reducing"
    STEP_COMMITTED = "step_committed"
    CONTINUATION_APPLIED = "continuation_applied"
    RUN_TERMINATED = "run_terminated"


class ContextCompiler(Protocol):
    def compile(self, state: RuntimeState) -> Any: ...


class DecisionValidator(Protocol):
    def validate(self, state: Any, decision: Any) -> None: ...


class ActionResolver(Protocol):
    def resolve(self, state: Any, decision: Any) -> Any: ...


class ActionExecutor(Protocol):
    async def execute(self, request: ActionRequest[Any]) -> Any: ...


class ObservationProcessor(Protocol):
    def build_delta(
        self,
        state: Any,
        decision: Any,
        observation: Any,
    ) -> Any: ...


class IdFactory(Protocol):
    def step_id(self, run_id: str, step_index: int) -> str: ...

    def action_id(
        self,
        run_id: str,
        step_id: str,
        attempt: int,
    ) -> str: ...


class LoopHook(Protocol):
    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None: ...


class NoopLoopHook:
    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        return None


class AgentLoop:
    def __init__(
        self,
        *,
        model: ModelClient[Any, Any],
        context_compiler: ContextCompiler,
        decision_validator: DecisionValidator,
        action_resolver: ActionResolver,
        action_executor: ActionExecutor,
        observation_processor: ObservationProcessor,
        completion_evaluator: CompletionEvaluator[Any, Any, Any],
        reducer: Callable[[Any, Any], Any],
        checkpoint_store: CheckpointStore[RuntimeState],
        id_factory: IdFactory,
        max_steps: int,
        max_decision_attempts: int = 2,
        cancellation_signal: CancellationSignal | None = None,
        hook: LoopHook | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least one")
        if max_decision_attempts < 1:
            raise ValueError("max_decision_attempts must be at least one")

        self._model = model
        self._context_compiler = context_compiler
        self._decision_validator = decision_validator
        self._action_resolver = action_resolver
        self._action_executor = action_executor
        self._observation_processor = observation_processor
        self._completion_evaluator = completion_evaluator
        self._reducer = reducer
        self._checkpoint_store = checkpoint_store
        self._id_factory = id_factory
        self._max_steps = max_steps
        self._max_decision_attempts = max_decision_attempts
        self._cancellation_signal = cancellation_signal or NeverCancelledSignal()
        self._hook = hook or NoopLoopHook()

    async def resume(self) -> RunResult[Any]:
        state = await self._checkpoint_store.load()
        return await self.run(state)

    async def run(self, state: RuntimeState) -> RunResult[Any]:
        while True:
            resume_action = classify_resume(state)

            if resume_action is ResumeAction.RETURN_RESULT:
                return result_from_state(state)

            if (
                state.status is RunStatus.RUNNING
                and self._cancellation_signal.is_cancelled()
                and resume_action is not ResumeAction.REDUCE_OBSERVATION
            ):
                state = terminate_run(
                    state,
                    target_status=RunStatus.CANCELLED,
                    reason="The run was cancelled.",
                )
                await self._save(
                    CheckpointBoundary.RUN_TERMINATED,
                    state,
                )
                continue

            if resume_action is ResumeAction.START_RUN:
                state = start_run(state)
                await self._save(CheckpointBoundary.RUN_STARTED, state)
                continue

            if resume_action is ResumeAction.EVALUATE_CONTINUATION:
                committed_step = state.committed_steps[-1]
                if (
                    committed_step.decision is None
                    or committed_step.observation is None
                ):
                    raise RuntimeError("committed step has no decision or observation")

                verdict = self._completion_evaluator.evaluate(
                    state.domain_state,
                    committed_step.decision.decision,
                    committed_step.observation.observation,
                )
                if verdict is None:
                    state = apply_continuation(
                        state,
                        target_status=RunStatus.RUNNING,
                    )
                else:
                    target_status = status_for_completion(verdict)
                    state = apply_continuation(
                        state,
                        target_status=target_status,
                        reason=(
                            verdict.reason
                            if target_status is not RunStatus.RUNNING
                            else None
                        ),
                    )

                await self._save(
                    CheckpointBoundary.CONTINUATION_APPLIED,
                    state,
                )
                continue

            if resume_action is ResumeAction.OPEN_STEP:
                if state.next_step_index > self._max_steps:
                    state = terminate_run(
                        state,
                        target_status=RunStatus.PARTIAL,
                        reason=("The maximum number of committed steps was reached."),
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue

                step_id = self._id_factory.step_id(
                    state.run_id,
                    state.next_step_index,
                )
                state = open_step(state, step_id=step_id)
                await self._save(CheckpointBoundary.STEP_OPENED, state)
                continue

            if resume_action is ResumeAction.REQUEST_DECISION:
                if state.active_step is None:
                    raise RuntimeError("decision phase has no active step")
                if state.active_step.phase is StepPhase.OPENED:
                    state = mark_deciding(state)
                    await self._save(CheckpointBoundary.DECIDING, state)

                step = state.active_step
                if step is None:
                    raise RuntimeError("deciding state has no active step")
                try:
                    context = self._context_compiler.compile(state)
                except ContextOverflowError as exc:
                    state = terminate_run(
                        state,
                        target_status=RunStatus.PARTIAL,
                        reason=str(exc),
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue

                try:
                    decision_payload = await self._await_operation(
                        lambda: self._model.decide(context)
                    )
                except _RunCancelled:
                    state = terminate_run(
                        state,
                        target_status=RunStatus.CANCELLED,
                        reason="The run was cancelled.",
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue
                except ModelClientError as exc:
                    state = await self._recover_decision_failure(
                        state,
                        _runtime_failure_for_model_error(exc),
                    )
                    continue

                try:
                    self._decision_validator.validate(
                        state.domain_state,
                        decision_payload,
                    )
                except DecisionValidationError as exc:
                    state = await self._recover_decision_failure(
                        state,
                        RuntimeFailure(kind=exc.kind, message=str(exc)),
                    )
                    continue
                except ValueError as exc:
                    state = await self._recover_decision_failure(
                        state,
                        RuntimeFailure(
                            kind=RuntimeFailureKind.INVALID_DECISION,
                            message=str(exc),
                        ),
                    )
                    continue
                decision = DecisionEnvelope(
                    run_id=state.run_id,
                    step_id=step.step_id,
                    attempt=step.attempt,
                    decision=decision_payload,
                )
                state = accept_decision(state, decision)
                await self._save(
                    CheckpointBoundary.DECISION_ACCEPTED,
                    state,
                )
                continue

            if resume_action is ResumeAction.RESOLVE_ACTION:
                step = state.active_step
                if step is None or step.decision is None:
                    raise RuntimeError("action resolution has no accepted decision")
                try:
                    action_payload = self._action_resolver.resolve(
                        state.domain_state,
                        step.decision.decision,
                    )
                except ValueError as exc:
                    failure = RuntimeFailure(
                        kind=RuntimeFailureKind.INVALID_ACTION,
                        message=str(exc),
                    )
                    state = await self._recover_decision_failure(state, failure)
                    continue
                action = ActionRequest(
                    run_id=state.run_id,
                    step_id=step.step_id,
                    attempt=step.attempt,
                    action_id=self._id_factory.action_id(
                        state.run_id,
                        step.step_id,
                        step.attempt,
                    ),
                    action=action_payload,
                )
                state = start_action(state, action)
                await self._save(
                    CheckpointBoundary.ACTION_RUNNING,
                    state,
                )
                continue

            if resume_action is ResumeAction.EXECUTE_ACTION:
                step = state.active_step
                if step is None or step.action is None:
                    raise RuntimeError("action phase has no ActionRequest")
                try:
                    observation_payload = await self._await_operation(
                        lambda: self._action_executor.execute(step.action)
                    )
                except _RunCancelled:
                    state = terminate_run(
                        state,
                        target_status=RunStatus.CANCELLED,
                        reason="The run was cancelled.",
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue
                observation = ObservationEnvelope(
                    run_id=state.run_id,
                    step_id=step.step_id,
                    attempt=step.attempt,
                    action_id=step.action.action_id,
                    observation=observation_payload,
                )
                state = record_observation(state, observation)
                await self._save(
                    CheckpointBoundary.OBSERVATION_READY,
                    state,
                )
                continue

            if resume_action is ResumeAction.REDUCE_OBSERVATION:
                step = state.active_step
                if (
                    step is None
                    or step.decision is None
                    or step.action is None
                    or step.observation is None
                ):
                    raise RuntimeError("reduction phase has incomplete step payloads")

                try:
                    delta_payload = self._observation_processor.build_delta(
                        state.domain_state,
                        step.decision.decision,
                        step.observation.observation,
                    )
                except ValueError as exc:
                    failure = RuntimeFailure(
                        kind=RuntimeFailureKind.REDUCER_INVARIANT,
                        message=str(exc),
                    )
                    state = terminate_run(
                        state,
                        target_status=RunStatus.FAILED,
                        reason=failure.message,
                        failure=failure,
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue
                state_delta = StateDelta(
                    run_id=state.run_id,
                    step_id=step.step_id,
                    attempt=step.attempt,
                    action_id=step.action.action_id,
                    delta=delta_payload,
                )

                if step.phase is StepPhase.OBSERVATION_READY:
                    state = mark_reducing(state)
                    await self._save(CheckpointBoundary.REDUCING, state)

                try:
                    state = commit_step(state, state_delta, self._reducer)
                except ValueError as exc:
                    failure = RuntimeFailure(
                        kind=RuntimeFailureKind.REDUCER_INVARIANT,
                        message=str(exc),
                    )
                    state = terminate_run(
                        state,
                        target_status=RunStatus.FAILED,
                        reason=failure.message,
                        failure=failure,
                    )
                    await self._save(
                        CheckpointBoundary.RUN_TERMINATED,
                        state,
                    )
                    continue
                await self._save(
                    CheckpointBoundary.STEP_COMMITTED,
                    state,
                )
                continue

            raise RuntimeError(f"unsupported resume action: {resume_action.value}")

    async def _recover_decision_failure(
        self,
        state: RuntimeState,
        failure: RuntimeFailure,
    ) -> RuntimeState:
        step = state.active_step
        if step is None or step.phase not in {
            StepPhase.DECIDING,
            StepPhase.DECISION_ACCEPTED,
        }:
            raise RuntimeError(
                "decision recovery requires a deciding or accepted step"
            )

        if failure.kind is RuntimeFailureKind.REPEATED_ACTION:
            next_state = terminate_run(
                state,
                target_status=RunStatus.PARTIAL,
                reason=failure.message,
            )
            await self._save(CheckpointBoundary.RUN_TERMINATED, next_state)
            return next_state

        non_retryable = {
            RuntimeFailureKind.MODEL_AUTHENTICATION,
            RuntimeFailureKind.MODEL_CONFIGURATION_ERROR,
        }
        if (
            failure.kind not in non_retryable
            and step.attempt < self._max_decision_attempts
        ):
            if step.phase is StepPhase.DECIDING:
                next_state = retry_decision(state, failure)
            else:
                next_state = repair_accepted_decision(state, failure)
            await self._save(CheckpointBoundary.DECIDING, next_state)
            return next_state

        if state.committed_steps:
            next_state = terminate_run(
                state,
                target_status=RunStatus.PARTIAL,
                reason=(f"Decision recovery was exhausted: {failure.message}"),
            )
        else:
            next_state = terminate_run(
                state,
                target_status=RunStatus.FAILED,
                reason=failure.message,
                failure=failure,
            )
        await self._save(CheckpointBoundary.RUN_TERMINATED, next_state)
        return next_state

    async def _save(
        self,
        boundary: CheckpointBoundary,
        state: RuntimeState,
    ) -> None:
        await self._checkpoint_store.save(state)
        await self._hook.after_checkpoint(boundary, state)

    async def _await_operation(self, operation) -> Any:
        if self._cancellation_signal.is_cancelled():
            raise _RunCancelled
        operation_task = asyncio.create_task(operation())
        wait_task = asyncio.create_task(
            self._cancellation_signal.wait_cancelled()
        )
        done, _pending = await asyncio.wait(
            {operation_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wait_task in done:
            operation_task.cancel()
            try:
                await operation_task
            except asyncio.CancelledError:
                pass
            raise _RunCancelled
        wait_task.cancel()
        try:
            await wait_task
        except asyncio.CancelledError:
            pass
        return await operation_task


_RUNTIME_KIND_BY_MODEL_ERROR = {
    ModelErrorKind.MALFORMED_RESPONSE: (RuntimeFailureKind.MODEL_MALFORMED_RESPONSE),
    ModelErrorKind.EMPTY_RESPONSE: RuntimeFailureKind.MODEL_EMPTY_RESPONSE,
    ModelErrorKind.REFUSAL: RuntimeFailureKind.MODEL_REFUSAL,
    ModelErrorKind.TIMEOUT: RuntimeFailureKind.MODEL_TIMEOUT,
    ModelErrorKind.RATE_LIMITED: RuntimeFailureKind.MODEL_RATE_LIMITED,
    ModelErrorKind.AUTHENTICATION: RuntimeFailureKind.MODEL_AUTHENTICATION,
    ModelErrorKind.INVALID_REQUEST: (RuntimeFailureKind.MODEL_CONFIGURATION_ERROR),
    ModelErrorKind.SERVER_ERROR: RuntimeFailureKind.MODEL_SERVER_ERROR,
}


def _runtime_failure_for_model_error(
    error: ModelClientError,
) -> RuntimeFailure:
    return RuntimeFailure(
        kind=_RUNTIME_KIND_BY_MODEL_ERROR[error.error.kind],
        message=error.error.message,
    )
