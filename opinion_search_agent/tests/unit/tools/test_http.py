import asyncio

import httpx
import pytest

from opinion_search.tools.contracts import ToolAdapterError, ToolErrorKind
from opinion_search.tools.http import HttpxTransport


def test_httpx_transport_enforces_response_limit_while_streaming() -> None:
    transport = HttpxTransport(
        max_response_bytes=8,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"0123456789",
                request=request,
            )
        ),
    )

    with pytest.raises(ToolAdapterError) as captured:
        asyncio.run(
            transport.request(
                method="GET",
                url="https://example.com/large",
                headers={},
            )
        )

    assert captured.value.kind is ToolErrorKind.CONTENT_TOO_LARGE


def test_httpx_transport_parses_a_bounded_json_response() -> None:
    transport = HttpxTransport(
        max_response_bytes=100,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"ok": True},
                request=request,
            )
        ),
    )

    response = asyncio.run(
        transport.request(
            method="GET",
            url="https://example.com/data",
            headers={},
        )
    )

    assert response.json_body == {"ok": True}


def test_httpx_transport_never_forwards_credentials_across_redirects() -> None:
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/collect"},
            request=request,
        )

    transport = HttpxTransport(
        transport=httpx.MockTransport(redirect),
    )

    response = asyncio.run(
        transport.request(
            method="GET",
            url="https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": "secret"},
        )
    )

    assert response.status_code == 302
    assert len(requests) == 1
    assert requests[0].url.host == "api.search.brave.com"
