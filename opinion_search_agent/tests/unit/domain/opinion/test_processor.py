from datetime import datetime, timezone

import pytest

from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.decisions import (
    ClaimProposal,
    FinishDecision,
    GapAssessmentProposal,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.processor import (
    FinishObservation,
    OpinionSearchCompletionEvaluator,
    OpinionSearchObservationProcessor,
    ProcessorInvariantError,
    ReflectObservation,
    ToolObservation,
)
from opinion_search.domain.opinion.state import (
    CandidateSource,
    ClaimKind,
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    SourceKind,
    stable_domain_id,
)
from opinion_search.runtime.completion import (
    CompletionDisposition,
    CompletionVerdict,
)
from opinion_search.tools.capabilities.web import ReadResult, SearchHit, SearchResults
from opinion_search.tools.contracts import ToolError, ToolErrorKind, ToolResult


URL = "https://example.com/primary"


def _state(*, with_candidate: bool = True) -> OpinionSearchState:
    candidates = (
        (
            CandidateSource(
                source_id=URL,
                url=URL,
                title="Primary",
                snippet="Official facts.",
                discovered_for_gap_ids=("gap-primary",),
            ),
        )
        if with_candidate
        else ()
    )
    return OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-primary",
                question="Find the primary account.",
                priority=5,
            ),
        ),
        candidates=candidates,
    )


def _search_decision() -> SearchDecision:
    return SearchDecision(
        action="search",
        query="official announcement",
        target_gap_id="gap-primary",
        purpose="Find a primary source.",
    )


def test_search_snippets_become_candidates_not_evidence() -> None:
    payload = SearchResults(
        query="official announcement",
        items=(SearchHit(title="Primary", url=URL, snippet="Official facts."),),
    ).model_dump(mode="json")
    observation = ToolObservation(
        action="search",
        outcome=ToolResult(
            action_id="action-1",
            tool_name="search.web",
            payload=payload,
            attempts=1,
        ),
    )

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(with_candidate=False),
        _search_decision(),
        observation,
    )

    assert tuple(item.source_id for item in delta.add_candidates) == (URL,)
    assert delta.add_evidence == ()
    assert delta.record_query_by_gap == (("gap-primary", "official announcement"),)


def test_search_enforces_domain_scope_before_candidates_enter_state() -> None:
    state = _state(with_candidate=False).model_copy(
        update={
            "request": SearchRequest(
                question="What happened?",
                include_domains=("example.com",),
                exclude_domains=("blocked.example.com",),
            )
        }
    )
    payload = SearchResults(
        query="official announcement",
        items=(
            SearchHit(
                title="Allowed subdomain",
                url="https://News.Example.COM:443/report#fragment",
                snippet="Allowed.",
            ),
            SearchHit(
                title="Explicitly blocked",
                url="https://blocked.example.com/report",
                snippet="Blocked.",
            ),
            SearchHit(
                title="Outside allowlist",
                url="https://outside.test/report",
                snippet="Outside.",
            ),
        ),
    ).model_dump(mode="json")

    delta = OpinionSearchObservationProcessor().build_delta(
        state,
        _search_decision(),
        ToolObservation(
            action="search",
            outcome=ToolResult(
                action_id="action-1",
                tool_name="search.web",
                payload=payload,
                attempts=1,
            ),
        ),
    )

    assert tuple(item.source_id for item in delta.add_candidates) == (
        "https://news.example.com/report",
    )


def test_search_failure_records_attempt_without_creating_facts() -> None:
    observation = ToolObservation(
        action="search",
        outcome=ToolError(
            action_id="action-1",
            tool_name="search.web",
            kind=ToolErrorKind.TIMEOUT,
            message="Tool execution timed out.",
            attempts=2,
        ),
    )

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(), _search_decision(), observation
    )

    assert delta.add_candidates == ()
    assert delta.add_evidence == ()
    assert delta.record_query_by_gap


def test_successful_read_creates_normalized_source_and_locatable_evidence() -> None:
    decision = ReadDecision(
        action="read",
        candidate_source_id=URL,
        target_gap_id="gap-primary",
        focus="event date",
        source_kind=SourceKind.PRIMARY,
    )
    result = ReadResult(
        url=URL,
        title="Primary",
        content="The organization says the event occurred on 20 August.",
        published_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        publication_time_status="reported",
    )
    observation = ToolObservation(
        action="read",
        outcome=ToolResult(
            action_id="action-2",
            tool_name="read.web",
            payload=result.model_dump(mode="json"),
            artifact_refs=("artifact-primary",),
            attempts=1,
        ),
    )

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(), decision, observation
    )

    assert delta.add_sources[0].source_kind is SourceKind.PRIMARY
    assert delta.add_sources[0].artifact_ref == "artifact-primary"
    assert delta.add_sources[0].published_at == result.published_at
    assert delta.add_sources[0].publication_status.value == "reported"
    assert delta.add_evidence[0].source_id == URL
    assert delta.add_evidence[0].acquired_for_gap_id == "gap-primary"
    assert "event date" in delta.add_evidence[0].locator
    assert "normalized block 1, chars 0-" in delta.add_evidence[0].locator


def test_evidence_locator_retains_original_selected_block_index() -> None:
    decision = ReadDecision(
        action="read",
        candidate_source_id=URL,
        target_gap_id="gap-primary",
        focus="distinctive correction",
    )
    content = (
        "Generic introduction.\n\n"
        "The distinctive correction changes the reported date.\n\n"
        "Generic closing."
    )
    result = ReadResult(url=URL, title="Primary", content=content)

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(),
        decision,
        ToolObservation(
            action="read",
            outcome=ToolResult(
                action_id="action-2",
                tool_name="read.web",
                payload=result.model_dump(mode="json"),
                attempts=1,
            ),
        ),
    )

    selected = next(
        item for item in delta.add_evidence if "distinctive correction" in item.excerpt
    )
    assert "normalized block 2, chars 0-" in selected.locator


def test_read_filters_promoted_navigation_and_bounds_evidence() -> None:
    decision = ReadDecision(
        action="read",
        candidate_source_id=URL,
        target_gap_id="gap-primary",
        focus="Codex quota user reactions",
    )
    content = (
        "推广：AnySearch 一站式搜索，立即注册并领取优惠。\n\n"
        "[首页](https://example.com) [产品](https://example.com/p) "
        "[下载](https://example.com/d) [登录](https://example.com/login)\n\n"
        "Codex users report that the latest quota change reduces interruptions "
        "during long coding sessions, although some users still want clearer limits.\n\n"
        "Several Codex users say quota visibility matters more than a larger "
        "headline allowance because unexpected throttling disrupts their work.\n\n"
        "Codex quota discussions also compare the experience across paid plans "
        "and ask for consistent documentation of the applicable limits.\n\n"
        "A fourth Codex quota paragraph should not exceed the per-source cap."
    )

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(),
        decision,
        ToolObservation(
            action="read",
            outcome=ToolResult(
                action_id="action-quality",
                tool_name="read.web",
                payload=ReadResult(
                    url=URL,
                    title="User reactions",
                    content=content,
                ).model_dump(mode="json"),
                artifact_refs=("artifact-full-page",),
                attempts=1,
            ),
        ),
    )

    assert len(delta.add_evidence) == 3
    assert all("AnySearch" not in item.excerpt for item in delta.add_evidence)
    assert all("立即注册" not in item.excerpt for item in delta.add_evidence)
    assert delta.add_sources[0].artifact_ref == "artifact-full-page"


def test_reflect_turns_evidence_links_into_claims_and_gap_updates() -> None:
    read_decision = ReadDecision(
        action="read",
        candidate_source_id=URL,
        target_gap_id="gap-primary",
        focus="event date",
    )
    read_result = ReadResult(
        url=URL,
        title="Primary",
        content="The event occurred on 20 August.",
    )
    read_delta = OpinionSearchObservationProcessor().build_delta(
        _state(),
        read_decision,
        ToolObservation(
            action="read",
            outcome=ToolResult(
                action_id="action-read",
                tool_name="read.web",
                payload=read_result.model_dump(mode="json"),
                attempts=1,
            ),
        ),
    )
    evidence = read_delta.add_evidence[0]
    state = _state().model_copy(
        update={
            "sources": read_delta.add_sources,
            "evidence": read_delta.add_evidence,
        }
    )
    state = OpinionSearchState.model_validate(state.model_dump())
    decision = ReflectDecision(
        action="reflect",
        assessment="The primary account supports the event date.",
        next_focus="Find independent confirmation.",
        gap_assessments=(
            GapAssessmentProposal(
                gap_id="gap-primary",
                outcome=GapStatus.RESOLVED,
                evidence_ids=(evidence.evidence_id,),
                rationale="The event date is source-backed.",
            ),
        ),
        claim_proposals=(
            ClaimProposal(
                text="The event occurred on 20 August.",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )

    delta = OpinionSearchObservationProcessor().build_delta(
        state,
        decision,
        ReflectObservation(
            assessment=decision.assessment,
            assessed_gap_ids=("gap-primary",),
        ),
    )

    assert delta.gap_assessments[0].gap_id == "gap-primary"
    assert delta.gap_assessments[0].evidence_ids == (evidence.evidence_id,)
    assert delta.upsert_claims[0].claim_id == stable_domain_id(
        "claim", "The event occurred on 20 August."
    )
    assert delta.upsert_claims[0].supporting_evidence_ids == (evidence.evidence_id,)
    assert delta.set_current_focus == "Find independent confirmation."


def test_processor_rejects_unknown_claim_evidence_and_mismatched_tool() -> None:
    decision = ReflectDecision(
        action="reflect",
        assessment="Unsupported.",
        next_focus="Continue.",
        gap_assessments=(
            GapAssessmentProposal(
                gap_id="gap-primary",
                outcome=GapStatus.OPEN,
                rationale="The claim is unsupported.",
            ),
        ),
        claim_proposals=(
            ClaimProposal(
                text="Unknown claim.",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=("evidence-missing",),
            ),
        ),
    )
    with pytest.raises(ProcessorInvariantError, match="unknown evidence"):
        OpinionSearchObservationProcessor().build_delta(
            _state(),
            decision,
            ReflectObservation(
                assessment=decision.assessment,
                assessed_gap_ids=("gap-primary",),
            ),
        )

    wrong_tool = ToolObservation(
        action="search",
        outcome=ToolResult(
            action_id="action-1",
            tool_name="read.web",
            payload={"url": URL},
            attempts=1,
        ),
    )
    with pytest.raises(ProcessorInvariantError, match="tool name"):
        OpinionSearchObservationProcessor().build_delta(
            _state(), _search_decision(), wrong_tool
        )


def test_accepted_finish_commits_a_recoverable_final_synthesis() -> None:
    verdict = CompletionVerdict(
        disposition=CompletionDisposition.ACCEPT_COMPLETE,
        reason="Complete.",
    )
    decision = FinishDecision(
        action="finish",
        answer_candidate="Complete.",
        resolved_gap_ids=(),
        unresolved_gap_ids=("gap-primary",),
    )
    observation = FinishObservation(completion_verdict=verdict)

    delta = OpinionSearchObservationProcessor().build_delta(
        _state(), decision, observation
    )
    evaluated = OpinionSearchCompletionEvaluator().evaluate(
        _state(), decision, observation
    )

    assert delta.set_final_synthesis is not None
    assert delta.set_final_synthesis.summary == "Complete."
    assert delta.set_final_synthesis.limitation_gap_ids == ("gap-primary",)
    assert evaluated is verdict


def test_rejected_finish_does_not_commit_a_final_synthesis() -> None:
    decision = FinishDecision(
        action="finish",
        answer_candidate="Not ready.",
        resolved_gap_ids=(),
        unresolved_gap_ids=("gap-primary",),
    )
    delta = OpinionSearchObservationProcessor().build_delta(
        _state(),
        decision,
        FinishObservation(
            completion_verdict=CompletionVerdict(
                disposition=CompletionDisposition.REJECT_AND_CONTINUE,
                reason="The gap remains open.",
            )
        ),
    )

    assert delta.set_final_synthesis is None
