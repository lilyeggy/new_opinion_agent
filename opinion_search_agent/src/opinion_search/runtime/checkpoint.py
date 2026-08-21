import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel


StateT = TypeVar("StateT", bound=BaseModel)

CHECKPOINT_SCHEMA_VERSION = 4


class CheckpointError(RuntimeError):
    """Base class for checkpoint persistence failures."""


class CheckpointReadError(CheckpointError):
    """Raised when a checkpoint cannot be read or decoded."""


class CheckpointWriteError(CheckpointError):
    """Raised when a checkpoint cannot be written atomically."""


class CheckpointVersionError(CheckpointReadError):
    """Raised when a checkpoint schema version is unsupported."""


class CheckpointProfileError(CheckpointReadError):
    """Raised when a checkpoint belongs to another app composition."""


class CheckpointStore(Protocol[StateT]):
    async def save(self, state: StateT) -> None: ...

    async def load(self) -> StateT: ...


class JsonCheckpointStore(Generic[StateT]):
    def __init__(
        self,
        path: Path,
        state_type: type[StateT],
        *,
        execution_profile: str | None = None,
    ) -> None:
        self._path = path
        self._state_type = state_type
        self._execution_profile = execution_profile

    @property
    def path(self) -> Path:
        return self._path

    async def save(self, state: StateT) -> None:
        await asyncio.to_thread(self._save_sync, state)

    async def load(self) -> StateT:
        return await asyncio.to_thread(self._load_sync)

    def _save_sync(self, state: StateT) -> None:
        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "execution_profile": self._execution_profile or "unbound",
            "state": state.model_dump(mode="json"),
        }
        temporary_path: Path | None = None

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, self._path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise CheckpointWriteError(
                f"failed to write checkpoint {self._path}"
            ) from exc

    def _load_sync(self) -> StateT:
        try:
            raw_payload = self._path.read_text(encoding="utf-8")
            payload = json.loads(raw_payload)
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointReadError(
                f"failed to read checkpoint {self._path}"
            ) from exc

        if not isinstance(payload, dict):
            raise CheckpointReadError("checkpoint root must be an object")

        version = payload.get("schema_version")
        if version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointVersionError(
                "unsupported checkpoint schema version: "
                f"expected={CHECKPOINT_SCHEMA_VERSION}, actual={version}"
            )

        stored_profile = payload.get("execution_profile")
        if not isinstance(stored_profile, str) or not stored_profile:
            raise CheckpointReadError("checkpoint has no valid execution profile")
        if (
            self._execution_profile is not None
            and stored_profile != self._execution_profile
        ):
            raise CheckpointProfileError(
                "checkpoint execution profile does not match the selected "
                "application composition"
            )

        if "state" not in payload:
            raise CheckpointReadError("checkpoint has no state payload")

        try:
            return self._state_type.model_validate(payload["state"])
        except (TypeError, ValueError) as exc:
            raise CheckpointReadError("checkpoint state payload is invalid") from exc
