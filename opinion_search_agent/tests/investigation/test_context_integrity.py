"""R01: review material and investigation state must not be silently dropped."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opinion_search.context.compactor import compact_context_sections
from opinion_search.context.models import (
    CompactionMode, ContextContentOrigin as Origin, HeuristicTokenEstimator, RequiredContextOverflow,
)
from opinion_search.domain.investigation.models import (
    Action, Evidence, Finding, InvestigationRequest, Issue, ReviewDecision, ReviewResult,
    SourceVersion, State, uid, utcnow,
)
from opinion_search.investigation.context import Compiler, section, structured_context
from opinion_search.investigation.service import Executor
from opinion_search.investigation.storage import Budget, Corpus
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.protocols import ActionRequest
from opinion_search.runtime.transaction import RunState
from opinion_search.tools.contracts import ToolError


def _issues() -> tuple[Issue, ...]:
    return tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("发生了什么", "争议是什么", "回应如何"))


def _evidence():
    source = SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                           title="公告", fetched_at=utcnow(), artifact_ref="artifact://sha256/" + "2" * 64,
                           content_hash="2" * 64)
    excerpt = "工作日末班提前至22时。"
    return source, Evidence(evidence_id="e1", version_id="v1", excerpt=excerpt, start=0, end=len(excerpt), locator="chars 0:10")


def test_structured_material_is_never_droppable():
    context = structured_context("instructions", ReviewResult, {"findings": [], "evidence": []})
    material = next(s for s in context.sections if s.section_id == "input.material")
    assert material.compaction is CompactionMode.NEVER


def test_protected_section_overflows_loudly_instead_of_disappearing():
    estimator = HeuristicTokenEstimator()
    protected = section("memory.questions", "Q" * 4000, Origin.MODEL, priority=100, protected=True)
    filler = tuple(section(f"cand.{i}", "x" * 4000, Origin.TOOL, priority=60) for i in range(50))

    result = compact_context_sections((protected, *filler), input_token_limit=5000, estimator=estimator)
    kept = {s.section_id for s in result.sections}
    assert "memory.questions" in kept
    assert "memory.questions" not in result.dropped_section_ids
    assert result.dropped_section_ids

    with pytest.raises(RequiredContextOverflow):
        compact_context_sections(
            (section("memory.questions", "Q" * 200_000, Origin.MODEL, protected=True),),
            input_token_limit=500,
            estimator=estimator,
        )


def test_compiler_keeps_questions_and_findings_under_pressure(tmp_path: Path):
    source, evidence = _evidence()
    issues = _issues()
    findings = tuple(
        Finding(issue_id=issues[0].issue_id, text=f"判断 {i} " + "细节" * 20, kind="interpretation",
                evidence_ids=("e1",), finding_id=uid("finding", str(i)))
        for i in range(4)
    )
    state = State(
        request=InvestigationRequest(question="公交夜班调整的争议"),
        subject="公交夜班调整", cutoff=utcnow(), required_questions=("争议是什么",),
        issues=(issues[0].model_copy(update={"origin_questions": ("争议是什么",)}), *issues[1:]),
        sources=(source,), evidence=(evidence,), findings=findings,
        candidates=tuple({"url": f"https://example.org/{i}", "title": "t", "snippet": "s"} for i in range(300)),
    )
    budget = Budget(tmp_path / "budget.json")
    compiler = Compiler(budget)
    run = SimpleNamespace(run_id="r", domain_state=state, next_step_index=3, committed_steps=(),
                          active_step=SimpleNamespace(step_id="s1", failures=()))

    context = compiler.compile(run)
    kept = {s.section_id for s in context.sections}
    assert "memory.questions" in kept
    assert "memory.findings" in kept
    assert "memory.questions" not in context.plan.dropped_section_ids
    assert "memory.findings" not in context.plan.dropped_section_ids


class _RefusingReviewer:
    async def decide(self, context):
        raise AssertionError("reviewer must not run without review material")


def test_review_context_overflow_degrades_to_unverified(tmp_path: Path):
    source, evidence = _evidence()
    issues = _issues()
    finding = Finding(issue_id=issues[0].issue_id, text="判断", kind="interpretation",
                      evidence_ids=("e1",), finding_id=uid("finding", "review"))
    state = State(request=InvestigationRequest(question="公交夜班调整的争议"), subject="公交夜班调整",
                  cutoff=utcnow(), issues=issues, sources=(source,), evidence=(evidence,), findings=(finding,))
    checkpoint = JsonCheckpointStore(tmp_path / "run.json", RunState, execution_profile="test-profile")
    asyncio.run(checkpoint.save(RunState(run_id="r", domain_state=state)))
    executor = Executor(None, checkpoint, Corpus(tmp_path / "case"), _RefusingReviewer(), "test-model")

    decision = ReviewDecision(finding_ids=(finding.finding_id,))
    payload = {"findings": [{"finding_id": finding.finding_id}], "evidence": [{"blob": "x" * 200_000}]}
    action = Action(decision=decision, review_context=json.dumps(payload))
    request = ActionRequest(run_id="r", step_id="s", attempt=1, action_id="a", action=action)
    observation = asyncio.run(executor.execute(request))

    assert isinstance(observation.outcome, ToolError)
    assert observation.reviews == ()
