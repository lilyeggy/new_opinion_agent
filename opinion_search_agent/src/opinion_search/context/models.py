from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from math import ceil
from typing import Annotated, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.runtime.errors import ContextOverflowError


NonEmptyText = Annotated[str, Field(min_length=1)]
StableSectionId = Annotated[
    str,
    Field(min_length=1, pattern=r"^[a-z][a-z0-9_.:-]*$"),
]


class ContextLayer(StrEnum):
    IMMUTABLE_INSTRUCTIONS = "l0_instructions"
    STABLE_TASK = "l1_task"
    WORKING_MEMORY = "l2_memory"
    RECENT_INTERACTION = "l3_recent"


class TrustBoundary(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ContextContentOrigin(StrEnum):
    RUNTIME = "runtime"
    APP_CONFIG = "app_config"
    USER_TASK = "user_task"
    MODEL = "model"
    TOOL = "tool"
    PROVIDER = "provider"


_ALWAYS_UNTRUSTED_ORIGINS = frozenset(
    {
        ContextContentOrigin.MODEL,
        ContextContentOrigin.TOOL,
        ContextContentOrigin.PROVIDER,
    }
)


class CompactionMode(StrEnum):
    NEVER = "never"
    TRUNCATE = "truncate"
    DROP = "drop"


class ContextCompilationError(RuntimeError):
    """Base class for deterministic context compilation failures."""


class RequiredContextOverflow(ContextCompilationError, ContextOverflowError):
    """Raised when the required context floor exceeds the input allowance."""


class ContextSection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    section_id: StableSectionId
    layer: ContextLayer
    title: NonEmptyText
    content: NonEmptyText
    priority: Annotated[int, Field(ge=0, le=100)]
    required: bool = False
    trust: TrustBoundary
    origin: ContextContentOrigin
    provenance_refs: tuple[NonEmptyText, ...] = ()
    compaction: CompactionMode = CompactionMode.DROP

    @model_validator(mode="after")
    def validate_required_layers(self) -> Self:
        if self.layer is ContextLayer.IMMUTABLE_INSTRUCTIONS:
            if not self.required:
                raise ValueError("L0 sections must be required")
            if self.trust is not TrustBoundary.TRUSTED:
                raise ValueError("L0 sections must be trusted")
            if self.origin is not ContextContentOrigin.APP_CONFIG:
                raise ValueError("L0 immutable instructions require app_config origin")
            if self.compaction is not CompactionMode.NEVER:
                raise ValueError("L0 sections cannot be compacted")
        elif self.layer is ContextLayer.STABLE_TASK:
            if not self.required:
                raise ValueError("L1 sections must be required")
            if self.trust is not TrustBoundary.TRUSTED:
                raise ValueError("L1 sections must be trusted")
            if self.origin not in {
                ContextContentOrigin.APP_CONFIG,
                ContextContentOrigin.USER_TASK,
            }:
                raise ValueError(
                    "L1 stable task requires app_config or user_task origin"
                )
            if self.compaction is not CompactionMode.NEVER:
                raise ValueError("L1 sections cannot be compacted")

        if (
            self.origin in _ALWAYS_UNTRUSTED_ORIGINS
            and self.trust is TrustBoundary.TRUSTED
        ):
            raise ValueError("model/tool/provider origin can never be trusted")
        return self


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_context_tokens: Annotated[int, Field(ge=2)]
    output_headroom_tokens: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_headroom(self) -> Self:
        if self.output_headroom_tokens >= self.max_context_tokens:
            raise ValueError("output headroom must be smaller than the context limit")
        return self

    @property
    def input_token_limit(self) -> int:
        return self.max_context_tokens - self.output_headroom_tokens


class ContextSectionMeasure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: StableSectionId
    estimated_tokens: Annotated[int, Field(ge=1)]


class ContextPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_section_ids: tuple[StableSectionId, ...]
    dropped_section_ids: tuple[StableSectionId, ...] = ()
    compacted_section_ids: tuple[StableSectionId, ...] = ()
    input_token_limit: Annotated[int, Field(ge=1)]
    estimated_input_tokens: Annotated[int, Field(ge=0)]
    section_measures: tuple[ContextSectionMeasure, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        sequences = (
            self.selected_section_ids,
            self.dropped_section_ids,
            self.compacted_section_ids,
        )
        if any(len(values) != len(set(values)) for values in sequences):
            raise ValueError("context plan section IDs must be unique")
        selected = set(self.selected_section_ids)
        if selected & set(self.dropped_section_ids):
            raise ValueError("selected and dropped section IDs must differ")
        if not set(self.compacted_section_ids).issubset(selected):
            raise ValueError("compacted sections must remain selected")
        if self.estimated_input_tokens > self.input_token_limit:
            raise ValueError("estimated input exceeds the context limit")

        measured_ids = tuple(
            measure.section_id for measure in self.section_measures
        )
        if measured_ids != self.selected_section_ids:
            raise ValueError(
                "section measures must match the selected IDs in order"
            )
        if len(set(measured_ids)) != len(measured_ids):
            raise ValueError("section measure IDs must be unique")
        for measure in self.section_measures:
            if measure.estimated_tokens < 1:
                raise ValueError("section token estimate must be positive")
        return self


class CompiledContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    run_id: NonEmptyText
    step_id: NonEmptyText
    step_index: Annotated[int, Field(ge=1)]
    state_revision: Annotated[int, Field(ge=0)]
    sections: tuple[ContextSection, ...]
    rendered: NonEmptyText
    content_sha256: NonEmptyText
    estimated_input_tokens: Annotated[int, Field(ge=1)]
    input_token_limit: Annotated[int, Field(ge=1)]
    output_headroom_tokens: Annotated[int, Field(ge=1)]
    plan: ContextPlan

    @model_validator(mode="after")
    def validate_compilation(self) -> Self:
        section_ids = tuple(section.section_id for section in self.sections)
        if section_ids != self.plan.selected_section_ids:
            raise ValueError("compiled sections do not match the context plan")
        if self.estimated_input_tokens != self.plan.estimated_input_tokens:
            raise ValueError("compiled measurement does not match the plan")
        if self.input_token_limit != self.plan.input_token_limit:
            raise ValueError("compiled limit does not match the plan")
        if self.estimated_input_tokens > self.input_token_limit:
            raise ValueError("compiled context exceeds the input limit")
        expected_rendered = render_sections(self.sections)
        if self.rendered != expected_rendered:
            raise ValueError("rendered context does not match sections")
        expected_hash = sha256(expected_rendered.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected_hash:
            raise ValueError("content_sha256 does not match rendered bytes")
        return self


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class HeuristicTokenEstimator:
    """Offline-stable approximation; provider tokenizers may replace it."""

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, ceil(len(text.encode("utf-8")) / 4))


def render_sections(sections: tuple[ContextSection, ...]) -> str:
    rendered: list[str] = []
    for section in sections:
        rendered.extend(
            (
                (
                    f"[CONTEXT_SECTION id={section.section_id} "
                    f"layer={section.layer.value} origin={section.origin.value} "
                    f"trust={section.trust.value}]"
                ),
                section.title,
                _escape_embedded_section_markers(section.content),
                "[/CONTEXT_SECTION]",
            )
        )
    return "\n".join(rendered)


def _escape_embedded_section_markers(content: str) -> str:
    return content.replace(
        "[CONTEXT_SECTION",
        "［CONTEXT_SECTION",
    ).replace(
        "[/CONTEXT_SECTION]",
        "［/CONTEXT_SECTION］",
    )
