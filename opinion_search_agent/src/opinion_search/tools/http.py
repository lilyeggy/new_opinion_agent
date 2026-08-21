import json
from typing import Annotated, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from opinion_search.tools.contracts import ToolAdapterError, ToolErrorKind


class HttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: Annotated[int, Field(ge=100, le=599)]
    headers: dict[str, str]
    json_body: JsonValue | None = None
    text: str


class HttpTransport(Protocol):
    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: JsonValue | None = None,
    ) -> HttpResponse: ...


class HttpxTransport:
    def __init__(
        self,
        *,
        max_response_bytes: int = 2_500_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: JsonValue | None = None,
    ) -> HttpResponse:
        try:
            async with httpx.AsyncClient(
                timeout=None,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                ) as response:
                    declared_length = response.headers.get("content-length")
                    if (
                        declared_length is not None
                        and declared_length.isdigit()
                        and int(declared_length) > self._max_response_bytes
                    ):
                        raise ToolAdapterError(
                            ToolErrorKind.CONTENT_TOO_LARGE,
                            "The HTTP response exceeded the configured limit.",
                        )
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > self._max_response_bytes:
                            raise ToolAdapterError(
                                ToolErrorKind.CONTENT_TOO_LARGE,
                                "The HTTP response exceeded the configured limit.",
                            )
                        chunks.append(chunk)
                    raw_body = b"".join(chunks)
                    status_code = response.status_code
                    response_headers = {
                        key.lower(): value for key, value in response.headers.items()
                    }
        except httpx.TimeoutException as exc:
            raise ToolAdapterError(
                ToolErrorKind.TIMEOUT,
                "The HTTP request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolAdapterError(
                ToolErrorKind.SERVER_ERROR,
                "The HTTP request could not reach the provider.",
            ) from exc

        text = raw_body.decode("utf-8", errors="replace")
        try:
            parsed_json = json.loads(text)
        except (TypeError, ValueError):
            parsed_json = None

        return HttpResponse(
            status_code=status_code,
            headers=response_headers,
            json_body=parsed_json,
            text=text,
        )


def raise_for_http_status(
    response: HttpResponse,
    *,
    provider: str,
) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return

    if status == 401:
        kind = ToolErrorKind.AUTHENTICATION
        reason = "rejected authentication"
    elif status == 403:
        kind = ToolErrorKind.PERMISSION
        reason = "denied permission"
    elif status == 404:
        kind = ToolErrorKind.NOT_FOUND
        reason = "did not find the requested resource"
    elif status == 408:
        kind = ToolErrorKind.TIMEOUT
        reason = "timed out"
    elif status == 429:
        kind = ToolErrorKind.RATE_LIMITED
        reason = "rate limited the request"
    elif 500 <= status < 600:
        kind = ToolErrorKind.SERVER_ERROR
        reason = "reported a server error"
    else:
        kind = ToolErrorKind.UNKNOWN_PROVIDER_ERROR
        reason = "rejected the request"

    raise ToolAdapterError(
        kind,
        f"{provider} {reason} with HTTP status {status}.",
    )
