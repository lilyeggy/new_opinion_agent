"""Workbench projection: deterministic modules, states and citation labels."""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    Finding, FindingProposal, InvestigationRequest, Issue, SourceVersion, State, Evidence,
    ReviewRecord, finding_hash, uid, utcnow,
)
from opinion_search.investigation.metrics import METRIC_DEF_VERSION
from opinion_search.investigation.report import build_report
from opinion_search.investigation.workbench import FORMAT, build_workbench, workbench_revision


def _state(sources=(), evidence=(), findings=(), reviews=()) -> State:
    issues = tuple(Issue(issue_id=f"issue-{i}", question=f"问题{i}", status="answered") for i in range(3))
    return State(request=InvestigationRequest(question="某市公交夜班车调整的争议与回应"), subject="夜班调整",
        cutoff=utcnow(), issues=issues, sources=sources, evidence=evidence, findings=findings, reviews=reviews)


def _source(version_id, published_at=None, duplicate_of=None) -> SourceVersion:
    return SourceVersion(version_id=version_id, url=f"https://a.example/{version_id}",
        final_url=f"https://a.example/{version_id}", title=f"来源{version_id}", fetched_at=utcnow(),
        published_at=published_at, artifact_ref="artifacts/x", content_hash="hash-" + version_id,
        duplicate_of=duplicate_of)


def _evidence(evidence_id, version_id) -> Evidence:
    return Evidence(evidence_id=evidence_id, version_id=version_id, excerpt="末班提前至22时", start=0, end=8,
        locator="Reader text chars 0:8")


def _finding(issue_id, evidence_ids, text="公告称末班提前。", event_time=None) -> Finding:
    proposal = FindingProposal(issue_id=issue_id, text=text, kind="attributed", stakeholder="交通部门",
        evidence_ids=evidence_ids, event_time=event_time)
    return Finding(**proposal.model_dump(), finding_id=uid("finding", issue_id, text))


def test_projection_is_deterministic_and_versioned():
    report = build_report(_state(), "completed", "完成", case_id="c", run_id="r1")
    first = build_workbench(report)
    second = build_workbench(report)
    assert first["format"] == FORMAT
    assert first["snapshot_id"] == second["snapshot_id"] == workbench_revision(report)
    assert first["modules"] == second["modules"]
    assert all(m["state"] in {"ready", "provisional", "insufficient", "unavailable", "not_applicable"} for m in first["modules"])
    assert first["views"]["overview"]["source_relation_counts"]["version_count"] == 0


def test_empty_report_keeps_modules_insufficient_without_inventing_content():
    report = build_report(_state(), "partial", "材料有限", case_id="c", run_id="r2")
    workbench = build_workbench(report)
    states = {m["module_type"]: m for m in workbench["modules"]}
    assert states["current-judgments"]["state"] == "insufficient"
    assert states["event-timeline"]["state"] == "insufficient"
    assert states["publication-distribution"]["state"] == "insufficient"
    assert workbench["views"]["overview"]["judgments"] == []
    assert workbench["views"]["overview"]["publication_distribution"] is None


def test_citation_labels_are_human_readable_markers():
    state = _state(sources=(_source("v1"),), evidence=(_evidence("evidence-abcdef1234567890", "v1"),),
        findings=(_finding("issue-0", ("evidence-abcdef1234567890",)),))
    report = build_report(state, "completed", "完成", case_id="c", run_id="r3")
    workbench = build_workbench(report)
    assert list(workbench["citations"]) == ["evidence-abcdef1234567890"]
    citation = workbench["citations"]["evidence-abcdef1234567890"]
    assert citation["label"] == "引1" and citation["source_title"] == "来源v1"
    # findings keep the binding needed for click-through, labels stay presentable
    assert workbench["views"]["issues"]["issues"][0]["findings"][0]["citations"]["support"] == ["evidence-abcdef1234567890"]


def test_duplicate_sources_are_counted_without_claiming_independence():
    state = _state(sources=(_source("v1"), _source("v2", duplicate_of="v1"), _source("v3")))
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r4")
    workbench = build_workbench(report)
    counts = workbench["views"]["overview"]["source_relation_counts"]
    assert counts["version_count"] == 3
    assert counts["identified_duplicate_count"] == 1
    assert counts["unverified_relation_count"] == 2
    materials = workbench["views"]["coverage"]["materials"]
    assert [m["relation"] for m in materials] == ["unverified", "duplicate", "unverified"]


def test_materials_order_unknown_dates_last_and_distribution_splits_unknown():
    state = _state(sources=(_source("v1"), _source("v2", published_at=utcnow()), _source("v3")))
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r5")
    workbench = build_workbench(report)
    materials = workbench["views"]["coverage"]["materials"]
    assert materials[-1]["published_at"] is None
    assert workbench["views"]["coverage"]["unknown_date_count"] == 2
    distribution = workbench["views"]["overview"]["publication_distribution"]
    assert distribution is not None and distribution["unknown_count"] == 2


def test_distribution_counts_documents_not_versions_and_binds_members():
    from datetime import timedelta

    stamp = utcnow()
    v1 = SourceVersion(version_id="v1", url="https://a.example/doc", final_url="https://a.example/doc",
        title="页面", fetched_at=stamp, published_at=stamp, artifact_ref="artifacts/a", content_hash="h1")
    v1b = v1.model_copy(update={"version_id": "v1b", "content_hash": "h2", "fetched_at": stamp + timedelta(hours=1)})
    other = _source("v2", published_at=stamp + timedelta(days=1))
    report = build_report(_state(sources=(v1, v1b, other)), "partial", "no findings", case_id="c", run_id="r8")
    distribution = build_workbench(report)["views"]["overview"]["publication_distribution"]
    assert [b["count"] for b in distribution["buckets"]] == [1, 1], "same URL with two body versions counts once"
    first = distribution["buckets"][0]["members"][0]
    assert first["version_ids"] == ["v1", "v1b"]
    total_members = sum(len(m["version_ids"]) for b in distribution["buckets"] for m in b["members"])
    assert total_members == 3


def test_unparsable_event_times_are_listed_separately_without_sorting():
    shared = (_evidence("e1", "v1"),)
    findings = (_finding("issue-0", ("e1",), text="无法定位的时间", event_time="2026年春节前后"),
                _finding("issue-1", ("e1",), text="早先节点", event_time="2026-01-02"),
                _finding("issue-2", ("e1",), text="较晚节点", event_time="2026-01-10"))
    state = _state(sources=(_source("v1"),), evidence=shared, findings=findings)
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r6")
    workbench = build_workbench(report)
    timeline = workbench["views"]["overview"]["timeline"]
    assert [node["event_time"] for node in timeline["events"]] == ["2026-01-02", "2026-01-10"]
    assert [node["event_time"] for node in timeline["unparsed"]] == ["2026年春节前后"]


def test_review_verdict_flows_into_judgement_display():
    finding = _finding("issue-0", ("e1",))
    review = ReviewRecord(finding_id=finding.finding_id, verdict="partial", reason="限定说明",
        finding_hash=finding_hash(finding), model="test", reviewed_at=utcnow())
    state = _state(sources=(_source("v1"),), evidence=(_evidence("e1", "v1"),), findings=(finding,), reviews=(review,))
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r7")
    workbench = build_workbench(report)
    assert workbench["views"]["issues"]["issues"][0]["findings"][0]["review"] == "partial"


def test_publication_distribution_carries_its_metric_definition():
    from datetime import timedelta

    stamp = utcnow()
    v1 = SourceVersion(version_id="v1", url="https://a.example/doc", final_url="https://a.example/doc",
        title="页面", fetched_at=stamp, published_at=stamp, artifact_ref="artifacts/a", content_hash="h1")
    other = _source("v2", published_at=stamp + timedelta(days=1))
    report = build_report(_state(sources=(v1, other)), "partial", "no findings", case_id="c", run_id="r9")
    distribution = build_workbench(report)["views"]["overview"]["publication_distribution"]
    assert distribution["metric_def_version"] == METRIC_DEF_VERSION
    assert "同 URL 多个正文版本按一个文档计" in distribution["inclusion"]
    rebuilt = build_workbench(build_report(_state(sources=(v1, other)), "partial", "no findings", case_id="c", run_id="r9"))
    assert distribution["material_set_version"] == rebuilt["views"]["overview"]["publication_distribution"]["material_set_version"]
    changed = build_workbench(build_report(_state(sources=(v1,)), "partial", "no findings", case_id="c", run_id="r9"))
    assert distribution["material_set_version"] != changed["views"]["overview"]["publication_distribution"]["material_set_version"]


def test_issue_involvement_counts_match_the_drilldown_membership():
    shared = (_evidence("e1", "v1"), _evidence("e2", "v2"))
    findings = (_finding("issue-0", ("e1",)), _finding("issue-1", ("e1", "e2"), text="反驳意见"),
                _finding("issue-2", ("e2",), text="未激活的判断"))
    state = _state(sources=(_source("v1"), _source("v2")), evidence=shared, findings=findings)
    state = state.model_copy(update={"findings": tuple(
        f.model_copy(update={"active": False}) if f.text == "未激活的判断" else f for f in state.findings)})
    report = build_report(state, "partial", "no findings", case_id="c", run_id="r10")
    workbench = build_workbench(report)
    issues = {entry["issue_id"]: entry for entry in workbench["views"]["issues"]["issues"]}
    # one version cited by two issues counts once per issue and repeats across issues
    assert issues["issue-0"]["involved_materials"]["count"] == 1
    assert issues["issue-1"]["involved_materials"]["count"] == 2
    assert issues["issue-1"]["involved_materials"]["members"] == ["v1", "v2"]
    assert issues["issue-1"]["involved_materials"]["members_hash"] == issues["issue-1"]["involved_materials"]["members_hash"]
    # an inactive finding must not contribute members
    assert issues["issue-2"]["involved_materials"]["count"] == 0
    assert issues["issue-2"]["involved_materials"]["members"] == []
    # members mirror the coverage filter basis: citations (support + contradict) of active findings
    for entry in workbench["views"]["issues"]["issues"]:
        cited_versions = {item["version_id"] for material in workbench["views"]["coverage"]["materials"]
                          for item in [material] if set(material["citation_ids"]) &
                          {eid for f in entry["findings"]
                           for eid in f["citations"]["support"] + f["citations"]["contradict"]}}
        assert len(cited_versions) == entry["involved_materials"]["count"]
