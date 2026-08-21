from opinion_search.domain.opinion.decisions import FinishDecision
from opinion_search.domain.opinion.provenance import build_provenance_index
from opinion_search.domain.opinion.state import (
    COUNTER_NARRATIVES_GAP_ID,
    DOMINANT_NARRATIVES_GAP_ID,
    FACTUAL_BASELINE_GAP_ID,
    STAKEHOLDER_POSITIONS_GAP_ID,
    ClaimKind,
    ClaimStatus,
    GapStatus,
    NarrativeKind,
    OpinionSearchState,
)
from opinion_search.runtime.completion import (
    CompletionDisposition,
    CompletionPolicy,
    CompletionVerdict,
)


class OpinionSearchCompletionPolicy(
    CompletionPolicy[OpinionSearchState, FinishDecision]
):
    def evaluate(
        self,
        state: OpinionSearchState,
        proposal: FinishDecision,
    ) -> CompletionVerdict:
        if set(proposal.resolved_gap_ids) != set(state.resolved_gap_ids):
            return CompletionVerdict(
                disposition=CompletionDisposition.REJECT_AND_CONTINUE,
                reason=(
                    "Finish rejected because the proposed resolved gaps do "
                    "not match committed state."
                ),
            )
        if set(proposal.unresolved_gap_ids) != set(state.open_gap_ids):
            return CompletionVerdict(
                disposition=CompletionDisposition.REJECT_AND_CONTINUE,
                reason=(
                    "Finish rejected because the proposed unresolved gaps do "
                    "not match committed state."
                ),
            )
        if state.open_gap_ids:
            return CompletionVerdict(
                disposition=CompletionDisposition.REJECT_AND_CONTINUE,
                reason=(
                    "Finish rejected because investigation gaps remain open: "
                    f"{list(state.open_gap_ids)}"
                ),
            )
        if not state.sources or not state.evidence:
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason="No source-backed evidence supports a complete outcome.",
            )
        if any(gap.status is GapStatus.BLOCKED for gap in state.gaps):
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason="The investigation stopped with explicitly blocked gaps.",
            )
        if not state.claims:
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason=(
                    "Sources were read, but no evidence-linked claim was committed."
                ),
            )

        gaps_by_id = {gap.gap_id: gap for gap in state.gaps}
        required_dimension_ids = {
            FACTUAL_BASELINE_GAP_ID,
            STAKEHOLDER_POSITIONS_GAP_ID,
            DOMINANT_NARRATIVES_GAP_ID,
            COUNTER_NARRATIVES_GAP_ID,
        }
        missing_dimensions = required_dimension_ids - set(gaps_by_id)
        if missing_dimensions:
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason=(
                    "The opinion investigation is missing required dimensions: "
                    f"{sorted(missing_dimensions)}."
                ),
            )
        baseline_ids = set(gaps_by_id[FACTUAL_BASELINE_GAP_ID].evidence_ids)
        if not any(
            claim.kind is ClaimKind.FACT
            and set(claim.supporting_evidence_ids) & baseline_ids
            for claim in state.claims
        ):
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason="The factual baseline lacks an evidence-linked fact claim.",
            )

        stakeholder_ids = set(gaps_by_id[STAKEHOLDER_POSITIONS_GAP_ID].evidence_ids)
        if not any(
            set(position.evidence_ids) & stakeholder_ids
            for position in state.stakeholder_positions
        ):
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason=("The stakeholder dimension lacks an evidence-linked position."),
            )

        narrative_ids = set(gaps_by_id[DOMINANT_NARRATIVES_GAP_ID].evidence_ids)
        if not any(
            narrative.kind in {NarrativeKind.DOMINANT, NarrativeKind.EMERGING}
            and set(narrative.evidence_ids) & narrative_ids
            for narrative in state.narratives
        ):
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason="The narrative dimension lacks an evidence-linked frame.",
            )

        counter_ids = set(gaps_by_id[COUNTER_NARRATIVES_GAP_ID].evidence_ids)
        if not any(
            narrative.kind is NarrativeKind.COUNTER
            and set(narrative.evidence_ids) & counter_ids
            for narrative in state.narratives
        ):
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason=(
                    "The counter-narrative dimension lacks an "
                    "evidence-linked counter frame."
                ),
            )

        provenance = build_provenance_index(state)
        semantically_linked_source_ids = {
            source_id
            for gap in state.gaps
            for source_id in provenance.source_ids_for_gap(gap.gap_id)
        }
        if len(semantically_linked_source_ids) < 2:
            return CompletionVerdict(
                disposition=CompletionDisposition.ACCEPT_PARTIAL,
                reason=(
                    "The opinion map relies on fewer than two distinct, "
                    "semantically linked source records."
                ),
            )
        for claim in state.claims:
            if claim.status is not ClaimStatus.CONTESTED:
                continue
            linked_ids = (
                claim.supporting_evidence_ids + claim.contradicting_evidence_ids
            )
            source_count = len(
                {
                    provenance.record(item_id).source_id for item_id in linked_ids
                }
            )
            if source_count < 2:
                return CompletionVerdict(
                    disposition=CompletionDisposition.ACCEPT_PARTIAL,
                    reason=(
                        "A contested claim is backed by fewer than two "
                        "distinct source records."
                    ),
                )

        return CompletionVerdict(
            disposition=CompletionDisposition.ACCEPT_COMPLETE,
            reason=(
                "The factual baseline, stakeholder positions, dominant "
                "narratives, and counter-narratives are resolved with "
                "source-backed provenance."
            ),
        )
