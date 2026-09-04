from datetime import datetime

from opinion_search.tools.capabilities.web import (
    PublicationTimeStatus,
    ReadResult,
    ReaderArguments,
)
from opinion_search.tools.artifacts import (
    ArtifactStoreError,
    ArtifactTooLargeError,
    TextArtifactStore,
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


class JinaReaderAdapter:
    def __init__(
        self,
        *,
        transport: HttpTransport,
        api_key: str | None = None,
        endpoint: str = "https://r.jina.ai/",
        artifact_store: TextArtifactStore | None = None,
        max_inline_content_bytes: int = 64_000,
    ) -> None:
        if max_inline_content_bytes < 1:
            raise ValueError("max_inline_content_bytes must be positive")
        try:
            normalized_endpoint = normalize_secure_provider_endpoint(endpoint)
        except InvalidPublicUrl as exc:
            raise ValueError("Jina Reader endpoint must be a public HTTPS URL") from exc
        self._transport = transport
        self._api_key = api_key.strip() if api_key else None
        self._endpoint = normalized_endpoint.rstrip("/") + "/"
        self._artifact_store = artifact_store
        self._max_inline_content_bytes = max_inline_content_bytes

    async def invoke(
        self,
        invocation: ToolInvocation[ReaderArguments],
    ) -> ToolAdapterResponse:
        try:
            requested_url = normalize_public_url(invocation.arguments.url)
        except InvalidPublicUrl as exc:
            raise ToolAdapterError(
                ToolErrorKind.INVALID_ARGUMENTS,
                "Reader received an unsupported public URL.",
            ) from exc

        headers = {"Accept": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = await self._transport.request(
            method="GET",
            url=f"{self._endpoint}{requested_url}",
            headers=headers,
        )
        raise_for_http_status(response, provider="Jina Reader")

        payload = response.json_body
        if not isinstance(payload, dict):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Jina Reader returned an invalid JSON response.",
            )
        raw_data = payload.get("data", payload)
        if not isinstance(raw_data, dict):
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "Jina Reader returned an invalid data object.",
            )

        title = raw_data.get("title")
        content = raw_data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ToolAdapterError(
                ToolErrorKind.UNREADABLE_CONTENT,
                "Jina Reader returned no readable page content.",
            )
        if not isinstance(title, str) or not title.strip():
            raise ToolAdapterError(
                ToolErrorKind.UNREADABLE_CONTENT,
                "Jina Reader returned no page title.",
            )

        final_url = None
        raw_final_url = raw_data.get("url")
        if isinstance(raw_final_url, str):
            try:
                normalized_final_url = normalize_public_url(raw_final_url)
            except InvalidPublicUrl:
                normalized_final_url = None
            if normalized_final_url != requested_url:
                final_url = normalized_final_url

        artifact_refs: tuple[str, ...] = ()
        if self._artifact_store is not None:
            try:
                artifact_ref = await self._artifact_store.put_text(content)
            except ArtifactTooLargeError as exc:
                raise ToolAdapterError(
                    ToolErrorKind.CONTENT_TOO_LARGE,
                    "Reader content exceeded the configured artifact limit.",
                ) from exc
            except ArtifactStoreError as exc:
                raise ToolAdapterError(
                    ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                    "Reader content could not be persisted safely.",
                ) from exc
            artifact_refs = (artifact_ref,)

        inline_content = _truncate_utf8(
            content,
            self._max_inline_content_bytes,
        )
        published_at = _reported_publication_time(raw_data)
        result = ReadResult(
            url=requested_url,
            final_url=final_url,
            title=title,
            content=inline_content,
            published_at=published_at,
            publication_time_status=(
                PublicationTimeStatus.REPORTED
                if published_at is not None
                else PublicationTimeStatus.UNAVAILABLE
            ),
        )
        return ToolAdapterResponse(
            payload=result.model_dump(mode="json", exclude_none=True),
            artifact_refs=artifact_refs,
        )


def _truncate_utf8(content: str, max_bytes: int) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    if not truncated:
        raise ToolAdapterError(
            ToolErrorKind.UNREADABLE_CONTENT,
            "Reader content could not fit the inline content limit.",
        )
    return truncated


def _reported_publication_time(raw_data: dict[object, object]) -> datetime | None:
    for field_name in ("publishedTime", "published_time", "timestamp"):
        value = raw_data.get(field_name)
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
    return None
