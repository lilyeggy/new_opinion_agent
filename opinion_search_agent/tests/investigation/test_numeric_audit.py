"""The numeric ledger, and the disagreement section it feeds into the report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opinion_search.domain.investigation.engine import merge, reduce_state
from opinion_search.domain.investigation.models import (
    Delta, NumericObservation, Observation, ReadDecision, State, uid,
)
from opinion_search.domain.numeric import extract_quantities
from opinion_search.evaluation.bundle import load_bundle
from opinion_search.investigation import numeric_audit
from opinion_search.investigation.report import build_report, markdown

ROOT = Path(__file__).resolve().parents[2]
CASE = {
    "case_id": "sanjiu-adversarial",
    "domain": "investigation",
    "run_dir": "artifacts/adversarial-cases/sanjiu-2026-09/runs-root/runs/452e0b05aca84ad39fb0f9d4427cfb81",
    "materials_dir": "artifacts/adversarial-cases/sanjiu-2026-09/materials",
    "materials_manifest": "artifacts/adversarial-cases/sanjiu-2026-09/case.json",
}


def _observation(source_id: str, text: str, index: int) -> NumericObservation:
    return NumericObservation(
        observation_id=uid("numeric", source_id, str(index)),
        version_id=source_id,
        metric="销售费用",
        value="90890000000",
        literal="908.9亿元",
        start=index,
        end=index + 6,
    )


def test_merge_keeps_ledger_entries_unique():
    first = _observation("source-a", "908.9亿元", 0)
    second = _observation("source-b", "908.9亿元", 0)

    merged = merge((first,), (first, second), "observation_id")

    assert merged == (first, second)


def test_reducer_appends_read_observations_to_the_ledger(frozen_run):
    loaded, _ = frozen_run
    state = loaded.model_copy(update={"numeric_ledger": ()})
    source = state.sources[0]
    item = NumericObservation(
        observation_id=uid("numeric", source.version_id, "0", "6"),
        version_id=source.version_id,
        metric="销售费用",
        value="90890000000",
        literal="908.9亿元",
        start=0,
        end=6,
    )
    delta = Delta(
        decision=ReadDecision(issue_id=state.issues[0].issue_id, url=source.url, focus="测试"),
        observation=Observation(action="read", numeric=(item,)),
    )

    reduced = reduce_state(state, delta)

    assert reduced.numeric_ledger == (item,)
    assert reduce_state(reduced, Delta(decision=delta.decision, observation=Observation(action="read", numeric=(item,)))).numeric_ledger == (item,)


@pytest.fixture(scope="module")
def frozen_run():
    run_dir = ROOT / CASE["run_dir"]
    if not (run_dir / "run.json").exists():
        pytest.skip("frozen adversarial run is not present")
    bundle = load_bundle(CASE, ROOT)
    ledger = tuple(
        NumericObservation(
            observation_id=uid("numeric", source.source_id, str(item.span[0]), str(item.span[1])),
            version_id=source.source_id,
            metric=item.metric,
            value=str(item.value),
            literal=item.literal,
            start=item.span[0],
            end=item.span[1],
        )
        for source in bundle.sources
        if source.text
        for item in extract_quantities(source.source_id, source.text)
    )
    raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    state = State.model_validate(raw["state"]["domain_state"])
    return state.model_copy(update={"numeric_ledger": ledger}), ledger


def test_frozen_materials_surface_the_planted_numbers(frozen_run):
    state, ledger = frozen_run

    assert len(ledger) == 52
    found = numeric_audit.conflicts(state)

    metrics = {conflict.metric for conflict in found}
    assert {"营业收入", "销售费用", "推广费", "归母净利润"} <= metrics
    assert all(conflict.factor == 10 for conflict in found)
    literals = {(conflict.lower.literal, conflict.higher.literal) for conflict in found}
    assert ("316.03亿元", "3160.3亿元") in literals
    assert ("90.89亿元", "900亿元") in literals


def test_report_renders_the_disagreement_before_the_evidence_appendix(frozen_run):
    state, _ = frozen_run
    rows = numeric_audit.describe(state, numeric_audit.conflicts(state))

    text = markdown(
        build_report(
            state,
            "partial",
            "The maximum number of committed steps was reached.",
            case_id="sanjiu-adversarial-2026-09",
            run_id="452e0b05aca84ad39fb0f9d4427cfb81",
            numeric_conflicts=rows,
        )
    )

    assert "## 数据口径存疑" in text
    assert text.index("## 数据口径存疑") < text.index("## 来源与证据")
    assert "316.03亿元" in text and "3160.3亿元" in text
    assert "不判断哪一方正确" in text


def test_report_without_a_ledger_has_no_numeric_section(frozen_run):
    state, _ = frozen_run
    text = markdown(
        build_report(state, "partial", "已经写完。", case_id="sanjiu-adversarial-2026-09",
                     run_id="452e0b05aca84ad39fb0f9d4427cfb81")
    )

    assert "## 数据口径存疑" not in text
