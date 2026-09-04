from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.domain.opinion.provenance import build_provenance_index
from opinion_search.domain.opinion.state import (
    ClaimKind,
    ClaimStatus,
    GapStatus,
    NarrativeKind,
    OpinionSearchState,
    SourceKind,
    SourcePublicationStatus,
)
from opinion_search.runtime.lifecycle import RunStatus

NonEmptyText = Annotated[str, Field(min_length=1)]


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ReportTimeScope(_ReportModel):
    start_date: date
    end_date: date
    provenance: NonEmptyText


class ReportConclusion(_ReportModel):
    summary: NonEmptyText
    source_refs: tuple[NonEmptyText, ...] = ()
    limitation_gap_ids: tuple[NonEmptyText, ...] = ()


class ReportClaim(_ReportModel):
    claim_id: NonEmptyText
    text: NonEmptyText
    kind: ClaimKind
    status: ClaimStatus
    supporting_source_refs: tuple[NonEmptyText, ...] = ()
    contradicting_source_refs: tuple[NonEmptyText, ...] = ()


class ReportStakeholderPosition(_ReportModel):
    position_id: NonEmptyText
    stakeholder: NonEmptyText
    statement: NonEmptyText
    source_refs: tuple[NonEmptyText, ...]


class ReportNarrative(_ReportModel):
    narrative_id: NonEmptyText
    summary: NonEmptyText
    kind: NarrativeKind
    stakeholder_names: tuple[NonEmptyText, ...] = ()
    source_refs: tuple[NonEmptyText, ...]


class ReportCoverage(_ReportModel):
    gap_id: NonEmptyText
    question: NonEmptyText
    status: GapStatus
    source_refs: tuple[NonEmptyText, ...] = ()


class ReportEvidence(_ReportModel):
    evidence_id: NonEmptyText
    excerpt: NonEmptyText
    source_ref: NonEmptyText
    locator: NonEmptyText


class ReportGap(_ReportModel):
    gap_id: NonEmptyText
    question: NonEmptyText
    status: GapStatus
    detail: NonEmptyText


class ReportSource(_ReportModel):
    source_ref: NonEmptyText
    title: NonEmptyText
    url: NonEmptyText
    kind: SourceKind
    published_at: datetime | None = None
    publication_status: SourcePublicationStatus


class SearchReportView(_ReportModel):
    """Stable projection consumed by HTTP, UI and Markdown export."""

    question: NonEmptyText
    time_scope: ReportTimeScope | None = None
    conclusion: ReportConclusion | None = None
    claims: tuple[ReportClaim, ...] = ()
    stakeholder_positions: tuple[ReportStakeholderPosition, ...] = ()
    narratives: tuple[ReportNarrative, ...] = ()
    coverage: tuple[ReportCoverage, ...] = ()
    evidence_appendix: tuple[ReportEvidence, ...] = ()
    remaining_gaps: tuple[ReportGap, ...] = ()
    sources: tuple[ReportSource, ...] = ()
    scope_limitation: NonEmptyText


class SearchOutcome(_ReportModel):
    status: RunStatus
    stop_reason: NonEmptyText
    report: SearchReportView
    markdown: NonEmptyText
    source_urls: tuple[NonEmptyText, ...]
    remaining_gap_ids: tuple[NonEmptyText, ...]


_SCOPE_LIMITATION = (
    "This brief summarizes accessible public-Web sources and does not "
    "measure whole-network sentiment, reach, or prevalence."
)


def build_search_outcome(
    state: OpinionSearchState, *, status: RunStatus, stop_reason: str,
) -> SearchOutcome:
    report = _build_report_view(state)
    return SearchOutcome(
        status=status,
        stop_reason=stop_reason,
        report=report,
        markdown=_render_markdown(report, status=status, stop_reason=stop_reason),
        source_urls=tuple(source.url for source in report.sources),
        remaining_gap_ids=tuple(gap.gap_id for gap in report.remaining_gaps),
    )


def _build_report_view(state: OpinionSearchState) -> SearchReportView:
    source_refs = {
        source.source_id: f"S{index}"
        for index, source in enumerate(state.sources, start=1)
    }
    provenance = build_provenance_index(state)

    def refs_for(evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
        refs = (
            source_refs[provenance.record(evidence_id).source_id]
            for evidence_id in evidence_ids
        )
        return tuple(dict.fromkeys(refs))

    time_scope = None
    if state.task_frame is not None and state.task_frame.temporal_scope.is_bounded:
        scope = state.task_frame.temporal_scope
        assert scope.start_date is not None and scope.end_date is not None
        time_scope = ReportTimeScope(
            start_date=scope.start_date,
            end_date=scope.end_date,
            provenance=scope.provenance.value,
        )
    conclusion = None
    if state.final_synthesis is not None:
        conclusion = ReportConclusion(
            summary=state.final_synthesis.summary,
            source_refs=refs_for(state.final_synthesis.evidence_ids),
            limitation_gap_ids=state.final_synthesis.limitation_gap_ids,
        )
    remaining = tuple(gap for gap in state.gaps if gap.status is not GapStatus.RESOLVED)
    return SearchReportView(
        question=state.request.question,
        time_scope=time_scope,
        conclusion=conclusion,
        claims=tuple(
            ReportClaim(
                claim_id=claim.claim_id, text=claim.text, kind=claim.kind,
                status=claim.status,
                supporting_source_refs=refs_for(claim.supporting_evidence_ids),
                contradicting_source_refs=refs_for(claim.contradicting_evidence_ids),
            ) for claim in state.claims
        ),
        stakeholder_positions=tuple(
            ReportStakeholderPosition(
                position_id=item.position_id, stakeholder=item.stakeholder,
                statement=item.statement, source_refs=refs_for(item.evidence_ids),
            ) for item in state.stakeholder_positions
        ),
        narratives=tuple(
            ReportNarrative(
                narrative_id=item.narrative_id, summary=item.summary,
                kind=item.kind, stakeholder_names=item.stakeholder_names,
                source_refs=refs_for(item.evidence_ids),
            ) for item in state.narratives
        ),
        coverage=tuple(
            ReportCoverage(
                gap_id=gap.gap_id, question=gap.question, status=gap.status,
                source_refs=refs_for(gap.evidence_ids),
            ) for gap in state.gaps
        ),
        evidence_appendix=tuple(
            ReportEvidence(
                evidence_id=item.evidence_id, excerpt=item.excerpt,
                source_ref=source_refs[item.source_id], locator=item.locator,
            ) for item in state.evidence
        ),
        remaining_gaps=tuple(
            ReportGap(
                gap_id=gap.gap_id, question=gap.question, status=gap.status,
                detail=gap.resolution_note or "Still open.",
            ) for gap in remaining
        ),
        sources=tuple(
            ReportSource(
                source_ref=source_refs[source.source_id], title=source.title,
                url=source.final_url or source.url, kind=source.source_kind,
                published_at=source.published_at,
                publication_status=source.publication_status,
            ) for source in state.sources
        ),
        scope_limitation=_SCOPE_LIMITATION,
    )


def _render_markdown(
    report: SearchReportView, *, status: RunStatus, stop_reason: str,
) -> str:
    lines = [
        "# OpinionSearch Brief", "",
        f"**Question:** {_escape_markdown(report.question)}",
        f"**Run status:** {status.value}",
        f"**Stop reason:** {_escape_markdown(stop_reason)}",
    ]
    if report.time_scope is not None:
        scope = report.time_scope
        lines.append(
            f"**Time scope:** {scope.start_date.isoformat()} to "
            f"{scope.end_date.isoformat()} ({scope.provenance})"
        )
    lines.extend(["", "## Core conclusion", ""])
    if report.conclusion is None:
        lines.append("- No validated final synthesis was committed.")
    else:
        conclusion = report.conclusion
        lines.append(
            f"- {_escape_markdown(conclusion.summary)}{_refs_suffix(conclusion.source_refs)}"
        )
        if conclusion.limitation_gap_ids:
            lines.append(
                "- **Limitations:** " + ", ".join(
                    f"`{_escape_code_span(gap_id)}`"
                    for gap_id in conclusion.limitation_gap_ids
                )
            )
    lines.extend(["", "## Evidence-backed claims", ""])
    if not report.claims:
        lines.append("- No evidence-linked claim was committed.")
    for claim in report.claims:
        citations = []
        if claim.supporting_source_refs:
            citations.append(f"supports: {_refs(claim.supporting_source_refs)}")
        if claim.contradicting_source_refs:
            citations.append(f"contradicts: {_refs(claim.contradicting_source_refs)}")
        suffix = f" ({'; '.join(citations)})" if citations else ""
        lines.append(
            f"- **{claim.kind.value} / {claim.status.value}:** "
            f"{_escape_markdown(claim.text)}{suffix}"
        )
    lines.extend(["", "## Stakeholder positions", ""])
    if not report.stakeholder_positions:
        lines.append("- No evidence-linked stakeholder position was recorded.")
    for item in report.stakeholder_positions:
        lines.append(
            f"- **{_escape_markdown(item.stakeholder)}:** "
            f"{_escape_markdown(item.statement)} ({_refs(item.source_refs)})"
        )
    lines.extend(["", "## Public narratives", ""])
    if not report.narratives:
        lines.append("- No evidence-linked public narrative was recorded.")
    for item in report.narratives:
        stakeholders = (
            "; attributed to: "
            + ", ".join(_escape_markdown(name) for name in item.stakeholder_names)
            if item.stakeholder_names else ""
        )
        lines.append(
            f"- **{item.kind.value}:** {_escape_markdown(item.summary)}"
            f"{stakeholders} ({_refs(item.source_refs)})"
        )
    lines.extend(["", "## Opinion coverage", ""])
    for gap in report.coverage:
        lines.append(
            f"- `{_escape_code_span(gap.gap_id)}` [{gap.status.value}] "
            f"{_escape_markdown(gap.question)} — "
            f"{_refs(gap.source_refs) or 'no linked evidence'}"
        )
    lines.extend(["", "## Evidence appendix", ""])
    if not report.evidence_appendix:
        lines.append("- No readable evidence was collected.")
    for item in report.evidence_appendix:
        lines.append(
            f"- `{_escape_code_span(item.evidence_id)}` "
            f"{_escape_markdown(item.excerpt)} ([{item.source_ref}])"
        )
    lines.extend(["", "## Remaining gaps", ""])
    if not report.remaining_gaps:
        lines.append("- None recorded.")
    for gap in report.remaining_gaps:
        lines.append(
            f"- `{_escape_code_span(gap.gap_id)}` [{gap.status.value}] "
            f"{_escape_markdown(gap.question)} — {_escape_markdown(gap.detail)}"
        )
    lines.extend(["", "## Sources", ""])
    if not report.sources:
        lines.append("- No source was successfully read.")
    for source in report.sources:
        publication = (
            source.published_at.date().isoformat()
            if source.published_at is not None else "unknown publication time"
        )
        lines.append(
            f"- [{source.source_ref}] [{_escape_markdown(source.title)}]"
            f"({_safe_markdown_destination(source.url)}) "
            f"— {source.kind.value}; {publication}"
        )
    lines.extend(["", "## Scope limitation", "", report.scope_limitation])
    return "\n".join(lines)


def _refs(source_refs: tuple[str, ...]) -> str:
    return ", ".join(f"[{source_ref}]" for source_ref in source_refs)


def _refs_suffix(source_refs: tuple[str, ...]) -> str:
    citations = _refs(source_refs)
    return f" ({citations})" if citations else ""


def _escape_markdown(value: str) -> str:
    escaped_html = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#!])", r"\\\1", escaped_html)


def _escape_code_span(value: str) -> str:
    return value.replace("`", "\\`")


def _safe_markdown_destination(url: str) -> str:
    return quote(url, safe=":/?&=#%@+;,$-_.~*'")
