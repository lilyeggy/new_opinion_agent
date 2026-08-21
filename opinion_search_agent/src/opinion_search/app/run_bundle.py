from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from opinion_search.domain.opinion.brief import SearchOutcome


class RunBundleError(RuntimeError):
    """Raised when the terminal Markdown report cannot be written."""


class RunBundleWriter:
    """Atomically write the terminal Markdown report for a run.

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

    async def write_report(self, outcome: SearchOutcome) -> Path:
        return await asyncio.to_thread(self._write_sync, outcome)

    def _write_sync(self, outcome: SearchOutcome) -> Path:
        report_path = self._checkpoint_path.parent / "report.md"
        content = outcome.markdown
        if not content.endswith("\n"):
            content += "\n"

        temporary_path: Path | None = None
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=report_path.parent,
                prefix=f".{report_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, report_path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise RunBundleError(
                f"failed to write report {report_path}"
            ) from exc
        return report_path.resolve()
