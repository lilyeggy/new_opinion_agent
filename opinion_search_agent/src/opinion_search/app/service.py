from __future__ import annotations

from hashlib import sha256
from datetime import date
from pathlib import Path
from typing import TypeAlias

from pydantic import TypeAdapter

from opinion_search.app.action_executor import OpinionActionExecutor
from opinion_search.app.config import LiveConfig
from opinion_search.app.contracts import SearchRequest
from opinion_search.context.compiler import OpinionContextCompiler
from opinion_search.context.models import ContextBudget
from opinion_search.domain.opinion.action_resolver import (
    OpinionSearchActionResolver,
)
from opinion_search.domain.opinion.actions import OpinionAction
from opinion_search.domain.opinion.brief import SearchOutcome, build_search_outcome
from opinion_search.domain.opinion.completion import OpinionSearchCompletionPolicy
from opinion_search.domain.opinion.framing import build_task_frame
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    ClaimProposal,
    FinishDecision,
    GapAssessmentProposal,
    NarrativeProposal,
    OpinionSearchDecisionValidator,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
    StakeholderPositionProposal,
)
from opinion_search.domain.opinion.processor import (
    OpinionObservation,
    OpinionSearchCompletionEvaluator,
    OpinionSearchObservationProcessor,
)
from opinion_search.domain.opinion.reducer import reduce_opinion_state
from opinion_search.domain.opinion.state import (
    COUNTER_NARRATIVES_GAP_ID,
    DOMINANT_NARRATIVES_GAP_ID,
    FACTUAL_BASELINE_GAP_ID,
    STAKEHOLDER_POSITIONS_GAP_ID,
    ClaimKind,
    InvestigationGap,
    GapStatus,
    NarrativeKind,
    OpinionSearchState,
    SourceKind,
    stable_domain_id,
)
from opinion_search.models.fake import DeterministicIdFactory, ScriptedModelClient
from opinion_search.models.openai_compatible import OpenAICompatibleModelClient
from opinion_search.runtime.checkpoint import JsonCheckpointStore
from opinion_search.runtime.loop import AgentLoop, LoopHook
from opinion_search.runtime.transaction import RunState
from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
    fake_reader_definition,
    fake_search_definition,
)
from opinion_search.tools.adapters.brave_search import BraveSearchAdapter
from opinion_search.tools.adapters.jina_reader import JinaReaderAdapter
from opinion_search.tools.artifacts import LocalTextArtifactStore
from opinion_search.tools.capabilities.web import (
    SearchHit,
    reader_tool_definition,
    search_tool_definition,
)
from opinion_search.tools.cache import ToolResultCache
from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolAdapterError,
    ToolErrorKind,
)
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.http import HttpxTransport
from opinion_search.tools.persistent_cache import JsonActionResultCache
from opinion_search.tools.registry import ToolRegistry


OpinionRunState: TypeAlias = RunState[
    OpinionSearchState,
    AgentDecision,
    OpinionAction,
    OpinionObservation,
]

_OFFICIAL_URL = "https://example.org/official-announcement"
_REPORT_URL = "https://news.example.org/independent-report"
_ALTERNATE_URL = "https://analysis.example.org/correction"
_OFFICIAL_QUERY = "example event official announcement"
_REPORT_QUERY = "example event independent report"
_ALTERNATE_QUERY = "example event correction alternative account"
_OFFICIAL_CONTENT = (
    "The organization announced that the example event occurred on 20 August "
    "and attributed the disruption to a technical fault."
)
_REPORT_CONTENT = (
    "Independent reporting confirms the 20 August disruption and notes that "
    "the technical cause has not been independently verified."
)
_ALTERNATE_CONTENT = (
    "A later analysis agrees that disruption occurred but disputes whether the "
    "available records establish a single technical cause."
)
_CORE_CLAIM = "The example event caused a disruption on 20 August."
_CAUSE_CLAIM = "A technical fault was the established cause of the disruption."


class OpinionSearchService:
    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    async def investigate(
        self,
        request: SearchRequest,
        *,
        run_id: str,
    ) -> SearchOutcome:
        state = OpinionRunState(
            run_id=run_id,
            domain_state=OpinionSearchState(
                request=request,
                gaps=default_investigation_gaps(request),
                task_frame=build_task_frame(request, anchor_date=date.today()),
                current_focus=request.focus,
            ),
        )
        result = await self._loop.run(state)
        return build_search_outcome(
            result.domain_state,
            status=result.status,
            stop_reason=result.stop_reason,
        )

    async def resume(self) -> SearchOutcome:
        result = await self._loop.resume()
        return build_search_outcome(
            result.domain_state,
            status=result.status,
            stop_reason=result.stop_reason,
        )


def default_investigation_gaps(
    request: SearchRequest,
) -> tuple[InvestigationGap, ...]:
    topic = request.topic or request.question
    return (
        InvestigationGap(
            gap_id=FACTUAL_BASELINE_GAP_ID,
            question=f"What verifiable events and claims establish the factual baseline for {topic}?",
            priority=5,
        ),
        InvestigationGap(
            gap_id=STAKEHOLDER_POSITIONS_GAP_ID,
            question=f"Which stakeholders have publicly taken positions on {topic}, and what did they say?",
            priority=5,
        ),
        InvestigationGap(
            gap_id=DOMINANT_NARRATIVES_GAP_ID,
            question=(f"Which dominant or emerging public narratives frame {topic}?"),
            priority=4,
        ),
        InvestigationGap(
            gap_id=COUNTER_NARRATIVES_GAP_ID,
            question=(
                f"Which counter-narratives, criticisms, or material "
                f"disagreements challenge the main framing of {topic}?"
            ),
            priority=4,
        ),
    )


def build_offline_service(
    checkpoint_path: Path,
    *,
    hook: LoopHook | None = None,
) -> OpinionSearchService:
    registry = ToolRegistry()
    registry.register(
        fake_search_definition(),
        FakeSearchAdapter(
            {
                _OFFICIAL_QUERY: (
                    SearchHit(
                        title="Official announcement",
                        url=_OFFICIAL_URL,
                        snippet="Official account of the event.",
                    ),
                ),
                _REPORT_QUERY: (
                    SearchHit(
                        title="Independent report",
                        url=_REPORT_URL,
                        snippet="Independent reporting on the disruption.",
                    ),
                ),
                _ALTERNATE_QUERY: (
                    SearchHit(
                        title="Later correction analysis",
                        url=_ALTERNATE_URL,
                        snippet="Alternative account of the claimed cause.",
                    ),
                ),
            }
        ),
    )
    registry.register(
        fake_reader_definition(),
        FakeReaderAdapter(
            pages={
                _OFFICIAL_URL: FakePage(
                    title="Official announcement",
                    content=_OFFICIAL_CONTENT,
                    artifact_ref="artifact-official",
                ),
                _REPORT_URL: FakePage(
                    title="Independent report",
                    content=_REPORT_CONTENT,
                    artifact_ref="artifact-report",
                ),
                _ALTERNATE_URL: FakePage(
                    title="Later correction analysis",
                    content=_ALTERNATE_CONTENT,
                    artifact_ref="artifact-alternate",
                ),
            }
        ),
    )
    model = ScriptedModelClient(_offline_decisions())
    result_cache = JsonActionResultCache(
        checkpoint_path.parent / "action_results"
    )
    return OpinionSearchService(
        _build_loop(
            model=model,
            registry=registry,
            checkpoint_path=checkpoint_path,
            max_steps=12,
            max_decision_attempts=2,
            max_context_tokens=16_000,
            output_headroom_tokens=2_000,
            execution_profile=_execution_profile_id("opinion-search-offline-v2"),
            hook=hook,
            result_cache=result_cache,
        )
    )


class _FailingToolAdapter:
    """Probe adapter that always fails with a safe, retryable error."""

    def __init__(
        self,
        *,
        kind: ToolErrorKind = ToolErrorKind.SERVER_ERROR,
        message: str = "Provider unavailable.",
    ) -> None:
        self._kind = kind
        self._message = message
        self.invocations: list = []

    async def invoke(self, invocation):
        self.invocations.append(invocation)
        raise ToolAdapterError(self._kind, self._message)


def build_offline_fallback_service(
    checkpoint_path: Path,
    *,
    search_primary,
    search_secondary,
    reader_primary,
    reader_secondary,
    hook: LoopHook | None = None,
) -> OpinionSearchService:
    """Offline composition proving provider fallback for OpinionSearch.

    The primary providers fail with retryable errors; the secondary providers
    succeed with contract-equivalent results. Provider order is deterministic
    by registration. This path is for offline fallback acceptance only; the
    live default keeps one provider per capability.
    """
    registry = ToolRegistry()
    registry.register_provider(
        fake_search_definition(),
        "primary-search",
        search_primary,
    )
    registry.register_provider(
        fake_search_definition(),
        "secondary-search",
        search_secondary,
    )
    registry.register_provider(
        fake_reader_definition(),
        "primary-read",
        reader_primary,
    )
    registry.register_provider(
        fake_reader_definition(),
        "secondary-read",
        reader_secondary,
    )
    result_cache = JsonActionResultCache(
        checkpoint_path.parent / "action_results"
    )
    return OpinionSearchService(
        _build_loop(
            model=ScriptedModelClient(_offline_decisions()),
            registry=registry,
            checkpoint_path=checkpoint_path,
            max_steps=12,
            max_decision_attempts=2,
            max_context_tokens=16_000,
            output_headroom_tokens=2_000,
            execution_profile=_execution_profile_id(
                "opinion-search-offline-fallback-v1",
                "primary-search",
                "secondary-search",
                "primary-read",
                "secondary-read",
            ),
            hook=hook,
            result_cache=result_cache,
        )
    )


def build_live_service(
    checkpoint_path: Path,
    config: LiveConfig,
    *,
    hook: LoopHook | None = None,
) -> OpinionSearchService:
    transport = HttpxTransport()
    registry = ToolRegistry()
    registry.register(
        search_tool_definition(),
        BraveSearchAdapter(
            transport=transport,
            api_key=config.brave_search_api_key.get_secret_value(),
        ),
    )
    registry.register(
        reader_tool_definition(),
        JinaReaderAdapter(
            transport=transport,
            api_key=(
                config.jina_api_key.get_secret_value()
                if config.jina_api_key is not None
                else None
            ),
            artifact_store=LocalTextArtifactStore(checkpoint_path.parent / "artifacts"),
        ),
    )
    model = OpenAICompatibleModelClient(
        api_key=config.model_api_key.get_secret_value(),
        base_url=config.model_base_url,
        model=config.model_name,
        timeout_seconds=config.model_timeout_seconds,
        allow_insecure_loopback=config.allow_insecure_model_endpoint,
        extra_headers=config.model_extra_headers,
        max_transport_attempts=config.model_transport_attempts,
    )
    result_cache = JsonActionResultCache(
        checkpoint_path.parent / "action_results"
    )
    return OpinionSearchService(
        _build_loop(
            model=model,
            registry=registry,
            checkpoint_path=checkpoint_path,
            max_steps=config.max_steps,
            max_decision_attempts=config.max_decision_attempts,
            max_context_tokens=config.max_context_tokens,
            output_headroom_tokens=config.output_headroom_tokens,
            tool_timeout_seconds=config.tool_timeout_seconds,
            execution_profile=_execution_profile_id(
                "opinion-search-live-v5",
                config.model_base_url,
                config.model_name,
                "brave-search",
                "jina-reader",
                str(config.max_steps),
                str(config.max_decision_attempts),
                str(config.max_context_tokens),
                str(config.output_headroom_tokens),
                str(config.model_timeout_seconds),
                str(config.tool_timeout_seconds),
                str(config.allow_insecure_model_endpoint),
            ),
            hook=hook,
            result_cache=result_cache,
        )
    )


def _build_loop(
    *,
    model,
    registry: ToolRegistry,
    checkpoint_path: Path,
    max_steps: int,
    max_decision_attempts: int,
    max_context_tokens: int,
    output_headroom_tokens: int,
    execution_profile: str,
    tool_timeout_seconds: float = 5,
    hook: LoopHook | None = None,
    result_cache: ToolResultCache | None = None,
) -> AgentLoop:
    compiler = OpinionContextCompiler(
        budget=ContextBudget(
            max_context_tokens=max_context_tokens,
            output_headroom_tokens=output_headroom_tokens,
        ),
        recent_step_limit=3,
        tool_specs=registry.model_specs(),
        decision_schema=TypeAdapter(AgentDecision).json_schema(),
    )
    policy = OpinionSearchCompletionPolicy()
    return AgentLoop(
        model=model,
        context_compiler=compiler,
        decision_validator=OpinionSearchDecisionValidator(),
        action_resolver=OpinionSearchActionResolver(policy),
        action_executor=OpinionActionExecutor(
            ToolExecutor(
                registry,
                retry_policy=RetryPolicy(
                    max_attempts_per_provider=2,
                    timeout_seconds=tool_timeout_seconds,
                    backoff_seconds=0,
                ),
                result_cache=result_cache,
            )
        ),
        observation_processor=OpinionSearchObservationProcessor(),
        completion_evaluator=OpinionSearchCompletionEvaluator(),
        reducer=reduce_opinion_state,
        checkpoint_store=JsonCheckpointStore(
            checkpoint_path,
            OpinionRunState,
            execution_profile=execution_profile,
        ),
        id_factory=DeterministicIdFactory(),
        max_steps=max_steps,
        max_decision_attempts=max_decision_attempts,
        hook=hook,
    )


def _execution_profile_id(*parts: str) -> str:
    material = "\x1f".join(parts)
    return "profile-" + sha256(material.encode("utf-8")).hexdigest()[:16]


def _offline_decisions() -> tuple[AgentDecision, ...]:
    official_evidence = stable_domain_id(
        "evidence",
        _OFFICIAL_URL,
        FACTUAL_BASELINE_GAP_ID,
        _OFFICIAL_CONTENT,
    )
    report_evidence = stable_domain_id(
        "evidence",
        _REPORT_URL,
        DOMINANT_NARRATIVES_GAP_ID,
        _REPORT_CONTENT,
    )
    alternate_evidence = stable_domain_id(
        "evidence",
        _ALTERNATE_URL,
        COUNTER_NARRATIVES_GAP_ID,
        _ALTERNATE_CONTENT,
    )
    return (
        SearchDecision(
            action="search",
            query=_OFFICIAL_QUERY,
            target_gap_id=FACTUAL_BASELINE_GAP_ID,
            purpose="Find the original account.",
        ),
        ReadDecision(
            action="read",
            candidate_source_id=_OFFICIAL_URL,
            target_gap_id=FACTUAL_BASELINE_GAP_ID,
            focus="date, event and stated cause",
            source_kind=SourceKind.PRIMARY,
        ),
        ReflectDecision(
            action="reflect",
            assessment="The original account establishes the event statement.",
            next_focus="Find independent corroboration.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id=FACTUAL_BASELINE_GAP_ID,
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(official_evidence,),
                    rationale="The original account establishes the event baseline.",
                ),
                GapAssessmentProposal(
                    gap_id=STAKEHOLDER_POSITIONS_GAP_ID,
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(official_evidence,),
                    rationale="The organization states its causal position.",
                ),
            ),
            claim_proposals=(
                ClaimProposal(
                    text=_CORE_CLAIM,
                    kind=ClaimKind.FACT,
                    supporting_evidence_ids=(official_evidence,),
                ),
                ClaimProposal(
                    text=_CAUSE_CLAIM,
                    kind=ClaimKind.ATTRIBUTED_STATEMENT,
                    supporting_evidence_ids=(official_evidence,),
                ),
            ),
            stakeholder_position_proposals=(
                StakeholderPositionProposal(
                    stakeholder="The organization",
                    statement="It attributed the disruption to a technical fault.",
                    evidence_ids=(official_evidence,),
                ),
            ),
        ),
        SearchDecision(
            action="search",
            query=_REPORT_QUERY,
            target_gap_id=DOMINANT_NARRATIVES_GAP_ID,
            purpose="Find an independently reported public framing.",
        ),
        ReadDecision(
            action="read",
            candidate_source_id=_REPORT_URL,
            target_gap_id=DOMINANT_NARRATIVES_GAP_ID,
            focus="independent confirmation and caveats",
            source_kind=SourceKind.REPORTING,
        ),
        ReflectDecision(
            action="reflect",
            assessment="Independent reporting corroborates the event and date.",
            next_focus="Find a materially different account.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id=DOMINANT_NARRATIVES_GAP_ID,
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(report_evidence,),
                    rationale="Independent reporting supplies the dominant framing.",
                ),
            ),
            claim_proposals=(
                ClaimProposal(
                    text=_CORE_CLAIM,
                    kind=ClaimKind.FACT,
                    supporting_evidence_ids=(report_evidence,),
                ),
            ),
            narrative_proposals=(
                NarrativeProposal(
                    summary=(
                        "Independent coverage frames the disruption as real "
                        "while treating the proposed cause as unverified."
                    ),
                    kind=NarrativeKind.DOMINANT,
                    stakeholder_names=("Independent reporters",),
                    evidence_ids=(report_evidence,),
                ),
            ),
        ),
        SearchDecision(
            action="search",
            query=_ALTERNATE_QUERY,
            target_gap_id=COUNTER_NARRATIVES_GAP_ID,
            purpose="Find correction or alternative causal accounts.",
        ),
        ReadDecision(
            action="read",
            candidate_source_id=_ALTERNATE_URL,
            target_gap_id=COUNTER_NARRATIVES_GAP_ID,
            focus="correction and disagreement about cause",
            source_kind=SourceKind.ANALYSIS,
        ),
        ReflectDecision(
            action="reflect",
            assessment="The later account preserves a causal contradiction.",
            next_focus="Prepare an evidence-linked brief.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id=COUNTER_NARRATIVES_GAP_ID,
                    outcome=GapStatus.RESOLVED,
                    evidence_ids=(alternate_evidence,),
                    rationale="A later analysis supplies a material counter-frame.",
                ),
            ),
            claim_proposals=(
                ClaimProposal(
                    text=_CAUSE_CLAIM,
                    kind=ClaimKind.ATTRIBUTED_STATEMENT,
                    contradicting_evidence_ids=(alternate_evidence,),
                ),
            ),
            narrative_proposals=(
                NarrativeProposal(
                    summary=(
                        "The available record does not establish one technical "
                        "cause for the disruption."
                    ),
                    kind=NarrativeKind.COUNTER,
                    stakeholder_names=("Later analysts",),
                    evidence_ids=(alternate_evidence,),
                ),
            ),
        ),
        FinishDecision(
            action="finish",
            answer_candidate="The investigation has sufficient sourced coverage.",
            resolved_gap_ids=(
                FACTUAL_BASELINE_GAP_ID,
                STAKEHOLDER_POSITIONS_GAP_ID,
                DOMINANT_NARRATIVES_GAP_ID,
                COUNTER_NARRATIVES_GAP_ID,
            ),
            unresolved_gap_ids=(),
        ),
    )
