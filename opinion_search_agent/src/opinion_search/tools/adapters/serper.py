from pydantic import ValidationError

from opinion_search.tools.capabilities.web import (
    SearchArguments,
    SearchHit,
    SearchResults,
)
from opinion_search.tools.contracts import (
    ToolAdapterError,
    ToolAdapterResponse,
    ToolErrorKind,
    ToolInvocation,
)
from opinion_search.tools.http import HttpTransport, raise_for_http_status
from opinion_search.tools.url import (
    InvalidPublicUrl,
    normalize_public_url,
    normalize_secure_provider_endpoint,
)


class SerperAdapter:
    def __init__(
        self,
        *,
        transport: HttpTransport,
        api_key: str,
        endpoint: str = "https://google.serper.dev/search",
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("Serper api_key must not be empty")
        try:
            normalized_endpoint = normalize_secure_provider_endpoint(endpoint)
        except InvalidPublicUrl as exc:
            raise ValueError("Serper endpoint must be a public HTTPS URL") from exc
        self._transport = transport
        self._api_key = normalized_key
        self._endpoint = normalized_endpoint

    async def invoke(
        self,
        invocation: ToolInvocation[SearchArguments],
    ) -> ToolAdapterResponse:
        arguments = invocation.arguments
        response = await self._transport.request(
            method="POST",
            url=self._endpoint,
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json_body={
                "q": arguments.query,
                "num": arguments.max_results,
            },
        )
        raise_for_http_status(response, provider="Serper")

        payload = response.json_body
        if not isinstance(payload, dict):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Serper returned an invalid JSON response.",
            )
        organic = payload.get("organic", [])
        if not isinstance(organic, list):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Serper returned an invalid organic result list.",
            )

        items: list[SearchHit] = []
        for raw_item in organic:
            if not isinstance(raw_item, dict):
                continue
            try:
                item = SearchHit(
                    title=raw_item.get("title"),
                    url=normalize_public_url(raw_item.get("link", "")),
                    snippet=raw_item.get("snippet"),
                )
            except (InvalidPublicUrl, ValidationError):
                continue
            items.append(item)
            if len(items) >= arguments.max_results:
                break

        results = SearchResults(query=arguments.query, items=tuple(items))
        return ToolAdapterResponse(payload=results.model_dump(mode="json"))
