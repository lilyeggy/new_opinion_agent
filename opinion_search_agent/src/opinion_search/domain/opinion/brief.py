from __future__ import annotations

import html
import re
from typing import Annotated
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from opinion_search.domain.opinion.provenance import ProvenanceIndex, build_provenance_index
from opinion_search.domain.opinion.state import (
    GapStatus,
    OpinionSearchState,
)
from opinion_search.runtime.lifecycle import RunStatus


NonEmptyText = Annotated[str, Field(min_length=1)]


class SearchOutcome(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    status: RunStatus
    stop_reason: NonEmptyText
    markdown: NonEmptyText
    source_urls: tuple[NonEmptyText, ...]
    remaining_gap_ids: tuple[NonEmptyText, ...]


def build_search_outcome(
    state: OpinionSearchState,
    *,
    status: RunStatus,
    stop_reason: str,
) -> SearchOutcome:
    source_number = {
        source.source_id: index for index, source in enumerate(state.sources, start=1)
    }
    provenance = build_provenance_index(state)

    lines = [
        "# OpinionSearch Brief",
        "",
        f"**Question:** {_escape_markdown(state.request.question)}",
        f"**Run status:** {status.value}",
        f"**Stop reason:** {_escape_markdown(stop_reason)}",
        "",
        "## Evidence-backed claims",
        "",
    ]
    if not state.claims:
        lines.append("- No evidence-linked claim was committed.")
    for claim in state.claims:
        supporting = _citation_list(
            claim.supporting_evidence_ids,
            provenance,
            source_number,
        )
        contradicting = _citation_list(
            claim.contradicting_evidence_ids,
            provenance,
            source_number,
        )
        citations = []
        if supporting:
            citations.append(f"supports: {supporting}")
        if contradicting:
            citations.append(f"contradicts: {contradicting}")
        suffix = f" ({'; '.join(citations)})" if citations else ""
        lines.append(
            f"- **{claim.kind.value} / {claim.status.value}:** "
            f"{_escape_markdown(claim.text)}{suffix}"
        )

    lines.extend(["", "## Stakeholder positions", ""])
    if not state.stakeholder_positions:
        lines.append("- No evidence-linked stakeholder position was recorded.")
    for position in state.stakeholder_positions:
        citations = _citation_list(
            position.evidence_ids,
            provenance,
            source_number,
        )
        lines.append(
            f"- **{_escape_markdown(position.stakeholder)}:** "
            f"{_escape_markdown(position.statement)} ({citations})"
        )

    lines.extend(["", "## Public narratives", ""])
    if not state.narratives:
        lines.append("- No evidence-linked public narrative was recorded.")
    for narrative in state.narratives:
        citations = _citation_list(
            narrative.evidence_ids,
            provenance,
            source_number,
        )
        stakeholders = (
            "; attributed to: "
            + ", ".join(_escape_markdown(name) for name in narrative.stakeholder_names)
            if narrative.stakeholder_names
            else ""
        )
        lines.append(
            f"- **{narrative.kind.value}:** "
            f"{_escape_markdown(narrative.summary)}"
            f"{stakeholders} ({citations})"
        )

    lines.extend(["", "## Opinion coverage", ""])
    for gap in state.gaps:
        citations = _citation_list(
            gap.evidence_ids,
            provenance,
            source_number,
        )
        evidence_note = citations or "no linked evidence"
        lines.append(
            f"- `{_escape_code_span(gap.gap_id)}` [{gap.status.value}] "
            f"{_escape_markdown(gap.question)} — {evidence_note}"
        )

    lines.extend(["", "## Evidence excerpts", ""])
    if not state.evidence:
        lines.append("- No readable evidence was collected.")
    for item in state.evidence:
        citation = _source_citation(item.source_id, source_number)
        lines.append(
            f"- `{_escape_code_span(item.evidence_id)}` "
            f"{_escape_markdown(item.excerpt)} ({citation})"
        )

    remaining = tuple(gap for gap in state.gaps if gap.status is not GapStatus.RESOLVED)
    lines.extend(["", "## Remaining gaps", ""])
    if not remaining:
        lines.append("- None recorded.")
    for gap in remaining:
        detail = gap.resolution_note or "Still open."
        lines.append(
            f"- `{_escape_code_span(gap.gap_id)}` [{gap.status.value}] "
            f"{_escape_markdown(gap.question)} — {_escape_markdown(detail)}"
        )

    lines.extend(["", "## Sources", ""])
    if not state.sources:
        lines.append("- No source was successfully read.")
    for source in state.sources:
        number = source_number[source.source_id]
        lines.append(
            f"- [S{number}] [{_escape_markdown(source.title)}]"
            f"({_safe_markdown_destination(source.final_url or source.url)}) "
            f"— {source.source_kind.value}"
        )

    lines.extend(
        [
            "",
            "## Scope limitation",
            "",
            "This brief summarizes accessible public-Web sources and does not "
            "measure whole-network sentiment, reach, or prevalence.",
        ]
    )
    return SearchOutcome(
        status=status,
        stop_reason=stop_reason,
        markdown="\n".join(lines),
        source_urls=tuple(source.final_url or source.url for source in state.sources),
        remaining_gap_ids=tuple(gap.gap_id for gap in remaining),
    )


def _citation_list(
    evidence_ids: tuple[str, ...],
    provenance: ProvenanceIndex,
    source_number: dict[str, int],
) -> str:
    citations = []
    for evidence_id in evidence_ids:
        source_id = provenance.record(evidence_id).source_id
        citations.append(_source_citation(source_id, source_number))
    return ", ".join(dict.fromkeys(citations))


def _source_citation(source_id: str, source_number: dict[str, int]) -> str:
    return f"[S{source_number[source_id]}]"


def _escape_markdown(value: str) -> str:
    escaped_html = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#!])", r"\\\1", escaped_html)


def _escape_code_span(value: str) -> str:
    return value.replace("`", "\\`")


def _safe_markdown_destination(url: str) -> str:
    return quote(
        url,
        safe=":/?&=#%@+;,$-_.~*'",
    )
