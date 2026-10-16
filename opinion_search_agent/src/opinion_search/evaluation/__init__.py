"""Deterministic report-quality evaluation.

The gate answers the same questions about a run every time it is asked, using
only files that already exist on disk: the run checkpoint (``run.json``), the
terminal report, and the reader snapshots the evidence excerpts point at. No
model call and no network access happen here.
"""

from opinion_search.evaluation.bundle import RunBundle, load_bundle
from opinion_search.evaluation.gate import check_gate, run_gate

__all__ = ["RunBundle", "check_gate", "load_bundle", "run_gate"]
