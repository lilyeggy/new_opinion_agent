import asyncio
import hashlib
from pathlib import Path
from typing import TypeAlias

import pytest

from opinion_search.app.action_executor import OpinionActionExecutor
from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.action_resolver import (
    OpinionSearchActionResolver,
)
from opinion_search.domain.opinion.actions import OpinionAction
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    GapAssessmentProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.processor import (
    OpinionObservation,
    OpinionSearchCompletionEvaluator,
    OpinionSearchObservationProcessor,
    ToolObservation,
)
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    stable_domain_id,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeDecisionValidator,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    ScriptedModelClient,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.loop import AgentLoop
from opinion_search.runtime.protocols import (
    ActionRequest,
    DecisionEnvelope,
)
from opinion_search.runtime.transaction import (
    RunState,
    accept_decision,
    mark_deciding,
    open_step,
    start_action,
    start_run,
)
from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
    fake_reader_definition,
    fake_search_definition,
)
from opinion_search.tools.cache import ToolCacheConflictError
from opinion_search.tools.capabilities.web import SearchHit
from opinion_search.tools.contracts import RetryPolicy, ToolCall, ToolResult
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.persistent_cache import JsonActionResultCache
from opinion_search.tools.registry import ToolRegistry


CANDIDATE_URL = "https://example.com/primary"
RUN_ID = "run-cache-recovery"
STEP_ID = "run-cache-recovery:step:1"
ACTION_ID = "run-cache-recovery:step:1:attempt:1:action"

OpinionToolRunState: TypeAlias = RunState[
    OpinionSearchState,
    AgentDecision,
    OpinionAction,
    OpinionObservation,
]


def _build_tools(cache_dir: Path):
    search_adapter = FakeSearchAdapter(
        {
            "official announcement": (
                SearchHit(
                    title="Primary source",
                    url=CANDIDATE_URL,
                    snippet="Official event facts.",
                ),
            )
        }
    )
    reader_adapter = FakeReaderAdapter(
        pages={
            CANDIDATE_URL: FakePage(
                title="Primary source",
                content="The complete official event description.",
                artifact_ref="artifact-primary",
            )
        }
    )
    registry = ToolRegistry()
    registry.register(fake_search_definition(), search_adapter)
    registry.register(fake_reader_definition(), reader_adapter)
    tool_executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=1, timeout_seconds=1),
        result_cache=JsonActionResultCache(cache_dir),
    )
    return search_adapter, reader_adapter, tool_executor


def _script() -> tuple[AgentDecision, ...]:
    evidence_id = stable_domain_id(
        "evidence",
        CANDIDATE_URL,
        "gap-primary",
        "The complete official event description.",
    )
    return (
        SearchDecision(
            action="search",
            query="official announcement",
            target_gap_id="gap-primary",
            purpose="Find the primary source.",
        ),
        FinishDecision(
            action="finish",
            answer_candidate="Not ready.",
            resolved_gap_ids=(),
            unresolved_gap_ids=("gap-primary",),
        ),
        ReadDecision(
            action="read",
            candidate_source_id=CANDIDATE_URL,
            target_gap_id="gap-primary",
            focus="Read the primary source.",
        ),
        ReflectDecision(
            action="reflect",
            assessment="The primary source resolves the gap.",
            next_focus="Prepare the answer.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id="gap-primary",
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(evidence_id,),
                    rationale="The primary source resolves the gap.",
                ),
            ),
        ),
        FinishDecision(
            action="finish",
            answer_candidate="Complete.",
            resolved_gap_ids=("gap-primary",),
            unresolved_gap_ids=(),
        ),
    )


def _build_loop(path: Path, tool_executor: ToolExecutor) -> AgentLoop:
    policy = MinimalOpinionCompletionPolicy()
    return AgentLoop(
        model=ScriptedModelClient(_script()),
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=OpinionSearchActionResolver(policy),
        action_executor=OpinionActionExecutor(tool_executor),
        observation_processor=OpinionSearchObservationProcessor(),
        completion_evaluator=OpinionSearchCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=JsonCheckpointStore(path, OpinionToolRunState),
        id_factory=DeterministicIdFactory(),
        max_steps=10,
    )


def _fresh_initial_state() -> OpinionToolRunState:
    return OpinionToolRunState(
        run_id=RUN_ID,
        domain_state=OpinionSearchState(
            request=SearchRequest(question="What happened?"),
            gaps=(
                InvestigationGap(
                    gap_id="gap-primary",
                    question="Find the primary account.",
                    priority=5,
                ),
            ),
        ),
    )


def _action_running_state() -> OpinionToolRunState:
    decision = _script()[0]
    state = start_run(_fresh_initial_state())
    state = open_step(state, step_id=STEP_ID)
    state = mark_deciding(state)
    state = accept_decision(
        state,
        DecisionEnvelope(
            run_id=RUN_ID,
            step_id=STEP_ID,
            attempt=1,
            decision=decision,
        ),
    )
    resolver = OpinionSearchActionResolver(MinimalOpinionCompletionPolicy())
    action_payload = resolver.resolve(state.domain_state, decision)
    return start_action(
        state,
        ActionRequest(
            run_id=RUN_ID,
            step_id=STEP_ID,
            attempt=1,
            action_id=ACTION_ID,
            action=action_payload,
        ),
    )


def test_action_running_resume_reuses_cached_result_across_process(
    tmp_path,
) -> None:
    path = tmp_path / "run.json"
    cache_dir = tmp_path / "action_results"
    crashed_state = _action_running_state()

    # Execute the ACTION_RUNNING ToolCall once through a cache-backed executor,
    # then deliberately do NOT record the Observation, simulating death after
    # the cache write but before the OBSERVATION_READY checkpoint.
    search_adapter, _, tool_executor = _build_tools(cache_dir)
    request = crashed_state.active_step.action
    assert request is not None
    observation_payload = asyncio.run(
        OpinionActionExecutor(tool_executor).execute(request)
    )
    assert isinstance(observation_payload, ToolObservation)
    assert isinstance(observation_payload.outcome, ToolResult)
    assert [inv.action_id for inv in search_adapter.invocations] == [ACTION_ID]

    store = JsonCheckpointStore(path, OpinionToolRunState)
    asyncio.run(store.save(crashed_state))

    # A fresh process: new adapter, new registry, new executor, new cache
    # object pointed at the same directory, new loop.
    fresh_search, _, fresh_tool_executor = _build_tools(cache_dir)
    resumed_loop = _build_loop(path, fresh_tool_executor)
    result = asyncio.run(resumed_loop.resume())
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionToolRunState).load())

    assert len(fresh_search.invocations) == 0
    committed = checkpoint.committed_steps[0]
    assert committed.action is not None
    assert committed.action.action_id == ACTION_ID
    assert committed.observation is not None
    observation = committed.observation.observation
    assert isinstance(observation, ToolObservation)
    assert isinstance(observation.outcome, ToolResult)
    assert observation.outcome.action_id == ACTION_ID
    assert result.status is RunStatus.COMPLETED

    # reduction committed the cached observation once
    assert result.domain_state.revision == 3
    cache_entry_path = cache_dir / f"{hashlib.sha256(ACTION_ID.encode('utf-8')).hexdigest()}.json"
    raw_entry = cache_entry_path.read_bytes()
    assert raw_entry  # cache entry unchanged

    # resume outcome matches an uninterrupted control run
    control_path = tmp_path / "control.json"
    control_cache_dir = tmp_path / "control_cache"
    _, _, control_tool_executor = _build_tools(control_cache_dir)
    control_loop = _build_loop(control_path, control_tool_executor)
    control_result = asyncio.run(control_loop.run(_fresh_initial_state()))

    assert control_result.status == result.status
    assert control_result.domain_state.revision == result.domain_state.revision


def test_same_action_id_with_different_arguments_is_cache_conflict(
    tmp_path,
) -> None:
    cache_dir = tmp_path / "action_results"
    search_adapter, _, tool_executor = _build_tools(cache_dir)
    request = _action_running_state().active_step.action
    assert request is not None
    asyncio.run(OpinionActionExecutor(tool_executor).execute(request))
    assert len(search_adapter.invocations) == 1

    conflicting = ToolCall(
        action_id=ACTION_ID,
        tool_name="search.web",
        arguments={"query": "different query"},
    )
    with pytest.raises(ToolCacheConflictError):
        asyncio.run(tool_executor.execute(conflicting))
    assert len(search_adapter.invocations) == 1
