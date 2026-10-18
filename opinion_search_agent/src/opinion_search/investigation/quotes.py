"""Deterministic quote provenance for findings.

A finding that puts words in quotation marks makes a checkable claim: those
words should exist in a document the run actually read. The reviewer is a model,
so this module provides the cheap, reproducible half of that check -- it only
compares strings, never judges meaning.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

# Corner brackets are included because the corpus mixes both styles. The floor of
# five characters skips one- or two-word scare quotes, which are not claims.
QUOTED_SPAN = re.compile(r"[\u201c\u300c]([^\u201c\u201d\u300c\u300d]{5,})[\u201d\u300d]")

# Twelve characters identify a span while tolerating an excerpt that stops
# mid-sentence or a document that wraps the line.
_NEEDLE = 12


def quoted_spans(text: str) -> tuple[str, ...]:
    """Every quoted span in a piece of prose, in order and deduplicated."""
    return tuple(dict.fromkeys(QUOTED_SPAN.findall(text or "")))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def unbacked_quotes(text: str, documents: Iterable[str]) -> tuple[str, ...]:
    """Quoted spans whose words appear in none of the given documents."""
    haystack = _squash("".join(documents))
    missing = []
    for quote in quoted_spans(text):
        needle = _squash(quote)[:_NEEDLE]
        if needle and needle not in haystack:
            missing.append(quote)
    return tuple(missing)


def missing_from_excerpts(text: str, excerpts: Iterable[str]) -> tuple[str, ...]:
    """Quoted spans a finding states that its own excerpts cannot show."""
    haystack = _squash("".join(excerpts))
    missing = []
    for quote in quoted_spans(text):
        needle = _squash(quote)[:_NEEDLE]
        if needle and needle not in haystack:
            missing.append(quote)
    return tuple(missing)


def _flexible(quote: str) -> re.Pattern[str]:
    return re.compile(r"\s*".join(re.escape(part) for part in quote))


_QUOTE_STYLES = (("\u2018", "\u201c", "\u2019", "\u201d"), ("\u201c", "\u2018", "\u201d", "\u2019"))


def _variants(quote: str) -> tuple[str, ...]:
    """The quote as written, plus the same words in the other bracket style.

    Findings and source pages disagree about corner brackets ('...' versus
    "...") often enough to be worth bridging: the words in between are what the
    claim rests on, and the span bound back is always the document's own text.
    """

    variants = [quote]
    for left, other_left, right, other_right in _QUOTE_STYLES:
        swapped = quote.replace(left, other_left).replace(right, other_right)
        if swapped != quote and swapped not in variants:
            variants.append(swapped)
    return tuple(variants)


def locate(quote: str, documents: Sequence[tuple[str, str]]) -> tuple[str, int, int, str] | None:
    """Find a quote in the first document that contains it, whitespace-tolerant."""
    for version_id, text in documents:
        for variant in _variants(quote):
            start = text.find(variant)
            if start >= 0:
                return version_id, start, start + len(variant), variant
            match = _flexible(variant).search(text)
            if match:
                return version_id, match.start(), match.end(), match.group(0)
    return None
