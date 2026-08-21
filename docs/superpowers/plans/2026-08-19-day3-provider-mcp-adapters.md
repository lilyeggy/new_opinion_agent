# Day 3 Provider and MCP Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Day 3 with production HTTP adapters for Serper and Jina Reader, action-result caching, URL normalization, and a minimal MCP discovery/call adapter over the existing Tool Runtime.

**Architecture:** Provider adapters depend on an injectable HTTP transport and normalize into the existing Web capability schemas. MCP remains another adapter boundary: remote JSON Schema becomes a validating internal ToolDefinition, and structured or unstructured MCP results become ToolOutcome. AgentLoop and Domain State contracts remain unchanged.

**Tech Stack:** Python 3.12, Pydantic 2, httpx, jsonschema, asyncio, pytest.

---

## Scope and files

- Create `opinion_search_agent/src/opinion_search/tools/http.py` for the HTTP transport boundary and status normalization.
- Create `opinion_search_agent/src/opinion_search/tools/url.py` for public URL normalization and local/private literal-host rejection.
- Create `opinion_search_agent/src/opinion_search/tools/cache.py` for action-identity result caching.
- Modify `opinion_search_agent/src/opinion_search/tools/executor.py` to reuse cached successful results.
- Create `opinion_search_agent/src/opinion_search/tools/adapters/serper.py`.
- Create `opinion_search_agent/src/opinion_search/tools/adapters/jina_reader.py`.
- Create `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`.
- Add provider, MCP, URL, cache, and opt-in live tests.
- Modify `opinion_search_agent/pyproject.toml` for required runtime dependencies and a registered live marker.
- Update the five-day plan and implementation memory after verification.

## Tasks

- [x] Freeze public URL normalization, HTTP response, status mapping, and cache behavior with failing tests.
- [x] Implement URL, HTTP, and action-result cache primitives; connect the cache to ToolExecutor.
- [x] Freeze Serper request/response/error normalization with provider contract tests.
- [x] Implement SerperAdapter against the injectable transport and stable SearchResults schema.
- [x] Freeze Jina Reader request/response/error normalization with provider contract tests.
- [x] Implement JinaReaderAdapter against the same transport and stable ReadResult schema.
- [x] Relax internal tool names only as far as current MCP compatibility requires.
- [x] Freeze MCP discovery, JSON Schema validation, call normalization, pagination, error, and output-schema behavior with contract tests.
- [x] Implement MCP descriptor/result models, validating dynamic input model, fake transport, discovery registration, and adapter.
- [x] Add an explicitly gated live Serper-to-Jina smoke test and record whether credentials permit execution.
- [x] Run all tests with warnings as errors, compile checks, diff checks, and a focused architecture review.
- [x] Update implementation memory and mark Day 3 complete only after every offline acceptance gate passes.

## Completion record

Completed on 2026-08-19. The offline acceptance suite passed with `305 passed, 1 skipped`; the skipped case is the deliberately opt-in real-provider smoke because `RUN_LIVE_TOOL_TESTS=1` was not set. Compile and whitespace checks also passed.

## Acceptance criteria

- Serper and FakeSearch satisfy the same SearchResults contract without changing AgentLoop.
- Jina and FakeReader satisfy the same ReadResult contract without changing AgentLoop.
- HTTP 401/403/404/408/429/5xx map to stable ToolError semantics.
- Repeated execution of the same ToolCall on one executor reuses a cached success; action ID reuse with different call data is rejected.
- MCP tools are discovered with deterministic namespaced names and exact model-visible input schema.
- MCP arguments are validated before transport call, structuredContent is preferred, unstructured content remains JSON-safe, and tool-reported errors become non-retryable ToolError.
- Tool annotations and content remain untrusted and do not alter Runtime policy.
- Full offline suite passes without credentials or network access.
