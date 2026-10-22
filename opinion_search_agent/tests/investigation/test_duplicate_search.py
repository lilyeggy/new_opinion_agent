"""A repeated search is rejected, but the run must survive the rejection.

Repeating a query is still refused: allowing it lets a stubborn model burn the
step budget on duplicates. What changed is that one rejection no longer decides
the run - the loop repairs or retries, and the budget is what stops it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opinion_search.domain.investigation.engine import Validator
from opinion_search.domain.investigation.models import (
    SearchAttempt, SearchDecision, State,
)

RUN = (
    Path(__file__).resolve().parents[2]
    / "artifacts/live-quality-20261018/live-runs/investigations/runs/166742aa691b4e79acc5db5c9a47793b/run.json"
)


def _state() -> State:
    return State.model_validate(json.loads(RUN.read_text())["state"]["domain_state"])


def test_a_repeated_query_is_rejected():
    state = _state()
    issue_id = state.issues[0].issue_id
    # Clear the finding backlog: a review requirement would be checked first and
    # this test is about the repeated query.
    state = state.model_copy(update={"findings": (), "reviews": (), "sources": (), "evidence": (), "searches": (SearchAttempt(
        issue_id=issue_id, query="罗永浩 野人先生", purpose="original", page=0,
        outcome="candidates", count=3),)})

    with pytest.raises(ValueError, match="already attempted"):
        Validator().validate(state, SearchDecision(
            issue_id=issue_id, query="罗永浩 野人先生", page=0, purpose="original"))
