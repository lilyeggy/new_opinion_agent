from collections import Counter
from typing import Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict

from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    GapAssessmentProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
    OpinionSearchDecisionValidator,
)
from opinion_search.domain.opinion.processor import (
    FinishObservation,
    ToolObservation,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Evidence,
    GapAssessment,
    GapStatus,
    OpinionSearchDelta,
    OpinionSearchState,
    Source,
    stable_domain_id,
)
from opinion_search.runtime.completion import (
    CompletionDisposition,
    CompletionPolicy,
    CompletionVerdict,
)
from opinion_search.runtime.loop import RuntimeState
from opinion_search.runtime.protocols import ActionRequest
from opinion_search.runtime.transaction import RunState
from opinion_search.tools.contracts import ToolError


class FakeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    step_id: str
    step_index: int
    state_revision: int
    open_gap_ids: tuple[str, ...]
    candidate_source_ids: tuple[str, ...]
    read_source_ids: tuple[str, ...]
    last_completion_feedback: str | None = None
    last_tool_feedback: str | None = None


class DecisionContext(Protocol):
    step_index: int


class FakeAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: AgentDecision
    completion_verdict: CompletionVerdict | None = None


class FakeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["search", "read", "reflect", "finish"]
    add_candidates: tuple[CandidateSource, ...] = ()
    add_sources: tuple[Source, ...] = ()
    add_evidence: tuple[Evidence, ...] = ()
    gap_assessments: tuple[GapAssessment, ...] = ()
    append_reflections: tuple[str, ...] = ()
    completion_verdict: CompletionVerdict | None = None


OpinionRunState: TypeAlias = RunState[
    OpinionSearchState,
    AgentDecision,
    FakeAction,
    FakeObservation,
]


class MinimalContextCompiler:
    def compile(self, state: RuntimeState) -> FakeContext:
        if state.active_step is None:
            raise ValueError("context compilation requires an active step")

        domain_state = state.domain_state
        if not isinstance(domain_state, OpinionSearchState):
            raise TypeError("fake compiler requires OpinionSearchState")

        last_completion_feedback = None
        last_tool_feedback = None
        if state.committed_steps:
            last_observation = state.committed_steps[-1].observation
            if last_observation is not None:
                observation = last_observation.observation
                if isinstance(observation, FakeObservation):
                    verdict = observation.completion_verdict
                elif isinstance(observation, FinishObservation):
                    verdict = observation.completion_verdict
                else:
                    verdict = None

                if (
                    verdict is not None
                    and verdict.disposition is CompletionDisposition.REJECT_AND_CONTINUE
                ):
                    last_completion_feedback = verdict.reason

                if isinstance(observation, ToolObservation) and isinstance(
                    observation.outcome, ToolError
                ):
                    last_tool_feedback = observation.outcome.message

        return FakeContext(
            run_id=state.run_id,
            step_id=state.active_step.step_id,
            step_index=state.next_step_index,
            state_revision=domain_state.revision,
            open_gap_ids=domain_state.open_gap_ids,
            candidate_source_ids=domain_state.candidate_source_ids,
            read_source_ids=domain_state.read_source_ids,
            last_completion_feedback=last_completion_feedback,
            last_tool_feedback=last_tool_feedback,
        )


class ScriptedModelClient:
    def __init__(self, decisions: tuple[AgentDecision, ...]) -> None:
        self._decisions = decisions
        self.calls: list[DecisionContext] = []

    async def decide(self, context: DecisionContext) -> AgentDecision:
        self.calls.append(context)
        decision_index = context.step_index - 1
        try:
            return self._decisions[decision_index]
        except IndexError as exc:
            raise RuntimeError(
                f"script has no decision for step {context.step_index}"
            ) from exc


class FakeDecisionValidator(OpinionSearchDecisionValidator):
    pass


class MinimalOpinionCompletionPolicy(
    CompletionPolicy[OpinionSearchState, FinishDecision]
):
    def evaluate(
        self,
        state: OpinionSearchState,
        proposal: FinishDecision,
    ) -> CompletionVerdict:
        if state.open_gap_ids:
            return CompletionVerdict(
                disposition=CompletionDisposition.REJECT_AND_CONTINUE,
                reason=(
                    "Finish rejected because investigation gaps remain open: "
                    f"{list(state.open_gap_ids)}"
                ),
            )
        if not state.read_source_ids:
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason="No successfully read source supports completion.",
            )
        return CompletionVerdict(
            disposition=CompletionDisposition.ACCEPT_COMPLETE,
            reason="All minimal gaps are resolved with a read source.",
        )


class FakeActionResolver:
    def __init__(
        self,
        completion_policy: CompletionPolicy[
            OpinionSearchState,
            FinishDecision,
        ],
    ) -> None:
        self._completion_policy = completion_policy

    def resolve(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
    ) -> FakeAction:
        completion_verdict = None
        if isinstance(decision, FinishDecision):
            completion_verdict = self._completion_policy.evaluate(
                state,
                decision,
            )
        return FakeAction(
            decision=decision,
            completion_verdict=completion_verdict,
        )


class FakeActionExecutor:
    def __init__(self) -> None:
        self.execution_counts: Counter[str] = Counter()
        self._results: dict[str, FakeObservation] = {}

    async def execute(
        self,
        request: ActionRequest[FakeAction],
    ) -> FakeObservation:
        self.execution_counts[request.action_id] += 1
        if request.action_id in self._results:
            return self._results[request.action_id]

        decision = request.action.decision
        if isinstance(decision, SearchDecision):
            candidate_url = f"https://example.test/{decision.target_gap_id}"
            observation = FakeObservation(
                action="search",
                add_candidates=(
                    CandidateSource(
                        source_id=candidate_url,
                        url=candidate_url,
                        title="Deterministic fake source",
                        snippet="Deterministic fake search result.",
                        discovered_for_gap_ids=(decision.target_gap_id,),
                    ),
                ),
            )
        elif isinstance(decision, ReadDecision):
            excerpt = "Deterministic source-backed evidence."
            observation = FakeObservation(
                action="read",
                add_sources=(
                    Source(
                        source_id=decision.candidate_source_id,
                        url=decision.candidate_source_id,
                        title="Deterministic fake source",
                    ),
                ),
                add_evidence=(
                    Evidence(
                        evidence_id=stable_domain_id(
                            "evidence",
                            decision.candidate_source_id,
                            decision.target_gap_id,
                            excerpt,
                        ),
                        source_id=decision.candidate_source_id,
                        acquired_for_gap_id=decision.target_gap_id,
                        excerpt=excerpt,
                        locator="Deterministic fake reader excerpt.",
                    ),
                ),
            )
        elif isinstance(decision, ReflectDecision):
            observation = FakeObservation(
                action="reflect",
                gap_assessments=tuple(
                    GapAssessment(
                        gap_id=item.gap_id,
                        outcome=item.outcome,
                        evidence_ids=item.evidence_ids,
                        rationale=item.rationale,
                    )
                    for item in decision.gap_assessments
                ),
                append_reflections=(decision.assessment,),
            )
        else:
            observation = FakeObservation(
                action="finish",
                completion_verdict=request.action.completion_verdict,
            )

        self._results[request.action_id] = observation
        return observation


class FakeObservationProcessor:
    def build_delta(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
        observation: FakeObservation,
    ) -> OpinionSearchDelta:
        if decision.action != observation.action:
            raise ValueError("observation action does not match decision")
        record_query_by_gap = ()
        record_source_attempt_by_gap = ()
        if isinstance(decision, SearchDecision):
            record_query_by_gap = ((decision.target_gap_id, decision.query),)
        elif isinstance(decision, ReadDecision):
            record_source_attempt_by_gap = (
                (decision.target_gap_id, decision.candidate_source_id),
            )
        return OpinionSearchDelta(
            add_candidates=observation.add_candidates,
            add_sources=observation.add_sources,
            add_evidence=observation.add_evidence,
            record_query_by_gap=record_query_by_gap,
            record_source_attempt_by_gap=record_source_attempt_by_gap,
            gap_assessments=observation.gap_assessments,
            append_reflections=observation.append_reflections,
        )


class FakeCompletionEvaluator:
    def evaluate(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
        observation: FakeObservation,
    ) -> CompletionVerdict | None:
        if not isinstance(decision, FinishDecision):
            return None
        if observation.completion_verdict is None:
            raise ValueError("finish observation has no completion verdict")
        return observation.completion_verdict


class DeterministicIdFactory:
    def step_id(self, run_id: str, step_index: int) -> str:
        return f"{run_id}:step:{step_index}"

    def action_id(
        self,
        run_id: str,
        step_id: str,
        attempt: int,
    ) -> str:
        return f"{step_id}:attempt:{attempt}:action"


def default_script(gap_id: str = "gap-primary") -> tuple[AgentDecision, ...]:
    candidate_id = f"https://example.test/{gap_id}"
    evidence_id = stable_domain_id(
        "evidence",
        candidate_id,
        gap_id,
        "Deterministic source-backed evidence.",
    )
    return (
        SearchDecision(
            action="search",
            query="official announcement",
            target_gap_id=gap_id,
            purpose="Find a candidate primary source.",
        ),
        FinishDecision(
            action="finish",
            answer_candidate="The investigation is not ready.",
            resolved_gap_ids=(),
            unresolved_gap_ids=(gap_id,),
        ),
        ReadDecision(
            action="read",
            candidate_source_id=candidate_id,
            target_gap_id=gap_id,
            focus="Read the source for the core event facts.",
        ),
        ReflectDecision(
            action="reflect",
            assessment="The primary source resolves the minimal gap.",
            next_focus="Prepare the final answer.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id=gap_id,
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(evidence_id,),
                    rationale="The source resolves the minimal gap.",
                ),
            ),
        ),
        FinishDecision(
            action="finish",
            answer_candidate="The minimal investigation is complete.",
            resolved_gap_ids=(gap_id,),
            unresolved_gap_ids=(),
        ),
    )
