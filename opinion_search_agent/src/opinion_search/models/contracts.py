from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field


ContextT = TypeVar("ContextT", contravariant=True)
DecisionT = TypeVar("DecisionT", covariant=True)
NonEmptyText = Annotated[str, Field(min_length=1)]


class ModelErrorKind(StrEnum):
    MALFORMED_RESPONSE = "malformed_response"
    EMPTY_RESPONSE = "empty_response"
    REFUSAL = "refusal"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    SERVER_ERROR = "server_error"


_RETRYABLE_MODEL_ERRORS = frozenset(
    {
        ModelErrorKind.MALFORMED_RESPONSE,
        ModelErrorKind.EMPTY_RESPONSE,
        ModelErrorKind.REFUSAL,
        ModelErrorKind.TIMEOUT,
        ModelErrorKind.RATE_LIMITED,
        ModelErrorKind.SERVER_ERROR,
    }
)


class ModelError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    kind: ModelErrorKind
    message: NonEmptyText

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE_MODEL_ERRORS


class ModelClientError(RuntimeError):
    def __init__(self, error: ModelError) -> None:
        super().__init__(error.message)
        self.error = error


class ModelClient(Protocol[ContextT, DecisionT]):
    async def decide(self, context: ContextT) -> DecisionT: ...
