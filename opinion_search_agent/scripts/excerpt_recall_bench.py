"""Offline excerpt-recall benchmark over frozen reader bodies.

For every (page, labeled item) pair where the full page text contains the
item's keywords, check whether the excerpts selected for that item's focus
cover those keywords. The focus is the item's fact description, standing in
for the gap question the investigation would have asked. Labels were written
before this measurement and are keyword-based.

Usage: python scripts/excerpt_recall_bench.py <labels.json> <page-glob>...
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Callable

from opinion_search.domain.opinion import processor

Selector = Callable[..., tuple[processor._EvidenceExcerpt, ...]]


def covers(text: str, keywords: list[str]) -> bool:
    return sum(k in text for k in keywords) >= min(2, len(keywords))


def measure(selector: Selector, labels: dict, pages: list[str]) -> tuple[int, int]:
    gold = hit = 0
    for text in pages:
        for item in labels["items"]:
            if not covers(text, item["kw"]):
                continue
            gold += 1
            selected = selector(text, focus=item["fact"])
            hit += covers(" ".join(e.text for e in selected), item["kw"])
    return hit, gold


def main() -> None:
    labels = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pages: dict[str, str] = {}
    for pattern in sys.argv[2:]:
        for path in glob.glob(pattern, recursive=True):
            pages.setdefault(Path(path).read_text(encoding="utf-8", errors="replace"), path)
    hit, gold = measure(processor._select_evidence_excerpts, labels, list(pages))
    print(f"excerpt recall (per-item focus): {hit}/{gold} = {hit / gold:.0%} pages={len(pages)}")


if __name__ == "__main__":
    main()
