"""R14: the budget clock covers planning and never resets on recovery."""

from __future__ import annotations

import json

import pytest

from opinion_search.investigation.storage import read_json


def test_clarification_waits_pause_the_budget_clock(manager, wait_for_terminal):
    import time

    created = manager.create({"mode": "offline", "question": "某市公交夜班调整", "time_range": "下周"})
    run_id = created["run_id"]
    deadline = time.monotonic() + 10
    while manager.snapshot(run_id)["status"] not in {"needs_clarification", "failed"}:
        if time.monotonic() > deadline:
            raise AssertionError("run did not request clarification")
        time.sleep(0.02)
    assert manager.snapshot(run_id)["status"] == "needs_clarification"
    budget_path = manager.path(run_id) / "budget.json"
    assert read_json(budget_path)["started_at"] is None

    manager.clarify(run_id, {"answer": "2026-01-01 至 2026-01-30"})
    snapshot = wait_for_terminal(manager, run_id)
    assert snapshot["status"] in {"completed", "partial"}
    budget = read_json(budget_path)
    assert budget["started_at"] is not None
    assert budget["model"] > 0


def test_resume_does_not_reset_consumed_budget(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    run_id = snapshot["run_id"]
    budget_path = manager.path(run_id) / "budget.json"
    before = read_json(budget_path)

    data = manager.load(run_id)
    data.pop("published", None)
    manager.save(data, status="finalizing", phase="正在写入报告与版本")
    manager.resume(run_id)

    import time
    deadline = time.monotonic() + 20
    while manager.snapshot(run_id)["status"] not in {"completed", "partial", "failed", "cancelled"}:
        if time.monotonic() > deadline:
            raise AssertionError("resume did not finish")
        time.sleep(0.02)

    after = read_json(budget_path)
    assert after["started_at"] == before["started_at"]
    assert after["model"] >= before["model"]
    assert after["search"] == before["search"]


def test_budget_limits_come_from_env_without_losing_defaults(monkeypatch):
    from opinion_search.investigation.manager import budget_limits

    monkeypatch.delenv("OPINION_INVESTIGATION_SECONDS", raising=False)
    assert budget_limits() == {}

    monkeypatch.setenv("OPINION_INVESTIGATION_SECONDS", "2400")
    monkeypatch.setenv("OPINION_INVESTIGATION_MODEL_CALLS", "120")
    assert budget_limits() == {"seconds": 2400, "model": 120}

    monkeypatch.setenv("OPINION_INVESTIGATION_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="positive integer"):
        budget_limits()


def test_pause_folds_elapsed_time_into_accumulated_budget(tmp_path):
    """A clarified/paused run must not get a fresh time window on resume."""

    from datetime import datetime, timedelta, timezone

    from opinion_search.investigation.storage import Budget, atomic_json, read_json

    budget = Budget(tmp_path / "budget.json", {"seconds": 1200})
    budget.start()
    data = read_json(budget.path)
    data["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
    atomic_json(budget.path, data)

    budget.pause()
    paused = read_json(budget.path)
    assert paused["started_at"] is None
    assert paused["accumulated_seconds"] >= 100

    budget.start()
    snapshot = budget.snapshot()
    assert snapshot["elapsed_seconds"] >= 100, "resumed run must keep its already spent time"
    assert snapshot["search"] == 0 and snapshot["read"] == 0 and snapshot["model"] == 0

    data = read_json(budget.path)
    data["started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=50)).isoformat()
    atomic_json(budget.path, data)
    budget.pause()
    assert read_json(budget.path)["accumulated_seconds"] >= 150


def test_budget_file_from_older_version_without_accumulator_still_works(tmp_path):
    from datetime import datetime, timedelta, timezone

    from opinion_search.investigation.storage import Budget, atomic_json

    path = tmp_path / "budget.json"
    atomic_json(path, {"started_at": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
                       "search": 1, "read": 0, "model": 0,
                       "limits": {"search": 20, "read": 24, "model": 80, "seconds": 1200, "consolidate_seconds": 900}})
    snapshot = Budget(path).snapshot()
    assert snapshot["elapsed_seconds"] >= 30
    assert snapshot["search"] == 1
