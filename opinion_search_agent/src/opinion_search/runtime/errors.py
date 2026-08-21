from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class RuntimeFailureKind(StrEnum):
    MODEL_MALFORMED_RESPONSE = "model_malformed_response"
    MODEL_EMPTY_RESPONSE = "model_empty_response"
    MODEL_REFUSAL = "model_refusal"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_RATE_LIMITED = "model_rate_limited"
    MODEL_AUTHENTICATION = "model_authentication"
    MODEL_CONFIGURATION_ERROR = "model_configuration_error"
    MODEL_SERVER_ERROR = "model_server_error"
    INVALID_DECISION = "invalid_decision"
    INVALID_ACTION = "invalid_action"
    TOOL_ERROR = "tool_error"
    TOOL_CONFIGURATION_ERROR = "tool_configuration_error"
    REDUCER_INVARIANT = "reducer_invariant"
    CHECKPOINT_READ = "checkpoint_read"
    CHECKPOINT_WRITE = "checkpoint_write"
    CHECKPOINT_VERSION = "checkpoint_version"
    CONTEXT_OVERFLOW = "context_overflow"
    REPEATED_ACTION = "repeated_action"
    CANCELLED = "cancelled"
    SAFETY_LIMIT = "safety_limit"


class RecoveryDirective(StrEnum):
    RETRY_ATTEMPT = "retry_attempt"
    FEEDBACK_AND_CONTINUE = "feedback_and_continue"
    PARTIAL_STOP = "partial_stop"
    FAIL_RUN = "fail_run"
    CANCEL_RUN = "cancel_run"


_RECOVERY_DIRECTIVE_BY_FAILURE_KIND = {
    RuntimeFailureKind.MODEL_MALFORMED_RESPONSE: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.MODEL_EMPTY_RESPONSE: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.MODEL_REFUSAL: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.MODEL_TIMEOUT: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.MODEL_RATE_LIMITED: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.MODEL_AUTHENTICATION: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.MODEL_CONFIGURATION_ERROR: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.MODEL_SERVER_ERROR: RecoveryDirective.RETRY_ATTEMPT,
    RuntimeFailureKind.INVALID_DECISION: RecoveryDirective.FEEDBACK_AND_CONTINUE,
    RuntimeFailureKind.INVALID_ACTION: RecoveryDirective.FEEDBACK_AND_CONTINUE,
    RuntimeFailureKind.TOOL_ERROR: RecoveryDirective.FEEDBACK_AND_CONTINUE,
    RuntimeFailureKind.TOOL_CONFIGURATION_ERROR: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.REDUCER_INVARIANT: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.CHECKPOINT_READ: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.CHECKPOINT_WRITE: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.CHECKPOINT_VERSION: RecoveryDirective.FAIL_RUN,
    RuntimeFailureKind.CONTEXT_OVERFLOW: RecoveryDirective.PARTIAL_STOP,
    RuntimeFailureKind.REPEATED_ACTION: RecoveryDirective.PARTIAL_STOP,
    RuntimeFailureKind.SAFETY_LIMIT: RecoveryDirective.PARTIAL_STOP,
    RuntimeFailureKind.CANCELLED: RecoveryDirective.CANCEL_RUN,
}


def recovery_directive_for(
    kind: RuntimeFailureKind,
) -> RecoveryDirective:
    return _RECOVERY_DIRECTIVE_BY_FAILURE_KIND[kind]


NonEmptyMessage = Annotated[str, Field(min_length=1)]


class RuntimeFailure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    kind: RuntimeFailureKind
    message: NonEmptyMessage

    @property
    def directive(self) -> RecoveryDirective:
        return recovery_directive_for(self.kind)


class DecisionValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        kind: RuntimeFailureKind = RuntimeFailureKind.INVALID_DECISION,
    ) -> None:
        if kind not in {
            RuntimeFailureKind.INVALID_DECISION,
            RuntimeFailureKind.REPEATED_ACTION,
        }:
            raise ValueError("decision validation error requires decision kind")
        super().__init__(message)
        self.kind = kind


class ContextOverflowError(RuntimeError):
    """Raised when required model context cannot fit the configured window."""
