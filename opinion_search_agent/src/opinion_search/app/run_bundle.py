from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from opinion_search.domain.opinion.brief import SearchOutcome


class RunBundleError(RuntimeError):
    """Raised when a terminal run artifact cannot be written."""


class RunBundleWriter:
    """Atomically write the terminal Markdown and typed outcome artifacts.

    The report is a deterministic projection of the latest terminal Domain
    State, so overwriting an existing report is allowed. Reader artifacts stay
    at ``checkpoint_path.parent / "artifacts"`` and are never copied here. No
    secret or config value is serialized into the report.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self._checkpoint_path = checkpoint_path

    @property
    def report_path(self) -> Path:
        return (self._checkpoint_path.parent / "report.md").resolve()

    @property
    def outcome_path(self) -> Path:
        return (self._checkpoint_path.parent / "outcome.json").resolve()

    async def write_report(self, outcome: SearchOutcome) -> Path:
        return await asyncio.to_thread(self._write_sync, outcome)

    def _write_sync(self, outcome: SearchOutcome) -> Path:
        report_path = self._checkpoint_path.parent / "report.md"
        content = outcome.markdown
        if not content.endswith("\n"):
            content += "\n"
        outcome_content = json.dumps(
            outcome.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(report_path, content)
            _atomic_write(self._checkpoint_path.parent / "outcome.json", outcome_content)
        except (OSError, TypeError, ValueError) as exc:
            raise RunBundleError(
                f"failed to write terminal bundle beside {report_path}"
            ) from exc
        return report_path.resolve()


def _atomic_write(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
