from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.domain.opinion.state import (
    COUNTER_NARRATIVES_GAP_ID,
    DOMINANT_NARRATIVES_GAP_ID,
    FACTUAL_BASELINE_GAP_ID,
    STAKEHOLDER_POSITIONS_GAP_ID,
    ClaimKind,
    GapStatus,
    NarrativeKind,
    OpinionSearchState,
    SourceKind,
    stable_domain_id,
)
from opinion_search.runtime.errors import (
    DecisionValidationError,
    RuntimeFailureKind,
)


NonEmptyText = Annotated[str, Field(min_length=1)]


class _DecisionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class SearchDecision(_DecisionModel):
    action: Literal["search"]
    query: NonEmptyText = Field(
        description="A new public-Web query not already attempted for the gap."
    )
    target_gap_id: NonEmptyText = Field(
        description="The stable ID of one currently open investigation gap."
    )
    purpose: NonEmptyText = Field(
        description="Why this query can reduce the target gap."
    )


class ReadDecision(_DecisionModel):
    action: Literal["read"]
    candidate_source_id: NonEmptyText = Field(
        description="A discovered, unread candidate source ID from memory."
    )
    target_gap_id: NonEmptyText = Field(
        description="The open gap this source should help investigate."
    )
    focus: NonEmptyText = Field(
        description="Facts, statements, or contradictions to extract."
    )
    source_kind: SourceKind = Field(
        default=SourceKind.OTHER,
        description=(
            "An untrusted analytic label proposed by the model. Runtime "
            "completion never treats this label as verified source quality."
        ),
    )


class ClaimProposal(_DecisionModel):
    text: NonEmptyText = Field(
        description="One atomic claim, without merging fact and interpretation."
    )
    kind: ClaimKind
    supporting_evidence_ids: tuple[NonEmptyText, ...] = ()
    contradicting_evidence_ids: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "ClaimProposal":
        if not (self.supporting_evidence_ids or self.contradicting_evidence_ids):
            raise ValueError("claim proposal requires at least one evidence reference")
        if len(self.supporting_evidence_ids) != len(
            set(self.supporting_evidence_ids)
        ) or len(self.contradicting_evidence_ids) != len(
            set(self.contradicting_evidence_ids)
        ):
            raise ValueError("claim proposal evidence IDs must be unique")
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError(
                "claim proposal evidence cannot both support and contradict"
            )
        return self


class StakeholderPositionProposal(_DecisionModel):
    stakeholder: NonEmptyText
    statement: NonEmptyText
    evidence_ids: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "StakeholderPositionProposal":
        if not self.evidence_ids:
            raise ValueError("stakeholder position proposal requires evidence")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("position proposal evidence IDs must be unique")
        return self


class NarrativeProposal(_DecisionModel):
    summary: NonEmptyText = Field(
        description="One observed public framing, not a factual conclusion."
    )
    kind: NarrativeKind
    stakeholder_names: tuple[NonEmptyText, ...] = ()
    evidence_ids: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "NarrativeProposal":
        if not self.evidence_ids:
            raise ValueError("narrative proposal requires evidence")
        if len(self.stakeholder_names) != len(set(self.stakeholder_names)):
            raise ValueError("narrative stakeholder names must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("narrative proposal evidence IDs must be unique")
        return self


class GapAssessmentProposal(_DecisionModel):
    gap_id: NonEmptyText = Field(
        description="One currently open opinion-investigation dimension."
    )
    outcome: GapStatus = Field(
        description=(
            "Keep the dimension open, resolve it with the listed evidence, "
            "or block it when accessible public sources cannot answer it."
        )
    )
    evidence_ids: tuple[NonEmptyText, ...] = Field(
        default=(),
        description=(
            "Known Evidence IDs that semantically support this assessment. "
            "A resolved outcome requires at least one ID."
        ),
    )
    rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_outcome(self) -> "GapAssessmentProposal":
        if self.outcome is GapStatus.RESOLVED and not self.evidence_ids:
            raise ValueError("resolved gap assessment requires evidence")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("gap assessment evidence IDs must be unique")
        return self


class ReflectDecision(_DecisionModel):
    action: Literal["reflect"]
    assessment: NonEmptyText
    next_focus: NonEmptyText
    gap_assessments: tuple[GapAssessmentProposal, ...] = Field(
        description=(
            "Explicit semantic assessments for currently open opinion "
            "dimensions. Do not resolve a dimension merely because a source "
            "was acquired for it."
        )
    )
    claim_proposals: tuple[ClaimProposal, ...] = ()
    stakeholder_position_proposals: tuple[
        StakeholderPositionProposal,
        ...,
    ] = ()
    narrative_proposals: tuple[NarrativeProposal, ...] = ()

    @model_validator(mode="after")
    def validate_gap_outcomes(self) -> "ReflectDecision":
        if not self.gap_assessments:
            raise ValueError("reflect decision requires a gap assessment")
        gap_ids = tuple(item.gap_id for item in self.gap_assessments)
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("reflect gap assessment IDs must be unique")
        return self


class FinishDecision(_DecisionModel):
    action: Literal["finish"]
    answer_candidate: NonEmptyText
    resolved_gap_ids: tuple[NonEmptyText, ...] = Field(
        description="Exactly the resolved gap IDs currently visible in memory."
    )
    unresolved_gap_ids: tuple[NonEmptyText, ...] = Field(
        description="Exactly the still-open gap IDs currently visible in memory."
    )

    @model_validator(mode="after")
    def validate_gap_accounting(self) -> "FinishDecision":
        if len(self.resolved_gap_ids) != len(set(self.resolved_gap_ids)):
            raise ValueError("finish resolved gap IDs must be unique")
        if len(self.unresolved_gap_ids) != len(set(self.unresolved_gap_ids)):
            raise ValueError("finish unresolved gap IDs must be unique")
        if set(self.resolved_gap_ids) & set(self.unresolved_gap_ids):
            raise ValueError("finish gap outcomes must not overlap")
        return self


AgentDecision: TypeAlias = Annotated[
    SearchDecision | ReadDecision | ReflectDecision | FinishDecision,
    Field(discriminator="action"),
]


class OpinionSearchDecisionValidator:
    def validate(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
    ) -> None:
        if isinstance(decision, SearchDecision):
            gap = self._require_open_gap(state, decision.target_gap_id)
            if decision.query in gap.attempted_queries:
                raise DecisionValidationError(
                    "search decision repeats an attempted query",
                    kind=RuntimeFailureKind.REPEATED_ACTION,
                )
            return

        if isinstance(decision, ReadDecision):
            self._require_open_gap(state, decision.target_gap_id)
            if decision.candidate_source_id not in state.candidate_source_ids:
                raise DecisionValidationError(
                    "read decision targets an unknown candidate"
                )
            if decision.candidate_source_id in state.read_source_ids:
                raise DecisionValidationError(
                    "read decision repeats an already read source",
                    kind=RuntimeFailureKind.REPEATED_ACTION,
                )
            return

        if isinstance(decision, ReflectDecision):
            for assessment in decision.gap_assessments:
                self._require_open_gap(state, assessment.gap_id)
            known_evidence_ids = {item.evidence_id for item in state.evidence}
            assessment_evidence_ids = {
                evidence_id
                for assessment in decision.gap_assessments
                for evidence_id in assessment.evidence_ids
            }
            unknown_assessment_evidence = assessment_evidence_ids - known_evidence_ids
            if unknown_assessment_evidence:
                raise DecisionValidationError(
                    "gap assessments reference unknown evidence IDs: "
                    f"{sorted(unknown_assessment_evidence)}; "
                    "known_evidence_ids="
                    f"{sorted(known_evidence_ids)}"
                )
            existing_claims = {claim.claim_id: claim for claim in state.claims}
            proposed_claim_kinds: dict[str, ClaimKind] = {}
            for proposal in decision.claim_proposals:
                linked = set(proposal.supporting_evidence_ids) | set(
                    proposal.contradicting_evidence_ids
                )
                if not linked.issubset(known_evidence_ids):
                    raise DecisionValidationError(
                        "claim proposal references unknown evidence"
                    )
                claim_id = stable_domain_id("claim", proposal.text)
                current = existing_claims.get(claim_id)
                if current is not None and current.kind is not proposal.kind:
                    raise DecisionValidationError(
                        "claim proposal conflicts with an existing claim kind"
                    )
                prior_kind = proposed_claim_kinds.setdefault(claim_id, proposal.kind)
                if prior_kind is not proposal.kind:
                    raise DecisionValidationError(
                        "claim proposals conflict on a stable claim kind"
                    )
            for proposal in decision.stakeholder_position_proposals:
                if not set(proposal.evidence_ids).issubset(known_evidence_ids):
                    raise DecisionValidationError(
                        "stakeholder position references unknown evidence"
                    )
            existing_narratives = {
                narrative.narrative_id: narrative for narrative in state.narratives
            }
            proposed_narrative_kinds: dict[str, NarrativeKind] = {}
            for proposal in decision.narrative_proposals:
                unknown_narrative_evidence = (
                    set(proposal.evidence_ids) - known_evidence_ids
                )
                if unknown_narrative_evidence:
                    raise DecisionValidationError(
                        "narrative proposal references unknown evidence IDs: "
                        f"{sorted(unknown_narrative_evidence)}"
                    )
                narrative_id = stable_domain_id("narrative", proposal.summary)
                current = existing_narratives.get(narrative_id)
                if current is not None and current.kind is not proposal.kind:
                    raise DecisionValidationError(
                        "narrative proposal conflicts with an existing narrative kind"
                    )
                prior_kind = proposed_narrative_kinds.setdefault(
                    narrative_id,
                    proposal.kind,
                )
                if prior_kind is not proposal.kind:
                    raise DecisionValidationError(
                        "narrative proposals conflict on a stable narrative kind"
                    )
            self._validate_opinion_dimension_semantics(state, decision)
            return

        if set(decision.resolved_gap_ids) != set(state.resolved_gap_ids):
            raise DecisionValidationError(
                "finish decision resolved gaps do not match committed state"
            )
        if set(decision.unresolved_gap_ids) != set(state.open_gap_ids):
            raise DecisionValidationError(
                "finish decision unresolved gaps do not match committed state"
            )

    @staticmethod
    def _require_open_gap(state: OpinionSearchState, gap_id: str):
        for gap in state.gaps:
            if gap.gap_id == gap_id and gap_id in state.open_gap_ids:
                return gap
        raise DecisionValidationError(f"decision targets non-open gap {gap_id}")

    @staticmethod
    def _validate_opinion_dimension_semantics(
        state: OpinionSearchState,
        decision: ReflectDecision,
    ) -> None:
        fact_evidence_ids = {
            evidence_id
            for claim in state.claims
            if claim.kind is ClaimKind.FACT
            for evidence_id in claim.supporting_evidence_ids
        } | {
            evidence_id
            for proposal in decision.claim_proposals
            if proposal.kind is ClaimKind.FACT
            for evidence_id in proposal.supporting_evidence_ids
        }
        position_evidence_ids = {
            evidence_id
            for position in state.stakeholder_positions
            for evidence_id in position.evidence_ids
        } | {
            evidence_id
            for proposal in decision.stakeholder_position_proposals
            for evidence_id in proposal.evidence_ids
        }
        dominant_evidence_ids = {
            evidence_id
            for narrative in state.narratives
            if narrative.kind
            in {
                NarrativeKind.DOMINANT,
                NarrativeKind.EMERGING,
            }
            for evidence_id in narrative.evidence_ids
        } | {
            evidence_id
            for proposal in decision.narrative_proposals
            if proposal.kind
            in {
                NarrativeKind.DOMINANT,
                NarrativeKind.EMERGING,
            }
            for evidence_id in proposal.evidence_ids
        }
        counter_evidence_ids = {
            evidence_id
            for narrative in state.narratives
            if narrative.kind is NarrativeKind.COUNTER
            for evidence_id in narrative.evidence_ids
        } | {
            evidence_id
            for proposal in decision.narrative_proposals
            if proposal.kind is NarrativeKind.COUNTER
            for evidence_id in proposal.evidence_ids
        }
        semantic_evidence_by_gap = {
            FACTUAL_BASELINE_GAP_ID: fact_evidence_ids,
            STAKEHOLDER_POSITIONS_GAP_ID: position_evidence_ids,
            DOMINANT_NARRATIVES_GAP_ID: dominant_evidence_ids,
            COUNTER_NARRATIVES_GAP_ID: counter_evidence_ids,
        }
        missing: dict[str, str] = {}
        requirement_by_gap = {
            FACTUAL_BASELINE_GAP_ID: "fact claim",
            STAKEHOLDER_POSITIONS_GAP_ID: "stakeholder position",
            DOMINANT_NARRATIVES_GAP_ID: "dominant or emerging narrative",
            COUNTER_NARRATIVES_GAP_ID: "counter narrative",
        }
        for assessment in decision.gap_assessments:
            if assessment.outcome is not GapStatus.RESOLVED:
                continue
            semantic_ids = semantic_evidence_by_gap.get(assessment.gap_id)
            if semantic_ids is None:
                continue
            if not set(assessment.evidence_ids) & semantic_ids:
                missing[assessment.gap_id] = requirement_by_gap[assessment.gap_id]
        if missing:
            eligible = sorted(
                gap_id
                for gap_id, evidence_ids in semantic_evidence_by_gap.items()
                if evidence_ids
            )
            raise DecisionValidationError(
                "resolved opinion dimensions lack matching semantic records: "
                f"{missing}; eligible_resolved_gap_ids={eligible}"
            )
