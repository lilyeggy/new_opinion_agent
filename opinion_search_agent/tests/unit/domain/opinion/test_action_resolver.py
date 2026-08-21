from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.action_resolver import (
    OpinionSearchActionResolver,
)
from opinion_search.domain.opinion.actions import (
    FinishAction,
    ReflectAction,
    ToolAction,
)
from opinion_search.domain.opinion.decisions import (
    FinishDecision,
    GapAssessmentProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Evidence,
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    Source,
)
from opinion_search.models.fake import MinimalOpinionCompletionPolicy
from opinion_search.runtime.completion import CompletionDisposition


def _state(*, resolved: bool = False) -> OpinionSearchState:
    url = "https://example.com/primary"
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Find the primary account.",
                status=(GapStatus.RESOLVED if resolved else GapStatus.OPEN),
                evidence_ids=("evidence-primary",) if resolved else (),
                resolution_note=("The source was read." if resolved else None),
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="Primary",
                snippet="Primary account.",
                discovered_for_gap_ids=("gap-primary",),
            ),
        ),
        sources=(
            (Source(source_id=url, url=url, title="Primary"),) if resolved else ()
        ),
        evidence=(
            (
                Evidence(
                    evidence_id="evidence-primary",
                    source_id=url,
                    acquired_for_gap_id="gap-primary",
                    excerpt="Primary evidence.",
                    locator="Fixture.",
                ),
            )
            if resolved
            else ()
        ),
    )


def _resolver() -> OpinionSearchActionResolver:
    return OpinionSearchActionResolver(MinimalOpinionCompletionPolicy())


def test_resolver_maps_search_decision_to_stable_tool_action() -> None:
    action = _resolver().resolve(
        _state(),
        SearchDecision(
            action="search",
            query="official announcement",
            target_gap_id="gap-primary",
            purpose="Find the primary source.",
        ),
    )

    assert isinstance(action, ToolAction)
    assert action.decision_action == "search"
    assert action.tool_name == "search.web"
    assert action.arguments == {
        "query": "official announcement",
        "max_results": 5,
    }


def test_resolver_maps_candidate_url_to_reader_tool_action() -> None:
    action = _resolver().resolve(
        _state(),
        ReadDecision(
            action="read",
            candidate_source_id="https://example.com/primary",
            target_gap_id="gap-primary",
            focus="Read the event facts.",
        ),
    )

    assert isinstance(action, ToolAction)
    assert action.decision_action == "read"
    assert action.tool_name == "read.web"
    assert action.arguments == {"url": "https://example.com/primary"}


def test_resolver_keeps_reflect_as_typed_internal_action() -> None:
    action = _resolver().resolve(
        _state(),
        ReflectDecision(
            action="reflect",
            assessment="The source resolves the gap.",
            next_focus="Prepare the answer.",
            gap_assessments=(
                GapAssessmentProposal(
                    gap_id="gap-primary",
                    outcome=GapStatus.OPEN,
                    rationale="More interpretation is needed.",
                ),
            ),
        ),
    )

    assert isinstance(action, ReflectAction)
    assert action.assessment == "The source resolves the gap."
    assert action.assessed_gap_ids == ("gap-primary",)


def test_resolver_evaluates_finish_before_creating_internal_action() -> None:
    proposal = FinishDecision(
        action="finish",
        answer_candidate="Not ready.",
        resolved_gap_ids=(),
        unresolved_gap_ids=("gap-primary",),
    )

    action = _resolver().resolve(_state(), proposal)

    assert isinstance(action, FinishAction)
    assert (
        action.completion_verdict.disposition
        is CompletionDisposition.REJECT_AND_CONTINUE
    )


def test_resolver_accepts_finish_after_gap_and_source_are_complete() -> None:
    proposal = FinishDecision(
        action="finish",
        answer_candidate="Complete.",
        resolved_gap_ids=("gap-primary",),
        unresolved_gap_ids=(),
    )

    action = _resolver().resolve(_state(resolved=True), proposal)

    assert isinstance(action, FinishAction)
    assert (
        action.completion_verdict.disposition is CompletionDisposition.ACCEPT_COMPLETE
    )
