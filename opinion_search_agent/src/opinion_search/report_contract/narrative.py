"""Keep only the summary sentences a reader can check.

The presentation agent may write prose, but every clause has to rest on findings
that already passed review. Three deterministic gates enforce that, and a clause
that fails any of them is dropped rather than softened: an unwritten sentence is
honest, an unsupported one is not.

1. binding - the clause names at least one reviewed finding
2. support - every number and every quoted span in the clause appears in the
   evidence those findings cite
3. fallback - a paragraph with no surviving clauses disappears, and a section
   with no paragraphs becomes None, so the report degrades to cards only
"""

from __future__ import annotations

import re
from typing import Any

from opinion_search.report_contract.contracts import (
    NarrativeClause, NarrativeParagraph, NarrativeSection,
)

# Dates first: a bare "9" would otherwise "match" any other date in the excerpt.
_NUMBER = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d[\d,.]*\s*%?"
)
_QUOTED = re.compile(r"[\u201c\u300c]([^\u201c\u201d\u300c\u300d]{4,})[\u201d\u300d]")
_SQUASH = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _SQUASH.sub("", text or "")


def _support_text(finding_ids, findings_by_id, evidence_by_id) -> str:
    excerpts = []
    for finding_id in finding_ids:
        finding = findings_by_id.get(finding_id) or {}
        for evidence_id in finding.get("evidence_ids") or ():
            item = evidence_by_id.get(evidence_id) or {}
            excerpt = item.get("excerpt")
            if excerpt:
                excerpts.append(excerpt)
    return _squash("".join(excerpts))


def unsupported_tokens(text: str, support: str) -> list[str]:
    """Numbers and quoted spans in ``text`` that ``support`` does not contain."""

    missing = []
    for number in _NUMBER.findall(text or ""):
        if _squash(number) and _squash(number) not in support:
            missing.append(number)
    for quote in _QUOTED.findall(text or ""):
        if _squash(quote)[:12] and _squash(quote)[:12] not in support:
            missing.append(quote)
    return list(dict.fromkeys(missing))


def filter_narrative(
    narrative: NarrativeSection | None,
    findings_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    approved_ids: set[str],
) -> tuple[NarrativeSection | None, list[dict[str, Any]]]:
    """Apply the three gates and report what was dropped, and why."""

    if narrative is None:
        return None, []

    dropped: list[dict[str, Any]] = []

    def keep(clause: NarrativeClause) -> bool:
        ids = tuple(fid for fid in clause.finding_ids if fid in approved_ids)
        if not ids:
            dropped.append({"text": clause.text, "reason": "no_reviewed_finding"})
            return False
        missing = unsupported_tokens(clause.text, _support_text(ids, findings_by_id, evidence_by_id))
        if missing:
            dropped.append({"text": clause.text, "reason": "unsupported_specifics", "tokens": missing})
            return False
        return True

    headline = narrative.headline.strip()
    if headline:
        missing = unsupported_tokens(
            headline, _support_text(narrative.headline_finding_ids, findings_by_id, evidence_by_id)
        )
        if not set(narrative.headline_finding_ids) & approved_ids or missing:
            dropped.append({"text": headline, "reason": "headline_unbacked", "tokens": missing})
            headline = ""

    paragraphs: list[NarrativeParagraph] = []
    for paragraph in narrative.paragraphs:
        clauses = tuple(clause for clause in paragraph.clauses if keep(clause))
        if clauses:
            paragraphs.append(NarrativeParagraph(role=paragraph.role, clauses=clauses))
        else:
            dropped.append({"text": "", "reason": "empty_paragraph", "role": paragraph.role})

    if not paragraphs:
        return None, dropped
    return NarrativeSection(
        headline=headline,
        headline_finding_ids=tuple(narrative.headline_finding_ids),
        paragraphs=tuple(paragraphs),
    ), dropped
