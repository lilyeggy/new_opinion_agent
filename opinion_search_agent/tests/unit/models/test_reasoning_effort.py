"""The reasoning budget is a request parameter, not a hope."""

from __future__ import annotations

import asyncio
import json

from tests.support.opinion.decisions import AgentDecision

from opinion_search.context.models import CompiledContext
from opinion_search.models.openai_compatible import (
    HttpxModelTransport, ModelHttpResponse, OpenAICompatibleModelClient,
)


class _Capture(HttpxModelTransport):
    def __init__(self) -> None:
        self.body: dict = {}

    async def post(self, *, url, headers, json_body):  # type: ignore[override]
        self.body = json_body
        return ModelHttpResponse(
            status_code=200,
            json_body={"choices": [{"message": {"content": json.dumps({
                "action": "search", "purpose": "测试", "query": "测试", "target_gap_id": "gap-1"
            })}, "finish_reason": "stop"}]},
            text="",
        )


def _context() -> CompiledContext:
    return CompiledContext.model_construct(rendered="test")


def test_effort_is_sent_when_configured():
    capture = _Capture()
    client = OpenAICompatibleModelClient(decision_type=AgentDecision,
        api_key="k", transport=capture, base_url="https://example.com/v1",
        model="m", reasoning_effort="low",
    )
    asyncio.run(client.decide(_context()))
    assert capture.body.get("reasoning_effort") == "low"


def test_no_effort_key_when_unset():
    capture = _Capture()
    client = OpenAICompatibleModelClient(decision_type=AgentDecision,
        api_key="k", transport=capture, base_url="https://example.com/v1", model="m",
    )
    asyncio.run(client.decide(_context()))
    assert "reasoning_effort" not in capture.body
