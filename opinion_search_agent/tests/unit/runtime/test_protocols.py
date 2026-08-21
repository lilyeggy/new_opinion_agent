from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from opinion_search.runtime.lifecycle import StepPhase
from opinion_search.runtime.protocols import (
    ActionRequest,
    DecisionEnvelope,
    ObservationEnvelope,
    StateDelta,
    StepRecord,
)


class StubDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["search"]
    query: str


class StubAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["tool"]
    tool_name: str
    arguments: dict[str, str]


class StubObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["succeeded"]
    candidate_ids: tuple[str, ...]


class StubDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    added_candidate_ids: tuple[str, ...]


DecisionUnderTest = DecisionEnvelope[StubDecision]
ActionUnderTest = ActionRequest[StubAction]
ObservationUnderTest = ObservationEnvelope[StubObservation]
DeltaUnderTest = StateDelta[StubDelta]
StepRecordUnderTest = StepRecord[StubDecision, StubAction, StubObservation]


def test_decision_envelope_preserves_typed_payload_and_correlation() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "decision": {
            "action": "search",
            "query": "official product recall announcement",
        },
    }

    envelope = DecisionUnderTest.model_validate(payload)

    assert envelope.run_id == "run-001"
    assert envelope.step_id == "step-003"
    assert envelope.attempt == 1
    assert isinstance(envelope.decision, StubDecision)
    assert envelope.decision.query == "official product recall announcement"
    assert envelope.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"run_id": ""},
        {"run_id": "   "},
        {"step_id": ""},
        {"step_id": "   "},
        {"attempt": 0},
        {"attempt": -1},
    ],
)
def test_decision_envelope_rejects_invalid_correlation(
    invalid_fields: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "decision": {
            "action": "search",
            "query": "official announcement",
        },
    }
    payload.update(invalid_fields)

    with pytest.raises(ValidationError):
        DecisionUnderTest.model_validate(payload)


def test_decision_envelope_rejects_runtime_extra_fields() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "decision": {
            "action": "search",
            "query": "official announcement",
        },
        "provider_request_id": "provider-private-123",
    }

    with pytest.raises(ValidationError):
        DecisionUnderTest.model_validate(payload)


def test_decision_payload_owns_domain_fields() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "decision": {
            "action": "search",
            "query": "official announcement",
            "provider_model": "provider-private-model",
        },
    }

    with pytest.raises(ValidationError):
        DecisionUnderTest.model_validate(payload)


def test_decision_envelope_is_immutable() -> None:
    envelope = DecisionUnderTest.model_validate(
        {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "decision": {
                "action": "search",
                "query": "official announcement",
            },
        }
    )

    with pytest.raises(ValidationError):
        envelope.attempt = 2


def test_action_request_preserves_accepted_action_and_identity() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": "action-003-001",
        "action": {
            "kind": "tool",
            "tool_name": "search",
            "arguments": {"query": "official announcement"},
        },
    }

    request = ActionUnderTest.model_validate(payload)

    assert request.action_id == "action-003-001"
    assert isinstance(request.action, StubAction)
    assert request.action.tool_name == "search"
    assert request.model_dump(mode="json") == payload


def test_observation_envelope_correlates_result_to_action() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": "action-003-001",
        "observation": {
            "status": "succeeded",
            "candidate_ids": ["candidate-001", "candidate-002"],
        },
    }

    envelope = ObservationUnderTest.model_validate(payload)

    assert envelope.action_id == "action-003-001"
    assert isinstance(envelope.observation, StubObservation)
    assert envelope.observation.candidate_ids == (
        "candidate-001",
        "candidate-002",
    )
    assert envelope.model_dump(mode="json") == payload


def test_state_delta_correlates_proposed_change_to_action() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": "action-003-001",
        "delta": {
            "added_candidate_ids": ["candidate-001", "candidate-002"],
        },
    }

    delta = DeltaUnderTest.model_validate(payload)

    assert delta.action_id == "action-003-001"
    assert isinstance(delta.delta, StubDelta)
    assert delta.delta.added_candidate_ids == (
        "candidate-001",
        "candidate-002",
    )
    assert delta.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    ("model_type", "payload_field", "payload_value"),
    [
        (
            ActionUnderTest,
            "action",
            {
                "kind": "tool",
                "tool_name": "search",
                "arguments": {"query": "official announcement"},
            },
        ),
        (
            ObservationUnderTest,
            "observation",
            {
                "status": "succeeded",
                "candidate_ids": ["candidate-001"],
            },
        ),
        (
            DeltaUnderTest,
            "delta",
            {"added_candidate_ids": ["candidate-001"]},
        ),
    ],
)
@pytest.mark.parametrize("invalid_action_id", ["", "   "])
def test_action_correlated_protocols_reject_blank_action_id(
    model_type: type[BaseModel],
    payload_field: str,
    payload_value: dict[str, object],
    invalid_action_id: str,
) -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": invalid_action_id,
        payload_field: payload_value,
    }

    with pytest.raises(ValidationError):
        model_type.model_validate(payload)


@pytest.mark.parametrize(
    ("model_type", "payload_field", "payload_value"),
    [
        (
            ActionUnderTest,
            "action",
            {
                "kind": "tool",
                "tool_name": "search",
                "arguments": {"query": "official announcement"},
            },
        ),
        (
            ObservationUnderTest,
            "observation",
            {
                "status": "succeeded",
                "candidate_ids": ["candidate-001"],
            },
        ),
        (
            DeltaUnderTest,
            "delta",
            {"added_candidate_ids": ["candidate-001"]},
        ),
    ],
)
def test_action_correlated_protocols_are_immutable(
    model_type: type[BaseModel],
    payload_field: str,
    payload_value: dict[str, object],
) -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": "action-003-001",
        payload_field: payload_value,
    }
    model = model_type.model_validate(payload)

    with pytest.raises(ValidationError):
        model.action_id = "different-action-id"


def test_action_request_rejects_provider_private_fields() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "action_id": "action-003-001",
        "action": {
            "kind": "tool",
            "tool_name": "search",
            "arguments": {"query": "official announcement"},
        },
        "provider_request_id": "provider-private-123",
    }

    with pytest.raises(ValidationError):
        ActionUnderTest.model_validate(payload)


def test_opened_step_record_has_only_runtime_identity() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "phase": "opened",
        "failures": [],
    }

    record = StepRecordUnderTest.model_validate(payload)

    assert record.phase is StepPhase.OPENED
    assert record.decision is None
    assert record.action is None
    assert record.observation is None
    assert record.model_dump(mode="json", exclude_none=True) == payload


def test_committed_step_record_round_trips_recovery_payloads() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "phase": "committed",
        "failures": [],
        "decision": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "decision": {
                "action": "search",
                "query": "official announcement",
            },
        },
        "action": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "action_id": "action-003-001",
            "action": {
                "kind": "tool",
                "tool_name": "search",
                "arguments": {"query": "official announcement"},
            },
        },
        "observation": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "action_id": "action-003-001",
            "observation": {
                "status": "succeeded",
                "candidate_ids": ["candidate-001"],
            },
        },
    }

    record = StepRecordUnderTest.model_validate(payload)

    assert isinstance(record.decision, DecisionEnvelope)
    assert isinstance(record.action, ActionRequest)
    assert isinstance(record.observation, ObservationEnvelope)
    assert record.model_dump(mode="json") == payload


def test_step_record_rejects_extra_fields() -> None:
    payload = {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "phase": "opened",
        "trace_span_id": "observability-private-123",
    }

    with pytest.raises(ValidationError):
        StepRecordUnderTest.model_validate(payload)


def test_step_record_is_immutable() -> None:
    record = StepRecordUnderTest.model_validate(
        {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "phase": "opened",
        }
    )

    with pytest.raises(ValidationError):
        record.phase = StepPhase.DECIDING


def _complete_step_record_payload() -> dict[str, object]:
    return {
        "run_id": "run-001",
        "step_id": "step-003",
        "attempt": 1,
        "phase": "committed",
        "decision": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "decision": {
                "action": "search",
                "query": "official announcement",
            },
        },
        "action": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "action_id": "action-003-001",
            "action": {
                "kind": "tool",
                "tool_name": "search",
                "arguments": {"query": "official announcement"},
            },
        },
        "observation": {
            "run_id": "run-001",
            "step_id": "step-003",
            "attempt": 1,
            "action_id": "action-003-001",
            "observation": {
                "status": "succeeded",
                "candidate_ids": ["candidate-001"],
            },
        },
    }


@pytest.mark.parametrize(
    ("phase", "included_payloads"),
    [
        (StepPhase.OPENED, frozenset()),
        (StepPhase.DECIDING, frozenset()),
        (StepPhase.DECISION_ACCEPTED, frozenset({"decision"})),
        (StepPhase.ACTION_RUNNING, frozenset({"decision", "action"})),
        (
            StepPhase.OBSERVATION_READY,
            frozenset({"decision", "action", "observation"}),
        ),
        (
            StepPhase.REDUCING,
            frozenset({"decision", "action", "observation"}),
        ),
        (
            StepPhase.COMMITTED,
            frozenset({"decision", "action", "observation"}),
        ),
    ],
)
def test_step_record_accepts_exact_payloads_for_phase(
    phase: StepPhase,
    included_payloads: frozenset[str],
) -> None:
    payload = _complete_step_record_payload()
    payload["phase"] = phase.value
    for field_name in {"decision", "action", "observation"} - included_payloads:
        payload.pop(field_name)

    record = StepRecordUnderTest.model_validate(payload)

    assert record.phase is phase


@pytest.mark.parametrize(
    ("phase", "missing_field"),
    [
        (StepPhase.DECISION_ACCEPTED, "decision"),
        (StepPhase.ACTION_RUNNING, "action"),
        (StepPhase.OBSERVATION_READY, "observation"),
        (StepPhase.COMMITTED, "observation"),
    ],
)
def test_step_record_rejects_missing_phase_payload(
    phase: StepPhase,
    missing_field: str,
) -> None:
    payload = _complete_step_record_payload()
    payload["phase"] = phase.value
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        StepRecordUnderTest.model_validate(payload)


@pytest.mark.parametrize(
    ("phase", "premature_field"),
    [
        (StepPhase.OPENED, "decision"),
        (StepPhase.DECIDING, "decision"),
        (StepPhase.DECISION_ACCEPTED, "action"),
        (StepPhase.ACTION_RUNNING, "observation"),
    ],
)
def test_step_record_rejects_payload_from_future_phase(
    phase: StepPhase,
    premature_field: str,
) -> None:
    complete_payload = _complete_step_record_payload()
    payload = {
        "run_id": complete_payload["run_id"],
        "step_id": complete_payload["step_id"],
        "attempt": complete_payload["attempt"],
        "phase": phase.value,
        premature_field: complete_payload[premature_field],
    }

    with pytest.raises(ValidationError):
        StepRecordUnderTest.model_validate(payload)


@pytest.mark.parametrize(
    ("envelope_name", "field_name", "invalid_value"),
    [
        ("decision", "run_id", "different-run"),
        ("action", "step_id", "different-step"),
        ("observation", "attempt", 2),
        ("observation", "action_id", "different-action"),
    ],
)
def test_step_record_rejects_mismatched_recovery_correlation(
    envelope_name: str,
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _complete_step_record_payload()
    envelope = payload[envelope_name]
    assert isinstance(envelope, dict)
    envelope[field_name] = invalid_value

    with pytest.raises(ValidationError):
        StepRecordUnderTest.model_validate(payload)
