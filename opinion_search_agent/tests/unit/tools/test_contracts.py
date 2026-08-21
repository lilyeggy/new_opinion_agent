import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolAdapterError,
    ToolAdapterResponse,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolErrorKind,
    ToolInvocation,
    ToolResult,
)


class QueryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str


def test_tool_definition_exports_only_model_visible_contract() -> None:
    definition = ToolDefinition(
        name="search.web",
        description="Search the public web.",
        capability="search",
        input_model=QueryArguments,
    )

    assert definition.model_spec() == {
        "name": "search.web",
        "description": "Search the public web.",
        "input_schema": QueryArguments.model_json_schema(),
    }


@pytest.mark.parametrize("name", ["", "1search", "search web", "-search"])
def test_tool_definition_rejects_invalid_stable_names(name: str) -> None:
    with pytest.raises(ValidationError):
        ToolDefinition(
            name=name,
            description="Search.",
            capability="search",
            input_model=QueryArguments,
        )


def test_tool_definition_accepts_names_exposed_by_mcp_servers() -> None:
    definition = ToolDefinition(
        name="MCP.search_v2",
        description="Search through an MCP server.",
        capability="mcp",
        input_model=QueryArguments,
    )

    assert definition.name == "MCP.search_v2"


def test_tool_call_and_invocation_are_strict_and_json_safe() -> None:
    call = ToolCall(
        action_id="action-1",
        tool_name="search.web",
        arguments={"query": "agent infrastructure"},
    )
    invocation = ToolInvocation[QueryArguments](
        action_id=call.action_id,
        tool_name=call.tool_name,
        attempt=1,
        arguments=QueryArguments(query="agent infrastructure"),
    )

    assert call.model_dump(mode="json")["arguments"] == {
        "query": "agent infrastructure"
    }
    assert invocation.attempt == 1

    with pytest.raises(ValidationError):
        ToolInvocation[QueryArguments](
            action_id="action-1",
            tool_name="search.web",
            attempt=0,
            arguments=QueryArguments(query="query"),
        )


def test_tool_result_and_adapter_response_reject_non_json_payloads() -> None:
    response = ToolAdapterResponse(
        payload={"items": [{"url": "https://example.com"}]},
        artifact_refs=("artifact-1",),
    )
    result = ToolResult(
        action_id="action-1",
        tool_name="search.web",
        payload=response.payload,
        artifact_refs=response.artifact_refs,
        attempts=1,
    )

    assert result.model_dump(mode="json")["payload"] == response.payload

    with pytest.raises(ValidationError):
        ToolAdapterResponse(payload=object())


@pytest.mark.parametrize(
    ("kind", "retryable"),
    [
        (ToolErrorKind.TIMEOUT, True),
        (ToolErrorKind.RATE_LIMITED, True),
        (ToolErrorKind.SERVER_ERROR, True),
        (ToolErrorKind.INVALID_ARGUMENTS, False),
        (ToolErrorKind.AUTHENTICATION, False),
        (ToolErrorKind.PERMISSION, False),
        (ToolErrorKind.NOT_FOUND, False),
        (ToolErrorKind.UNREADABLE_CONTENT, False),
        (ToolErrorKind.CANCELLED, False),
        (ToolErrorKind.UNKNOWN_PROVIDER_ERROR, False),
    ],
)
def test_tool_error_retryability_is_derived_from_kind(
    kind: ToolErrorKind,
    retryable: bool,
) -> None:
    error = ToolError(
        action_id="action-1",
        tool_name="search.web",
        kind=kind,
        message="Safe diagnostic.",
        attempts=1,
    )

    assert error.retryable is retryable
    assert error.model_dump(mode="json")["retryable"] is retryable
    assert ToolError.model_validate_json(error.model_dump_json()) == error


def test_tool_error_rejects_inconsistent_serialized_retryability() -> None:
    with pytest.raises(ValidationError, match="retryable"):
        ToolError(
            action_id="action-1",
            tool_name="search.web",
            kind=ToolErrorKind.TIMEOUT,
            message="Timed out.",
            attempts=1,
            retryable=False,
        )


def test_adapter_error_exposes_only_normalized_safe_fields() -> None:
    error = ToolAdapterError(
        ToolErrorKind.RATE_LIMITED,
        "The provider rate limit was reached.",
    )

    assert error.kind is ToolErrorKind.RATE_LIMITED
    assert error.safe_message == "The provider rate limit was reached."
    assert str(error) == "The provider rate limit was reached."


def test_retry_policy_validates_limits_and_decides_from_kind() -> None:
    policy = RetryPolicy(
        max_attempts_per_provider=3,
        timeout_seconds=2.0,
        backoff_seconds=0.1,
    )

    assert policy.should_retry(ToolErrorKind.TIMEOUT, attempt=1)
    assert not policy.should_retry(ToolErrorKind.TIMEOUT, attempt=3)
    assert not policy.should_retry(
        ToolErrorKind.AUTHENTICATION,
        attempt=1,
    )

    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts_per_provider=0)
