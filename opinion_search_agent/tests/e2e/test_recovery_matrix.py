import asyncio

import pytest

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    GapAssessmentProposal,
    NarrativeProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Evidence,
    GapStatus,
    InvestigationGap,
    Narrative,
    NarrativeKind,
    OpinionSearchState,
    Source,
    stable_domain_id,
)
from opinion_search.models.contracts import (
    ModelClientError,
    ModelError,
    ModelErrorKind,
)
from opinion_search.models.fake import (
    DeterministicIdFactory,
    FakeActionExecutor,
    FakeActionResolver,
    FakeCompletionEvaluator,
    FakeDecisionValidator,
    FakeObservationProcessor,
    MinimalContextCompiler,
    MinimalOpinionCompletionPolicy,
    OpinionRunState,
    default_script,
)
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.errors import (
    ContextOverflowError,
    RuntimeFailureKind,
)
from opinion_search.runtime.lifecycle import RunStatus, StepPhase
from opinion_search.runtime.loop import AgentLoop, CheckpointBoundary
from opinion_search.runtime.transaction import start_run


class RecoveringScriptModel:
    def __init__(
        self,
        decisions: tuple[AgentDecision, ...],
        first_error: ModelError | None = None,
    ) -> None:
        self._decisions = decisions
        self._first_error = first_error
        self.calls = 0

    async def decide(self, context) -> AgentDecision:
        self.calls += 1
        if self._first_error is not None:
            error = self._first_error
            self._first_error = None
            raise ModelClientError(error)
        return self._decisions[context.step_index - 1]


class OverflowCompiler:
    def compile(self, state):
        raise ContextOverflowError("Required context exceeds the input limit.")


def _initial_state() -> OpinionRunState:
    return OpinionRunState(
        run_id="run-recovery",
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


def _loop(
    path,
    model,
    *,
    compiler=None,
    max_steps: int = 10,
    resolver=None,
    observation_processor=None,
    reducer=None,
):
    return AgentLoop(
        model=model,
        context_compiler=compiler or MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=resolver or FakeActionResolver(
            MinimalOpinionCompletionPolicy()
        ),
        action_executor=FakeActionExecutor(),
        observation_processor=observation_processor or FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reducer or reduce_opinion_state,
        checkpoint_store=JsonCheckpointStore(path, OpinionRunState),
        id_factory=DeterministicIdFactory(),
        max_steps=max_steps,
        max_decision_attempts=2,
    )


def test_empty_model_response_retries_same_step_and_commits_attempt_two(
    tmp_path,
) -> None:
    model = RecoveringScriptModel(
        default_script(),
        ModelError(
            kind=ModelErrorKind.EMPTY_RESPONSE,
            message="The model returned an empty decision.",
        ),
    )
    path = tmp_path / "run.json"

    result = asyncio.run(_loop(path, model).run(_initial_state()))
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())

    assert result.status is RunStatus.COMPLETED
    assert model.calls == 6
    first_step = checkpoint.committed_steps[0]
    assert first_step.step_id == "run-recovery:step:1"
    assert first_step.attempt == 2
    assert first_step.failures[0].kind is (RuntimeFailureKind.MODEL_EMPTY_RESPONSE)
    assert first_step.action.action_id.endswith("attempt:2:action")


def test_authentication_failure_fails_before_any_action(tmp_path) -> None:
    model = RecoveringScriptModel(
        default_script(),
        ModelError(
            kind=ModelErrorKind.AUTHENTICATION,
            message="The model provider rejected authentication.",
        ),
    )

    result = asyncio.run(_loop(tmp_path / "run.json", model).run(_initial_state()))

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is RuntimeFailureKind.MODEL_AUTHENTICATION
    assert result.domain_state.revision == 0


def test_invalid_candidate_gets_one_same_step_repair_attempt(tmp_path) -> None:
    invalid = ReadDecision(
        action="read",
        candidate_source_id="https://example.com/missing",
        target_gap_id="gap-primary",
        focus="Read missing candidate.",
    )

    class RepairingModel:
        def __init__(self) -> None:
            self.calls = 0

        async def decide(self, context):
            self.calls += 1
            if self.calls == 1:
                return invalid
            return default_script()[0]

    model = RepairingModel()
    path = tmp_path / "run.json"

    result = asyncio.run(_loop(path, model, max_steps=1).run(_initial_state()))
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())

    assert result.status is RunStatus.PARTIAL
    assert model.calls == 2
    assert checkpoint.committed_steps[0].attempt == 2
    assert checkpoint.committed_steps[0].failures[0].kind is (
        RuntimeFailureKind.INVALID_DECISION
    )


def test_narrative_identity_conflict_retries_instead_of_failing_run(
    tmp_path,
) -> None:
    url = "https://example.com/report"
    summary = "The change is framed as incremental."
    initial = OpinionRunState(
        run_id="run-recovery",
        domain_state=OpinionSearchState(
            request=SearchRequest(question="How is the event framed?"),
            gaps=(
                InvestigationGap(
                    gap_id="gap-primary",
                    question="Map the framing.",
                    priority=5,
                ),
            ),
            candidates=(
                CandidateSource(
                    source_id=url,
                    url=url,
                    title="Report",
                    snippet="A public account.",
                    discovered_for_gap_ids=("gap-primary",),
                ),
            ),
            sources=(Source(source_id=url, url=url, title="Report"),),
            evidence=(
                Evidence(
                    evidence_id="evidence-known",
                    source_id=url,
                    acquired_for_gap_id="gap-primary",
                    excerpt="The change is described as incremental.",
                    locator="Paragraph 2.",
                ),
            ),
            narratives=(
                Narrative(
                    narrative_id=stable_domain_id("narrative", summary),
                    summary=summary,
                    kind=NarrativeKind.DOMINANT,
                    evidence_ids=("evidence-known",),
                ),
            ),
        ),
    )
    conflicting = ReflectDecision(
        action="reflect",
        assessment="Reclassify the frame.",
        next_focus="Continue.",
        gap_assessments=(
            GapAssessmentProposal(
                gap_id="gap-primary",
                outcome=GapStatus.OPEN,
                rationale="More evidence is needed.",
            ),
        ),
        narrative_proposals=(
            NarrativeProposal(
                summary=summary,
                kind=NarrativeKind.COUNTER,
                evidence_ids=("evidence-known",),
            ),
        ),
    )
    repair = SearchDecision(
        action="search",
        query="additional public framing",
        target_gap_id="gap-primary",
        purpose="Find more evidence before reclassification.",
    )

    class RepairingModel:
        def __init__(self) -> None:
            self.calls = 0

        async def decide(self, context):
            self.calls += 1
            return conflicting if self.calls == 1 else repair

    model = RepairingModel()
    path = tmp_path / "run.json"

    result = asyncio.run(_loop(path, model, max_steps=1).run(initial))
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())

    assert result.status is RunStatus.PARTIAL
    assert result.failure is None
    assert model.calls == 2
    assert checkpoint.committed_steps[0].attempt == 2
    assert checkpoint.committed_steps[0].failures[0].kind is (
        RuntimeFailureKind.INVALID_DECISION
    )


def test_context_overflow_stops_partial_without_calling_model(tmp_path) -> None:
    model = RecoveringScriptModel(default_script())

    result = asyncio.run(
        _loop(
            tmp_path / "run.json",
            model,
            compiler=OverflowCompiler(),
        ).run(_initial_state())
    )

    assert result.status is RunStatus.PARTIAL
    assert model.calls == 0
    assert "exceeds" in result.stop_reason


def test_repeated_query_stops_partial_without_second_tool_execution(
    tmp_path,
) -> None:
    repeated = SearchDecision(
        action="search",
        query="official announcement",
        target_gap_id="gap-primary",
        purpose="Repeat the same direction.",
    )
    model = RecoveringScriptModel((default_script()[0], repeated))

    result = asyncio.run(_loop(tmp_path / "run.json", model).run(_initial_state()))

    assert result.status is RunStatus.PARTIAL
    assert result.domain_state.gaps[0].attempted_queries == ("official announcement",)
    assert "repeats" in result.stop_reason


class RejectingActionResolver:
    def __init__(self, base, *, reject_first: int = 1) -> None:
        self._base = base
        self._reject_first = reject_first
        self.resolve_calls = 0

    def resolve(self, state, decision):
        self.resolve_calls += 1
        if self.resolve_calls <= self._reject_first:
            raise ValueError("ActionResolver rejected the decision for the test.")
        return self._base.resolve(state, decision)


def test_invalid_action_repairs_same_step_and_commits_attempt_two(
    tmp_path,
) -> None:
    model = RecoveringScriptModel(default_script())
    path = tmp_path / "run.json"
    executor = FakeActionExecutor()
    resolver = RejectingActionResolver(
        FakeActionResolver(MinimalOpinionCompletionPolicy())
    )
    loop = AgentLoop(
        model=model,
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=resolver,
        action_executor=executor,
        observation_processor=FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=JsonCheckpointStore(path, OpinionRunState),
        id_factory=DeterministicIdFactory(),
        max_steps=1,
        max_decision_attempts=2,
    )

    result = asyncio.run(loop.run(_initial_state()))
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())

    assert result.status is RunStatus.PARTIAL
    assert resolver.resolve_calls == 2
    first_step = checkpoint.committed_steps[0]
    assert first_step.attempt == 2
    assert first_step.failures[0].kind is RuntimeFailureKind.INVALID_ACTION
    assert sum(executor.execution_counts.values()) == 1
    assert not any(
        "attempt:1" in action_id for action_id in executor.execution_counts
    )


def test_invalid_action_exhausted_without_committed_step_fails_run(
    tmp_path,
) -> None:
    resolver = RejectingActionResolver(
        FakeActionResolver(MinimalOpinionCompletionPolicy()),
        reject_first=5,
    )

    result = asyncio.run(
        _loop(
            tmp_path / "run.json",
            RecoveringScriptModel(default_script()),
            max_steps=1,
            resolver=resolver,
        ).run(_initial_state())
    )

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is RuntimeFailureKind.INVALID_ACTION
    assert result.domain_state.revision == 0


class BrokenObservationProcessor:
    def build_delta(self, state, decision, observation):
        raise ValueError("processor cannot reduce this observation")


class BrokenReducer:
    def __call__(self, state, delta):
        raise ValueError("reducer invariant violated")


def test_processor_failure_is_terminal_failed(tmp_path) -> None:
    result = asyncio.run(
        _loop(
            tmp_path / "run.json",
            RecoveringScriptModel(default_script()),
            observation_processor=BrokenObservationProcessor(),
        ).run(_initial_state())
    )

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is RuntimeFailureKind.REDUCER_INVARIANT


def test_reducer_failure_is_terminal_failed(tmp_path) -> None:
    result = asyncio.run(
        _loop(
            tmp_path / "run.json",
            RecoveringScriptModel(default_script()),
            reducer=BrokenReducer(),
        ).run(_initial_state())
    )

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.kind is RuntimeFailureKind.REDUCER_INVARIANT


class CrashAtBoundary:
    def __init__(
        self,
        boundary: CheckpointBoundary,
        occurrence: int = 1,
    ) -> None:
        self._boundary = boundary
        self._occurrence = occurrence
        self._seen = 0

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state,
    ) -> None:
        if boundary is self._boundary:
            self._seen += 1
            if self._seen == self._occurrence:
                raise RuntimeError("injected boundary crash")


def _loop_with_executor(
    path,
    model,
    executor,
    *,
    max_steps: int = 10,
    hook=None,
):
    return AgentLoop(
        model=model,
        context_compiler=MinimalContextCompiler(),
        decision_validator=FakeDecisionValidator(),
        action_resolver=FakeActionResolver(MinimalOpinionCompletionPolicy()),
        action_executor=executor,
        observation_processor=FakeObservationProcessor(),
        completion_evaluator=FakeCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=JsonCheckpointStore(path, OpinionRunState),
        id_factory=DeterministicIdFactory(),
        max_steps=max_steps,
        max_decision_attempts=2,
        hook=hook,
    )


def test_created_run_start_invokes_no_model_or_tool(tmp_path) -> None:
    path = tmp_path / "run.json"
    model = RecoveringScriptModel(default_script())
    executor = FakeActionExecutor()
    loop = _loop_with_executor(
        path,
        model,
        executor,
        hook=CrashAtBoundary(CheckpointBoundary.RUN_STARTED),
    )

    with pytest.raises(RuntimeError):
        asyncio.run(loop.run(_initial_state()))

    assert model.calls == 0
    assert sum(executor.execution_counts.values()) == 0
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())
    assert checkpoint.status is RunStatus.RUNNING
    assert checkpoint.active_step is None


def test_running_without_active_step_opens_step_without_replay(
    tmp_path,
) -> None:
    path = tmp_path / "run.json"
    model = RecoveringScriptModel(default_script())
    executor = FakeActionExecutor()
    loop = _loop_with_executor(
        path,
        model,
        executor,
        hook=CrashAtBoundary(CheckpointBoundary.STEP_OPENED),
    )

    # RUNNING, no active step; opening the step must not replay any prior
    # action nor call the model.
    with pytest.raises(RuntimeError):
        asyncio.run(loop.run(start_run(_initial_state())))

    assert model.calls == 0
    assert sum(executor.execution_counts.values()) == 0
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())
    assert checkpoint.active_step is not None
    assert checkpoint.active_step.phase is StepPhase.OPENED
    assert checkpoint.next_step_index == 1


def test_reducing_resume_does_not_invoke_tool(tmp_path) -> None:
    path = tmp_path / "run.json"

    crashing = _loop_with_executor(
        path,
        RecoveringScriptModel(default_script()),
        FakeActionExecutor(),
        hook=CrashAtBoundary(CheckpointBoundary.REDUCING),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(crashing.run(_initial_state()))

    crashed = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.REDUCING
    action_id = crashed.active_step.action.action_id

    fresh_executor = FakeActionExecutor()
    fresh = _loop_with_executor(
        path,
        RecoveringScriptModel(default_script()),
        fresh_executor,
    )
    result = asyncio.run(fresh.resume())

    assert result.status is RunStatus.COMPLETED
    assert fresh_executor.execution_counts.get(action_id, 0) == 0


def test_terminal_resume_returns_without_any_component_invocation(
    tmp_path,
) -> None:
    path = tmp_path / "run.json"
    asyncio.run(
        _loop(path, RecoveringScriptModel(default_script())).run(_initial_state())
    )

    fresh_model = RecoveringScriptModel(default_script())
    fresh_executor = FakeActionExecutor()
    fresh = _loop_with_executor(path, fresh_model, fresh_executor)
    result = asyncio.run(fresh.resume())

    assert result.status is RunStatus.COMPLETED
    assert fresh_model.calls == 0
    assert sum(fresh_executor.execution_counts.values()) == 0


def test_decision_accepted_resume_does_not_recall_model(tmp_path) -> None:
    path = tmp_path / "run.json"

    crashing = _loop_with_executor(
        path,
        RecoveringScriptModel(default_script()),
        FakeActionExecutor(),
        hook=CrashAtBoundary(CheckpointBoundary.DECISION_ACCEPTED),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(crashing.run(_initial_state()))

    crashed = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())
    assert crashed.active_step is not None
    assert crashed.active_step.phase is StepPhase.DECISION_ACCEPTED
    step_id = crashed.active_step.step_id
    attempt = crashed.active_step.attempt

    fresh_model = RecoveringScriptModel(default_script())
    fresh_executor = FakeActionExecutor()
    fresh = _loop_with_executor(
        path,
        fresh_model,
        fresh_executor,
        max_steps=1,
    )
    result = asyncio.run(fresh.resume())

    assert result.status is not RunStatus.FAILED
    assert fresh_model.calls == 0
    checkpoint = asyncio.run(JsonCheckpointStore(path, OpinionRunState).load())
    committed = checkpoint.committed_steps[0]
    assert committed.step_id == step_id
    assert committed.attempt == attempt
    assert committed.action is not None
    assert committed.action.action_id.endswith(":attempt:1:action")
