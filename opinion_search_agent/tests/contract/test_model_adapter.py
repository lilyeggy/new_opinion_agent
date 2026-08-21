import asyncio
from dataclasses import dataclass, field

import pytest

from opinion_search.context.models import (
    CompactionMode,
    CompiledContext,
    ContextContentOrigin,
    ContextLayer,
    ContextPlan,
    ContextSection,
    ContextSectionMeasure,
    HeuristicTokenEstimator,
    TrustBoundary,
    render_sections,
)
from opinion_search.domain.opinion.decisions import SearchDecision
from opinion_search.models.contracts import ModelClientError, ModelErrorKind
from opinion_search.models.openai_compatible import (
    ModelHttpResponse,
    OpenAICompatibleModelClient,
)


def _context() -> CompiledContext:
    section = ContextSection(
        section_id="instructions.core",
        layer=ContextLayer.IMMUTABLE_INSTRUCTIONS,
        title="Instructions",
        content="Return one decision.",
        priority=100,
        required=True,
        trust=TrustBoundary.TRUSTED,
        origin=ContextContentOrigin.APP_CONFIG,
        compaction=CompactionMode.NEVER,
    )
    rendered = render_sections((section,))
    measured = HeuristicTokenEstimator().estimate(rendered)
    section_measured = HeuristicTokenEstimator().estimate(
        render_sections((section,))
    )
    plan = ContextPlan(
        selected_section_ids=(section.section_id,),
        input_token_limit=2_000,
        estimated_input_tokens=measured,
        section_measures=(
            ContextSectionMeasure(
                section_id=section.section_id,
                estimated_tokens=section_measured,
            ),
        ),
    )
    from hashlib import sha256

    return CompiledContext(
        run_id="run-1",
        step_id="step-1",
        step_index=1,
        state_revision=0,
        sections=(section,),
        rendered=rendered,
        content_sha256=sha256(rendered.encode("utf-8")).hexdigest(),
        estimated_input_tokens=measured,
        input_token_limit=2_000,
        output_headroom_tokens=400,
        plan=plan,
    )


@dataclass
class FakeModelTransport:
    responses: list[ModelHttpResponse]
    delay_seconds: float = 0
    calls: list[dict[str, object]] = field(default_factory=list)

    async def post(self, **kwargs) -> ModelHttpResponse:
        self.calls.append(kwargs)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.responses.pop(0)


def _success(content: str) -> ModelHttpResponse:
    return ModelHttpResponse(
        status_code=200,
        json_body={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ]
        },
    )


def test_adapter_sends_compiled_context_and_returns_typed_decision() -> None:
    transport = FakeModelTransport(
        responses=[
            _success(
                '{"action":"search","query":"official statement",'
                '"target_gap_id":"gap-primary",'
                '"purpose":"Find the primary account."}'
            )
        ]
    )
    client = OpenAICompatibleModelClient(
        api_key="secret-key",
        transport=transport,
    )

    decision = asyncio.run(client.decide(_context()))

    assert isinstance(decision, SearchDecision)
    call = transport.calls[0]
    assert call["url"] == ("https://opencode.ai/zen/go/v1/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["json_body"]["model"] == "deepseek-v4-flash"
    assert call["json_body"]["response_format"] == {"type": "json_object"}
    assert call["json_body"]["messages"][0]["content"] == _context().rendered
    assert "max_tokens" not in call["json_body"]
    assert "max_completion_tokens" not in call["json_body"]


@pytest.mark.parametrize(
    ("response", "expected_kind"),
    [
        (_success(""), ModelErrorKind.EMPTY_RESPONSE),
        (_success("not-json"), ModelErrorKind.MALFORMED_RESPONSE),
        (
            ModelHttpResponse(
                status_code=200,
                json_body={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "refusal": "Cannot comply.",
                            }
                        }
                    ]
                },
            ),
            ModelErrorKind.REFUSAL,
        ),
        (ModelHttpResponse(status_code=401), ModelErrorKind.AUTHENTICATION),
        (ModelHttpResponse(status_code=429), ModelErrorKind.RATE_LIMITED),
        (ModelHttpResponse(status_code=400), ModelErrorKind.INVALID_REQUEST),
        (ModelHttpResponse(status_code=503), ModelErrorKind.SERVER_ERROR),
    ],
)
def test_adapter_normalizes_provider_and_payload_failures(
    response: ModelHttpResponse,
    expected_kind: ModelErrorKind,
) -> None:
    client = OpenAICompatibleModelClient(
        api_key="secret-key",
        transport=FakeModelTransport(responses=[response]),
    )

    with pytest.raises(ModelClientError) as captured:
        asyncio.run(client.decide(_context()))

    assert captured.value.error.kind is expected_kind
    assert "secret-key" not in str(captured.value)


def test_adapter_timeout_is_typed_and_configuration_is_strict() -> None:
    client = OpenAICompatibleModelClient(
        api_key="secret-key",
        transport=FakeModelTransport(
            responses=[_success("{}")],
            delay_seconds=0.02,
        ),
        timeout_seconds=0.001,
    )

    with pytest.raises(ModelClientError) as captured:
        asyncio.run(client.decide(_context()))

    assert captured.value.error.kind is ModelErrorKind.TIMEOUT
    with pytest.raises(ValueError, match="api_key"):
        OpenAICompatibleModelClient(api_key="   ")


def test_adapter_requires_https_except_explicit_loopback_development() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAICompatibleModelClient(
            api_key="secret-key",
            base_url="http://models.example.com/v1",
        )
    with pytest.raises(ValueError, match="development opt-in"):
        OpenAICompatibleModelClient(
            api_key="secret-key",
            base_url="http://127.0.0.1:8080/v1",
        )

    client = OpenAICompatibleModelClient(
        api_key="secret-key",
        base_url="http://127.0.0.1:8080/v1",
        allow_insecure_loopback=True,
    )

    assert client._endpoint == "http://127.0.0.1:8080/v1/chat/completions"


def test_empty_response_preserves_only_safe_provider_diagnostics() -> None:
    client = OpenAICompatibleModelClient(
        api_key="secret-key",
        transport=FakeModelTransport(
            responses=[
                ModelHttpResponse(
                    status_code=200,
                    json_body={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {
                                    "content": "",
                                    "reasoning": "private reasoning text",
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 30_000,
                            "completion_tokens": 2_000,
                        },
                    },
                )
            ]
        ),
    )

    with pytest.raises(ModelClientError) as captured:
        asyncio.run(client.decide(_context()))

    message = captured.value.error.message
    assert "finish_reason='length'" in message
    assert "reasoning_chars=22" in message
    assert "prompt_tokens=30000" in message
    assert "completion_tokens=2000" in message
    assert "private reasoning text" not in message
    assert "secret-key" not in message
