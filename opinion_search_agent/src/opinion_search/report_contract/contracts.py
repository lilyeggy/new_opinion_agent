from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModuleState(StrEnum):
    READY = "ready"
    PROVISIONAL = "provisional"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    NOT_FOUND = "not_found"
    PENDING = "pending"
    OMITTED = "omitted"


class VisualEncoding(StrEnum):
    TEXT = "text"
    CARDS = "cards"
    TIMELINE = "timeline"
    COMPARISON_TABLE = "comparison_table"
    POSITION_MATRIX = "position_matrix"
    DEBATE_VERSUS = "debate_versus"
    RESPONSE_SCORECARD = "response_scorecard"
    RELATION_GRAPH = "relation_graph"
    DISTRIBUTION_CHART = "distribution_chart"
    TREND_CHART = "trend_chart"
    RISK_MATRIX = "risk_matrix"
    EVIDENCE_DRAWER = "evidence_drawer"
    ACTION_CARDS = "action_cards"


class Presence(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    CONDITIONAL = "conditional"
    NOT_APPLICABLE = "not_applicable"


class ReviewGate(StrEnum):
    NONE = "none"
    REQUIRED = "required"
    SUPPORTED_ONLY = "supported_only"


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_evidence: int = 0
    required_source_roles: tuple[str, ...] = ()
    original_source_required: bool = False
    reviewed_finding_required: bool = False


class ModuleContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_type: str
    title: str
    semantic_domain: str
    applies_when: str
    presence: Presence
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    data_bindings: tuple[str, ...] = ()
    evidence_requirements: EvidenceRequirement = Field(default_factory=EvidenceRequirement)
    review_gate: ReviewGate = ReviewGate.NONE
    visual_encodings: tuple[VisualEncoding, ...] = (VisualEncoding.TEXT,)
    selection_rules: tuple[str, ...] = ()
    fallback_visual: VisualEncoding = VisualEncoding.TEXT
    empty_state: ModuleState = ModuleState.OMITTED
    priority: int = 50
    version: str = "report-contract/1"


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    source_version_id: str
    label: str = ""
    excerpt: str = ""
    locator: str = ""


class ModuleInstance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    module_id: str
    semantic_type: str
    title: str
    state: ModuleState
    selected_visual: VisualEncoding
    summary: str = ""
    table_columns: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()
    citations: tuple[CitationRef, ...] = ()
    limitations: tuple[str, ...] = ()
    empty_reason: str = ""
    view_id: str = ""


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: str
    title: str
    order: int = Field(ge=0)
    modules: tuple[ModuleInstance, ...] = ()


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    revision: int = Field(ge=0)
    subject: str
    status: str
    generated_at: str
    profile: dict[str, Any] = Field(default_factory=dict)
    sections: tuple[ReportSection, ...]


class DataShape(StrEnum):
    TEXT = "text"
    CARDS = "cards"
    TIMELINE = "timeline"
    COMPARISON = "comparison"
    MATRIX = "matrix"
    CATEGORICAL = "categorical"
    TREND = "trend"
    RELATION = "relation"
    EVIDENCE = "evidence"
    ACTION = "action"


class ContentModule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    module_id: str
    semantic_type: str
    title: str
    state: ModuleState
    data_shape: DataShape
    preferred_visual: VisualEncoding | None = None
    summary: str = ""
    table_columns: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()
    citations: tuple[CitationRef, ...] = ()
    limitations: tuple[str, ...] = ()
    empty_reason: str = ""
    view_id: str = ""


class ContentSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: str
    title: str
    order: int = Field(ge=0)
    view_id: str = ""
    view_title: str = ""
    modules: tuple[ContentModule, ...] = ()


class ContentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    revision: int = Field(ge=0)
    subject: str
    status: str
    generated_at: str
    profile: dict[str, Any] = Field(default_factory=dict)
    sections: tuple[ContentSection, ...]


class PlannedModule(ContentModule):
    selected_visual: VisualEncoding
    selection_reason: str = ""


class PlannedSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: str
    title: str
    order: int = Field(ge=0)
    view_id: str = ""
    view_title: str = ""
    modules: tuple[PlannedModule, ...] = ()


class PresentationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_version: str = "presentation-plan/1"
    source_content_revision: int = Field(ge=0)
    report_id: str
    subject: str
    status: str
    generated_at: str
    sections: tuple[PlannedSection, ...]
