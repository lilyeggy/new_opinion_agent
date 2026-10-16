from opinion_search.presentation_skill.llm_planner import (
    DynamicItemProposal,
    DynamicModuleProposal,
    LlmPresentationPlanner,
    VisualChoice,
    VisualPlanOutput,
)
from opinion_search.report_contract.contracts import (
    CitationRef,
    ContentDocument,
    ContentModule,
    ContentSection,
    DataShape,
    ModuleState,
)
from opinion_search.report_contract.projector import build_presentation_plan


class FakeModel:
    def __init__(self, decision: object):
        self._decision = decision
        self.last_context = None

    async def decide(self, context):
        self.last_context = context
        return self._decision


def _content() -> ContentDocument:
    return ContentDocument(
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
                view_id="overview",
                modules=(
                    ContentModule(
                        module_id="m1",
                        semantic_type="event-summary",
                        title="事件概况",
                        state=ModuleState.READY,
                        data_shape=DataShape.CARDS,
                        summary="测试摘要",
                        items=({"title": "核心结论", "summary": "共涉及 3 条线路调整"},),
                    ),
                ),
            ),
            ContentSection(
                section_id="focus",
                title="争议交锋",
                order=2,
                view_id="focus",
                modules=(),
            ),
        ),
    )


def test_llm_presentation_planner_applies_allowed_visual_choice() -> None:
    base_plan = build_presentation_plan(_content())
    model = FakeModel(
        VisualPlanOutput(
            choices=(
                VisualChoice(module_id="m1", selected_visual="text", reason="更适合纯文本"),
            )
        )
    )

    plan = LlmPresentationPlanner(model).plan(base_plan)

    assert plan.sections[0].modules[0].selected_visual.value == "text"
    assert plan.sections[0].modules[0].selection_reason == "更适合纯文本"


def test_llm_presentation_planner_validates_dynamic_modules_and_guards_unbacked_numbers() -> None:
    base_plan = build_presentation_plan(_content())
    findings_by_id = {
        "f1": {
            "finding_id": "f1",
            "stakeholder": "消费者",
            "stance": "oppose",
            "text": "质疑门店宣称现做但使用了隔夜奶浆，售价 28 元。",
            "evidence_ids": ["e1"],
        },
        "f2": {
            "finding_id": "f2",
            "stakeholder": "品牌方",
            "stance": "support",
            "text": "回应称采用当天鲜奶现制，单杯定价 28 元符合原料成本。",
            "evidence_ids": ["e2"],
        },
    }
    evidence_by_id = {
        "e1": {"evidence_id": "e1", "excerpt": "门店宣称现做但使用了隔夜奶浆，售价 28 元"},
        "e2": {"evidence_id": "e2", "excerpt": "采用当天鲜奶现制，单杯定价 28 元"},
    }
    citation_labels = {"e1": "引1", "e2": "引2"}
    citation_refs = {
        "e1": CitationRef(evidence_id="e1", source_version_id="v1", label="[引1] 报道A", excerpt="售价 28 元"),
        "e2": CitationRef(evidence_id="e2", source_version_id="v2", label="[引2] 声明B", excerpt="定价 28 元"),
    }

    model = FakeModel(
        VisualPlanOutput(
            dynamic_modules=(
                DynamicModuleProposal(
                    module_id="dyn-versus",
                    semantic_type="debate-comparison",
                    title="现制工艺与定价争议正反交锋",
                    selected_visual="debate_versus",
                    reason="存在直接对立主张",
                    table_columns=("争议焦点", "质疑与批评主张", "回应与抗辩主张", "证据索引"),
                    items=(
                        DynamicItemProposal(
                            cells={
                                "争议焦点": "现制工艺与 28 元定价",
                                "质疑与批评主张": "质疑使用隔夜奶浆，售价 28 元",
                                "回应与抗辩主张": "回应称当天鲜奶现制，定价 28 元",
                            },
                            source_finding_ids=("f1", "f2"),
                        ),
                        # Second item injects an unbacked number "99%" -> must trigger deterministic fallback
                        DynamicItemProposal(
                            cells={
                                "争议焦点": "原料比例",
                                "质疑与批评主张": "高达 99% 的门店使用预制料",
                            },
                            source_finding_ids=("f1",),
                        ),
                        # Third item has unknown finding_id -> must be dropped
                        DynamicItemProposal(
                            cells={"争议焦点": "无依据条目"},
                            source_finding_ids=("unknown-id",),
                        ),
                    ),
                ),
            )
        )
    )

    plan = LlmPresentationPlanner(model).plan(
        base_plan,
        findings_by_id=findings_by_id,
        evidence_by_id=evidence_by_id,
        citation_labels=citation_labels,
        citation_refs=citation_refs,
    )

    focus_section = next(s for s in plan.sections if s.view_id == "focus")
    assert len(focus_section.modules) == 1
    dyn_mod = focus_section.modules[0]
    assert dyn_mod.selected_visual.value == "debate_versus"
    assert len(dyn_mod.items) == 2
    # First item passes numeric verification and receives inline citation badges
    assert "[引1]" in dyn_mod.items[0]["证据索引"]
    assert "[引2]" in dyn_mod.items[0]["证据索引"]
    # Second item had unbacked "99%" -> fell back to verbatim finding text without "99%"
    assert "99%" not in str(dyn_mod.items[1])
    assert "28 元" in dyn_mod.items[1]["核查判断"]
    assert "未锚定数值" in dyn_mod.selection_reason


def test_manager_publish_dossier_artifacts_persists_plan_and_html(tmp_path) -> None:
    from opinion_search.investigation.manager import Manager
    from opinion_search.investigation.workbench import build_workbench

    run_id = "a" * 32
    run_root = tmp_path / "runs" / run_id
    run_root.mkdir(parents=True)
    report = {
        "schema_version": 2,
        "case_id": "b" * 32,
        "run_id": run_id,
        "mode": "live",
        "subject": "野人先生现制工艺与定价争议",
        "question": "野人先生现制工艺与定价争议",
        "status": "completed",
        "stop_reason": "completed",
        "cutoff": "2026-10-14T10:00:00+08:00",
        "generated_at": "2026-10-14T10:00:00+08:00",
        "required_questions": [],
        "issues": [
            {
                "issue_id": "i1",
                "question": "现制工艺与定价是否存在争议？",
                "status": "supported_with_dispute",
                "required": True,
                "origin_questions": [],
                "components": [],
                "evidence_ids": ["e1", "e2"],
                "note": "存在正反争议",
            }
        ],
        "findings": [
            {
                "finding_id": "f1",
                "issue_id": "i1",
                "text": "消费者质疑使用冷冻奶浆且单杯售价 28 元偏高。",
                "kind": "concern",
                "stakeholder": "消费者",
                "stance": "oppose",
                "stance_target": "野人先生",
                "response": "none",
                "evidence_ids": ["e1"],
                "contradicting_ids": [],
                "active": True,
                "review": "supported",
            },
            {
                "finding_id": "f2",
                "issue_id": "i1",
                "text": "品牌方回应称门店当天鲜奶现做，28 元定价符合原料成本。",
                "kind": "fact",
                "stakeholder": "野人先生",
                "stance": "support",
                "stance_target": "现制工艺",
                "response": "direct",
                "evidence_ids": ["e2"],
                "contradicting_ids": [],
                "active": True,
                "review": "supported",
            },
        ],
        "retired": [],
        "conclusions": [],
        "sources": [
            {
                "version_id": "v1",
                "url": "https://example.com/1",
                "final_url": "https://example.com/1",
                "title": "报道A",
                "fetched_at": "2026-10-14T09:00:00+08:00",
                "published_at": "2026-10-13T09:00:00+08:00",
                "updated_at": None,
                "content_hash": "h1",
                "artifact_ref": "a1",
                "role": "reporting",
            }
        ],
        "evidence": [
            {"evidence_id": "e1", "version_id": "v1", "excerpt": "消费者质疑使用冷冻奶浆且单杯售价 28 元偏高。", "start": 0, "end": 22, "locator": "p1"},
            {"evidence_id": "e2", "version_id": "v1", "excerpt": "品牌方回应称门店当天鲜奶现做，28 元定价符合原料成本。", "start": 23, "end": 50, "locator": "p2"},
        ],
        "source_relations": [],
        "searches": [],
        "read_errors": [],
        "changes": [],
        "no_material_change": False,
        "budget": {"search": 1, "read": 1, "model": 2, "elapsed_seconds": 5},
    }
    projection = build_workbench(report)
    mgr = Manager(tmp_path)
    model = FakeModel(
        VisualPlanOutput(
            dynamic_modules=(
                DynamicModuleProposal(
                    module_id="dyn-versus",
                    semantic_type="debate-comparison",
                    title="现制工艺正反交锋",
                    selected_visual="debate_versus",
                    reason="正反交锋鲜明",
                    items=(
                        DynamicItemProposal(
                            cells={"争议焦点": "现制与 28 元定价", "质疑与批评主张": "质疑冷冻奶浆售价 28 元", "回应与抗辩主张": "回应鲜奶现做 28 元合理"},
                            source_finding_ids=("f1", "f2"),
                        ),
                    ),
                ),
            )
        )
    )
    mgr._publish_dossier_artifacts(run_root, report, projection, planner_model=model)
    assert (run_root / "presentation_plan.json").is_file()
    assert (run_root / "dossier.html").is_file()
    html_text = (run_root / "dossier.html").read_text(encoding="utf-8")
    assert "debate-versus-card" in html_text
    assert "vs-tug-bar" in html_text
    assert "relation-graph-svg" in html_text
    assert "stance-swimlanes" in html_text



