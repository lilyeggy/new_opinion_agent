import asyncio
import os

import pytest

from opinion_search.app.config import LiveConfig
from opinion_search.app.contracts import SearchRequest
from opinion_search.app.service import build_live_service
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.tools.adapters.brave_search import BraveSearchAdapter
from opinion_search.tools.adapters.jina_reader import JinaReaderAdapter
from opinion_search.tools.capabilities.web import (
    ReadResult,
    SearchResults,
    reader_tool_definition,
    search_tool_definition,
)
from opinion_search.tools.contracts import RetryPolicy, ToolCall, ToolResult
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.http import HttpxTransport
from opinion_search.tools.registry import ToolRegistry


pytestmark = pytest.mark.live


def test_real_search_then_read_smoke() -> None:
    if os.getenv("RUN_LIVE_TOOL_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TOOL_TESTS=1 to enable provider smoke tests")
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not brave_key:
        pytest.skip("BRAVE_SEARCH_API_KEY is required for the live provider smoke test")

    transport = HttpxTransport()
    registry = ToolRegistry()
    registry.register(
        search_tool_definition(),
        BraveSearchAdapter(transport=transport, api_key=brave_key),
    )
    registry.register(
        reader_tool_definition(),
        JinaReaderAdapter(
            transport=transport,
            api_key=os.getenv("JINA_API_KEY"),
        ),
    )
    executor = ToolExecutor(
        registry,
        retry_policy=RetryPolicy(
            max_attempts_per_provider=2,
            timeout_seconds=30,
            backoff_seconds=0.25,
        ),
    )

    search_outcome = asyncio.run(
        executor.execute(
            ToolCall(
                action_id="live-search-1",
                tool_name="search.web",
                arguments={
                    "query": "OpenAI official company news",
                    "max_results": 3,
                },
            )
        )
    )
    assert isinstance(search_outcome, ToolResult), search_outcome
    results = SearchResults.model_validate(search_outcome.payload)
    assert results.items

    read_outcome = asyncio.run(
        executor.execute(
            ToolCall(
                action_id="live-read-1",
                tool_name="read.web",
                arguments={"url": results.items[0].url},
            )
        )
    )
    assert isinstance(read_outcome, ToolResult), read_outcome
    page = ReadResult.model_validate(read_outcome.payload)
    assert page.content.strip()


def test_real_model_search_agent_smoke(tmp_path) -> None:
    if os.getenv("RUN_LIVE_AGENT_TESTS") != "1":
        pytest.skip("set RUN_LIVE_AGENT_TESTS=1 to enable the live Agent smoke test")
    config = LiveConfig.from_env()
    service = build_live_service(tmp_path / "live-agent.json", config)

    outcome = asyncio.run(
        service.investigate(
            SearchRequest(
                question=(
                    "What did OpenAI announce about GPT-5.4, and how did "
                    "independent public-Web coverage describe it?"
                ),
                topic="OpenAI GPT-5.4 announcement",
                time_range="2026-03-01/2026-04-30",
                focus=(
                    "Original announcement, independent coverage, and any "
                    "material corrections or disagreements."
                ),
                language="en",
            ),
            run_id="live-agent-smoke",
        )
    )

    assert outcome.status in {RunStatus.COMPLETED, RunStatus.PARTIAL}
    assert outcome.source_urls
    assert "## Sources" in outcome.markdown
    assert "## Remaining gaps" in outcome.markdown
