"""Controlled one-pass baseline uses frozen input and auditable citations."""

from __future__ import annotations

from hashlib import sha256
import json

import pytest

from opinion_search.investigation.baseline import (
    BaselineAnswer, BaselineCitation, BaselineClaim, BaselineReport,
    baseline_payload, resolve_citations, run_baseline,
)
from opinion_search.investigation.replay import load_replay_case


def _case(tmp_path):
    contents = ["第一行\n机构称已退款100元。", "报道转述该机构说明。\n第二行"]
    materials = []
    for index, content in enumerate(contents, 1):
        path = tmp_path / f"m{index:02d}.txt"
        path.write_text(content, encoding="utf-8")
        materials.append({
            "url": f"https://example.org/{index}",
            "title": f"材料{index}",
            "snapshot_path": path.name,
            "sha256": sha256(content.encode()).hexdigest(),
            "role": "original" if index == 1 else "reporting",
        })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "case_id": "baseline-case",
        "request_question": "核对退款回应及证据边界",
        "materials": materials,
    }, ensure_ascii=False), encoding="utf-8")
    return manifest


def _report(citation=None):
    citation = citation or BaselineCitation(material_id="m01", line_start=2, line_end=2)
    return BaselineReport(
        subject="退款回应",
        current_status="机构称已退款，缺少到账独立核验。",
        answers=(BaselineAnswer(question="是否退款", disposition="answered",
                                answer="机构作出退款表述。", citations=(citation,)),),
        claims=(BaselineClaim(text="机构称已退款100元。", kind="attributed",
                              stakeholder="机构", citations=(citation,)),),
        key_unknowns=("是否实际到账",),
        scope_limitation="仅使用两份冻结材料。",
    )


def test_baseline_payload_contains_materials_but_no_expected_answers(tmp_path):
    case = load_replay_case(_case(tmp_path), require_snapshot_hashes=True)
    payload = baseline_payload(case)
    assert [item["material_id"] for item in payload["materials"]] == ["m01", "m02"]
    assert "L2: 机构称已退款100元。" in payload["materials"][0]["content_with_line_numbers"]
    assert "expected" not in json.dumps(payload, ensure_ascii=False)


def test_resolve_citations_rejects_unknown_or_out_of_bounds_lines(tmp_path):
    case = load_replay_case(_case(tmp_path), require_snapshot_hashes=True)
    with pytest.raises(ValueError, match="exceeds"):
        resolve_citations(_report(BaselineCitation(material_id="m01", line_start=9, line_end=9)), case)
    resolved = resolve_citations(_report(), case)
    assert resolved["claims"][0]["citations"][0]["excerpt"] == "机构称已退款100元。"


def test_run_baseline_persists_input_output_and_resolved_citations(tmp_path):
    class FakeModel:
        async def decide(self, _context):
            return _report()

    root = tmp_path / "run"
    result = run_baseline(root, _case(tmp_path), model=FakeModel(), request_limit=2)
    assert result["status"] == "completed"
    assert (root / "input.rendered.txt").is_file()
    assert json.loads((root / "citations.json").read_text())["claims"][0]["citations"][0]["line_start"] == 2
    assert "缺少到账独立核验" in (root / "report.md").read_text()
