from typing import TypeAlias

import pytest
from pydantic import TypeAdapter, ValidationError

from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    GapAssessmentProposal,
    NarrativeProposal,
    OpinionSearchDecisionValidator,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.state import (
    COUNTER_NARRATIVES_GAP_ID,
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
from opinion_search.runtime.errors import DecisionValidationError


DECISION_ADAPTER = TypeAdapter(AgentDecision)
JsonPayload: TypeAlias = dict[str, object]


def test_search_decision_parses_as_typed_variant() -> None:
    payload = {
        "action": "search",
        "query": "official product recall announcement",
        "target_gap_id": "gap-primary-source",
        "purpose": "Find the original announcement.",
    }

    decision = DECISION_ADAPTER.validate_python(payload)

    assert isinstance(decision, SearchDecision)
    assert decision.target_gap_id == "gap-primary-source"
    assert (
        DECISION_ADAPTER.dump_python(
            decision,
            mode="json",
            exclude_defaults=True,
        )
        == payload
    )


def test_read_decision_targets_discovered_candidate() -> None:
    payload = {
        "action": "read",
        "candidate_source_id": "candidate-official-001",
        "target_gap_id": "gap-primary-source",
        "focus": "announcement date and stated reason",
    }

    decision = DECISION_ADAPTER.validate_python(payload)

    assert isinstance(decision, ReadDecision)
    assert decision.candidate_source_id == "candidate-official-001"
    assert (
        DECISION_ADAPTER.dump_python(
            decision,
            mode="json",
            exclude_defaults=True,
        )
        == payload
    )


def test_reflect_decision_proposes_assessment_and_next_focus() -> None:
    payload = {
        "action": "reflect",
        "assessment": "The official statement is found but lacks independent confirmation.",
        "next_focus": "Find an independent account of the recall reason.",
        "gap_assessments": [
            {
                "gap_id": "gap-independent-confirmation",
                "outcome": "open",
                "rationale": "Independent confirmation is still missing.",
            }
        ],
    }

    decision = DECISION_ADAPTER.validate_python(payload)

    assert isinstance(decision, ReflectDecision)
    assert decision.gap_assessments[0].gap_id == ("gap-independent-confirmation")
    assert (
        DECISION_ADAPTER.dump_python(
            decision,
            mode="json",
            exclude_defaults=True,
        )
        == payload
    )


def test_finish_decision_is_only_a_completion_proposal() -> None:
    payload = {
        "action": "finish",
        "answer_candidate": "The available sources support the stated recall date.",
        "resolved_gap_ids": ["gap-primary-source"],
        "unresolved_gap_ids": ["gap-independent-confirmation"],
    }

    decision = DECISION_ADAPTER.validate_python(payload)

    assert isinstance(decision, FinishDecision)
    assert decision.resolved_gap_ids == ("gap-primary-source",)
    assert decision.unresolved_gap_ids == ("gap-independent-confirmation",)
    assert DECISION_ADAPTER.dump_python(decision, mode="json") == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "invent", "purpose": "Use an unknown action."},
        {
            "action": "search",
            "query": "   ",
            "target_gap_id": "gap-source",
            "purpose": "Find a source.",
        },
        {
            "action": "read",
            "candidate_source_id": "   ",
            "target_gap_id": "gap-source",
            "focus": "publication date",
        },
        {
            "action": "reflect",
            "assessment": "   ",
            "next_focus": "Find independent confirmation.",
            "gap_assessments": [],
        },
        {
            "action": "finish",
            "answer_candidate": "   ",
            "resolved_gap_ids": [],
            "unresolved_gap_ids": [],
        },
    ],
)
def test_decisions_reject_unknown_action_and_blank_required_text(
    payload: JsonPayload,
) -> None:
    with pytest.raises(ValidationError):
        DECISION_ADAPTER.validate_python(payload)


def test_action_specific_fields_cannot_leak_between_variants() -> None:
    payload = {
        "action": "search",
        "query": "official announcement",
        "target_gap_id": "gap-source",
        "purpose": "Find the primary source.",
        "candidate_source_id": "candidate-should-not-be-here",
    }

    with pytest.raises(ValidationError):
        DECISION_ADAPTER.validate_python(payload)


def test_provider_fields_cannot_enter_domain_decision() -> None:
    payload = {
        "action": "search",
        "query": "official announcement",
        "target_gap_id": "gap-source",
        "purpose": "Find the primary source.",
        "provider_model": "provider-private-model",
    }

    with pytest.raises(ValidationError):
        DECISION_ADAPTER.validate_python(payload)


def test_read_decision_accepts_no_raw_url() -> None:
    payload = {
        "action": "read",
        "candidate_source_id": "candidate-official-001",
        "target_gap_id": "gap-source",
        "focus": "publication date",
        "url": "https://example.org/unvalidated",
    }

    with pytest.raises(ValidationError):
        DECISION_ADAPTER.validate_python(payload)


def test_decision_is_immutable() -> None:
    decision = DECISION_ADAPTER.validate_python(
        {
            "action": "search",
            "query": "official announcement",
            "target_gap_id": "gap-source",
            "purpose": "Find the primary source.",
        }
    )

    with pytest.raises(ValidationError):
        decision.query = "different query"


def test_reflect_and_finish_reject_ambiguous_evidence_or_gap_outcomes() -> None:
    with pytest.raises(ValidationError, match="both support and contradict"):
        DECISION_ADAPTER.validate_python(
            {
                "action": "reflect",
                "assessment": "Evidence is ambiguous.",
                "next_focus": "Continue.",
                "gap_assessments": [
                    {
                        "gap_id": "gap-1",
                        "outcome": "open",
                        "rationale": "More evidence is needed.",
                    }
                ],
                "claim_proposals": [
                    {
                        "text": "A claim.",
                        "kind": "fact",
                        "supporting_evidence_ids": ["evidence-1"],
                        "contradicting_evidence_ids": ["evidence-1"],
                    }
                ],
            }
        )

    with pytest.raises(ValidationError, match="must not overlap"):
        DECISION_ADAPTER.validate_python(
            {
                "action": "finish",
                "answer_candidate": "Done.",
                "resolved_gap_ids": ["gap-1"],
                "unresolved_gap_ids": ["gap-1"],
            }
        )


def test_reflect_requires_opinion_semantics_to_resolve_a_dimension() -> None:
    url = "https://example.com/report"
    state = OpinionSearchState(
        request=SearchRequest(question="How is the event being framed?"),
        gaps=(
            InvestigationGap(
                gap_id=COUNTER_NARRATIVES_GAP_ID,
                question="Find material counter-narratives.",
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="Report",
                snippet="A critical account.",
                discovered_for_gap_ids=(COUNTER_NARRATIVES_GAP_ID,),
            ),
        ),
        sources=(Source(source_id=url, url=url, title="Report"),),
        evidence=(
            Evidence(
                evidence_id="evidence-counter",
                source_id=url,
                acquired_for_gap_id=COUNTER_NARRATIVES_GAP_ID,
                excerpt="Critics challenge the dominant framing.",
                locator="Paragraph 3.",
            ),
        ),
    )
    assessment = GapAssessmentProposal(
        gap_id=COUNTER_NARRATIVES_GAP_ID,
        outcome=GapStatus.RESOLVED,
        evidence_ids=("evidence-counter",),
        rationale="A counter-frame was found.",
    )
    unsupported = ReflectDecision(
        action="reflect",
        assessment="A critical source was read.",
        next_focus="Record the counter-frame.",
        gap_assessments=(assessment,),
    )

    with pytest.raises(
        DecisionValidationError,
        match="counter narrative",
    ) as captured:
        OpinionSearchDecisionValidator().validate(state, unsupported)

    assert COUNTER_NARRATIVES_GAP_ID in str(captured.value)
    assert "Critics challenge" not in str(captured.value)

    supported = unsupported.model_copy(
        update={
            "narrative_proposals": (
                NarrativeProposal(
                    summary="Critics frame the change as incremental.",
                    kind=NarrativeKind.COUNTER,
                    evidence_ids=("evidence-counter",),
                ),
            )
        }
    )

    OpinionSearchDecisionValidator().validate(state, supported)


def test_unknown_gap_evidence_feedback_lists_only_safe_known_ids() -> None:
    url = "https://example.com/report"
    state = OpinionSearchState(
        request=SearchRequest(question="How is the event being framed?"),
        gaps=(
            InvestigationGap(
                gap_id=COUNTER_NARRATIVES_GAP_ID,
                question="Find material counter-narratives.",
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="Report",
                snippet="A critical account.",
                discovered_for_gap_ids=(COUNTER_NARRATIVES_GAP_ID,),
            ),
        ),
        sources=(Source(source_id=url, url=url, title="Report"),),
        evidence=(
            Evidence(
                evidence_id="evidence-known-hash",
                source_id=url,
                acquired_for_gap_id=COUNTER_NARRATIVES_GAP_ID,
                excerpt="Sensitive untrusted excerpt text.",
                locator="Paragraph 3.",
            ),
        ),
    )
    decision = ReflectDecision(
        action="reflect",
        assessment="A counter-frame was found.",
        next_focus="Record the counter-frame.",
        gap_assessments=(
            GapAssessmentProposal(
                gap_id=COUNTER_NARRATIVES_GAP_ID,
                outcome=GapStatus.RESOLVED,
                evidence_ids=("evidence-invented-1",),
                rationale="A counter-frame was found.",
            ),
        ),
    )

    with pytest.raises(DecisionValidationError) as captured:
        OpinionSearchDecisionValidator().validate(state, decision)

    message = str(captured.value)
    assert "evidence-invented-1" in message
    assert "evidence-known-hash" in message
    assert "Sensitive untrusted excerpt text" not in message


def test_reflect_rejects_narrative_identity_conflict_before_reducer() -> None:
    url = "https://example.com/report"
    summary = "The change is framed as incremental."
    narrative_id = stable_domain_id("narrative", summary)
    state = OpinionSearchState(
        request=SearchRequest(question="How is the event being framed?"),
        gaps=(
            InvestigationGap(
                gap_id=COUNTER_NARRATIVES_GAP_ID,
                question="Find material counter-narratives.",
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="Report",
                snippet="A public account.",
                discovered_for_gap_ids=(COUNTER_NARRATIVES_GAP_ID,),
            ),
        ),
        sources=(Source(source_id=url, url=url, title="Report"),),
        evidence=(
            Evidence(
                evidence_id="evidence-known",
                source_id=url,
                acquired_for_gap_id=COUNTER_NARRATIVES_GAP_ID,
                excerpt="The change is described as incremental.",
                locator="Paragraph 2.",
            ),
        ),
        narratives=(
            Narrative(
                narrative_id=narrative_id,
                summary=summary,
                kind=NarrativeKind.DOMINANT,
                evidence_ids=("evidence-known",),
            ),
        ),
    )
    conflicting = ReflectDecision(
        action="reflect",
        assessment="Reclassify the existing frame.",
        next_focus="Continue the investigation.",
        gap_assessments=(
            GapAssessmentProposal(
                gap_id=COUNTER_NARRATIVES_GAP_ID,
                outcome=GapStatus.OPEN,
                rationale="More counter evidence is needed.",
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

    with pytest.raises(DecisionValidationError, match="existing narrative kind"):
        OpinionSearchDecisionValidator().validate(state, conflicting)
