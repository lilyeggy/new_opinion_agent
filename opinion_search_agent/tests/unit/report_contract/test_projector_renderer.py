from opinion_search.report_contract.contracts import (
    ContentDocument,
    ContentModule,
    ContentSection,
    DataShape,
    ModuleState,
    PlannedModule,
    PlannedSection,
    PresentationPlan,
    VisualEncoding,
)
from opinion_search.report_contract.projector import (
    build_content_document_from_investigation,
    build_presentation_plan,
)
from opinion_search.report_contract.renderer import render_html


def test_projector_chooses_allowed_visual() -> None:
    content = ContentDocument(
        report_id="r1",
        revision=1,
        subject="测试事件",
        status="partial",
        generated_at="2026-09-16T12:00:00+08:00",
        sections=(
            ContentSection(
                section_id="overview",
                title="事件总览",
                order=1,
                modules=(
                    ContentModule(
                        module_id="m1",
                        semantic_type="event-summary",
                        title="事件概况",
                        state=ModuleState.READY,
                        data_shape=DataShape.CARDS,
                        summary="测试摘要",
                    ),
                ),
            ),
        ),
    )

    plan = build_presentation_plan(content)

    assert plan.source_content_revision == 1
    assert plan.sections[0].modules[0].selected_visual.value == "cards"


def test_renderer_outputs_module_title() -> None:
    content = ContentDocument(
        report_id="r2",
        revision=1,
        subject="测试事件",
        status="partial",
        generated_at="2026-09-16T12:00:00+08:00",
        sections=(
            ContentSection(
                section_id="overview",
                title="事件总览",
                order=1,
                modules=(
                    ContentModule(
                        module_id="m2",
                        semantic_type="event-summary",
                        title="事件概况",
                        state=ModuleState.READY,
                        data_shape=DataShape.CARDS,
                        summary="测试摘要",
                    ),
                ),
            ),
        ),
    )

    html_text = render_html(build_presentation_plan(content))

    assert "事件概况" in html_text
    assert "测试摘要" in html_text
    assert "data-module=\"event-summary\"" in html_text


def test_renderer_schema_adapter_prevents_blank_cards_and_english_table_headers() -> None:
    plan = PresentationPlan(
        source_content_revision=1,
        report_id="r-adapter",
        subject="跨组件字段自适应测试",
        status="completed",
        generated_at="2026-10-14T12:00:00+08:00",
        sections=(
            PlannedSection(
                section_id="s1",
                title="焦点拆解",
                order=1,
                view_id="focus",
                modules=(
                    PlannedModule(
                        module_id="m-cards-from-chinese-dict",
                        semantic_type="claim-matrix",
                        title="中文键字典转卡片",
                        state=ModuleState.READY,
                        data_shape=DataShape.COMPARISON,
                        selected_visual=VisualEncoding.CARDS,
                        items=(
                            {"专项维度": "执行标准", "核查内容": "夜间22时收车", "证据索引": "[引1]"},
                        ),
                    ),
                    PlannedModule(
                        module_id="m-table-from-english-dict",
                        semantic_type="issue-map",
                        title="英文键卡片转表格",
                        state=ModuleState.READY,
                        data_shape=DataShape.CARDS,
                        selected_visual=VisualEncoding.COMPARISON_TABLE,
                        items=(
                            {"title": "公众质疑", "summary": "班次减少导致通勤不便", "meta": "[引2] 市民反馈"},
                        ),
                    ),
                    PlannedModule(
                        module_id="m-debate-versus",
                        semantic_type="debate-comparison",
                        title="双方交锋对照",
                        state=ModuleState.READY,
                        data_shape=DataShape.COMPARISON,
                        selected_visual=VisualEncoding.DEBATE_VERSUS,
                        items=(
                            {
                                "争议焦点": "是否为现制工艺",
                                "_left_actor": "测评博主",
                                "_left_claim": "门店后厨使用冷冻基底 [引1]",
                                "_right_actor": "品牌声明",
                                "_right_claim": "门店每日鲜奶现煮 [引2]",
                                "证据索引": "[引1] [引2]",
                            },
                        ),
                    ),
                ),
            ),
        ),
    )

    html_text = render_html(plan)

    assert "执行标准" in html_text
    assert "夜间22时收车" in html_text
    assert "<th>核心事项</th>" in html_text
    assert "<th>核查结论与摘要</th>" in html_text
    assert "<th>title</th>" not in html_text
    assert "debate-versus-card" in html_text
    assert "测评博主" in html_text
    assert "品牌声明" in html_text


def test_build_content_document_from_investigation_synthesizes_focus_modules() -> None:
    report = {
        "run_id": "run-synth-1",
        "case_id": "case-synth-1",
        "subject": "某品牌雪糕现制争议",
        "question": "某品牌雪糕现制争议及回应",
        "status": "completed",
        "cutoff": "2026-10-14T10:00:00+08:00",
        "generated_at": "2026-10-14T10:05:00+08:00",
        "state_revision": 3,
        "sources": [
            {
                "version_id": "v1",
                "url": "https://example.com/1",
                "final_url": "https://example.com/1",
                "title": "消费者测评报道",
                "published_at": "2026-10-10",
                "fetched_at": "2026-10-14T10:00:00+08:00",
                "role": "media",
                "relation": "independent",
            },
            {
                "version_id": "v2",
                "url": "https://example.com/2",
                "final_url": "https://example.com/2",
                "title": "品牌方情况说明",
                "published_at": "2026-10-11",
                "fetched_at": "2026-10-14T10:01:00+08:00",
                "role": "party",
                "relation": "official_statement",
            },
        ],
        "evidence": [
            {
                "evidence_id": "e1",
                "version_id": "v1",
                "excerpt": "吐槽门店使用预制奶浆且定价高昂。",
                "start": 0,
                "end": 16,
                "locator": "chars 0:16",
            },
            {
                "evidence_id": "e2",
                "version_id": "v2",
                "excerpt": "声明全部门店采用鲜奶现场制作，但承认部分时段排队较长。",
                "start": 0,
                "end": 26,
                "locator": "chars 0:26",
            },
        ],
        "issues": [
            {"issue_id": "i1", "question": "核心制作工艺与定价争议是什么？", "status": "answered"},
        ],
        "findings": [
            {
                "finding_id": "f1",
                "issue_id": "i1",
                "text": "质疑门店使用预制奶浆且定价高昂。",
                "kind": "attributed",
                "stakeholder": "大V博主",
                "stance": "oppose",
                "stance_target": "门店制作工艺",
                "support": "supported",
                "active": True,
                "event_time": "2026年10月10日",
                "evidence_ids": ["e1"],
                "contradicting_ids": [],
            },
            {
                "finding_id": "f2",
                "issue_id": "i1",
                "text": "声明采用鲜奶现场制作，但未公开具体供应商批次清单。",
                "kind": "attributed",
                "stakeholder": "涉事品牌方",
                "stance": "support",
                "stance_target": "门店制作工艺",
                "response": "partial",
                "covered": ["鲜奶现制流程"],
                "uncovered": ["供应商批次清单"],
                "coverage_reason": "仅说明门店操作流程，未披露原料批次证明",
                "support": "supported",
                "active": True,
                "event_time": "2026-10-11",
                "evidence_ids": ["e2"],
                "contradicting_ids": [],
            },
        ],
        "conclusions": [
            {
                "finding_id": "f1",
                "text": "质疑门店使用预制奶浆且定价高昂。",
                "support": "supported",
                "evidence_ids": ["e1"],
            }
        ],
    }

    doc = build_content_document_from_investigation(report)
    plan = build_presentation_plan(doc)
    html_text = render_html(plan)

    focus_section = next(s for s in plan.sections if s.view_id == "focus")
    semantic_types = {m.semantic_type for m in focus_section.modules}
    assert "debate-comparison" in semantic_types
    assert "position-matrix" in semantic_types
    assert "response-coverage" in semantic_types
    assert "大V博主" in html_text
    assert "涉事品牌方" in html_text
    assert "供应商批次清单" in html_text


def test_provenance_cluster_weighting_and_relative_time_anchoring() -> None:
    report = {
        "run_id": "run-cluster",
        "case_id": "case-cluster",
        "state_revision": 2,
        "subject": "通稿去重与相对时间锚定测试",
        "question": "争议与回应",
        "status": "completed",
        "cutoff": "2026-10-15T12:00:00+08:00",
        "generated_at": "2026-10-15T12:00:00+08:00",
        "sources": [
            {"version_id": "v1", "title": "媒体A首发", "url": "https://a.example.com/1", "final_url": "https://a.example.com/1", "published_at": "2026-10-14T10:00:00+08:00", "role": "media"},
            {"version_id": "v2", "title": "媒体B转载通稿", "url": "https://b.example.com/1", "final_url": "https://b.example.com/1", "published_at": "2026-10-14T11:00:00+08:00", "role": "media"},
            {"version_id": "v3", "title": "官方通报", "url": "https://gov.example.com/1", "final_url": "https://gov.example.com/1", "published_at": "2026-10-15T09:00:00+08:00", "role": "official"},
        ],
        "source_relations": [
            {"relation_id": "r1", "source_version_id": "v1", "related_version_id": "v2", "relation": "repost", "basis_evidence_ids": ["e1", "e2"]},
        ],
        "evidence": [
            {"evidence_id": "e1", "version_id": "v1", "excerpt": "消费者质疑门店使用隔夜预制奶浆且单杯售价28元。", "locator": "p1"},
            {"evidence_id": "e2", "version_id": "v2", "excerpt": "消费者质疑门店使用隔夜预制奶浆且单杯售价28元。", "locator": "p1"},
            {"evidence_id": "e3", "version_id": "v3", "excerpt": "品牌方昨日发布声明称门店全部采用当日鲜奶现制。", "locator": "p2"},
        ],
        "issues": [
            {"issue_id": "i1", "question": "现制工艺争议", "status": "disputed", "required": True, "components": []},
        ],
        "findings": [
            {
                "finding_id": "f1",
                "issue_id": "i1",
                "text": "质疑门店使用隔夜奶浆，售价28元。",
                "kind": "concern",
                "stakeholder": "消费者",
                "stance": "oppose",
                "stance_target": "门店工艺",
                "active": True,
                "support": "supported",
                "event_time": "10月13日",
                "evidence_ids": ["e1", "e2"],
                "contradicting_ids": [],
            },
            {
                "finding_id": "f2",
                "issue_id": "i1",
                "text": "声明称全部采用当日鲜奶现制。",
                "kind": "fact",
                "stakeholder": "品牌方",
                "stance": "support",
                "stance_target": "门店工艺",
                "response": "direct",
                "coverage_reason": "正面回应了鲜奶现制问题",
                "active": True,
                "support": "supported",
                "event_time": "昨日",
                "evidence_ids": ["e3"],
                "contradicting_ids": [],
            },
        ],
        "conclusions": [],
    }
    doc = build_content_document_from_investigation(report)
    overview = next(s for s in doc.sections if s.view_id == "overview")
    tl_mod = next(m for m in overview.modules if m.semantic_type == "event-timeline")
    times = [item["time"] for item in tl_mod.items]
    assert any("2026-10-13（10月13日）" in t for t in times)
    assert any("2026-10-14（昨日）" in t for t in times)

    focus = next(s for s in doc.sections if s.view_id == "focus")
    debate_mod = next(m for m in focus.modules if m.semantic_type == "debate-comparison")
    # Even though f1 cites 2 evidence items (e1, e2), v1 and v2 are linked by a repost relation,
    # so independent cluster count is 1 (matching f2's 1 independent source cluster).
    assert debate_mod.items[0]["_left_count"] == 1
    assert debate_mod.items[0]["_right_count"] == 1

