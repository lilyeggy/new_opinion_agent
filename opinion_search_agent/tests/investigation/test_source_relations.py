"""Source relations are model-proposed but program-bound to source evidence."""

from __future__ import annotations

import pytest

from opinion_search.domain.investigation.engine import Validator, reduce_state
from opinion_search.domain.investigation.models import (
    Delta, Evidence, InvestigationRequest, Issue, Observation, ReflectDecision,
    SourceRelationProposal, SourceVersion, State, uid, utcnow,
)
from opinion_search.investigation.report import build_report
from opinion_search.investigation.workbench import build_workbench


def _state() -> State:
    stamp = utcnow()
    issues = tuple(Issue(issue_id=uid("issue", text), question=text) for text in ("发生了什么", "争议是什么", "回应如何"))
    sources = (
        SourceVersion(version_id="v1", url="https://example.org/a", final_url="https://example.org/a",
                      title="公告", fetched_at=stamp, artifact_ref="artifact://sha256/" + "6" * 64,
                      content_hash="6" * 64),
        SourceVersion(version_id="v2", url="https://news.example.org/a", final_url="https://news.example.org/a",
                      title="报道", fetched_at=stamp, artifact_ref="artifact://sha256/" + "7" * 64,
                      content_hash="7" * 64),
    )
    evidence = (
        Evidence(evidence_id="e1", version_id="v1", excerpt="公告称调整已生效。", start=0, end=len("公告称调整已生效。"), locator="chars 0:8"),
        Evidence(evidence_id="e2", version_id="v2", excerpt="报道称居民未收到通知。", start=0, end=len("报道称居民未收到通知。"), locator="chars 0:10"),
    )
    return State(request=InvestigationRequest(question="事件关系测试"), subject="事件关系测试",
                 cutoff=stamp, issues=issues, sources=sources, evidence=evidence)


def test_source_relation_requires_basis_from_its_two_versions():
    state = _state()
    foreign = SourceRelationProposal(source_version_id="v1", related_version_id="v2", relation="excerpt",
                                     basis_evidence_ids=("e1", "e2"), explanation="跨版本对照")
    Validator().validate(state, ReflectDecision(source_relations=(foreign,), reason="测试"))

    bad = SourceRelationProposal(source_version_id="v1", related_version_id="v2", relation="repost",
                                 basis_evidence_ids=("e1", "ghost"), explanation="错误引用")
    with pytest.raises(ValueError, match="unknown evidence"):
        Validator().validate(state, ReflectDecision(source_relations=(bad,), reason="测试"))


def test_source_relation_rejects_self_and_duplicate_pairs():
    state = _state()
    self_relation = SourceRelationProposal(source_version_id="v1", related_version_id="v1", relation="same_text",
                                           basis_evidence_ids=("e1",), explanation="自引用")
    with pytest.raises(ValueError, match="two known source versions"):
        Validator().validate(state, ReflectDecision(source_relations=(self_relation,), reason="测试"))

    first = SourceRelationProposal(source_version_id="v1", related_version_id="v2", relation="repost",
                                   basis_evidence_ids=("e1",), explanation="转载")
    second = SourceRelationProposal(source_version_id="v2", related_version_id="v1", relation="excerpt",
                                    basis_evidence_ids=("e2",), explanation="反向重复")
    with pytest.raises(ValueError, match="duplicate source relation pair"):
        Validator().validate(state, ReflectDecision(source_relations=(first, second), reason="测试"))


def test_reducer_and_report_persist_model_proposed_relation_without_calling_it_verified():
    state = _state()
    proposal = SourceRelationProposal(source_version_id="v1", related_version_id="v2", relation="repost",
                                      basis_evidence_ids=("e1",), explanation="报道转述公告")
    decision = ReflectDecision(source_relations=(proposal,), reason="测试")
    reduced = reduce_state(state, Delta(decision=decision, observation=Observation(action="reflect")))
    relation = reduced.relations[0]
    assert relation.relation_id.startswith("relation-")
    assert relation.relation == "repost"

    report = build_report(reduced, "partial", "无判断", case_id="c", run_id="relations")
    first = next(source for source in report["sources"] if source["version_id"] == "v1")
    second = next(source for source in report["sources"] if source["version_id"] == "v2")
    assert first["relation"] == "repost" and first["relation_status"] == "model_proposed"
    assert first["relation_evidence_ids"] == ["e1"]
    assert second["relation"] == "unverified"
    assert report["source_relation_counts"]["repost_count"] == 1
    assert report["source_relation_counts"]["model_relation_count"] == 1
    assert report["relations"][0]["relation"] == "repost"

    materials = build_workbench(report)["views"]["coverage"]["materials"]
    first_material = next(material for material in materials if material["version_id"] == "v1")
    assert first_material["relation_status"] == "model_proposed"
    assert first_material["relation_explanation"] == "报道转述公告"


def test_export_marks_model_proposed_relation_as_pending_human_review():
    from opinion_search.investigation.export import render_page
    from opinion_search.investigation.workbench import build_workbench

    state = _state()
    proposal = SourceRelationProposal(source_version_id="v1", related_version_id="v2", relation="repost",
                                      basis_evidence_ids=("e1",), explanation="报道转述公告")
    reduced = reduce_state(state, Delta(decision=ReflectDecision(source_relations=(proposal,), reason="测试"),
                                        observation=Observation(action="reflect")))
    report = build_report(reduced, "partial", "无判断", case_id="c", run_id="relations-export")
    page = render_page(build_workbench(report), report=report, evidence_context={})
    assert "转载/转述关系" in page
    assert "模型基于原文提出，待人工复核" in page
    assert "关系依据（模型提出，待人工复核）" in page
