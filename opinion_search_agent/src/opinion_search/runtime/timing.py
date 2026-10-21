"""Where a step's wall-clock time actually goes.

The runtime recorded no per-step timing, so every optimisation was a guess: a
75-second step could have been the model, the tool, or a silent retry. This
sidecar appends one JSON line per measured phase and never touches state, the
checkpoint, or the journal, so replay is unaffected.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Iterator


class TimingRecorder:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(
        self,
        *,
        run_id: str,
        step_index: int,
        phase: str,
        seconds: float,
        tool_name: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        line = {
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": run_id,
            "step": step_index,
            "phase": phase,
            "seconds": round(float(seconds), 3),
        }
        if tool_name:
            line["tool"] = tool_name
        if detail:
            line.update(detail)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
                handle.flush()
        except OSError:
            # Timing must never break a run.
            return

    @contextmanager
    def phase(
        self,
        *,
        run_id: str,
        step_index: int,
        phase: str,
        tool_name: str | None = None,
    ) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            self.record(
                run_id=run_id, step_index=step_index, phase=phase,
                seconds=time.monotonic() - started, tool_name=tool_name,
            )


def summarise(path: Path) -> dict[str, Any]:
    """Aggregate a timing file: totals, counts and worst cases per phase."""

    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    by_phase: dict[str, dict[str, Any]] = {}
    for row in rows:
        phase = str(row.get("phase") or "?")
        bucket = by_phase.setdefault(phase, {"count": 0, "seconds": 0.0, "max": 0.0})
        bucket["count"] += 1
        bucket["seconds"] = round(bucket["seconds"] + float(row.get("seconds") or 0), 3)
        bucket["max"] = max(bucket["max"], float(row.get("seconds") or 0))
    total = round(sum(float(row.get("seconds") or 0) for row in rows), 3)
    worst = sorted(rows, key=lambda row: -float(row.get("seconds") or 0))[:5]
    return {
        "total_seconds": total,
        "by_phase": by_phase,
        "worst": [
            {"step": row.get("step"), "phase": row.get("phase"),
             "tool": row.get("tool"), "seconds": row.get("seconds")}
            for row in worst
        ],
    }
