"""Low-barrier clarification: deferral or repeated rounds must never stall.

The interface promises "一句话就能开始，缺什么系统会再问你" — the system side
has to honor that by proceeding on a recorded assumption instead of re-asking
the same questions when the user answers 不知道 or the round budget runs out.
"""

from __future__ import annotations

import time

from opinion_search.domain.investigation.models import PlanProposal
from opinion_search.investigation import offline
from opinion_search.investigation.manager import (
    _DEFER_ANSWER,
    _MAX_PLANNER_CLARIFY_ROUNDS,
    Manager,
)


def _ambiguous_clarification(manager: Manager) -> dict:
    snapshot = manager.create({"mode": "offline", "question": "食堂"})
    run_id = snapshot["run_id"]
    deadline = time.monotonic() + 10
    while True:
        snapshot = manager.snapshot(run_id)
        if snapshot["status"] == "needs_clarification":
            return snapshot
        assert snapshot["status"] == "planning", snapshot["status"]
        assert time.monotonic() < deadline, "run never asked for clarification"
        time.sleep(0.05)


def test_defer_pattern_matches_only_pure_deferrals() -> None:
    for answer in ("不知道", "我不清楚", "你看着办", "随便", "按你的理解", "就按你说的", "没有更多信息"):
        assert _DEFER_ANSWER.match(answer), answer
    for answer in ("我知道，是某市第一中学", "某高校食堂出事了", "上周开始的"):
        assert not _DEFER_ANSWER.match(answer), answer


def test_deferred_clarification_proceeds_on_assumption(manager, wait_for_terminal) -> None:
    snapshot = _ambiguous_clarification(manager)
    run_id = snapshot["run_id"]
    assert snapshot["phase"] == "需要明确调查对象"

    clarified = manager.clarify(run_id, {"answer": "不知道"})

    assert clarified["clarify_rounds"] == 1
    assert clarified["plan_hint"] == "proceed_on_assumption"
    final = wait_for_terminal(manager, run_id)
    assert final["status"] == "completed"
    # the interpretation the system picked stays visible in the report
    assert "最合理的理解" in final["report"]["scope_limitation"]


def test_second_round_forces_proceed_even_without_deferral(monkeypatch, manager, wait_for_terminal) -> None:
    calls = {"n": 0}
    real_plan = offline.offline_plan

    def scripted_plan(request):
        calls["n"] += 1
        if calls["n"] <= 2:
            return PlanProposal(subject=request.question, clarification=("请说明具体学校或地区。",))
        return real_plan(request)

    monkeypatch.setattr(offline, "offline_plan", scripted_plan)

    first = _ambiguous_clarification(manager)
    run_id = first["run_id"]

    answered = manager.clarify(run_id, {"answer": "某高校"})
    assert answered["clarify_rounds"] == 1
    assert answered["plan_hint"] is None
    # the scripted planner asks a second legitimate round
    deadline = time.monotonic() + 10
    second_round = manager.snapshot(run_id)
    while second_round["status"] != "needs_clarification":
        assert time.monotonic() < deadline, "planner never asked a second round"
        time.sleep(0.05)
        second_round = manager.snapshot(run_id)

    forced = manager.clarify(run_id, {"answer": "食堂饭菜"})
    assert forced["clarify_rounds"] == _MAX_PLANNER_CLARIFY_ROUNDS
    assert forced["plan_hint"] == "proceed_on_assumption"

    final = wait_for_terminal(manager, run_id)
    assert final["status"] == "completed"
    assert "最合理的理解" in final["report"]["scope_limitation"]
    assert "某高校" in final["request"]["clarification"]
