"""Replay record schema, canonical fingerprints and divergence comparison.

One ``StepJournalRecord`` describes one committed step: every model call made
while the step was active (with a fingerprint of the compiled context it saw),
the action that was resolved, the observation the executor returned, and the
fingerprint of the authoritative state after the step committed.

Comparison is field-ordered so that the first divergence names the earliest
step and the earliest differing field. Nothing in this module calls a model,
a tool or a clock.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python


NonEmptyId = Annotated[str, Field(min_length=1)]
StepIndex = Annotated[int, Field(ge=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ModelCallOutcome = Literal["decision", "error"]


def canonical_json(value: Any) -> str:
    """Serialize a value with sorted keys and no insignificant whitespace.

    Pydantic models, dataclasses and enums are converted to JSON-compatible
    values first, so the same logical value always yields the same string.
    """
    return json.dumps(
        to_jsonable_python(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ModelCallRecord(BaseModel):
    """One model invocation, identified by the fingerprint of its input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_hash: Sha256Hex
    outcome: ModelCallOutcome
    decision: Any = None
    error_kind: NonEmptyId | None = None
    error_message: NonEmptyId | None = None

    @model_validator(mode="after")
    def validate_outcome_payload(self) -> Self:
        if self.outcome == "decision":
            if self.error_kind is not None or self.error_message is not None:
                raise ValueError("decision outcome cannot carry an error")
            if self.decision is None:
                raise ValueError("decision outcome requires a decision payload")
        else:
            if self.decision is not None:
                raise ValueError("error outcome cannot carry a decision payload")
            if self.error_kind is None or self.error_message is None:
                raise ValueError("error outcome requires error_kind and message")
        return self


class StepJournalRecord(BaseModel):
    """Replay material for one committed step.

    ``complete`` is False when the step began in an earlier process, so some of
    its model calls were never persisted. Such a record can be stored and
    inspected but cannot drive a replay.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: StepIndex
    run_id: NonEmptyId
    step_id: NonEmptyId
    complete: bool
    model_calls: tuple[ModelCallRecord, ...]
    action_id: NonEmptyId
    action: Any
    observation: Any
    state_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_model_calls(self) -> Self:
        if self.complete and not self.model_calls:
            raise ValueError("a complete step requires at least one model call")
        return self


class Divergence(BaseModel):
    """The first point where a replay disagrees with the recorded run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int
    field: str
    expected: Any
    actual: Any


def compare_step_records(
    expected: StepJournalRecord,
    actual: StepJournalRecord,
) -> Divergence | None:
    """Return the first differing field of one step, or None when equal.

    Fields are compared in execution order so a divergence in an early model
    call is reported before its downstream effects.
    """
    if expected.step_index != actual.step_index:
        return _diverge(expected, "step_index", expected.step_index, actual.step_index)
    if expected.step_id != actual.step_id:
        return _diverge(expected, "step_id", expected.step_id, actual.step_id)
    if expected.run_id != actual.run_id:
        return _diverge(expected, "run_id", expected.run_id, actual.run_id)

    if len(expected.model_calls) != len(actual.model_calls):
        return _diverge(
            expected,
            "model_calls.length",
            len(expected.model_calls),
            len(actual.model_calls),
        )
    for position, (want, got) in enumerate(
        zip(expected.model_calls, actual.model_calls, strict=True)
    ):
        prefix = f"model_calls[{position}]"
        for field_name in (
            "context_hash",
            "outcome",
            "decision",
            "error_kind",
            "error_message",
        ):
            want_value = getattr(want, field_name)
            got_value = getattr(got, field_name)
            if canonical_json(want_value) != canonical_json(got_value):
                return _diverge(
                    expected,
                    f"{prefix}.{field_name}",
                    want_value,
                    got_value,
                )

    if expected.action_id != actual.action_id:
        return _diverge(expected, "action_id", expected.action_id, actual.action_id)
    if canonical_json(expected.action) != canonical_json(actual.action):
        return _diverge(expected, "action", expected.action, actual.action)
    if canonical_json(expected.observation) != canonical_json(actual.observation):
        return _diverge(
            expected,
            "observation",
            expected.observation,
            actual.observation,
        )
    if expected.state_fingerprint != actual.state_fingerprint:
        return _diverge(
            expected,
            "state_fingerprint",
            expected.state_fingerprint,
            actual.state_fingerprint,
        )
    return None


def compare_journals(
    expected: Sequence[StepJournalRecord],
    actual: Sequence[StepJournalRecord],
) -> Divergence | None:
    """Compare two ordered step sequences and return the first divergence."""
    for want, got in zip(expected, actual, strict=False):
        divergence = compare_step_records(want, got)
        if divergence is not None:
            return divergence

    if len(expected) != len(actual):
        boundary = min(len(expected), len(actual))
        next_index = (
            expected[boundary].step_index
            if len(expected) > boundary
            else actual[boundary].step_index
        )
        return Divergence(
            step_index=next_index,
            field="step_count",
            expected=len(expected),
            actual=len(actual),
        )
    return None


def _diverge(
    expected: StepJournalRecord,
    field: str,
    want: Any,
    got: Any,
) -> Divergence:
    return Divergence(
        step_index=expected.step_index,
        field=field,
        expected=to_jsonable_python(want),
        actual=to_jsonable_python(got),
    )
