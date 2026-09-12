"""Read-decision validation: normalization, feedback quality, recoverability.

The live run 73e84650… recorded five `read requires an allowed discovered
candidate` failures that cost a decision attempt each; these tests pin the
repaired contract (normalization + actionable feedback).
"""

from __future__ import annotations

import pytest

from opinion_search.domain.investigation.engine import Validator
from opinion_search.domain.investigation.models import (
    InvestigationRequest, Issue, ReadDecision, State, utcnow,
)


def _state(read_attempts: tuple[str, ...] = ()) -> State:
    issues = tuple(Issue(issue_id=f"issue-{i}", question=f"问题{i}", status="open") for i in range(3))
    return State(request=InvestigationRequest(question="某市公交夜班车调整的争议"), subject="夜班调整",
        cutoff=utcnow(), issues=issues,
        candidates=({"url": "https://a.example/1", "title": "公告", "issue_id": "issue-0"},
                    {"url": "https://b.example/2", "title": "报道", "issue_id": "issue-1"}),
        read_attempts=read_attempts)


def test_read_accepts_a_reformatted_known_candidate_url() -> None:
    state = _state()
    # same page, reformatted by the model (trailing slash): normalization must
    # match it against the candidate instead of burning a decision attempt
    Validator().validate(state, ReadDecision(action="read", issue_id="issue-0",
        url="https://a.example/1/", focus="核对原文"))


def test_read_rejection_names_the_rule_and_points_at_legal_candidates() -> None:
    with pytest.raises(ValueError) as captured:
        Validator().validate(_state(), ReadDecision(action="read", issue_id="issue-0",
            url="https://invented.example/page", focus="读一个没见过的链接"))
    message = str(captured.value)
    assert "not a discovered candidate" in message
    assert "https://a.example/1" in message, "feedback must list a legal candidate"
    assert "https://b.example/2" in message


def test_read_rejection_without_candidates_says_to_search_first() -> None:
    state = _state().model_copy(update={"candidates": ()})
    with pytest.raises(ValueError) as captured:
        Validator().validate(state, ReadDecision(action="read", issue_id="issue-0",
            url="https://a.example/1", focus="没有任何候选"))
    assert "run search first" in str(captured.value)


def test_already_read_url_points_at_retrieve() -> None:
    with pytest.raises(ValueError) as captured:
        Validator().validate(_state(read_attempts=("https://a.example/1",)),
            ReadDecision(action="read", issue_id="issue-0", url="https://a.example/1", focus="重读"))
    assert "retrieve" in str(captured.value)
