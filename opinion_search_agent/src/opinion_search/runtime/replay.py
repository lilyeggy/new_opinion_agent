"""Deterministic replay of a recorded run through the real runtime loop.

Only the two external boundaries are substituted: the model client and the
action executor. Both serve recorded outputs and refuse to serve anything the
recording does not contain. Context compilation, decision validation, action
resolution, observation processing, reduction and completion run as in
production. The replayed run is recorded with the same ``DecisionRecorder`` and
its journal is compared with the original, so the first divergence names the
step and field where behaviour changed.
"""

import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pydantic_core import to_jsonable_python

from opinion_search.models.contracts import ModelClientError, ModelError, ModelErrorKind
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.journal import RuntimeJournal
from opinion_search.runtime.loop import AgentLoop
from opinion_search.runtime.recording import (
    DecisionRecorder,
    JournalingCheckpointStore,
    RecordingModelClient,
)
from opinion_search.runtime.replay_record import (
    Divergence,
    StepJournalRecord,
    canonical_json,
    compare_journals,
    fingerprint,
)
from opinion_search.runtime.transaction import RunState


class ReplayMissingRecordError(RuntimeError):
    """Raised when a replay asks for an external output the journal does not hold."""


class ReplayRecordInvariantError(RuntimeError):
    """Raised when a journal record is missing a field its own schema requires."""


class ReplayStatus(StrEnum):
    MATCHED = "matched"
    DIVERGED = "diverged"
    UNREPLAYABLE = "unreplayable"


class ReplayReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReplayStatus
    steps_checked: int
    divergence: Divergence | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ReplayCodec:
    """Rebuilds typed model decisions and observations from journal JSON."""

    decision: TypeAdapter[Any]
    observation: TypeAdapter[Any]


class _DivergenceSignal(Exception):
    """Internal signal that a replayed boundary call disagrees with the record."""

    def __init__(self, divergence: Divergence) -> None:
        super().__init__(divergence.field)
        self.divergence = divergence


class _ReplayModel:
    def __init__(self, records: Sequence[StepJournalRecord], codec: ReplayCodec) -> None:
        self._codec = codec
        self._calls = [
            (record.step_index, position, call)
            for record in records
            for position, call in enumerate(record.model_calls)
        ]
        self._cursor = 0

    @property
    def unconsumed(self) -> int:
        return len(self._calls) - self._cursor

    async def decide(self, context: Any) -> Any:
        if self._cursor >= len(self._calls):
            raise ReplayMissingRecordError(
                "replay requested a model call that the journal does not contain"
            )
        step_index, position, call = self._calls[self._cursor]
        self._cursor += 1

        actual_hash = fingerprint(context)
        if actual_hash != call.context_hash:
            raise _DivergenceSignal(
                Divergence(
                    step_index=step_index,
                    field=f"model_calls[{position}].context_hash",
                    expected=call.context_hash,
                    actual=actual_hash,
                )
            )
        if call.outcome == "error":
            if call.error_kind is None or call.error_message is None:
                raise ReplayRecordInvariantError(
                    "an error record must carry both error_kind and error_message"
                )
            raise ModelClientError(
                ModelError(
                    kind=ModelErrorKind(call.error_kind),
                    message=call.error_message,
                )
            )
        return self._codec.decision.validate_python(call.decision)


class _ReplayExecutor:
    def __init__(self, records: Sequence[StepJournalRecord], codec: ReplayCodec) -> None:
        self._by_step_id = {record.step_id: record for record in records}
        self._codec = codec

    async def execute(self, request: Any) -> Any:
        record = self._by_step_id.get(request.step_id)
        if record is None:
            raise ReplayMissingRecordError(
                f"replay executed an action for unrecorded step {request.step_id}"
            )
        if request.action_id != record.action_id:
            raise _DivergenceSignal(
                Divergence(
                    step_index=record.step_index,
                    field="action_id",
                    expected=record.action_id,
                    actual=request.action_id,
                )
            )
        actual_action = to_jsonable_python(request.action)
        if canonical_json(actual_action) != canonical_json(record.action):
            raise _DivergenceSignal(
                Divergence(
                    step_index=record.step_index,
                    field="action",
                    expected=record.action,
                    actual=actual_action,
                )
            )
        return self._codec.observation.validate_python(record.observation)


async def replay_records(
    records: Sequence[StepJournalRecord],
    *,
    initial_state: RunState[Any, Any, Any, Any],
    codec: ReplayCodec,
    build_loop: Callable[[Any, Any, Any], AgentLoop],
) -> ReplayReport:
    """Replay a recorded run and report whether the runtime reproduced it.

    ``build_loop`` receives the model, the action executor and the checkpoint
    store to use. It must assemble the same runtime components as the original
    run, with a deterministic id factory. Replay never calls a real model or
    tool; a request beyond the recording raises ``ReplayMissingRecordError``.
    """
    unreplayable = next((r for r in records if not r.complete), None)
    if unreplayable is not None:
        return ReplayReport(
            status=ReplayStatus.UNREPLAYABLE,
            steps_checked=0,
            reason=(
                f"step {unreplayable.step_index} lost model calls across a restart"
            ),
        )

    model = _ReplayModel(records, codec)
    executor = _ReplayExecutor(records, codec)

    with tempfile.TemporaryDirectory(prefix="replay-") as scratch:
        scratch_dir = Path(scratch)
        recorder = DecisionRecorder(scratch_dir / "replay.journal")
        store = JournalingCheckpointStore(
            JsonCheckpointStore(
                scratch_dir / "replay.checkpoint.json",
                type(initial_state),
            ),
            recorder,
        )
        loop = build_loop(RecordingModelClient(model, recorder), executor, store)

        try:
            await loop.run(initial_state)
        except _DivergenceSignal as signal:
            return ReplayReport(
                status=ReplayStatus.DIVERGED,
                steps_checked=0,
                divergence=signal.divergence,
            )

        replayed = [
            StepJournalRecord.model_validate(entry)
            for entry in recorder.journal.read()
        ]

    if model.unconsumed:
        return ReplayReport(
            status=ReplayStatus.DIVERGED,
            steps_checked=len(replayed),
            divergence=Divergence(
                step_index=records[-1].step_index,
                field="model_calls.unconsumed",
                expected=model.unconsumed,
                actual=0,
            ),
        )

    divergence = compare_journals(records, replayed)
    if divergence is not None:
        return ReplayReport(
            status=ReplayStatus.DIVERGED,
            steps_checked=len(replayed),
            divergence=divergence,
        )
    return ReplayReport(status=ReplayStatus.MATCHED, steps_checked=len(replayed))


def load_step_records(journal_path: Path) -> list[StepJournalRecord]:
    """Parse a recorded journal into validated step records."""
    return [
        StepJournalRecord.model_validate(entry)
        for entry in RuntimeJournal(journal_path).read()
    ]
