"""A repeated search must not be able to kill the run.

Three rejections used to exhaust the decision budget and end a 41-step run as
partial, so an exact repeat is now allowed through (the reducer records it as a
duplicate) unless the same query already dominates the recent attempts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opinion_search.domain.investigation.engine import Validator
from opinion_search.domain.investigation.models import (
    InvestigationRequest, SearchAttempt, SearchDecision, State, utcnow,
)

RUN = (
    Path(__file__).resolve().parents[2]
    / "artifacts/live-quality-20261018/live-runs/investigations/runs/166742aa691b4e79acc5db5c9a47793b/run.json"
)


def _state() -> State:
    return State.model_validate(json.loads(RUN.read_text())["state"]["domain_state"])


def test_one_repeat_is_allowed_through():
    state = _state().model_copy(update={"searches": ()})
    decision = SearchDecision(issue_id=state.issues[0].issue_id, query="罗永浩 野人先生", page=0,
                              purpose="original")
    Validator().validate(state, decision)
    state = state.model_copy(update={"searches": (SearchAttempt(
        issue_id=decision.issue_id, query=decision.query, purpose="original", page=0,
        outcome="candidates", count=3),)})
    Validator().validate(state, decision)


def test_a_query_that_dominates_recent_attempts_is_rejected():
    state = _state()
    attempts = tuple(
        SearchAttempt(issue_id=state.issues[0].issue_id, query="同一个查询", purpose="original",
                      page=0, outcome="duplicate", count=0)
        for _ in range(2)
    )
    state = state.model_copy(update={"searches": attempts})
    with pytest.raises(ValueError, match="change the direction"):
        Validator().validate(state, SearchDecision(
            issue_id=state.issues[0].issue_id, query="同一个查询", page=0, purpose="original"))
