"""Minimal official SDK v2 MCP server for local stdio contract tests.

Deterministic, read-only, no network. Echoes a fixed allowlisted env token and
whether a parent-process env var leaked through the transport allowlist,
without reading any secret values into logs.

When the test-only allowlisted environment variable ``MCP_FIXTURE_LIFECYCLE_PATH``
is present, the fixture writes an atomic JSON lifecycle marker on start and
atomically replaces it with a closed marker when the server exits. The marker
contains only a generated instance ID; no environment, token, command or
credential is ever written.
"""

import asyncio
import json
import os
import tempfile
from uuid import uuid4

from mcp.server.mcpserver import MCPServer


def build_server(server_name: str = "read-only-fixture") -> MCPServer:
    server = MCPServer(server_name)

    @server.tool()
    async def search_fixture(query: str) -> dict[str, object]:
        """Deterministic search fixture over a fixed result list."""
        matches = {
            "alpha": ["alpha result one", "alpha result two"],
            "beta": ["beta result one"],
        }
        return {
            "query": query,
            "matches": matches.get(query, []),
            "env_token": os.environ.get("MCP_FIXTURE_TOKEN"),
            "env_leaked": "MCP_FIXTURE_SHOULD_NOT_LEAK" in os.environ,
        }

    return server


def _write_lifecycle(path: str, payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    target = os.path.abspath(path)
    target_dir = os.path.dirname(target)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target_dir,
        prefix=".lifecycle.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_path = temporary_file.name
        temporary_file.write(serialized)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())
    os.replace(temporary_path, target)


async def main() -> None:
    lifecycle_path = os.environ.get("MCP_FIXTURE_LIFECYCLE_PATH")
    instance_id = uuid4().hex
    if lifecycle_path:
        _write_lifecycle(
            lifecycle_path,
            {"state": "started", "instance_id": instance_id},
        )
    try:
        await build_server().run_stdio_async()
    finally:
        if lifecycle_path:
            _write_lifecycle(
                lifecycle_path,
                {"state": "closed", "instance_id": instance_id},
            )


if __name__ == "__main__":
    asyncio.run(main())