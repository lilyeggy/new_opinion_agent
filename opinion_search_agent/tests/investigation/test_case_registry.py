"""A: the real-case dataset registry must be complete, split, and honestly blocked."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

REGISTRY_PATH = Path(__file__).parent / "cases" / "registry.json"
CATEGORIES = {"公共交通", "公共设施", "文旅服务", "服务规则调整", "机构回应与修正"}


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_has_ten_cases_covering_every_category(registry):
    cases = registry["cases"]
    assert len(cases) == 10
    assert {case["category"] for case in cases} == CATEGORIES
    for category in CATEGORIES:
        splits = {case["split"] for case in cases if case["category"] == category}
        assert splits == {"dev", "holdout"}


def test_case_ids_are_unique_and_suffixed(registry):
    for case in registry["cases"]:
        assert case["case_id"].endswith("-dev") or case["case_id"].endswith("-holdout")
        assert (case["split"] == "dev") == case["case_id"].endswith("-dev")
    assert len({case["case_id"] for case in registry["cases"]}) == 10


def test_materials_are_never_fabricated(registry):
    for case in registry["cases"]:
        if case["status"] == "blocked":
            # A blocked case must not carry invented material or claimed gold answers.
            assert case["materials"] == []
            assert case["expected"] == {}
            assert case["annotation"]["reviewed_by_human"] is False
            assert case["annotation"]["author_kind"] == "none"
        else:
            for material in case["materials"]:
                assert material.get("snapshot_path") and material.get("sha256")
                assert len(material["sha256"]) == 64
                snapshot = REGISTRY_PATH.parent / material["snapshot_path"]
                if snapshot.is_file():
                    assert sha256(snapshot.read_bytes()).hexdigest() == material["sha256"]
                else:
                    assert case.get("material_storage") == "local_untracked"
                assert material.get("source_role") in {"original", "reporting", "commentary", "unknown"}
                assert isinstance(material.get("dependency_relations"), list)


def test_unreviewed_material_case_is_not_treated_as_gold(registry):
    collected = [case for case in registry["cases"] if case["status"] != "blocked"]
    assert {case["case_id"] for case in collected} == {"response-dev", "rules-dev"}
    for case in collected:
        assert case["material_storage"] == "local_untracked"
        assert case["annotation"]["author_kind"] == "model_preannotation"
        assert case["annotation"]["reviewed_by_human"] is False
        assert case["annotation"]["status"] == "UNREVIEWED"
        assert case["expected"] == {}


def test_holdout_answers_do_not_leak_into_production_code(registry):
    holdout = [case for case in registry["cases"] if case["split"] == "holdout"]
    assert len(holdout) == 5
    source_root = Path(__file__).resolve().parents[2] / "src" / "opinion_search"
    haystack = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in source_root.rglob("*.py")
    )
    for case in holdout:
        assert case["event_identity"] not in haystack
