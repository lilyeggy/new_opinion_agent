"""Frozen-material mechanism replay for the two complete synthetic event kits.

These cases verify that a case keeps its own materials, questions, modules,
components, source relation of fact and targeted-update semantics end to end.
They are deliberately marked mechanism-only: passing them is not live-search or
human-quality evidence, and the ten real-material slots in the registry remain
blocked until genuine snapshots and annotations exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPLAY_INDEX = Path(__file__).parent / "replay_cases" / "index.json"
REPLAY_CASES = json.loads(REPLAY_INDEX.read_text(encoding="utf-8"))["cases"]


def _module_map(run_id, manager):
    return {module["module_type"]: module for module in manager.workbench(run_id)["modules"]}


def _module_field(module, key):
    return next((field for field in module.get("fields", []) if field.get("key") == key), None)


@pytest.mark.parametrize("case", REPLAY_CASES, ids=[case["case_id"] for case in REPLAY_CASES])
def test_replay_case_keeps_its_own_frozen_semantics(case, manager, run_offline, wait_for_terminal):
    assert case["quality_claim"] == "mechanism_only"
    expected = case["expect"]
    parent = run_offline(manager, dict(case["request"]))
    run_id = parent["run_id"]
    assert manager.load(run_id)["fixture"] == case["fixture"]

    report = parent["report"]
    assert all(word in report["subject"] for word in expected["subject_contains"])
    assert report["profile"]["facets"] == expected["facets"]
    assert {source["title"] for source in report["sources"]} == set(expected["source_titles"])
    assert set(expected["search_purposes"]) <= {attempt["purpose"] for attempt in report["searches"]}

    all_finding_text = " ".join(finding["text"] for finding in report["findings"])
    for keyword in expected["finding_keywords"]:
        assert keyword in all_finding_text, (case["case_id"], keyword, all_finding_text)

    visible_text = report["subject"] + " " + all_finding_text
    visible_text += " " + " ".join(source["title"] for source in report["sources"])
    for forbidden in expected["forbidden_terms"]:
        assert forbidden not in visible_text, (case["case_id"], forbidden, visible_text)

    component_text = " ".join(component["text"] for issue in report["issues"]
                              for component in issue.get("components", []))
    for component in expected["component_texts"]:
        assert component in component_text, (case["case_id"], component, component_text)

    modules = _module_map(run_id, manager)
    for module_type, state in expected["module_states"].items():
        assert modules[module_type]["state"] == state, (case["case_id"], module_type, modules[module_type])
    for module_type, fields in expected["module_fields"].items():
        module = modules[module_type]
        for key, value in fields.items():
            field = _module_field(module, key)
            assert field is not None and field["state"] == "known", (case["case_id"], module_type, key)
            assert value in field.get("value", ""), (case["case_id"], key, field)

    update = case["update"]
    target = next(issue for issue in report["issues"]
                  if update["question_marker"] in issue["question"])
    child = manager.create({"issue_ids": [target["issue_id"]], "client_request_id": case["case_id"] + "-update"},
                           parent_id=run_id)
    child = wait_for_terminal(manager, child["run_id"])
    assert manager.load(child["run_id"])["fixture"] == case["fixture"]
    child_modules = _module_map(child["run_id"], manager)
    child_field = _module_field(child_modules[update["module_type"]], update["field_key"])
    assert child_field is not None and child_field["state"] == "known", (case["case_id"], child_field)
    assert update["field_contains"] in child_field.get("value", ""), (case["case_id"], child_field)


def test_replay_cases_do_not_claim_live_or_human_quality():
    assert REPLAY_CASES
    assert all(case["quality_claim"] == "mechanism_only" for case in REPLAY_CASES)
    registry = json.loads((Path(__file__).parent / "cases" / "registry.json").read_text(encoding="utf-8"))
    assert all(case["status"] == "blocked" for case in registry["cases"])
