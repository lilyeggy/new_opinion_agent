"""Capture of committed-step replay records from a live run.

Three pieces cooperate:

- ``RecordingModelClient`` wraps the model and reports every call's outcome.
- ``DecisionRecorder`` keeps the in-flight step's model calls in memory and in a
  side file, and turns a committed step into a ``StepJournalRecord``.
- ``JournalingCheckpointStore`` wraps the checkpoint store so that the journal
  record of a commit is durable before the checkpoint that commits the step.

Ordering on commit: journal append, checkpoint save, then in-flight cleanup. A
crash between the first two leaves the journal one record ahead; ``load``
truncates that record. A crash after the checkpoint but before cleanup leaves a
stale in-flight file; ``load`` discards it because its step is no longer active.

In-flight calls are persisted before the decision is used. Each decision attempt
makes exactly one model call, so the number of persisted calls for the active
step is derivable from the step's attempt number and phase. ``load`` uses that
count to keep the calls that belong to the current attempt history, and to flag
the step incomplete when calls were lost.
"""

from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from opinion_search.models.contracts import ModelClientError, ModelError
from opinion_search.runtime.checkpoint import CheckpointStore
from opinion_search.runtime.journal import JournalError, RuntimeJournal
from opinion_search.runtime.lifecycle import StepPhase
from opinion_search.runtime.replay_record import (
    ModelCallRecord,
    StepJournalRecord,
    fingerprint,
)
from opinion_search.runtime.transaction import RunState


IN_FLIGHT_SUFFIX = ".inflight"
_PHASES_BEFORE_ATTEMPT_CALL = frozenset({StepPhase.OPENED, StepPhase.DECIDING})


class _StepBuffer:
    def __init__(
        self,
        step_id: str,
        *,
        complete: bool,
        model_calls: list[ModelCallRecord],
    ) -> None:
        self.step_id = step_id
        self.complete = complete
        self.model_calls = model_calls


class DecisionRecorder:
    """Accumulates model calls per step and appends committed-step records."""

    def __init__(self, journal_path: Path) -> None:
        self._journal = RuntimeJournal(journal_path)
        self._in_flight = RuntimeJournal(
            journal_path.with_name(journal_path.name + IN_FLIGHT_SUFFIX)
        )
        self._journaled_count = len(self._journal.read())
        self._buffer: _StepBuffer | None = None

    @property
    def journal(self) -> RuntimeJournal:
        return self._journal

    def record_decision(self, context_hash: str, decision: Any) -> None:
        self._append_call(
            ModelCallRecord(
                context_hash=context_hash,
                outcome="decision",
                decision=to_jsonable_python(decision),
            )
        )

    def record_model_error(self, context_hash: str, error: ModelError) -> None:
        self._append_call(
            ModelCallRecord(
                context_hash=context_hash,
                outcome="error",
                error_kind=error.kind.value,
                error_message=error.message,
            )
        )

    def prepare_save(self, state: RunState[Any, Any, Any, Any]) -> None:
        """Make the commit record durable before the checkpoint is written."""
        committed = len(state.committed_steps)
        if committed < self._journaled_count:
            raise JournalError(
                "checkpoint is behind the decision journal; "
                "resume through the checkpoint store before saving"
            )
        if committed > self._journaled_count + 1:
            raise JournalError("more than one step committed between saves")
        if committed == self._journaled_count + 1:
            self._append_committed(state)
        self._observe_active(state)

    def after_save(self, state: RunState[Any, Any, Any, Any]) -> None:
        """Drop in-flight calls once no active step needs them."""
        if state.active_step is None:
            self._clear_in_flight()

    def reconcile_load(self, state: RunState[Any, Any, Any, Any]) -> None:
        """Align journal and in-flight files with a state loaded from a checkpoint."""
        committed = state.committed_steps
        expected_count = len(committed)
        records = self._journal.read()

        if len(records) == expected_count + 1:
            extra = records[-1]
            active = state.active_step
            if active is None or extra["step_id"] != active.step_id:
                raise JournalError(
                    "journal has an unmatched record beyond the checkpoint"
                )
            self._journal.truncate_after(expected_count)
            records = records[:-1]
        elif len(records) != expected_count:
            raise JournalError(
                "journal and checkpoint disagree on committed step count: "
                f"journal={len(records)}, checkpoint={expected_count}"
            )

        if expected_count:
            last = records[-1]
            if (
                last["step_index"] != expected_count
                or last["step_id"] != committed[-1].step_id
            ):
                raise JournalError("journal tail does not match checkpoint tail")

        self._journaled_count = expected_count
        self._buffer = None
        self._observe_active(state, loaded=True)

    def _append_call(self, call: ModelCallRecord) -> None:
        buffer = self._buffer
        if buffer is None:
            raise JournalError("model call recorded outside an active step")
        buffer.model_calls.append(call)
        self._in_flight.append(
            {
                "step_index": len(buffer.model_calls),
                "step_id": buffer.step_id,
                "call": call.model_dump(mode="json"),
            }
        )

    def _observe_active(
        self,
        state: RunState[Any, Any, Any, Any],
        *,
        loaded: bool = False,
    ) -> None:
        active = state.active_step
        if active is None:
            self._buffer = None
            return
        if self._buffer is not None and self._buffer.step_id == active.step_id:
            return

        if not loaded:
            self._buffer = _StepBuffer(
                active.step_id,
                complete=active.phase is StepPhase.OPENED,
                model_calls=[],
            )
            return

        expected_calls = _expected_model_calls(active.attempt, active.phase)
        entries = self._in_flight.read()
        kept = [entry for entry in entries if entry["step_id"] == active.step_id]
        kept = kept[:expected_calls]
        if kept != entries:
            self._in_flight.rewrite(kept)
        calls = [ModelCallRecord.model_validate(entry["call"]) for entry in kept]
        self._buffer = _StepBuffer(
            active.step_id,
            complete=len(kept) == expected_calls,
            model_calls=calls,
        )

    def _append_committed(self, state: RunState[Any, Any, Any, Any]) -> None:
        step = state.committed_steps[-1]
        buffer = self._buffer
        if buffer is None or buffer.step_id != step.step_id:
            raise JournalError("committed step has no matching decision buffer")
        if step.action is None or step.observation is None:
            raise JournalError("committed step is missing its action or observation")
        if buffer.complete and len(buffer.model_calls) != step.attempt:
            raise JournalError(
                "model call count does not match committed attempts: "
                f"calls={len(buffer.model_calls)}, attempts={step.attempt}"
            )

        record = StepJournalRecord(
            step_index=len(state.committed_steps),
            run_id=state.run_id,
            step_id=step.step_id,
            complete=buffer.complete,
            model_calls=tuple(buffer.model_calls),
            action_id=step.action.action_id,
            action=to_jsonable_python(step.action.action),
            observation=to_jsonable_python(step.observation.observation),
            state_fingerprint=fingerprint(state),
        )
        self._journal.append(record.model_dump(mode="json"))
        self._journaled_count += 1
        self._buffer = None

    def _clear_in_flight(self) -> None:
        self._in_flight.path.unlink(missing_ok=True)


def _expected_model_calls(attempt: int, phase: StepPhase) -> int:
    """Model calls already made for the step: earlier attempts plus the current one if decided."""
    completed_current = 0 if phase in _PHASES_BEFORE_ATTEMPT_CALL else 1
    return (attempt - 1) + completed_current


class RecordingModelClient:
    """Model wrapper that reports every outcome to the recorder before returning it."""

    def __init__(self, model: Any, recorder: DecisionRecorder) -> None:
        self._model = model
        self._recorder = recorder

    async def decide(self, context: Any) -> Any:
        context_hash = fingerprint(context)
        try:
            decision = await self._model.decide(context)
        except ModelClientError as exc:
            self._recorder.record_model_error(context_hash, exc.error)
            raise
        self._recorder.record_decision(context_hash, decision)
        return decision


class JournalingCheckpointStore:
    """Checkpoint store wrapper that keeps the decision journal ahead of checkpoints."""

    def __init__(
        self,
        store: CheckpointStore[Any],
        recorder: DecisionRecorder,
    ) -> None:
        self._store = store
        self._recorder = recorder

    async def save(self, state: Any) -> None:
        self._recorder.prepare_save(state)
        await self._store.save(state)
        self._recorder.after_save(state)

    async def load(self) -> Any:
        state = await self._store.load()
        self._recorder.reconcile_load(state)
        return state
