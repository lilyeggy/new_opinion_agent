"""R04: explicit user questions must survive planning and stay traceable."""

from __future__ import annotations

import pytest

from opinion_search.domain.investigation.models import (
    InvestigationRequest, Issue, QuestionProposal, PlanProposal, State, uid, utcnow,
)
from opinion_search.investigation.manager import _cover_required, required_questions


def test_extracts_only_explicit_questions():
    topic = InvestigationRequest(question="某市公交夜班车调整的争议与回应")
    assert required_questions(topic) == ()

    asked = InvestigationRequest(question="夜班车调整后工作日末班几点？周末班次保留了吗？")
    assert required_questions(asked) == ("夜班车调整后工作日末班几点", "周末班次保留了吗")


def test_enumerated_focus_lines_are_required():
    request = InvestigationRequest(question="公交夜班调整", focus="工作日替代出行怎么安排；\n票价是否变化")
    assert required_questions(request) == ("工作日替代出行怎么安排", "票价是否变化")


def test_uncovered_user_question_becomes_an_explicit_issue():
    required = ("工作日末班几点", "周末班次保留吗")
    planned = (Issue(issue_id=uid("issue", "发生了什么"), question="发生了什么调整？", origin_questions=("工作日末班几点",)),)
    issues = _cover_required(planned, required)
    covered = {text for issue in issues for text in issue.origin_questions}
    assert set(required) <= covered
    grouped = issues[-1]
    assert grouped.required is True
    assert "周末班次保留吗" in grouped.origin_questions


def test_state_rejects_a_dropped_user_question():
    base = dict(
        request=InvestigationRequest(question="公交夜班调整？票价变了吗？"),
        subject="公交夜班调整", cutoff=utcnow(), required_questions=("公交夜班调整", "票价变了吗"),
    )
    issues = tuple(
        Issue(issue_id=uid("issue", text), question=text, origin_questions=(text,))
        for text in ("公交夜班调整", "票价变了吗", "第三个问题")
    )
    State(**base, issues=issues)  # covered -> valid

    dropped = (
        Issue(issue_id=uid("issue", "公交夜班调整"), question="公交夜班调整", origin_questions=("公交夜班调整",)),
        Issue(issue_id=uid("issue", "发生了什么"), question="发生了什么调整？"),
        Issue(issue_id=uid("issue", "影响范围"), question="影响了哪些人？"),
    )
    with pytest.raises(ValueError):
        State(**base, issues=dropped)


def test_offline_run_preserves_user_questions(manager, run_offline):
    snapshot = run_offline(manager, {"question": "夜班车调整后工作日末班几点？周末班次保留了吗？"})
    report = snapshot["report"]
    assert report["required_questions"] == ["夜班车调整后工作日末班几点", "周末班次保留了吗"]
    covered = {text for issue in report["issues"] for text in issue["origin_questions"]}
    assert set(report["required_questions"]) <= covered
