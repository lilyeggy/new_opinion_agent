from opinion_search.report_contract.registry import default_module_registry, registry_by_type
from opinion_search.report_contract.projector import build_presentation_plan
from opinion_search.report_contract.renderer import render_html
from opinion_search.report_contract.validator import PresentationPlanValidationError, validate_presentation_plan
from opinion_search.report_contract.contracts import (
    CitationRef,
    EvidenceRequirement,
    ModuleContract,
    ModuleInstance,
    ModuleState,
    Presence,
    ReportDocument,
    ReportSection,
    ReviewGate,
    VisualEncoding,
)

__all__ = [
    "build_presentation_plan",
    "render_html",
    "PresentationPlanValidationError",
    "validate_presentation_plan",
    "default_module_registry",
    "registry_by_type",
    "CitationRef",
    "EvidenceRequirement",
    "ModuleContract",
    "ModuleInstance",
    "ModuleState",
    "Presence",
    "ReportDocument",
    "ReportSection",
    "ReviewGate",
    "VisualEncoding",
]
