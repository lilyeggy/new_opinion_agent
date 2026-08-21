from urllib.parse import urlencode

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


class BraveSearchAdapter:
    def __init__(
        self,
        *,
        transport: HttpTransport,
        api_key: str,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("Brave Search api_key must not be empty")
        try:
            normalized_endpoint = normalize_secure_provider_endpoint(endpoint)
        except InvalidPublicUrl as exc:
            raise ValueError(
                "Brave Search endpoint must be a public HTTPS URL"
            ) from exc
        self._transport = transport
        self._api_key = normalized_key
        self._endpoint = normalized_endpoint

    async def invoke(
        self,
        invocation: ToolInvocation[SearchArguments],
    ) -> ToolAdapterResponse:
        arguments = invocation.arguments
        query_string = urlencode(
            {
                "q": arguments.query,
                "count": arguments.max_results,
                "result_filter": "web",
                "text_decorations": "false",
            }
        )
        response = await self._transport.request(
            method="GET",
            url=f"{self._endpoint}?{query_string}",
            headers={
                "X-Subscription-Token": self._api_key,
                "Accept": "application/json",
            },
        )
        raise_for_http_status(response, provider="Brave Search")

        payload = response.json_body
        if not isinstance(payload, dict):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Brave Search returned an invalid JSON response.",
            )
        web = payload.get("web")
        if not isinstance(web, dict):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Brave Search returned no web result object.",
            )
        raw_results = web.get("results")
        if not isinstance(raw_results, list):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Brave Search returned an invalid web result list.",
            )

        items: list[SearchHit] = []
        for raw_item in raw_results:
            if not isinstance(raw_item, dict):
                continue
            try:
                item = SearchHit(
                    title=raw_item.get("title"),
                    url=normalize_public_url(raw_item.get("url", "")),
                    snippet=raw_item.get("description"),
                )
            except (InvalidPublicUrl, ValidationError):
                continue
            items.append(item)
            if len(items) >= arguments.max_results:
                break

        results = SearchResults(query=arguments.query, items=tuple(items))
        return ToolAdapterResponse(payload=results.model_dump(mode="json"))
