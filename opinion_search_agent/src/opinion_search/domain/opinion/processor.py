from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    Evidence,
    GapAssessment,
    Narrative,
    OpinionSearchDelta,
    OpinionSearchState,
    Source,
    StakeholderPosition,
    claim_status_for,
    stable_domain_id,
)
from opinion_search.runtime.completion import CompletionVerdict
from opinion_search.tools.capabilities.web import ReadResult, SearchResults
from opinion_search.tools.contracts import ToolError, ToolOutcome, ToolResult
from opinion_search.tools.url import InvalidPublicUrl, normalize_public_url


class ProcessorInvariantError(ValueError):
    """Raised when an observation conflicts with its accepted decision."""


class _ObservationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ToolObservation(_ObservationModel):
    action: Literal["search", "read"]
    outcome: ToolOutcome


class ReflectObservation(_ObservationModel):
    action: Literal["reflect"] = "reflect"
    assessment: str = Field(min_length=1)
    assessed_gap_ids: tuple[str, ...]


class FinishObservation(_ObservationModel):
    action: Literal["finish"] = "finish"
    completion_verdict: CompletionVerdict


OpinionObservation: TypeAlias = Annotated[
    ToolObservation | ReflectObservation | FinishObservation,
    Field(discriminator="action"),
]


class OpinionSearchObservationProcessor:
    def build_delta(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
        observation: OpinionObservation,
    ) -> OpinionSearchDelta:
        if decision.action != observation.action:
            raise ProcessorInvariantError(
                "observation action does not match accepted decision"
            )

        if isinstance(decision, SearchDecision):
            if not isinstance(observation, ToolObservation):
                raise ProcessorInvariantError("search requires a tool observation")
            return self._search_delta(
                state,
                decision,
                observation.outcome,
            )

        if isinstance(decision, ReadDecision):
            if not isinstance(observation, ToolObservation):
                raise ProcessorInvariantError("read requires a tool observation")
            return self._read_delta(state, decision, observation.outcome)

        if isinstance(decision, ReflectDecision):
            if not isinstance(observation, ReflectObservation):
                raise ProcessorInvariantError("reflect requires a reflect observation")
            if (
                observation.assessment != decision.assessment
                or observation.assessed_gap_ids
                != tuple(item.gap_id for item in decision.gap_assessments)
            ):
                raise ProcessorInvariantError(
                    "reflect observation does not match accepted decision"
                )
            return self._reflect_delta(state, decision)

        if not isinstance(observation, FinishObservation):
            raise ProcessorInvariantError("finish requires a finish observation")
        return OpinionSearchDelta()

    @staticmethod
    def _search_delta(
        state: OpinionSearchState,
        decision: SearchDecision,
        outcome: ToolOutcome,
    ) -> OpinionSearchDelta:
        OpinionSearchObservationProcessor._require_tool_name(
            outcome,
            "search.web",
        )
        attempted_query = ((decision.target_gap_id, decision.query),)
        if isinstance(outcome, ToolError):
            return OpinionSearchDelta(record_query_by_gap=attempted_query)

        results = SearchResults.model_validate(outcome.payload)
        if results.query != decision.query:
            raise ProcessorInvariantError(
                "search result query does not match accepted decision"
            )
        candidates: list[CandidateSource] = []
        for item in results.items:
            try:
                normalized_url = normalize_public_url(item.url)
            except InvalidPublicUrl:
                continue
            if not _url_matches_domain_scope(
                normalized_url,
                include_domains=state.request.include_domains,
                exclude_domains=state.request.exclude_domains,
            ):
                continue
            candidates.append(
                CandidateSource(
                    source_id=normalized_url,
                    url=normalized_url,
                    title=item.title,
                    snippet=item.snippet,
                    discovered_for_gap_ids=(decision.target_gap_id,),
                )
            )
        return OpinionSearchDelta(
            add_candidates=tuple(candidates),
            record_query_by_gap=attempted_query,
        )

    @staticmethod
    def _read_delta(
        state: OpinionSearchState,
        decision: ReadDecision,
        outcome: ToolOutcome,
    ) -> OpinionSearchDelta:
        OpinionSearchObservationProcessor._require_tool_name(
            outcome,
            "read.web",
        )
        attempted_source = ((decision.target_gap_id, decision.candidate_source_id),)
        if isinstance(outcome, ToolError):
            return OpinionSearchDelta(record_source_attempt_by_gap=attempted_source)

        if decision.candidate_source_id not in state.candidate_source_ids:
            raise ProcessorInvariantError("read targets an unknown candidate")
        result = ReadResult.model_validate(outcome.payload)
        if result.url != decision.candidate_source_id:
            raise ProcessorInvariantError(
                "read result does not match requested candidate"
            )

        gap = next(item for item in state.gaps if item.gap_id == decision.target_gap_id)
        excerpts = _select_evidence_excerpts(
            result.content,
            focus=f"{decision.focus} {gap.question}",
        )
        source = Source(
            source_id=decision.candidate_source_id,
            url=result.url,
            final_url=result.final_url,
            title=result.title,
            source_kind=decision.source_kind,
            artifact_ref=(outcome.artifact_refs[0] if outcome.artifact_refs else None),
        )
        evidence = tuple(
            Evidence(
                evidence_id=stable_domain_id(
                    "evidence",
                    decision.candidate_source_id,
                    decision.target_gap_id,
                    excerpt.text,
                ),
                source_id=decision.candidate_source_id,
                acquired_for_gap_id=decision.target_gap_id,
                excerpt=excerpt.text,
                locator=(
                    f"Reader normalized block {excerpt.block_index}, chars "
                    f"{excerpt.char_start}-{excerpt.char_end}; focus: "
                    f"{decision.focus}."
                ),
            )
            for excerpt in excerpts
        )
        return OpinionSearchDelta(
            add_sources=(source,),
            add_evidence=evidence,
            record_source_attempt_by_gap=attempted_source,
        )

    @staticmethod
    def _reflect_delta(
        state: OpinionSearchState,
        decision: ReflectDecision,
    ) -> OpinionSearchDelta:
        known_evidence_ids = {item.evidence_id for item in state.evidence}
        claims: list[Claim] = []
        for proposal in decision.claim_proposals:
            linked = set(proposal.supporting_evidence_ids) | set(
                proposal.contradicting_evidence_ids
            )
            if not linked.issubset(known_evidence_ids):
                raise ProcessorInvariantError(
                    "claim proposal references unknown evidence"
                )
            claims.append(
                Claim(
                    claim_id=stable_domain_id("claim", proposal.text),
                    text=proposal.text,
                    kind=proposal.kind,
                    supporting_evidence_ids=proposal.supporting_evidence_ids,
                    contradicting_evidence_ids=(proposal.contradicting_evidence_ids),
                    status=claim_status_for(
                        proposal.supporting_evidence_ids,
                        proposal.contradicting_evidence_ids,
                    ),
                )
            )

        positions: list[StakeholderPosition] = []
        for proposal in decision.stakeholder_position_proposals:
            if not set(proposal.evidence_ids).issubset(known_evidence_ids):
                raise ProcessorInvariantError(
                    "stakeholder position references unknown evidence"
                )
            positions.append(
                StakeholderPosition(
                    position_id=stable_domain_id(
                        "position",
                        proposal.stakeholder,
                        proposal.statement,
                    ),
                    stakeholder=proposal.stakeholder,
                    statement=proposal.statement,
                    evidence_ids=proposal.evidence_ids,
                )
            )

        narratives = tuple(
            Narrative(
                narrative_id=stable_domain_id("narrative", proposal.summary),
                summary=proposal.summary,
                kind=proposal.kind,
                stakeholder_names=proposal.stakeholder_names,
                evidence_ids=proposal.evidence_ids,
            )
            for proposal in decision.narrative_proposals
        )
        assessments = tuple(
            GapAssessment(
                gap_id=proposal.gap_id,
                outcome=proposal.outcome,
                evidence_ids=proposal.evidence_ids,
                rationale=proposal.rationale,
            )
            for proposal in decision.gap_assessments
        )

        return OpinionSearchDelta(
            upsert_claims=tuple(claims),
            add_stakeholder_positions=tuple(positions),
            upsert_narratives=narratives,
            gap_assessments=assessments,
            append_reflections=(decision.assessment,),
            set_current_focus=decision.next_focus,
        )

    @staticmethod
    def _require_tool_name(
        outcome: ToolResult | ToolError,
        expected: str,
    ) -> None:
        if outcome.tool_name != expected:
            raise ProcessorInvariantError(
                "tool name does not match accepted decision: "
                f"expected={expected}, actual={outcome.tool_name}"
            )


class OpinionSearchCompletionEvaluator:
    def evaluate(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
        observation: OpinionObservation,
    ) -> CompletionVerdict | None:
        if not isinstance(decision, FinishDecision):
            return None
        if not isinstance(observation, FinishObservation):
            raise ProcessorInvariantError("finish decision has no finish observation")
        return observation.completion_verdict


def _select_evidence_excerpts(
    content: str,
    *,
    focus: str,
    block_limit: int = 1_200,
    max_blocks: int = 8,
) -> tuple[_EvidenceExcerpt, ...]:
    raw_blocks = re.split(r"\n\s*\n", content)
    blocks: list[_EvidenceExcerpt] = []
    for block_index, raw_block in enumerate(raw_blocks, start=1):
        normalized = " ".join(raw_block.split())
        char_start = 0
        while normalized:
            text = normalized[:block_limit]
            blocks.append(
                _EvidenceExcerpt(
                    text=text,
                    block_index=block_index,
                    char_start=char_start,
                    char_end=char_start + len(text),
                )
            )
            normalized = normalized[block_limit:]
            char_start += len(text)
    if not blocks:
        raise ProcessorInvariantError("reader content produced no evidence block")

    focus_terms = {
        token.casefold()
        for token in re.findall(
            r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}",
            focus,
        )
    }
    ranked = sorted(
        range(len(blocks)),
        key=lambda index: (
            -sum(term in blocks[index].text.casefold() for term in focus_terms),
            index,
        ),
    )[:max_blocks]
    return tuple(blocks[index] for index in sorted(ranked))


@dataclass(frozen=True)
class _EvidenceExcerpt:
    text: str
    block_index: int
    char_start: int
    char_end: int


def _url_matches_domain_scope(
    url: str,
    *,
    include_domains: tuple[str, ...],
    exclude_domains: tuple[str, ...],
) -> bool:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    if any(_host_matches(host, domain) for domain in exclude_domains):
        return False
    if include_domains and not any(
        _host_matches(host, domain) for domain in include_domains
    ):
        return False
    return True


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")
