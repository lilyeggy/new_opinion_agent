"""Self-contained HTML export: one snapshot, escaped content, inlined excerpts."""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    Evidence, EventProfile, Finding, FindingProposal, InvestigationRequest, Issue, SourceVersion,
    State, uid, utcnow,
)
from opinion_search.investigation.export import render_page
from opinion_search.investigation.report import build_report
from opinion_search.investigation.workbench import build_workbench

EXCERPT = "末班提前至22时"


def _state(source_title="来源v1") -> State:
    issues = tuple(Issue(issue_id=f"issue-{i}", question=f"问题{i}", status="answered") for i in range(3))
    source = SourceVersion(version_id="v1", url="https://a.example/1", final_url="https://a.example/1",
        title=source_title, fetched_at=utcnow(), published_at=utcnow(),
        artifact_ref="artifacts/x", content_hash="h1")
    evidence = Evidence(evidence_id="evidence-secret-id", version_id="v1", excerpt=EXCERPT, start=0, end=8,
        locator="Reader text chars 0:8")
    proposal = FindingProposal(issue_id="issue-0", text="公告称末班提前。", kind="attributed",
        stakeholder="交通部门", evidence_ids=("evidence-secret-id",), event_time="2026-01-10")
    finding = Finding(**proposal.model_dump(), finding_id=uid("finding", "f1"))
    return State(request=InvestigationRequest(question="某市公交夜班车调整"), subject="夜班调整",
        cutoff=utcnow(), issues=issues, sources=(source,), evidence=(evidence,), findings=(finding,),
        profile=EventProfile(facets=("rule_change",), rationale="规则变化"))


def _page(state=None, status="completed", contexts=None):
    state = state or _state()
    report = build_report(state, status, "完成", case_id="c", run_id="r1")
    workbench = build_workbench(report)
    return render_page(workbench, report=report, evidence_context=contexts or {})


def test_export_is_one_self_contained_document_bound_to_one_snapshot():
    state = _state()
    report = build_report(state, "completed", "完成", case_id="c", run_id="r1")
    workbench = build_workbench(report)
    page = render_page(workbench, report=report)
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert "<style>" in page and "/assets/workbench.css" not in page, "export must inline its stylesheet"
    assert workbench["snapshot_id"] in page
    assert "引1" in page


def test_export_never_prints_internal_evidence_ids():
    page = _page()
    assert "evidence-secret-id" not in page


def test_export_escapes_untrusted_material_text():
    page = _page(_state(source_title="<script>alert('x')</script>"))
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_export_inlines_excerpt_context_and_marks_the_locator():
    page = _page(contexts={"evidence-secret-id": {"before": "前文。", "after": "后文。"}})
    assert EXCERPT in page and "<mark>" in page
    assert "前文。" in page and "后文。" in page
    assert "Reader text chars 0:8" in page


def test_export_states_missing_evidence_and_module_gaps_honestly():
    state = _state()
    report = build_report(state, "partial", "材料有限", case_id="c", run_id="r2")
    workbench = build_workbench(report)
    workbench["citations"]["ghost"] = {"index": 9, "label": "引9", "source_title": "缺失来源", "version_id": "v-missing"}
    page = render_page(workbench, report=report)
    assert "该引用缺少可核对的保存正文" in page
    assert "仍缺" in page or "材料不足" in page


def test_export_marks_a_running_projection_as_unreviewed():
    page = _page(status="running")
    assert "阶段投影，待核查" in page or "调查进行中" in page
    assert "静态导出" in page


def test_export_flags_offline_fixture_materials():
    state = _state()
    report = build_report(state, "completed", "完成", case_id="c", run_id="r3", mode="offline")
    page = render_page(build_workbench(report), report=report)
    assert "虚构材料演示" in page


def test_export_renders_facet_module_cards_instead_of_template_literals():
    page = _page()  # _state() carries the rule_change facet
    assert "{cards}" not in page, "projection fields must be interpolated, never printed"
    assert "新旧规则对照" in page


def test_export_shows_per_issue_material_counts_from_the_snapshot():
    page = _page()
    assert "涉及材料：1 篇" in page
