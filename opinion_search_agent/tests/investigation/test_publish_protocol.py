"""R02: a user-visible terminal state must never precede a complete report."""

from __future__ import annotations

import time


def test_terminal_snapshot_always_carries_a_report(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    assert snapshot["status"] in {"completed", "partial"}
    assert "report" in snapshot


def test_running_snapshot_never_claims_terminal_without_report(manager):
    created = manager.create({"mode": "offline", "question": "某市公交夜班车调整的争议与回应"})
    run_id = created["run_id"]
    for _ in range(400):
        snapshot = manager.snapshot(run_id)
        if snapshot["status"] in {"completed", "partial", "failed", "cancelled"}:
            assert "report" in snapshot, "terminal status was exposed before the report existed"
            return
        assert "report" not in snapshot
        time.sleep(0.005)
    raise AssertionError("run did not terminate in time")


def test_interrupted_publish_is_recovered_on_resume(manager, run_offline):
    snapshot = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    run_id = snapshot["run_id"]

    # Simulate a crash between writing report.json and exposing the published version.
    data = manager.load(run_id)
    data.pop("published", None)
    manager.save(data, status="finalizing", phase="正在写入报告与版本")

    interrupted = manager.snapshot(run_id)
    assert interrupted["status"] == "finalizing"
    assert interrupted["report_pending"] is True
    assert "report" not in interrupted
    assert interrupted["resumable"] is True

    manager.resume(run_id)
    deadline = time.monotonic() + 20
    while manager.snapshot(run_id)["status"] not in {"completed", "partial", "failed", "cancelled"}:
        if time.monotonic() > deadline:
            raise AssertionError("resume did not republish the version")
        time.sleep(0.02)

    recovered = manager.snapshot(run_id)
    assert recovered["status"] in {"completed", "partial"}
    assert "report" in recovered
    assert recovered["report"]["run_id"] == run_id


def test_cancel_is_never_terminal_without_a_report(manager, wait_for_terminal):
    created = manager.create({"mode": "offline", "question": "某市公交夜班车调整的争议与回应"})
    run_id = created["run_id"]
    manager.cancel(run_id)
    snapshot = wait_for_terminal(manager, run_id)
    # A fast offline run may win the race; either way a terminal state has a report
    # and committed material is never discarded.
    assert snapshot["status"] in {"cancelled", "completed", "partial"}
    assert "report" in snapshot


def _republish_as(manager, run_id, status):
    """Re-publish an already committed run under a different terminal status."""

    import asyncio
    from types import SimpleNamespace

    from opinion_search.investigation.service import InvestigationRun
    from opinion_search.investigation.storage import read_json

    data = manager.load(run_id)
    raw = read_json(manager.path(run_id) / "run.json")
    state = InvestigationRun.model_validate(raw["state"]).domain_state
    result = SimpleNamespace(status=SimpleNamespace(value=status), domain_state=state, stop_reason="重新发布验证")
    budget = SimpleNamespace(snapshot=lambda: {})
    parent_id = data.get("parent_id")
    parent = read_json(manager.path(parent_id) / "report.json") if parent_id else None
    asyncio.run(manager._publish(run_id, data, result, parent, manager.path(run_id),
                                 manager.root / "cases" / data["case_id"], budget))


def test_partial_result_never_hides_the_last_completed_version(manager, run_offline):
    from opinion_search.investigation.storage import read_json

    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    parent_id, case_id = parent["run_id"], parent["case_id"]
    child = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    manager.save(manager.load(child["run_id"]), case_id=case_id, parent_id=parent_id)

    _republish_as(manager, child["run_id"], "partial")

    latest = read_json(manager.root / "cases" / case_id / "latest.json")
    latest_completed = read_json(manager.root / "cases" / case_id / "latest_completed.json")
    assert latest["run_id"] == child["run_id"], "latest still points at the most recent readable result"
    assert latest_completed["run_id"] == parent_id, "a partial update must not overwrite the last complete pointer"
    child_snapshot = manager.snapshot(child["run_id"])
    assert child_snapshot["latest_completed_run_id"] == parent_id


def test_completed_child_updates_the_complete_pointer(manager, run_offline):
    from opinion_search.investigation.storage import read_json

    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    child = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    manager.save(manager.load(child["run_id"]), case_id=parent["case_id"], parent_id=parent["run_id"])
    _republish_as(manager, child["run_id"], "completed")

    latest_completed = read_json(manager.root / "cases" / parent["case_id"] / "latest_completed.json")
    assert latest_completed["run_id"] == child["run_id"]

