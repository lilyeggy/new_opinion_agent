"""A report must name the questions it did not close, not imply they were covered."""

from __future__ import annotations

import json
from pathlib import Path

from opinion_search.domain.investigation.models import State
from opinion_search.investigation.report import build_report, markdown

RUN = (
    Path(__file__).resolve().parents[2]
    / "artifacts/live-runs/investigations/runs/9b1bf7d631804cffbfc85a00086aef52/run.json"
)


def _state() -> State:
    return State.model_validate(json.loads(RUN.read_text())["state"]["domain_state"])


def _with_status(state: State, status: str) -> State:
    return state.model_copy(
        update={"issues": tuple(issue.model_copy(update={"status": status}) for issue in state.issues)}
    )


def test_open_questions_become_a_named_section() -> None:
    state = _with_status(_state(), "open")
    report = build_report(
        state,
        status="partial",
        reason="The maximum number of committed steps was reached.",
        case_id="sanjiu",
        run_id="test",
    )
    assert report["unresolved"]["issues"] == [
        {"issue_id": issue.issue_id, "question": issue.question} for issue in state.issues
    ]
    rendered = markdown(report).replace("\\", "")
    assert "## 未收口的问题" in rendered
    assert "这表示这一轮没有查到可以引用的材料" in rendered
    for issue in state.issues:
        assert issue.question in rendered


def test_closed_questions_leave_no_section() -> None:
    state = _with_status(_state(), "answered")
    report = build_report(
        state, status="partial", reason="done", case_id="sanjiu", run_id="test"
    )
    assert report["unresolved"] is None
    assert "## 未收口的问题" not in markdown(report)
