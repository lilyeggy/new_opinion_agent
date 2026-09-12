"""Time-range clarification must accept natural answers and never loop silently.

Live run 09e78bcf got stuck: the user answered the time question with
"2026-09-07 到2026-09-12" (到 instead of 至), the answer was persisted but
never parsed, and every resubmission re-asked the identical question.
"""

from __future__ import annotations

import time

from opinion_search.investigation.manager import Manager


def _needs_time_clarification(manager: Manager) -> dict:
    snapshot = manager.create({"mode": "offline", "question": "某市公交夜班车调整的争议与回应",
                               "time_range": "过去五天"})
    run_id = snapshot["run_id"]
    deadline = time.monotonic() + 10
    while True:
        deadline_snapshot = manager.snapshot(run_id)
        if deadline_snapshot["status"] == "needs_clarification":
            break
        assert deadline_snapshot["status"] == "planning", deadline_snapshot["status"]
        assert time.monotonic() < deadline, "run never asked for a time range"
        time.sleep(0.05)
    assert deadline_snapshot["phase"] == "需要补充时间范围"
    return deadline_snapshot


def test_clarify_with_dao_separator_bounds_the_time_and_completes(manager, wait_for_terminal) -> None:
    snapshot = _needs_time_clarification(manager)
    run_id = snapshot["run_id"]

    clarified = manager.clarify(run_id, {"answer": "2026-09-07 到2026-09-12"})

    assert clarified["status"] in {"planning", "running", "finalizing"}
    final = wait_for_terminal(manager, run_id)
    assert final["status"] == "completed"
    # the canonical range is what the temporal parser consumed
    stored = manager.snapshot(run_id)
    assert "2026-09-07" in (stored["request"]["time_range"] or "")


def test_clarify_with_relative_days_bounds_the_time(manager, wait_for_terminal) -> None:
    snapshot = _needs_time_clarification(manager)
    run_id = snapshot["run_id"]

    clarified = manager.clarify(run_id, {"answer": "最近一周"})

    assert clarified["status"] in {"planning", "running", "finalizing"}
    assert "至" in clarified["request"]["time_range"]


def test_unparsable_time_answer_stays_on_the_clarification_page(manager, wait_for_terminal) -> None:
    snapshot = _needs_time_clarification(manager)
    run_id = snapshot["run_id"]

    stuck = manager.clarify(run_id, {"answer": "不知道"})

    # the loop guard: no silent re-ask, an explicit format hint instead
    assert stuck["status"] == "needs_clarification"
    assert stuck["phase"] == "时间范围未能识别"
    assert any("YYYY-MM-DD" in q for q in stuck["clarification_questions"])
    # prior answers stay visible so the user sees what was captured
    assert "不知道" in stuck["request"]["clarification"]

    recovered = manager.clarify(run_id, {"answer": "不限时间"})
    assert recovered["status"] in {"planning", "running", "finalizing"}
    assert recovered["request"]["time_range"] is None
    wait_for_terminal(manager, run_id)
