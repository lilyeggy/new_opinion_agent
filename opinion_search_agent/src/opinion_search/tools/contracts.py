from collections.abc import Mapping
from enum import StrEnum
from typing import (
    Annotated,
    Generic,
    Protocol,
    TypeAlias,
    TypeVar,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


ArgumentsT = TypeVar("ArgumentsT", bound=BaseModel)

NonEmptyText = Annotated[str, Field(min_length=1)]
ToolName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    ),
]
AttemptNumber = Annotated[int, Field(ge=1)]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    name: ToolName
    description: NonEmptyText
    capability: NonEmptyText
    input_model: type[BaseModel] = Field(exclude=True)

    def model_spec(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


class ToolCall(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    action_id: NonEmptyText
    tool_name: ToolName
    arguments: dict[str, JsonValue]


class ToolInvocation(BaseModel, Generic[ArgumentsT]):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    action_id: NonEmptyText
    tool_name: ToolName
    attempt: AttemptNumber
    arguments: ArgumentsT


class ToolAdapterResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    payload: JsonValue
    artifact_refs: tuple[NonEmptyText, ...] = ()


class ToolResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    action_id: NonEmptyText
    tool_name: ToolName
    payload: JsonValue
    artifact_refs: tuple[NonEmptyText, ...] = ()
    attempts: AttemptNumber


class ToolErrorKind(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    UNREADABLE_CONTENT = "unreadable_content"
    CONTENT_TOO_LARGE = "content_too_large"
    CANCELLED = "cancelled"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


_RETRYABLE_ERROR_KINDS = frozenset(
    {
        ToolErrorKind.TIMEOUT,
        ToolErrorKind.RATE_LIMITED,
        ToolErrorKind.SERVER_ERROR,
    }
)


class ToolError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    action_id: NonEmptyText
    tool_name: ToolName
    kind: ToolErrorKind
    message: NonEmptyText
    attempts: Annotated[int, Field(ge=0)]
    retryable: bool

    @model_validator(mode="before")
    @classmethod
    def derive_retryability(cls, raw: object) -> object:
        if not isinstance(raw, Mapping):
            return raw
        values = dict(raw)
        if "kind" not in values:
            return values
        kind = ToolErrorKind(values["kind"])
        expected = kind in _RETRYABLE_ERROR_KINDS
        if "retryable" in values and values["retryable"] != expected:
            raise ValueError("retryable does not match ToolError kind")
        values["retryable"] = expected
        return values


class ToolAdapterError(Exception):
    def __init__(
        self,
        kind: ToolErrorKind,
        safe_message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        normalized_message = safe_message.strip()
        if not normalized_message:
            raise ValueError("safe_message must not be empty")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        self.kind = kind
        self.safe_message = normalized_message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(normalized_message)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts_per_provider: Annotated[int, Field(ge=1)] = 3
    timeout_seconds: Annotated[float, Field(gt=0)] = 10.0
    backoff_seconds: Annotated[float, Field(ge=0)] = 0.0
    max_backoff_seconds: Annotated[float, Field(gt=0)] = 30.0

    def should_retry(self, kind: ToolErrorKind, *, attempt: int) -> bool:
        return (
            kind in _RETRYABLE_ERROR_KINDS
            and attempt < self.max_attempts_per_provider
        )

    def backoff_after(
        self,
        attempt: int,
        *,
        retry_after_seconds: float | None = None,
    ) -> float:
        if attempt < 1:
            raise ValueError("attempt must be at least one")
        exponential = self.backoff_seconds * (2 ** (attempt - 1))
        delay = max(exponential, retry_after_seconds or 0)
        return min(delay, self.max_backoff_seconds)


class ToolAdapter(Protocol[ArgumentsT]):
    async def invoke(
        self,
        invocation: ToolInvocation[ArgumentsT],
    ) -> ToolAdapterResponse: ...


ToolOutcome: TypeAlias = ToolResult | ToolError
