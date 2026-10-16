"""``record --report`` must reuse the served path's terminal bundle writer."""

from __future__ import annotations

import asyncio
import json

import pytest

from opinion_search.app.run_bundle import RunBundleWriter
from opinion_search.domain.opinion.brief import build_search_outcome
from opinion_search.domain.opinion.state import OpinionSearchState
from opinion_search.evaluation.gate import PACKAGE_ROOT
from opinion_search.runtime.completion import RunStatus

RUN_DIR = PACKAGE_ROOT / "artifacts" / "live-run-deepseek-20261017"


def test_terminal_bundle_from_a_frozen_checkpoint(tmp_path):
    if not (RUN_DIR / "run.json").is_file():
        pytest.skip("frozen live run missing")
    checkpoint = json.loads((RUN_DIR / "run.json").read_text(encoding="utf-8"))["state"]
    state = OpinionSearchState.model_validate(checkpoint["domain_state"])
    outcome = build_search_outcome(
        state, status=RunStatus.COMPLETED, stop_reason=checkpoint["stop_reason"]
    )
    writer = RunBundleWriter(tmp_path / "run.json")
    written = asyncio.run(writer.write_report(outcome))

    assert written == (tmp_path / "report.md").resolve()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert markdown.startswith("# OpinionSearch Brief")
    assert markdown.rstrip("\n") == outcome.markdown.rstrip("\n")

    payload = json.loads((tmp_path / "outcome.json").read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["markdown"] == outcome.markdown
    assert len(payload["source_urls"]) == len(state.sources)
    assert payload["remaining_gap_ids"] == list(outcome.remaining_gap_ids)
