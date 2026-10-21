"""A step must be able to say where its seconds went."""

from __future__ import annotations

from pathlib import Path

from opinion_search.runtime.timing import TimingRecorder, summarise


def test_recorder_writes_one_line_per_phase(tmp_path: Path):
    path = tmp_path / "timing.jsonl"
    recorder = TimingRecorder(path)
    recorder.record(run_id="r1", step_index=1, phase="model", seconds=1.5)
    recorder.record(run_id="r1", step_index=1, phase="tool", seconds=0.5, tool_name="read.web")

    summary = summarise(path)

    assert summary["total_seconds"] == 2.0
    assert summary["by_phase"]["model"]["count"] == 1
    assert summary["by_phase"]["tool"]["seconds"] == 0.5
    assert summary["worst"][0]["phase"] == "model"


def test_phase_context_manager_measures_elapsed_time(tmp_path: Path):
    path = tmp_path / "timing.jsonl"
    recorder = TimingRecorder(path)
    with recorder.phase(run_id="r1", step_index=2, phase="model"):
        pass

    summary = summarise(path)

    assert summary["by_phase"]["model"]["count"] == 1
    assert summary["by_phase"]["model"]["seconds"] >= 0


def test_missing_file_is_not_fatal(tmp_path: Path):
    recorder = TimingRecorder(tmp_path / "nope" / "timing.jsonl")
    recorder.record(run_id="r", step_index=1, phase="model", seconds=1.0)
    assert (tmp_path / "nope" / "timing.jsonl").exists()
