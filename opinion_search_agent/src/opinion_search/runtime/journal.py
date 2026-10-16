"""Append-only decision journal storage for deterministic replay.

The journal stores one JSON object per line. Each record carries an integer
``step_index``; indices must be strictly increasing within a file (invariant I1).
This module only owns durability and ordering. The meaning of record payloads
belongs to the runtime step recorder, not to this storage layer.

A torn final line (no trailing newline, produced by a crash during append) is
treated as never written: it is ignored on read and removed before the next
append, so it can never be concatenated with a later record.
"""

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


STEP_INDEX_KEY = "step_index"


class JournalError(RuntimeError):
    """Base class for journal storage failures."""


class JournalCorruptError(JournalError):
    """Raised when a complete journal line cannot be decoded or violates ordering."""


class JournalWriteError(JournalError):
    """Raised when a record cannot be durably appended or rewritten."""


class RuntimeJournal:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> list[dict[str, Any]]:
        """Return all complete records in order, ignoring a torn trailing line."""
        records, _ = self._read_with_tail()
        return records

    def append(self, record: Mapping[str, Any]) -> None:
        """Durably append one record whose step_index is greater than all prior ones."""
        step_index = _require_step_index(record)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            records, has_torn_tail = self._read_with_tail()
            if records and step_index <= records[-1][STEP_INDEX_KEY]:
                raise JournalCorruptError(
                    "journal step_index must be strictly increasing: "
                    f"last={records[-1][STEP_INDEX_KEY]}, new={step_index}"
                )
            if has_torn_tail:
                self.rewrite(records)

            line = _encode(record) + "\n"
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise JournalWriteError(f"failed to append to journal {self._path}") from exc

    def truncate_after(self, step_index: int) -> int:
        """Drop every record with step_index greater than the given value.

        Returns the number of records removed. Used during recovery to align the
        journal with the last checkpoint that was durably written.
        """
        records, has_torn_tail = self._read_with_tail()
        kept = [r for r in records if r[STEP_INDEX_KEY] <= step_index]
        removed = len(records) - len(kept)
        if removed or has_torn_tail:
            self.rewrite(kept)
        return removed

    def _read_with_tail(self) -> tuple[list[dict[str, Any]], bool]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return [], False
        except OSError as exc:
            raise JournalCorruptError(f"failed to read journal {self._path}") from exc

        has_torn_tail = bool(raw) and not raw.endswith(b"\n")
        lines = raw.split(b"\n")
        # split() yields a trailing empty element when the file ends with newline;
        # with a torn tail the final element is the incomplete fragment.
        complete = lines[:-1]
        records: list[dict[str, Any]] = []
        for number, line in enumerate(complete, start=1):
            if not line:
                raise JournalCorruptError(
                    f"journal {self._path} has an empty line at {number}"
                )
            records.append(_decode(line, self._path, number))

        _validate_monotonic(records, self._path)
        return records, has_torn_tail

    def rewrite(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Atomically replace the file content with the given ordered records."""
        for record in records:
            _require_step_index(record)
        _validate_monotonic([dict(r) for r in records], self._path)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                for record in records:
                    handle.write(_encode(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise JournalWriteError(f"failed to rewrite journal {self._path}") from exc


def _require_step_index(record: Mapping[str, Any]) -> int:
    step_index = record.get(STEP_INDEX_KEY)
    if not isinstance(step_index, int) or isinstance(step_index, bool):
        raise JournalError(f"journal record needs an integer {STEP_INDEX_KEY}")
    return step_index


def _encode(record: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise JournalError("journal record is not JSON serializable") from exc


def _decode(line: bytes, path: Path, number: int) -> dict[str, Any]:
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalCorruptError(
            f"journal {path} line {number} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise JournalCorruptError(f"journal {path} line {number} is not an object")
    _require_step_index_on_read(value, path, number)
    return value


def _require_step_index_on_read(value: dict[str, Any], path: Path, number: int) -> None:
    step_index = value.get(STEP_INDEX_KEY)
    if not isinstance(step_index, int) or isinstance(step_index, bool):
        raise JournalCorruptError(
            f"journal {path} line {number} has no integer {STEP_INDEX_KEY}"
        )


def _validate_monotonic(records: list[dict[str, Any]], path: Path) -> None:
    previous: int | None = None
    for record in records:
        current = record[STEP_INDEX_KEY]
        if previous is not None and current <= previous:
            raise JournalCorruptError(
                f"journal {path} step_index not strictly increasing: "
                f"{previous} then {current}"
            )
        previous = current
