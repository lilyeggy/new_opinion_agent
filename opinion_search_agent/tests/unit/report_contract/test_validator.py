from opinion_search.report_contract.contracts import (
    ContentDocument,
    ContentModule,
    ContentSection,
    DataShape,
    ModuleState,
)
from opinion_search.report_contract.projector import build_presentation_plan
from opinion_search.report_contract.validator import validate_presentation_plan


def _content_module(module_state: ModuleState = ModuleState.READY) -> ContentDocument:
    return ContentDocument(
        report_id="r3",
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
                        module_id="m3",
                        semantic_type="event-summary",
                        title="事件概况",
                        state=module_state,
                        data_shape=DataShape.CARDS,
                        summary="测试摘要",
                    ),
                ),
            ),
        ),
    )


def test_validator_accepts_default_plan() -> None:
    plan = build_presentation_plan(_content_module())

    validate_presentation_plan(plan)


def test_validator_rejects_distribution_chart_without_items() -> None:
    content = ContentDocument(
        report_id="r4",
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
                        module_id="m4",
                        semantic_type="source-structure",
                        title="来源结构",
                        state=ModuleState.READY,
                        data_shape=DataShape.CATEGORICAL,
                    ),
                ),
            ),
        ),
    )
    plan = build_presentation_plan(content)

    try:
        validate_presentation_plan(plan)
    except ValueError as exc:
        assert "distribution chart requires items" in str(exc)
    else:
        raise AssertionError("expected validator to reject distribution chart without items")
