"""Offline demo kits must never mix one event's materials with another's story."""

from __future__ import annotations


def test_bus_and_water_offline_kits_stay_separate(manager, run_offline):
    bus = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    water = run_offline(manager, {"question": "某市水费计费争议与回应"})

    bus_text = bus["report"]["subject"] + " ".join(
        finding["text"] for finding in bus["report"]["findings"])
    bus_text += " ".join(source["title"] for source in bus["report"]["sources"])
    water_text = water["report"]["subject"] + " ".join(
        finding["text"] for finding in water["report"]["findings"])
    water_text += " ".join(source["title"] for source in water["report"]["sources"])

    assert "公交" in bus_text and "夜班" in bus_text
    assert "水价" not in bus_text and "计费" not in bus_text
    assert "阶梯水价" in water_text or "水费" in water_text
    assert "末班" not in water_text and "公交" not in water_text

    assert bus["report"]["profile"]["facets"] == ["rule_change"]
    assert water["report"]["profile"]["facets"] == ["billing_remedy"]
    bus_modules = {module["module_type"] for module in manager.workbench(bus["run_id"])["modules"]}
    water_modules = {module["module_type"] for module in manager.workbench(water["run_id"])["modules"]}
    assert "rule-comparison" in bus_modules and "billing-remedy" not in bus_modules
    assert "billing-remedy" in water_modules and "rule-comparison" not in water_modules


def test_water_update_uses_water_fixture_response(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市水费计费争议与回应"})
    response_issue = next(issue for issue in parent["report"]["issues"] if "机构回应" in issue["question"])
    child = manager.create({"issue_ids": [response_issue["issue_id"]], "client_request_id": "water-target"},
                           parent_id=parent["run_id"])
    child = wait_for_terminal(manager, child["run_id"])
    texts = [finding["text"] for finding in child["report"]["findings"]
             if finding["issue_id"] == response_issue["issue_id"]]
    assert any("按原渠道退回" in text for text in texts)
    assert all("接驳车" not in text and "末班" not in text for text in texts)


def test_update_keeps_parent_fixture_even_when_focus_uses_price_words(manager, run_offline, wait_for_terminal):
    parent = run_offline(manager, {"question": "某市公交夜班车调整的争议与回应"})
    created = manager.create({"focus": "补充票价与退费口径的说明"}, parent_id=parent["run_id"])
    assert manager.load(created["run_id"])["fixture"] == "bus"
    child = wait_for_terminal(manager, created["run_id"])
    text = child["report"]["subject"] + " ".join(finding["text"] for finding in child["report"]["findings"])
    text += " ".join(source["title"] for source in child["report"]["sources"])
    assert "阶梯水价" not in text and "居民" not in text
    assert "公交" in text or "夜班" in text
