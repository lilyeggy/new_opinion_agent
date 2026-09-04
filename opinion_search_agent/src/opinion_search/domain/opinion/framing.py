from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_search.app.contracts import SearchRequest


NonEmptyText = Annotated[str, Field(min_length=1)]


class TemporalScopeProvenance(StrEnum):
    EXPLICIT_REQUEST = "explicit_request"
    INFERRED_FROM_QUESTION = "inferred_from_question"
    UNSPECIFIED = "unspecified"


class TemporalScope(BaseModel):
    """A time window anchored once when a run is created, never on resume."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    anchor_date: date
    start_date: date | None = None
    end_date: date | None = None
    provenance: TemporalScopeProvenance
    original_expression: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "TemporalScope":
        has_window = self.start_date is not None or self.end_date is not None
        if has_window and (self.start_date is None or self.end_date is None):
            raise ValueError("temporal scope requires both start and end dates")
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError("temporal scope start date must not exceed end date")
        if self.provenance is TemporalScopeProvenance.UNSPECIFIED and has_window:
            raise ValueError("unspecified temporal scope cannot have a window")
        if self.provenance is not TemporalScopeProvenance.UNSPECIFIED and not has_window:
            raise ValueError("specified temporal scope requires a window")
        return self

    @property
    def is_bounded(self) -> bool:
        return self.start_date is not None


class TaskFrame(BaseModel):
    """Trusted, persisted interpretation of request scope for one investigation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    subject: NonEmptyText
    temporal_scope: TemporalScope
    language: NonEmptyText
    include_domains: tuple[NonEmptyText, ...]
    exclude_domains: tuple[NonEmptyText, ...]


def build_task_frame(request: SearchRequest, *, anchor_date: date) -> TaskFrame:
    """Compile explicit request constraints first, then limited deterministic inference."""
    expression = request.time_range
    provenance = TemporalScopeProvenance.EXPLICIT_REQUEST
    if expression is None:
        expression = _find_relative_time_expression(request.question)
        provenance = TemporalScopeProvenance.INFERRED_FROM_QUESTION

    scope = parse_temporal_scope(
        expression,
        anchor_date=anchor_date,
        provenance=provenance,
    )
    return TaskFrame(
        subject=request.topic or request.question,
        temporal_scope=scope,
        language=request.language,
        include_domains=request.include_domains,
        exclude_domains=request.exclude_domains,
    )


def parse_temporal_scope(
    expression: str | None,
    *,
    anchor_date: date,
    provenance: TemporalScopeProvenance,
) -> TemporalScope:
    """Parse only unambiguous, explicitly supported Chinese/ISO time expressions."""
    if expression is None:
        return TemporalScope(
            anchor_date=anchor_date,
            provenance=TemporalScopeProvenance.UNSPECIFIED,
        )
    normalized = expression.strip()
    iso_range = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s*(?:至|to|~)\s*(\d{4}-\d{2}-\d{2})", normalized, re.I)
    if iso_range:
        return TemporalScope(
            anchor_date=anchor_date,
            start_date=date.fromisoformat(iso_range.group(1)),
            end_date=date.fromisoformat(iso_range.group(2)),
            provenance=provenance,
            original_expression=normalized,
        )
    days = {
        "过去一周": 7,
        "最近一周": 7,
        "最近7天": 7,
        "过去7天": 7,
        "过去一个月": 30,
        "最近一个月": 30,
        "最近30天": 30,
        "过去30天": 30,
    }.get(normalized)
    if days is None:
        return TemporalScope(
            anchor_date=anchor_date,
            provenance=TemporalScopeProvenance.UNSPECIFIED,
        )
    return TemporalScope(
        anchor_date=anchor_date,
        start_date=anchor_date - timedelta(days=days - 1),
        end_date=anchor_date,
        provenance=provenance,
        original_expression=normalized,
    )


def _find_relative_time_expression(question: str) -> str | None:
    for expression in (
        "过去一周", "最近一周", "最近7天", "过去7天",
        "过去一个月", "最近一个月", "最近30天", "过去30天",
    ):
        if expression in question:
            return expression
    return None
