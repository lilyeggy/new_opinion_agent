import asyncio
import sys
from pathlib import Path

import pytest

from opinion_search.tools.adapters.mcp import (
    McpToolBinding,
    canonical_schema_hash,
    register_mcp_tools,
)
from opinion_search.tools.adapters.mcp_sdk import (
    McpStdioConfig,
    SdkMcpTransport,
)
from opinion_search.tools.cache import ToolCacheConflictError
from opinion_search.tools.contracts import ToolCall, ToolResult
from opinion_search.tools.executor import ToolExecutor
from opinion_search.tools.registry import ToolRegistry


FIXTURE = str(
    (Path(__file__).parents[1] / "fixtures/mcp/read_only_server.py").resolve()
)


class CountingTransport:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[tuple[str, dict]] = []
        self.list_count = 0

    async def list_tools(self, *, cursor=None):
        self.list_count += 1
        return await self._inner.list_tools(cursor=cursor)

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return await self._inner.call_tool(name, arguments)


def run(awaitable):
    return asyncio.run(awaitable)


def test_mcp_tool_runs_through_registry_and_executor_end_to_end() -> None:
    transport = CountingTransport(
        SdkMcpTransport(
            McpStdioConfig(command=sys.executable, args=(FIXTURE,))
        )
    )
    discovered = run(transport.list_tools())
    descriptor = discovered.tools[0]

    binding = McpToolBinding(
        remote_name=descriptor.name,
        local_description="Reviewed local search description.",
        capability="mcp",
        expected_input_schema_sha256=canonical_schema_hash(
            descriptor.input_schema
        ),
        expected_output_schema_sha256=canonical_schema_hash(
            descriptor.output_schema
        ),
    )
    registry = ToolRegistry()
    run(register_mcp_tools(registry, transport, server_id="local", bindings=(binding,)))

    # model spec uses the local description, never the remote prose
    qualified = "mcp.local.search_fixture"
    model_spec = registry.model_specs()[0]
    assert model_spec["name"] == qualified
    assert model_spec["description"] == "Reviewed local search description."
    assert "Deterministic search fixture" not in model_spec["description"]

    # one definition, one provider
    registered = registry.resolve(qualified)
    assert registered.definition.name == qualified
    assert len(registered.providers) == 1
    assert registered.definition.capability == "mcp"

    executor = ToolExecutor(registry)
    call = ToolCall(
        action_id="mcp-action-1",
        tool_name=qualified,
        arguments={"query": "alpha"},
    )

    outcome = run(executor.execute(call))

    assert isinstance(outcome, ToolResult)
    assert outcome.action_id == "mcp-action-1"
    assert isinstance(outcome.payload, dict)
    assert outcome.payload["query"] == "alpha"
    assert outcome.payload["matches"] == [
        "alpha result one",
        "alpha result two",
    ]
    assert [name for name, _ in transport.calls] == ["search_fixture"]

    # identical action is served by cache without spawning/calling the server
    outcome2 = run(executor.execute(call))
    assert outcome2 == outcome
    assert len(transport.calls) == 1

    # same action id with different arguments is an identity conflict
    conflicting = ToolCall(
        action_id="mcp-action-1",
        tool_name=qualified,
        arguments={"query": "gamma"},
    )
    with pytest.raises(ToolCacheConflictError):
        run(executor.execute(conflicting))
    assert len(transport.calls) == 1
