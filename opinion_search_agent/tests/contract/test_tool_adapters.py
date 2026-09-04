import asyncio
from dataclasses import dataclass

import pytest

from opinion_search.tools.adapters.jina_reader import JinaReaderAdapter
from opinion_search.tools.adapters.serper import SerperAdapter
from opinion_search.tools.artifacts import LocalTextArtifactStore
from opinion_search.tools.capabilities.web import (
    ReadResult,
    SearchResults,
    reader_tool_definition,
    search_tool_definition,
)
from opinion_search.tools.contracts import (
    RetryPolicy,
    ToolCall,
    ToolError,
    ToolErrorKind,
    ToolResult,
)
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.http import HttpResponse
from opinion_search.tools.registry import ToolRegistry


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    json_body: object


class FakeHttpTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = responses
        self.requests: list[RecordedRequest] = []

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body=None,
    ) -> HttpResponse:
        self.requests.append(RecordedRequest(method, url, headers, json_body))
        return self._responses[len(self.requests) - 1]


def _execute(definition, adapter, call: ToolCall):
    registry = ToolRegistry()
    registry.register(definition, adapter)
    executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=1, timeout_seconds=1),
    )
    return asyncio.run(executor.execute(call))


def test_serper_normalizes_organic_results_to_search_contract() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                json_body={
                    "organic": [
                        {
                            "title": "Primary source",
                            "link": "HTTPS://Example.COM:443/a#fragment",
                            "snippet": "Official facts.",
                        },
                        {
                            "title": "Malformed result",
                            "link": "https://example.com/malformed",
                        },
                    ]
                },
                text="",
            )
        ]
    )
    adapter = SerperAdapter(transport=transport, api_key="secret-key")
    call = ToolCall(
        action_id="action-search",
        tool_name="search.web",
        arguments={"query": "public event", "max_results": 3},
    )

    outcome = _execute(search_tool_definition(), adapter, call)

    assert isinstance(outcome, ToolResult)
    results = SearchResults.model_validate(outcome.payload)
    assert results.query == "public event"
    assert len(results.items) == 1
    assert results.items[0].url == "https://example.com/a"
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == "https://google.serper.dev/search"
    assert request.headers["X-API-KEY"] == "secret-key"
    assert request.json_body == {"q": "public event", "num": 3}


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, ToolErrorKind.AUTHENTICATION),
        (429, ToolErrorKind.RATE_LIMITED),
        (503, ToolErrorKind.SERVER_ERROR),
    ],
)
def test_serper_normalizes_http_failures(
    status: int,
    kind: ToolErrorKind,
) -> None:
    transport = FakeHttpTransport(
        [HttpResponse(status_code=status, headers={}, text="secret raw body")]
    )
    outcome = _execute(
        search_tool_definition(),
        SerperAdapter(transport=transport, api_key="secret-key"),
        ToolCall(
            action_id="action-search",
            tool_name="search.web",
            arguments={"query": "event"},
        ),
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is kind
    assert "secret raw body" not in outcome.message


def test_serper_rejects_invalid_provider_payload() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={},
                json_body={"organic": "not-a-list"},
                text="",
            )
        ]
    )

    outcome = _execute(
        search_tool_definition(),
        SerperAdapter(transport=transport, api_key="secret-key"),
        ToolCall(
            action_id="action-search",
            tool_name="search.web",
            arguments={"query": "event"},
        ),
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNKNOWN_PROVIDER_ERROR


def test_jina_reader_normalizes_json_mode_response() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                json_body={
                    "data": {
                        "title": "Primary source",
                        "url": "HTTPS://Example.COM:443/article#fragment",
                        "content": "# Primary source\n\nFull content.",
                        "publishedTime": "2026-08-25T09:30:00+08:00",
                    }
                },
                text="",
            )
        ]
    )
    adapter = JinaReaderAdapter(
        transport=transport,
        api_key="jina-key",
    )
    call = ToolCall(
        action_id="action-read",
        tool_name="read.web",
        arguments={"url": "https://example.com/article#client-fragment"},
    )

    outcome = _execute(reader_tool_definition(), adapter, call)

    assert isinstance(outcome, ToolResult)
    result = ReadResult.model_validate(outcome.payload)
    assert result.url == "https://example.com/article"
    assert result.title == "Primary source"
    assert result.content.startswith("# Primary source")
    assert result.published_at.isoformat() == "2026-08-25T09:30:00+08:00"
    assert result.publication_time_status.value == "reported"
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url == "https://r.jina.ai/https://example.com/article"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Authorization"] == "Bearer jina-key"


def test_jina_reader_api_key_is_optional() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={},
                json_body={
                    "data": {
                        "title": "Example",
                        "url": "https://example.com/",
                        "content": "Readable content.",
                    }
                },
                text="",
            )
        ]
    )

    outcome = _execute(
        reader_tool_definition(),
        JinaReaderAdapter(transport=transport),
        ToolCall(
            action_id="action-read",
            tool_name="read.web",
            arguments={"url": "https://example.com"},
        ),
    )

    assert isinstance(outcome, ToolResult)
    assert "Authorization" not in transport.requests[0].headers


def test_credentialed_tool_adapters_require_public_https_endpoints() -> None:
    transport = FakeHttpTransport([])

    with pytest.raises(ValueError, match="HTTPS"):
        SerperAdapter(
            transport=transport,
            api_key="secret",
            endpoint="http://search.example.com/api",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        JinaReaderAdapter(
            transport=transport,
            api_key="secret",
            endpoint="http://reader.example.com/api",
        )


def test_jina_reader_reports_empty_content_as_unreadable() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={},
                json_body={
                    "data": {
                        "title": "Blocked",
                        "url": "https://example.com/blocked",
                        "content": "",
                    }
                },
                text="",
            )
        ]
    )

    outcome = _execute(
        reader_tool_definition(),
        JinaReaderAdapter(transport=transport),
        ToolCall(
            action_id="action-read",
            tool_name="read.web",
            arguments={"url": "https://example.com/blocked"},
        ),
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNREADABLE_CONTENT


def test_jina_reader_checkpoints_bounded_inline_content_and_artifact_ref(
    tmp_path,
) -> None:
    full_content = "evidence " * 100
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={},
                json_body={
                    "data": {
                        "title": "Large page",
                        "url": "https://example.com/large",
                        "content": full_content,
                    }
                },
                text="",
            )
        ]
    )
    store = LocalTextArtifactStore(tmp_path / "artifacts", max_bytes=2_000)

    outcome = _execute(
        reader_tool_definition(),
        JinaReaderAdapter(
            transport=transport,
            artifact_store=store,
            max_inline_content_bytes=64,
        ),
        ToolCall(
            action_id="action-read",
            tool_name="read.web",
            arguments={"url": "https://example.com/large"},
        ),
    )

    assert isinstance(outcome, ToolResult)
    result = ReadResult.model_validate(outcome.payload)
    assert len(result.content.encode("utf-8")) <= 64
    assert len(outcome.artifact_refs) == 1
    assert asyncio.run(store.get_text(outcome.artifact_refs[0])) == full_content


def test_jina_reader_rejects_content_over_artifact_limit(tmp_path) -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={},
                json_body={
                    "data": {
                        "title": "Oversized page",
                        "url": "https://example.com/oversized",
                        "content": "x" * 100,
                    }
                },
                text="",
            )
        ]
    )

    outcome = _execute(
        reader_tool_definition(),
        JinaReaderAdapter(
            transport=transport,
            artifact_store=LocalTextArtifactStore(
                tmp_path / "artifacts",
                max_bytes=32,
            ),
        ),
        ToolCall(
            action_id="action-read",
            tool_name="read.web",
            arguments={"url": "https://example.com/oversized"},
        ),
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.CONTENT_TOO_LARGE
