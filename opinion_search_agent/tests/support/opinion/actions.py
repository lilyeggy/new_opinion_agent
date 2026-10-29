from typing import Annotated, Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from opinion_search.runtime.completion import CompletionVerdict
from opinion_search.tools.contracts import ToolName


NonEmptyText = Annotated[str, Field(min_length=1)]

_TOOL_BY_DECISION_ACTION = {
    "search": "search.web",
    "read": "read.web",
}


class _ActionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ToolAction(_ActionModel):
    kind: Literal["tool"] = "tool"
    decision_action: Literal["search", "read"]
    tool_name: ToolName
    arguments: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_tool_matches_decision(self) -> Self:
        expected_tool = _TOOL_BY_DECISION_ACTION[self.decision_action]
        if self.tool_name != expected_tool:
            raise ValueError(
                "tool does not match OpinionSearch decision action: "
                f"expected={expected_tool}, actual={self.tool_name}"
            )
        return self


class ReflectAction(_ActionModel):
    kind: Literal["reflect"] = "reflect"
    assessment: NonEmptyText
    next_focus: NonEmptyText
    assessed_gap_ids: tuple[NonEmptyText, ...]


class FinishAction(_ActionModel):
    kind: Literal["finish"] = "finish"
    completion_verdict: CompletionVerdict


OpinionAction: TypeAlias = Annotated[
    ToolAction | ReflectAction | FinishAction,
    Field(discriminator="kind"),
]
