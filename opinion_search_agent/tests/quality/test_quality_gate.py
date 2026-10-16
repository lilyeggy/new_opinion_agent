"""The quality gate must say the same thing twice, from the files on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opinion_search.evaluation import metrics
from opinion_search.evaluation.bundle import load_bundle
from opinion_search.evaluation.gate import PACKAGE_ROOT, comparable, run_gate

CORPUS = PACKAGE_ROOT / "evaluation" / "corpus.json"
BASELINE = PACKAGE_ROOT / "artifacts" / "report-quality" / "quality-gate" / "baseline.json"

MATERIAL = "第一行\n机构称已退款100元。"
EXCERPT = "机构称已退款100元。"
URL = "https://example.org/1"


def _case(tmp_path: Path, *, excerpt: str, claim_refs: list[str]) -> dict:
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "abc.txt").write_text(MATERIAL, encoding="utf-8")
    state = {
        "run_id": "synthetic",
        "status": "completed",
        "stop_reason": "done",
        "committed_steps": 1,
        "domain_state": {
            "request": {"question": "退款", "time_scope": "2026-09"},
            "sources": [{
                "source_id": URL, "url": URL, "final_url": URL, "title": "材料",
                "source_kind": "reporting", "artifact_ref": "artifact://sha256/abc",
            }],
            "evidence": [{
                "evidence_id": "evidence-1", "source_id": URL, "excerpt": excerpt,
                "locator": "chars 0:12", "acquired_for_gap_id": "gap-1",
            }],
            "claims": [{
                "claim_id": "claim-1", "text": "机构称已退款。", "kind": "fact",
                "status": "supported", "supporting_evidence_ids": claim_refs,
                "contradicting_evidence_ids": [],
            }],
            "candidates": [{"url": URL, "title": "材料"}],
        },
    }
    (run_dir / "run.json").write_text(json.dumps({"state": state}, ensure_ascii=False), encoding="utf-8")
    return {"case_id": "synthetic", "domain": "opinion", "run_dir": "run"}


def test_excerpt_that_is_not_in_the_snapshot_is_a_mismatch(tmp_path):
    case = _case(tmp_path, excerpt="机构称已退款1000元。", claim_refs=["evidence-1"])
    grounding = metrics.excerpt_grounding(load_bundle(case, tmp_path))
    assert (grounding["verified"], grounding["mismatch"]) == (0, 1)
    assert grounding["grounding_rate"] == 0.0


def test_excerpt_inside_the_snapshot_is_verified(tmp_path):
    case = _case(tmp_path, excerpt=EXCERPT, claim_refs=["evidence-1"])
    grounding = metrics.excerpt_grounding(load_bundle(case, tmp_path))
    assert (grounding["verified"], grounding["mismatch"]) == (1, 0)


def test_dangling_evidence_reference_breaks_closure_and_grounding(tmp_path):
    case = _case(tmp_path, excerpt=EXCERPT, claim_refs=["evidence-999"])
    bundle = load_bundle(case, tmp_path)
    assert metrics.provenance_closure(bundle)["closure_rate"] < 1.0
    assert metrics.claim_grounding(bundle)["ungrounded_ids"] == ["claim-1"]


def test_metrics_change_only_when_the_frozen_input_changes(tmp_path):
    case = _case(tmp_path, excerpt=EXCERPT, claim_refs=["evidence-1"])
    first = load_bundle(case, tmp_path)
    second = load_bundle(case, tmp_path)
    assert metrics.excerpt_grounding(first) == metrics.excerpt_grounding(second)
    assert first.fingerprint == second.fingerprint


def test_gate_reproduces_the_committed_baseline(tmp_path):
    if not BASELINE.is_file():
        pytest.skip("committed baseline missing")
    cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
    missing = [case["run_dir"] for case in cases if not (PACKAGE_ROOT / case["run_dir"]).is_dir()]
    if missing:
        pytest.skip(f"frozen runs missing: {missing}")
    current = run_gate(CORPUS, PACKAGE_ROOT, tmp_path)
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert comparable(current) == comparable(expected)
