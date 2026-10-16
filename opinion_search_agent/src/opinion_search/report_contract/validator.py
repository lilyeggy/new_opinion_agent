from __future__ import annotations

from opinion_search.report_contract.contracts import (
    ModuleContract,
    ModuleState,
    PresentationPlan,
    VisualEncoding,
)
from opinion_search.report_contract.registry import registry_by_type


class PresentationPlanValidationError(ValueError):
    pass


def validate_presentation_plan(
    plan: PresentationPlan,
    registry: dict[str, ModuleContract] | None = None,
) -> None:
    active_registry = registry if registry is not None else registry_by_type()
    errors: list[str] = []

    if not (plan.plan_version == "presentation-plan/1"):
        errors.append(f"unsupported presentation plan version: {plan.plan_version}")

    for section in plan.sections:
        for module in section.modules:
            contract = active_registry.get(module.semantic_type)
            if contract is None:
                errors.append(f"unknown module semantic_type: {module.semantic_type}")
                continue

            if module.selected_visual not in contract.visual_encodings:
                errors.append(
                    f"{module.semantic_type}: selected_visual={module.selected_visual.value} "
                    f"is not allowed by contract={[item.value for item in contract.visual_encodings]}"
                )

            if (
                module.selected_visual is VisualEncoding.DISTRIBUTION_CHART
                and module.state in {ModuleState.READY, ModuleState.PROVISIONAL}
                and not module.items
            ):
                errors.append(
                    f"{module.semantic_type}: distribution chart requires items with labels and values"
                )

            if module.state is ModuleState.READY and module.selected_visual is VisualEncoding.EVIDENCE_DRAWER:
                if not module.citations and not module.items:
                    errors.append(
                        f"{module.semantic_type}: evidence drawer is ready but has no citations or items"
                    )

    if errors:
        raise PresentationPlanValidationError("; ".join(errors))
