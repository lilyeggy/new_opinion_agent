from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from collections.abc import Mapping
from typing import Annotated, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from opinion_search.context.models import CompiledContext
from opinion_search.domain.opinion.decisions import AgentDecision
from opinion_search.models.contracts import (
    ModelClientError,
    ModelError,
    ModelErrorKind,
)

_LOGGER = logging.getLogger(__name__)
_MAX_OUTPUT_TOKENS_CEILING = 32768


class ModelHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: Annotated[int, Field(ge=100, le=599)]
    json_body: JsonValue | None = None
    text: str = ""


class ModelHttpTransport(Protocol):
    async def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, JsonValue],
    ) -> ModelHttpResponse: ...


class HttpxModelTransport:
    async def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, JsonValue],
    ) -> ModelHttpResponse:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise ModelClientError(
                ModelError(
                    kind=ModelErrorKind.SERVER_ERROR,
                    message="The model provider could not be reached.",
                )
            ) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return ModelHttpResponse(
            status_code=response.status_code,
            json_body=payload,
            text=response.text,
        )


class OpenAICompatibleModelClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: ModelHttpTransport | None = None,
        base_url: str = "https://opencode.ai/zen/go/v1",
        model: str = "deepseek-v4-flash",
        timeout_seconds: float = 60,
        allow_insecure_loopback: bool = False,
        decision_type: object = AgentDecision,
        extra_headers: Mapping[str, str] | None = None,
        max_transport_attempts: int = 1,
        retry_backoff_seconds: float = 0.5,
        max_output_tokens: int = 4096,
    ) -> None:
        normalized_key = api_key.strip()
        normalized_model = model.strip()
        if not normalized_key:
            raise ValueError("model api_key must not be empty")
        if not normalized_model:
            raise ValueError("model name must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("model timeout_seconds must be positive")
        if max_transport_attempts < 1:
            raise ValueError("model max_transport_attempts must be at least one")
        if max_output_tokens < 1:
            raise ValueError("model max_output_tokens must be positive")
        normalized_base_url = _validated_model_base_url(
            base_url,
            allow_insecure_loopback=allow_insecure_loopback,
        )
        self._api_key = normalized_key
        self._transport = transport or HttpxModelTransport()
        self._endpoint = normalized_base_url + "/chat/completions"
        self._model = normalized_model
        self._timeout_seconds = timeout_seconds
        self._decision_adapter = TypeAdapter(decision_type)
        self._extra_headers = _validated_extra_headers(extra_headers)
        self._max_transport_attempts = max_transport_attempts
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._max_output_tokens = max_output_tokens

    async def decide(self, context: CompiledContext) -> AgentDecision:
        current_tokens = self._max_output_tokens
        request: dict[str, JsonValue] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": context.rendered,
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            # Reasoning-style models can drain a low cap on thinking alone and
            # cut the decision JSON mid-object; state the cap explicitly.
            "max_tokens": current_tokens,
        }
        for attempt in range(1, self._max_transport_attempts + 1):
            try:
                awaitable = self._transport.post(
                    url=self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        **self._extra_headers,
                    },
                    # a fresh payload per attempt: a retried call must keep its
                    # own recorded max_tokens, not alias the previous one
                    json_body={**request, "max_tokens": current_tokens},
                )
                async with asyncio.timeout(self._timeout_seconds):
                    response = await awaitable
                self._raise_for_status(response.status_code)
                content, finish_reason = self._extract_content(response.json_body)
            except ModelClientError as exc:
                # Provider faults are not model decisions: retry them so they do not
                # consume the loop's decision-recovery budget.
                if (
                    exc.error.kind not in _TRANSIENT_MODEL_ERRORS
                    or attempt >= self._max_transport_attempts
                ):
                    raise
                await asyncio.sleep(self._retry_backoff_seconds * attempt)
                continue
            except TimeoutError as exc:
                if attempt >= self._max_transport_attempts:
                    raise ModelClientError(
                        ModelError(
                            kind=ModelErrorKind.TIMEOUT,
                            message="The model request timed out.",
                        )
                    ) from exc
                await asyncio.sleep(self._retry_backoff_seconds * attempt)
                continue
            if finish_reason == "length":
                # An output-cap truncation is a request-parameter fault, not a
                # model decision: retry inside the transport budget with a
                # larger cap instead of burning decision-recovery attempts.
                if attempt >= self._max_transport_attempts:
                    choice, message, last_content = _last_choice(response.json_body)
                    diagnostics = _safe_empty_response_diagnostics(
                        response.json_body, choice, message, last_content
                    )
                    raise _model_error(
                        ModelErrorKind.EMPTY_RESPONSE,
                        "The model decision was truncated or empty at the "
                        f"output cap. {diagnostics}",
                    )
                current_tokens = min(current_tokens * 2, _MAX_OUTPUT_TOKENS_CEILING)
                await asyncio.sleep(self._retry_backoff_seconds * attempt)
                continue
            try:
                return self._decision_adapter.validate_python(_first_json_object(content))
            except ValueError as exc:
                # Keep the underlying cause and a content sample: without them a
                # schema death cannot be told apart from a truncation or a
                # field-type drift (P0 observability).
                cause = _schema_error_summary(exc)
                sample = " ".join(content[:240].split())
                _LOGGER.warning(
                    "decision schema mismatch (%s) | content sample: %s", cause, sample
                )
                message = (
                    "The model response did not match the decision schema: "
                    f"{cause} (content head: {sample[:160]})"
                )
                raise ModelClientError(
                    ModelError(kind=ModelErrorKind.MALFORMED_RESPONSE, message=message)
                ) from exc

    @staticmethod
    def _extract_content(payload: JsonValue | None) -> tuple[str, str]:
        if not isinstance(payload, dict):
            raise _model_error(
                ModelErrorKind.MALFORMED_RESPONSE,
                "The model provider returned an invalid JSON payload.",
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise _model_error(
                ModelErrorKind.MALFORMED_RESPONSE,
                "The model provider returned no response choice.",
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise _model_error(
                ModelErrorKind.MALFORMED_RESPONSE,
                "The model provider returned an invalid choice.",
            )
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            finish_reason = ""
        message = choice.get("message")
        if not isinstance(message, dict):
            raise _model_error(
                ModelErrorKind.MALFORMED_RESPONSE,
                "The model provider returned no assistant message.",
            )
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise _model_error(
                ModelErrorKind.REFUSAL,
                "The model refused to produce a decision.",
            )
        content = message.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            # A reasoning model can spend the whole output cap on thinking;
            # a length-flagged empty body goes back to the caller so it can
            # retry with a larger cap instead of burning a decision attempt.
            if finish_reason == "length":
                return "", finish_reason
            diagnostics = _safe_empty_response_diagnostics(
                payload,
                choice,
                message,
                content,
            )
            raise _model_error(
                ModelErrorKind.EMPTY_RESPONSE,
                f"The model returned an empty decision. {diagnostics}",
            )
        if not isinstance(content, str):
            raise _model_error(
                ModelErrorKind.MALFORMED_RESPONSE,
                "The model decision content was not text.",
            )
        return content, finish_reason

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            kind = ModelErrorKind.AUTHENTICATION
            message = "The model provider rejected authentication."
        elif status == 429:
            kind = ModelErrorKind.RATE_LIMITED
            message = "The model provider rate limited the request."
        elif 400 <= status < 500:
            kind = ModelErrorKind.INVALID_REQUEST
            message = (
                f"The model provider rejected the request with HTTP status {status}."
            )
        else:
            kind = ModelErrorKind.SERVER_ERROR
            message = f"The model provider returned HTTP status {status}."
        raise _model_error(kind, message)


def _model_error(kind: ModelErrorKind, message: str) -> ModelClientError:
    return ModelClientError(ModelError(kind=kind, message=message))


def _last_choice(payload: JsonValue | None) -> tuple[dict, dict, object]:
    """Best-effort (choice, message, content) extraction for post-hoc diagnostics."""

    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            message = choice.get("message")
            if isinstance(message, dict):
                return choice, message, message.get("content")
            return choice, {}, None
    return {}, {}, None


def _safe_empty_response_diagnostics(
    payload: dict,
    choice: dict,
    message: dict,
    content: object,
) -> str:
    finish_reason = choice.get("finish_reason")
    usage = payload.get("usage")
    prompt_tokens = None
    completion_tokens = None
    if isinstance(usage, dict):
        if isinstance(usage.get("prompt_tokens"), int):
            prompt_tokens = usage["prompt_tokens"]
        if isinstance(usage.get("completion_tokens"), int):
            completion_tokens = usage["completion_tokens"]
    reasoning_chars = 0
    for key in ("reasoning_content", "reasoning", "analysis"):
        value = message.get(key)
        if isinstance(value, str):
            reasoning_chars += len(value)
    content_state = "null" if content is None else "blank"
    return (
        "Safe provider metadata: "
        f"finish_reason={finish_reason!r}, "
        f"content_state={content_state}, "
        f"reasoning_chars={reasoning_chars}, "
        f"prompt_tokens={prompt_tokens}, "
        f"completion_tokens={completion_tokens}."
    )


_RESERVED_HEADERS = frozenset({"authorization", "content-type", "accept"})
_TRANSIENT_MODEL_ERRORS = frozenset(
    {
        ModelErrorKind.TIMEOUT,
        ModelErrorKind.SERVER_ERROR,
        ModelErrorKind.EMPTY_RESPONSE,
    }
)


def _schema_error_summary(exc: ValueError) -> str:
    """Short human-readable cause for a schema-validation failure.

    Pydantic and JSON errors carry the actual reason (field path, type
    expectation, byte offset); surfacing it makes a truncation, a field-type
    drift and an enum miss distinguishable instead of one generic message.
    """

    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors()[:3]:
            loc = ".".join(str(item) for item in error.get("loc", ())) or "<root>"
            parts.append(f"{loc}: {error.get('msg', 'invalid')}")
        return "; ".join(parts)[:220]
    text = str(exc)
    return text[:220] if text else "unparseable decision content"


def _first_json_object(content: str) -> JsonValue:
    """Parse the first JSON object in the model content.

    Instructed-JSON models still append commentary, a second object, or a
    tool-call block after the decision. Requiring the whole string to be one
    document drops otherwise valid decisions, so take the first balanced object.
    """
    text = content.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError("the model response contained no JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError("the model response contained no complete JSON object")


def _validated_extra_headers(
    extra_headers: Mapping[str, str] | None,
) -> dict[str, str]:
    if not extra_headers:
        return {}
    normalized: dict[str, str] = {}
    for name, value in extra_headers.items():
        key = str(name).strip()
        if not key:
            raise ValueError("extra header names must not be empty")
        if key.casefold() in _RESERVED_HEADERS:
            raise ValueError(f"extra headers must not override {key}")
        text = str(value).strip()
        if not text:
            raise ValueError(f"extra header {key} must not be empty")
        normalized[key] = text
    return normalized


def _validated_model_base_url(
    base_url: str,
    *,
    allow_insecure_loopback: bool,
) -> str:
    candidate = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        parsed.port
    except ValueError as exc:
        raise ValueError("model base_url is invalid") from exc
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("model base_url must be an absolute provider URL")
    if parsed.scheme == "https":
        return urlunsplit(parsed)
    if (
        parsed.scheme == "http"
        and allow_insecure_loopback
        and _is_loopback_host(parsed.hostname)
    ):
        return urlunsplit(parsed)
    raise ValueError(
        "model base_url must use HTTPS; loopback HTTP requires an explicit "
        "development opt-in"
    )


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
