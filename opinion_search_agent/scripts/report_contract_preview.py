from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opinion_search.report_contract.contracts import (  # noqa: E402
    CitationRef,
    ContentDocument,
    ContentModule,
    ContentSection,
    DataShape,
    ModuleState,
)
from opinion_search.report_contract.projector import build_presentation_plan  # noqa: E402
from opinion_search.report_contract.renderer import render_html  # noqa: E402
from opinion_search.report_contract.validator import validate_presentation_plan  # noqa: E402


def sample_document() -> ContentDocument:
    citation_1 = CitationRef(
        evidence_id="ev-001",
        source_version_id="src-001",
        label="官方公告",
        excerpt="自2026年10月1日起，市区公交线路基础票价由2元调整为3元。",
        locator="chars 120:160",
    )
    citation_2 = CitationRef(
        evidence_id="ev-002",
        source_version_id="src-002",
        label="听证会报道",
        excerpt="多位参会代表对调价幅度和配套优惠提出不同意见。",
        locator="chars 45:80",
    )

    sections = (
        ContentSection(
            section_id="overview",
            title="事件总览",
            order=1,
            modules=(
                ContentModule(
                    module_id="m-summary",
                    semantic_type="event-summary",
                    title="事件概况",
                    state=ModuleState.READY,
                    data_shape=DataShape.CARDS,
                    summary="某市公交票价调整引发公开讨论，官方公告与听证会报道是当前主要材料。",
                    items=(
                        {"title": "事件", "text": "市区公交基础票价调整", "meta": "公共服务"},
                        {"title": "时间", "text": "2026年10月1日起实施", "meta": "生效时间"},
                        {"title": "主要来源", "text": "官方公告、听证会报道", "meta": "公开网页"},
                    ),
                    citations=(citation_1,),
                ),
                ContentModule(
                    module_id="m-judgment",
                    semantic_type="current-judgments",
                    title="当前研判",
                    state=ModuleState.READY,
                    data_shape=DataShape.CARDS,
                    items=(
                        {"title": "已确认", "text": "官方公告确认基础票价由2元调整为3元。"},
                        {"title": "待观察", "text": "优惠群体范围和执行细节仍待更多材料。"},
                    ),
                    citations=(citation_1, citation_2),
                ),
                ContentModule(
                    module_id="m-limitations",
                    semantic_type="key-limitations",
                    title="关键限制",
                    state=ModuleState.INSUFFICIENT,
                    data_shape=DataShape.TEXT,
                    summary="当前仅覆盖公开网页材料，未接入社交平台数据。",
                    empty_reason="无法据此推断公众总体态度。",
                ),
            ),
        ),
        ContentSection(
            section_id="timeline",
            title="事件脉络",
            order=2,
            modules=(
                ContentModule(
                    module_id="m-timeline",
                    semantic_type="event-timeline",
                    title="事件时间线",
                    state=ModuleState.READY,
                    data_shape=DataShape.TIMELINE,
                    items=(
                        {"time": "2026-09-01", "title": "方案公开", "text": "官方发布票价调整方案。"},
                        {"time": "2026-09-10", "title": "听证会", "text": "举行公开听证会并出现不同意见。"},
                        {"time": "2026-10-01", "title": "正式实施", "text": "新票价机制开始执行。"},
                    ),
                    citations=(citation_1, citation_2),
                ),
            ),
        ),
        ContentSection(
            section_id="issues",
            title="议题、观点与回应",
            order=3,
            modules=(
                ContentModule(
                    module_id="m-issues",
                    semantic_type="issue-map",
                    title="议题与争议",
                    state=ModuleState.READY,
                    data_shape=DataShape.COMPARISON,
                    items=(
                        {"议题": "调价幅度", "状态": "争议中", "说明": "代表对2元到3元的幅度提出不同看法。"},
                        {"议题": "优惠群体", "状态": "待调查", "说明": "配套优惠范围仍需更多材料。"},
                    ),
                ),
                ContentModule(
                    module_id="m-positions",
                    semantic_type="position-matrix",
                    title="立场矩阵",
                    state=ModuleState.READY,
                    data_shape=DataShape.MATRIX,
                    items=(
                        {"主体": "运营方", "立场": "支持", "目标": "票价调整", "依据": "成本压力"},
                        {"主体": "部分参会代表", "立场": "条件支持", "目标": "配套优惠", "依据": "负担问题"},
                    ),
                    citations=(citation_2,),
                ),
                ContentModule(
                    module_id="m-response",
                    semantic_type="response-coverage",
                    title="回应覆盖",
                    state=ModuleState.READY,
                    data_shape=DataShape.COMPARISON,
                    items=(
                        {"问题": "为什么调价", "回应": "直接", "未覆盖": ""},
                        {"问题": "优惠如何执行", "回应": "部分", "未覆盖": "具体办理渠道"},
                    ),
                    citations=(citation_1,),
                ),
            ),
        ),
        ContentSection(
            section_id="evidence",
            title="来源、证据与限制",
            order=4,
            modules=(
                ContentModule(
                    module_id="m-source",
                    semantic_type="source-structure",
                    title="来源结构",
                    state=ModuleState.READY,
                    data_shape=DataShape.CATEGORICAL,
                    items=(
                        {"label": "官方来源", "value": 1, "display": "1"},
                        {"label": "媒体报道", "value": 1, "display": "1"},
                    ),
                ),
                ContentModule(
                    module_id="m-evidence",
                    semantic_type="evidence-index",
                    title="证据与原文",
                    state=ModuleState.READY,
                    data_shape=DataShape.EVIDENCE,
                    citations=(citation_1, citation_2),
                ),
                ContentModule(
                    module_id="m-heat",
                    semantic_type="sentiment-distribution",
                    title="情感分布",
                    state=ModuleState.UNAVAILABLE,
                    data_shape=DataShape.CATEGORICAL,
                    empty_reason="当前没有平台级情感数据，不能用公开网页样本推断。",
                ),
            ),
        ),
    )

    return ContentDocument(
        report_id="preview-social-event",
        revision=1,
        subject="某市公交票价调整",
        status="partial",
        generated_at="2026-09-16T12:00:00+08:00",
        profile={"event_type": "social_public_affairs"},
        sections=sections,
    )


def main() -> None:
    content = sample_document()
    plan = build_presentation_plan(content)
    validate_presentation_plan(plan)
    html_text = render_html(plan)
    output = ROOT / "artifacts" / "report-contract-preview.html"
    output.write_text(html_text, encoding="utf-8")
    plan_output = ROOT / "artifacts" / "report-contract-preview.plan.json"
    plan_output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(output)
    print(plan_output)


if __name__ == "__main__":
    main()
