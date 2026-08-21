import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError, TypeAdapter

from opinion_search.tools.cache import ToolCacheConflictError
from opinion_search.tools.contracts import ToolCall, ToolResult


CACHE_SCHEMA_VERSION = 1

_TOOL_CALL_ADAPTER = TypeAdapter(ToolCall)
_TOOL_RESULT_ADAPTER = TypeAdapter(ToolResult)


class ToolCacheReadError(RuntimeError):
    """Raised when a cached action result cannot be read or decoded."""


class JsonActionResultCache:
    """Atomic, cross-process cache of successful ToolResults keyed by action ID.

    One entry per action ID; the filename is the lowercase SHA-256 of the action
    ID UTF-8 bytes plus ``.json``, so arbitrary action IDs can never become
    filesystem paths. Writes use a temporary file, ``fsync`` and ``os.replace``
    in the destination directory, so a reader never observes a partial entry.

    Stores the requested ``ToolCall`` beside its ``ToolResult`` so identity
    conflicts are detected even after a process restart.

    Concurrency boundary: get/put are serialized by an in-process
    ``asyncio.Lock`` and atomic replace protects readers from partial files.
    Two independent processes may concurrently invoke the same not-yet-cached
    action; this cache does not claim distributed locking or cross-process
    mutual exclusion.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = asyncio.Lock()

    @property
    def directory(self) -> Path:
        return self._directory

    def _path_for(self, action_id: str) -> Path:
        digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"

    async def get(self, call: ToolCall) -> ToolResult | None:
        async with self._lock:
            return await asyncio.to_thread(self._get_sync, call)

    async def put(self, call: ToolCall, result: ToolResult) -> None:
        if result.action_id != call.action_id or result.tool_name != call.tool_name:
            raise ToolCacheConflictError(
                "cached result identity does not match ToolCall"
            )
        async with self._lock:
            await asyncio.to_thread(self._put_sync, call, result)

    def _get_sync(self, call: ToolCall) -> ToolResult | None:
        path = self._path_for(call.action_id)
        if not path.exists():
            return None
        payload = self._read_entry(path)
        stored_call = _TOOL_CALL_ADAPTER.validate_python(payload["call"])
        if stored_call != call:
            raise ToolCacheConflictError(
                "action ID was reused for a different ToolCall"
            )
        return _TOOL_RESULT_ADAPTER.validate_python(payload["result"])

    def _put_sync(self, call: ToolCall, result: ToolResult) -> None:
        path = self._path_for(call.action_id)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "action_id": call.action_id,
            "call": call.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
        if path.exists():
            existing = self._read_entry(path)
            stored_call = _TOOL_CALL_ADAPTER.validate_python(existing["call"])
            stored_result = _TOOL_RESULT_ADAPTER.validate_python(
                existing["result"]
            )
            if (stored_call, stored_result) != (call, result):
                raise ToolCacheConflictError(
                    "action ID already has a different cached result"
                )
            return

        self._directory.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._directory,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        except (OSError, TypeError, ValueError):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    def _read_entry(self, path: Path) -> dict:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolCacheReadError(
                f"failed to read cached action result {path.name}"
            ) from exc

        if not isinstance(payload, dict):
            raise ToolCacheReadError("cached action result root must be an object")

        version = payload.get("schema_version")
        if version != CACHE_SCHEMA_VERSION:
            raise ToolCacheReadError(
                "unsupported action result cache schema version: "
                f"expected={CACHE_SCHEMA_VERSION}, actual={version}"
            )

        stored_action_id = payload.get("action_id")
        if not isinstance(stored_action_id, str) or not stored_action_id:
            raise ToolCacheReadError("cached action result has no action_id")

        for field_name in ("call", "result"):
            if field_name not in payload:
                raise ToolCacheReadError(
                    f"cached action result has no {field_name} payload"
                )

        try:
            call = _TOOL_CALL_ADAPTER.validate_python(payload["call"])
            result = _TOOL_RESULT_ADAPTER.validate_python(payload["result"])
        except ValidationError as exc:
            raise ToolCacheReadError("cached action result payload is invalid") from exc

        if call.action_id != stored_action_id:
            raise ToolCacheReadError(
                "cached call action_id does not match cache entry"
            )
        if (
            result.action_id != call.action_id
            or result.tool_name != call.tool_name
        ):
            raise ToolCacheConflictError(
                "cached result identity does not match stored call"
            )
        return {"call": call, "result": result}
