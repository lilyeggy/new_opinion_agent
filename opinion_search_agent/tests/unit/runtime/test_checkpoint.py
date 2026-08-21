import asyncio
import json

import pytest

from opinion_search.runtime.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointProfileError,
    CheckpointReadError,
    CheckpointVersionError,
    JsonCheckpointStore,
)
from opinion_search.runtime.transaction import RunState, start_run


RuntimeStateFixture = RunState[str, str, str, str]


def test_json_checkpoint_round_trips_run_state(tmp_path) -> None:
    path = tmp_path / "nested" / "run.json"
    store = JsonCheckpointStore(path, RuntimeStateFixture)
    state = start_run(RuntimeStateFixture(run_id="run-1", domain_state="domain"))

    asyncio.run(store.save(state))
    restored = asyncio.run(store.load())

    assert restored == state
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert payload["execution_profile"] == "unbound"


def test_checkpoint_rejects_unknown_schema_version(tmp_path) -> None:
    path = tmp_path / "run.json"
    path.write_text(
        json.dumps({"schema_version": 999, "state": {}}),
        encoding="utf-8",
    )
    store = JsonCheckpointStore(path, RuntimeStateFixture)

    with pytest.raises(CheckpointVersionError):
        asyncio.run(store.load())


def test_checkpoint_rejects_corrupt_json(tmp_path) -> None:
    path = tmp_path / "run.json"
    path.write_text("not-json", encoding="utf-8")
    store = JsonCheckpointStore(path, RuntimeStateFixture)

    with pytest.raises(CheckpointReadError):
        asyncio.run(store.load())


def test_checkpoint_rejects_missing_file(tmp_path) -> None:
    store = JsonCheckpointStore(
        tmp_path / "missing.json",
        RuntimeStateFixture,
    )

    with pytest.raises(CheckpointReadError):
        asyncio.run(store.load())


def test_atomic_save_leaves_no_temporary_file(tmp_path) -> None:
    path = tmp_path / "run.json"
    store = JsonCheckpointStore(path, RuntimeStateFixture)
    state = RuntimeStateFixture(run_id="run-1", domain_state="domain")

    asyncio.run(store.save(state))

    temporary_files = tuple(tmp_path.glob(".run.json.*.tmp"))
    assert temporary_files == ()


def test_checkpoint_rejects_a_different_execution_profile(tmp_path) -> None:
    path = tmp_path / "run.json"
    writer = JsonCheckpointStore(
        path,
        RuntimeStateFixture,
        execution_profile="offline-v1",
    )
    reader = JsonCheckpointStore(
        path,
        RuntimeStateFixture,
        execution_profile="live-v1",
    )
    state = RuntimeStateFixture(run_id="run-1", domain_state="domain")

    asyncio.run(writer.save(state))

    with pytest.raises(CheckpointProfileError, match="profile"):
        asyncio.run(reader.load())
