import asyncio

from opinion_search.tools.adapters.fake import (
    FakePage,
    FakeReaderAdapter,
    FakeSearchAdapter,
    fake_reader_definition,
    fake_search_definition,
)
from opinion_search.tools.capabilities.web import SearchHit
from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolCall,
    ToolError,
    ToolErrorKind,
    ToolResult,
)
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.registry import ToolRegistry


def _executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(
        fake_search_definition(),
        FakeSearchAdapter(
            {
                "opinion search": (
                    SearchHit(
                        title="Primary source",
                        url="https://example.com/primary",
                        snippet="Official event details.",
                    ),
                    SearchHit(
                        title="Independent report",
                        url="https://example.com/report",
                        snippet="Independent account.",
                    ),
                )
            }
        ),
    )
    registry.register(
        fake_reader_definition(),
        FakeReaderAdapter(
            pages={
                "https://example.com/primary": FakePage(
                    title="Primary source",
                    content="The full official event description.",
                    artifact_ref="artifact-primary",
                )
            },
            unreadable_urls={"https://example.com/unreadable"},
        ),
    )
    return ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=3, timeout_seconds=1),
    )


def test_fake_search_uses_the_public_tool_contract() -> None:
    outcome = asyncio.run(
        _executor().execute(
            ToolCall(
                action_id="action-search",
                tool_name="search.web",
                arguments={"query": "opinion search", "max_results": 1},
            )
        )
    )

    assert isinstance(outcome, ToolResult)
    assert outcome.payload == {
        "query": "opinion search",
        "items": [
            {
                "title": "Primary source",
                "url": "https://example.com/primary",
                "snippet": "Official event details.",
            }
        ],
    }
    assert outcome.attempts == 1


def test_fake_search_returns_a_normalized_empty_result() -> None:
    outcome = asyncio.run(
        _executor().execute(
            ToolCall(
                action_id="action-search",
                tool_name="search.web",
                arguments={"query": "unknown topic"},
            )
        )
    )

    assert isinstance(outcome, ToolResult)
    assert outcome.payload == {"query": "unknown topic", "items": []}


def test_fake_reader_returns_content_and_artifact_reference() -> None:
    outcome = asyncio.run(
        _executor().execute(
            ToolCall(
                action_id="action-read",
                tool_name="read.web",
                arguments={"url": "https://example.com/primary"},
            )
        )
    )

    assert isinstance(outcome, ToolResult)
    assert outcome.payload == {
        "url": "https://example.com/primary",
        "title": "Primary source",
        "content": "The full official event description.",
        "publication_time_status": "unavailable",
    }
    assert outcome.artifact_refs == ("artifact-primary",)


def test_fake_reader_normalizes_not_found_without_retry() -> None:
    outcome = asyncio.run(
        _executor().execute(
            ToolCall(
                action_id="action-read",
                tool_name="read.web",
                arguments={"url": "https://example.com/missing"},
            )
        )
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.NOT_FOUND
    assert outcome.retryable is False
    assert outcome.attempts == 1


def test_fake_reader_normalizes_unreadable_content_without_retry() -> None:
    outcome = asyncio.run(
        _executor().execute(
            ToolCall(
                action_id="action-read",
                tool_name="read.web",
                arguments={"url": "https://example.com/unreadable"},
            )
        )
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNREADABLE_CONTENT
    assert outcome.retryable is False
    assert outcome.attempts == 1
