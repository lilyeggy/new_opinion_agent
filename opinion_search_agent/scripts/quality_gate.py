"""Recompute the frozen report-quality baseline without a model or a network.

Usage (from opinion_search_agent/):
    python scripts/quality_gate.py            # recompute and rewrite the baseline
    python scripts/quality_gate.py --check    # exit 1 if any number drifted

The corpus lives in evaluation/corpus.json and points at run directories that
are already in the tree. Human judgements live in evaluation/annotations/.
"""

from __future__ import annotations

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opinion_search.evaluation.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
