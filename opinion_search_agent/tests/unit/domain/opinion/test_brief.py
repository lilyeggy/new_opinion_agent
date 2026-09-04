from opinion_search.app.contracts import SearchRequest
from opinion_search.domain.opinion.brief import build_search_outcome
from opinion_search.domain.opinion.state import (
    CandidateSource,
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    FinalSynthesis,
    GapStatus,
    InvestigationGap,
    OpinionSearchState,
    Source,
    SourceKind,
)
from opinion_search.runtime.lifecycle import RunStatus


def test_brief_keeps_claim_provenance_remaining_gaps_and_scope_limit() -> None:
    url = "https://example.org/announcement"
    evidence = Evidence(
        evidence_id="evidence-1",
        source_id=url,
        acquired_for_gap_id="gap-event",
        excerpt="The announcement gives the event date.",
        locator="Opening paragraph.",
    )
    state = OpinionSearchState(
        request=SearchRequest(question="What happened?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-event",
                question="Establish the event.",
                status=GapStatus.RESOLVED,
                evidence_ids=("evidence-1",),
                resolution_note="The source was read.",
            ),
            InvestigationGap(
                gap_id="gap-independent",
                question="Find independent confirmation.",
                status=GapStatus.BLOCKED,
                resolution_note="No accessible independent account was found.",
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="Announcement",
                snippet="Event notice.",
                discovered_for_gap_ids=("gap-event",),
            ),
        ),
        sources=(
            Source(
                source_id=url,
                url=url,
                title="Announcement",
                source_kind=SourceKind.PRIMARY,
            ),
        ),
        evidence=(evidence,),
        claims=(
            Claim(
                claim_id="claim-1",
                text="The event date was announced.",
                kind=ClaimKind.ATTRIBUTED_STATEMENT,
                supporting_evidence_ids=(evidence.evidence_id,),
                status=ClaimStatus.SUPPORTED,
            ),
        ),
        final_synthesis=FinalSynthesis(
            summary="The event was announced, but independent confirmation is unavailable.",
            evidence_ids=("evidence-1",),
            limitation_gap_ids=("gap-independent",),
        ),
    )

    outcome = build_search_outcome(
        state,
        status=RunStatus.PARTIAL,
        stop_reason="An independent source remained unavailable.",
    )

    assert "[S1]" in outcome.markdown
    assert "## Core conclusion" in outcome.markdown
    assert outcome.markdown.index("## Core conclusion") < outcome.markdown.index(
        "## Evidence-backed claims"
    )
    assert "The event was announced" in outcome.markdown
    assert "https://example.org/announcement" in outcome.markdown
    assert "gap-independent" in outcome.markdown
    assert "whole-network sentiment" in outcome.markdown
    assert outcome.remaining_gap_ids == ("gap-independent",)
    assert outcome.report.question == "What happened?"
    assert outcome.report.conclusion is not None
    assert outcome.report.conclusion.source_refs == ("S1",)
    assert outcome.report.claims[0].supporting_source_refs == ("S1",)
    assert outcome.report.remaining_gaps[0].gap_id == "gap-independent"
    assert outcome.report.sources[0].source_ref == "S1"


def test_brief_escapes_model_and_page_markdown_payloads() -> None:
    url = "https://example.org/x) ![track](https://attacker.example/pixel"
    evidence = Evidence(
        evidence_id="evidence-1",
        source_id=url,
        acquired_for_gap_id="gap-event",
        excerpt="![track](https://attacker.example/pixel) <img src=x>",
        locator="Opening paragraph.",
    )
    state = OpinionSearchState(
        request=SearchRequest(question="Is *this* safe?"),
        gaps=(
            InvestigationGap(
                gap_id="gap-event",
                question="Establish the event.",
                status=GapStatus.RESOLVED,
                evidence_ids=("evidence-1",),
                resolution_note="Resolved.",
            ),
        ),
        candidates=(
            CandidateSource(
                source_id=url,
                url=url,
                title="[Injected title]",
                snippet="Candidate.",
                discovered_for_gap_ids=("gap-event",),
            ),
        ),
        sources=(Source(source_id=url, url=url, title="[Injected title]"),),
        evidence=(evidence,),
        claims=(
            Claim(
                claim_id="claim-1",
                text="**Injected claim**",
                kind=ClaimKind.FACT,
                supporting_evidence_ids=("evidence-1",),
                status=ClaimStatus.SUPPORTED,
            ),
        ),
    )

    outcome = build_search_outcome(
        state,
        status=RunStatus.COMPLETED,
        stop_reason="Complete.",
    )

    assert "![track]" not in outcome.markdown
    assert "<img" not in outcome.markdown
    assert "\\*\\*Injected claim\\*\\*" in outcome.markdown
    assert ") ![track](" not in outcome.markdown
    assert "%29%20%21%5Btrack%5D%28" in outcome.markdown
