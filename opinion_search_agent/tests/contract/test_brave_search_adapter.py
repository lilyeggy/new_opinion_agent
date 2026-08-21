import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import pytest

from opinion_search.tools.adapters.brave_search import BraveSearchAdapter
from opinion_search.tools.capabilities.web import (
    SearchResults,
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


class FakeHttpTransport:
    def __init__(self, response: HttpResponse) -> None:
        self._response = response
        self.requests: list[RecordedRequest] = []

    async def request(self, *, method, url, headers, json_body=None):
        self.requests.append(RecordedRequest(method, url, headers))
        return self._response


def _execute(adapter: BraveSearchAdapter):
    registry = ToolRegistry()
    registry.register(search_tool_definition(), adapter)
    executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(max_attempts_per_provider=1, timeout_seconds=1),
    )
    return asyncio.run(
        executor.execute(
            ToolCall(
                action_id="action-search",
                tool_name="search.web",
                arguments={"query": "example event", "max_results": 2},
            )
        )
    )


def test_brave_normalizes_web_results_into_provider_neutral_contract() -> None:
    transport = FakeHttpTransport(
        HttpResponse(
            status_code=200,
            headers={},
            json_body={
                "type": "search",
                "web": {
                    "results": [
                        {
                            "title": "Official source",
                            "url": "HTTPS://Example.COM:443/news#fragment",
                            "description": "Official account.",
                        },
                        {
                            "title": "Local target",
                            "url": "https://127.0.0.1/private",
                            "description": "Must be dropped.",
                        },
                    ]
                },
            },
            text="",
        )
    )

    outcome = _execute(BraveSearchAdapter(transport=transport, api_key="brave-secret"))

    assert isinstance(outcome, ToolResult)
    results = SearchResults.model_validate(outcome.payload)
    assert len(results.items) == 1
    assert results.items[0].url == "https://example.com/news"
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.headers["X-Subscription-Token"] == "brave-secret"
    query = parse_qs(urlsplit(request.url).query)
    assert query == {
        "q": ["example event"],
        "count": ["2"],
        "result_filter": ["web"],
        "text_decorations": ["false"],
    }


@pytest.mark.parametrize(
    ("status_code", "kind"),
    [
        (401, ToolErrorKind.AUTHENTICATION),
        (429, ToolErrorKind.RATE_LIMITED),
        (503, ToolErrorKind.SERVER_ERROR),
    ],
)
def test_brave_normalizes_http_failures(status_code, kind) -> None:
    adapter = BraveSearchAdapter(
        transport=FakeHttpTransport(
            HttpResponse(
                status_code=status_code,
                headers={},
                text="",
            )
        ),
        api_key="brave-secret",
    )

    outcome = _execute(adapter)

    assert isinstance(outcome, ToolError)
    assert outcome.kind is kind


def test_brave_rejects_malformed_payload_and_insecure_endpoint() -> None:
    outcome = _execute(
        BraveSearchAdapter(
            transport=FakeHttpTransport(
                HttpResponse(
                    status_code=200,
                    headers={},
                    json_body={"web": {"results": "not-a-list"}},
                    text="",
                )
            ),
            api_key="brave-secret",
        )
    )

    assert isinstance(outcome, ToolError)
    assert outcome.kind is ToolErrorKind.UNKNOWN_PROVIDER_ERROR
    with pytest.raises(ValueError, match="HTTPS"):
        BraveSearchAdapter(
            transport=FakeHttpTransport(
                HttpResponse(status_code=200, headers={}, text="")
            ),
            api_key="brave-secret",
            endpoint="http://search.example.com/api",
        )
