# Tool and MCP Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> If those skills are unavailable in the execution environment, follow the numbered Task, test-first sequence, stop conditions, and review handoff in this document directly; missing a skill is not permission to redesign the Task.

**Goal:** Turn the existing Tool Runtime and MCP contract adapter into a provider-independent, failure-aware execution layer with a real MCP v2 transport, explicit provider fallback, bounded retry, circuit breaking, and safe discovery.

**Architecture:** Preserve one stable ToolDefinition per model-visible capability. Registry owns the ordered provider bindings for that definition; ToolExecutor owns argument validation, same-provider retry, provider fallback, circuit state, timeout, backoff, and success caching; adapters only normalize one provider protocol. MCP discovery is allowlisted and schema-pinned before it can create a local ToolDefinition.

**Tech Stack:** Python 3.12+, Pydantic 2, official MCP Python SDK v2 (`mcp>=2,<3`), jsonschema Draft 2020-12, asyncio, pytest.

---

## Scope and authority

Read first:

1. `docs/agent-infra-interview-deepening.md`
2. `opinion_search_agent/src/opinion_search/tools/contracts.py`
3. `opinion_search_agent/src/opinion_search/tools/registry.py`
4. `opinion_search_agent/src/opinion_search/tools/executor.py`
5. `opinion_search_agent/src/opinion_search/tools/cache.py`
6. `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`
7. Brave/Jina adapters and their contract tests.

Official time-sensitive references:

- [MCP Python SDK v2 stable line](https://github.com/modelcontextprotocol/python-sdk)
- [MCP v2 Client API and pagination](https://py.sdk.modelcontextprotocol.io/client/)
- [MCP standard transports and security requirements](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

Do not use MCP v1 examples containing `ClientSession` as the implementation source. In v2, use the high-level `mcp.Client` API. Do not add the `mcp[cli]` extra to production dependencies; plain `mcp>=2,<3` is enough for the client. One-off developer Inspector usage is not a package dependency.

## Frozen ownership model

```text
Model
  -> stable local ToolDefinition only

ToolRegistry
  -> tool name resolution
  -> exact definition identity
  -> ordered provider bindings

ToolExecutor
  -> input validation
  -> success cache
  -> provider availability
  -> timeout
  -> same-provider retry
  -> cross-provider fallback
  -> safe ToolError

Provider Adapter
  -> one invocation to one provider
  -> provider request/response normalization
  -> ToolAdapterResponse or ToolAdapterError
```

An Adapter must never call another Adapter, perform its own retry loop, inspect Agent State, or choose the next provider.

## Retry and fallback semantics

For one `ToolCall`:

```text
validate once
check action-result cache once
for provider in configured order:
    skip provider if circuit is open
    invoke provider up to max_attempts_per_provider
    retry only timeout/rate_limited/server_error
    on success: close circuit, persist result, return
    on provider-scoped failure: record health and consider next provider
return one safe ToolError after all eligible providers are exhausted
```

Identity rules:

- `action_id` is constant across every provider and retry;
- `ToolInvocation.attempt` is a global monotonically increasing physical invocation count for that ToolCall, not a per-provider counter;
- `ToolResult.attempts` is total physical invocations before success;
- fallback does not create a new Agent step or Action;
- cache key remains exact ToolCall identity, not provider identity;
- model never receives `provider_id`.

Failure classification:

| Kind | Same-provider retry | Next provider | Stop immediately |
|---|---:|---:|---:|
| invalid_arguments | no | no | yes |
| unknown_tool | no | no | yes |
| cancelled | no | no | yes |
| timeout | yes | yes after exhaustion | no |
| rate_limited | yes | yes after exhaustion | no |
| server_error | yes | yes after exhaustion | no |
| authentication | no | yes | no |
| permission | no | yes | no |
| not_found | no | yes | no |
| unreadable_content | no | yes | no |
| content_too_large | no | yes | no |
| unknown_provider_error | no | yes | no |

The final ToolError keeps the last safe kind/message and total attempt count. Do not concatenate raw provider errors.

## MCP trust boundary

Remote MCP discovery is untrusted. A remote server cannot place arbitrary description or schema prose into trusted L1 Context merely by advertising a tool.

Registration requires an app-owned allowlist binding containing:

```text
remote_name
local_description
capability
expected_input_schema_sha256
expected_output_schema_sha256 (optional)
```

The local registered name remains `mcp.<server_id>.<remote_name>`. The local description comes from app config, never from the remote descriptor. Canonical JSON schema hashes pin the reviewed remote input/output contract. If a server changes a pinned schema, discovery fails atomically and registers nothing.

MCP `annotations`, remote description, content blocks and `_meta` have no policy authority. `_meta` is not forwarded to model Context and must never be assumed secret-safe.

## File map

Create:

- `opinion_search_agent/src/opinion_search/tools/routing.py` — provider binding, provider chain policy and fallback decisions.
- `opinion_search_agent/src/opinion_search/tools/circuit.py` — in-memory provider health state with injected monotonic clock.
- `opinion_search_agent/src/opinion_search/tools/adapters/mcp_sdk.py` — official SDK v2 transport implementation.
- `opinion_search_agent/tests/unit/tools/test_routing.py`
- `opinion_search_agent/tests/unit/tools/test_circuit.py`
- `opinion_search_agent/tests/contract/test_mcp_sdk_transport.py`
- `opinion_search_agent/tests/fixtures/mcp/read_only_server.py` — local deterministic stdio MCP server.

Modify:

- `opinion_search_agent/pyproject.toml`
- `opinion_search_agent/src/opinion_search/tools/contracts.py`
- `opinion_search_agent/src/opinion_search/tools/registry.py`
- `opinion_search_agent/src/opinion_search/tools/executor.py`
- `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`
- Tool, MCP and service composition tests.

## Task 1: Freeze provider binding contracts in the Registry

**Files:**

- Create: `opinion_search_agent/src/opinion_search/tools/routing.py`
- Modify: `opinion_search_agent/src/opinion_search/tools/registry.py`
- Test: `opinion_search_agent/tests/unit/tools/test_registry.py`
- Create: `opinion_search_agent/tests/unit/tools/test_routing.py`

### Required types

```text
ProviderId
  1..64 characters
  pattern: ^[a-z][a-z0-9_-]*$

ProviderBinding
  provider_id: ProviderId
  adapter: ToolAdapter (excluded from serialization)

RegisteredTool
  definition: ToolDefinition
  providers: non-empty ordered tuple[ProviderBinding, ...]
```

Keep `ToolRegistry.register(definition, adapter)` as a compatibility method. It registers provider ID `default`. Add:

```text
register_provider(
    definition: ToolDefinition,
    provider_id: str,
    adapter: ToolAdapter,
) -> None
```

### Registry rules

- first provider creates RegisteredTool;
- later provider for the same tool name is allowed only when ToolDefinition is exactly equal;
- same tool name with different description, capability or input model identity is `DuplicateToolError`;
- same provider ID for one tool is `DuplicateToolError`;
- provider order is registration order and deterministic;
- `definitions()` and `model_specs()` still return one definition per tool, never one per provider;
- `resolve()` returns the definition and all provider bindings;
- provider IDs and adapters never enter model specs.

### Tests

- [ ] Existing single-provider registration behavior remains green.
- [ ] Two exact-definition providers resolve in registration order.
- [ ] Duplicate provider ID fails.
- [ ] Same name/different definition fails without mutating the existing registration.
- [ ] Model specs are byte-identical with one or multiple providers.
- [ ] Capability filtering still returns one definition.

## Task 2: Move retry and fallback ownership into ToolExecutor

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/tools/contracts.py`
- Modify: `opinion_search_agent/src/opinion_search/tools/executor.py`
- Test: `opinion_search_agent/tests/unit/tools/test_executor.py`
- Test: `opinion_search_agent/tests/unit/tools/test_routing.py`

### RetryPolicy change

Rename the semantic meaning of `max_attempts` to `max_attempts_per_provider`. To avoid silently changing serialized config, either perform an explicit field rename with all callers updated in this Task or retain the field name and clearly document its new per-provider meaning. Prefer explicit rename because this object is app configuration, not checkpoint state.

Add:

```text
max_backoff_seconds > 0
```

Backoff is `min(base * 2^(local_attempt-1), max_backoff_seconds)`.

Extend `ToolAdapterError` with optional numeric `retry_after_seconds >= 0`. It is not included in the safe message. Delay for a retry is:

```text
max(exponential_backoff, retry_after_seconds or 0)
```

then capped by `max_backoff_seconds`.

### Executor algorithm requirements

- validate arguments before resolving provider attempts;
- cache lookup happens after validation and before provider health lookup;
- global invocation attempt begins at one and increments exactly once per adapter call;
- pass the global attempt into ToolInvocation;
- catch `asyncio.CancelledError` by not catching it; it must propagate to AgentLoop cancellation handling;
- catch TimeoutError, ToolAdapterError and unknown `Exception` as today;
- never catch `BaseException`;
- same-provider retry only for current retryable kinds;
- after provider exhaustion, consult the frozen fallback table above;
- success writes cache before returning;
- cache conflict is a Runtime/programming failure and must not be converted to provider ToolError;
- final ToolError attempt count is global physical invocation count.

### Required tests

- primary succeeds: fallback not called;
- timeout then primary succeeds: same provider called twice, global attempts 2;
- primary exhausts timeout, fallback succeeds: call order primary, primary, fallback;
- primary authentication fails, fallback succeeds without retrying primary;
- invalid arguments call no provider;
- cancelled primary calls no fallback;
- all providers fail: final safe error and correct total attempts;
- cache hit calls no provider even when every circuit is open;
- same action ID with changed call still raises cache conflict;
- Retry-After dominates smaller exponential delay and is capped;
- no provider ID appears in ToolResult/ToolError model dump.

## Task 3: Add an in-memory circuit breaker per tool/provider

**Files:**

- Create: `opinion_search_agent/src/opinion_search/tools/circuit.py`
- Modify: `opinion_search_agent/src/opinion_search/tools/executor.py`
- Create: `opinion_search_agent/tests/unit/tools/test_circuit.py`

### Required state

```text
CircuitStatus = closed | open | half_open

ProviderCircuitKey
  tool_name
  provider_id

ProviderCircuitRecord
  consecutive_failures
  opened_at_monotonic (optional)
  probe_in_flight
```

Configuration:

```text
failure_threshold >= 1, default 3
cooldown_seconds > 0, default 30
```

Only timeout, rate_limited, server_error and unknown_provider_error count toward opening. Authentication and permission may fallback but do not poison health permanently because they are usually configuration-specific and should remain visible on the next run. Success resets the record.

Algorithm:

- closed providers are allowed;
- reaching threshold opens the circuit and records monotonic time;
- before cooldown, open provider is skipped;
- after cooldown, one call becomes the half-open probe;
- concurrent requests while probe is in flight skip that provider;
- probe success closes/reset;
- probe counted failure reopens and resets open time.

Inject monotonic clock. Do not use wall clock or sleep in unit tests. Circuit state is intentionally in-memory and resets on process restart; it is execution health, not Domain State or checkpoint data.

### Tests

- threshold transition;
- open skip before cooldown;
- half-open single probe;
- success reset;
- failed probe reopen;
- independent records by tool and provider;
- non-counted error does not open;
- deterministic fake clock, no real waiting.

## Task 4: Make MCP discovery allowlisted and schema-pinned

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`
- Modify: `opinion_search_agent/tests/contract/test_mcp_adapter.py`

### Required config model

```text
McpToolBinding
  remote_name
  local_description
  capability
  expected_input_schema_sha256
  expected_output_schema_sha256: optional
```

Hash algorithm:

1. serialize schema with UTF-8, sorted keys, compact separators, no whitespace normalization inside string values;
2. SHA-256 bytes;
3. lowercase hex digest.

Change `register_mcp_tools()` to require an explicit non-empty tuple of bindings. It must not auto-register every discovered remote tool.

### Atomic discovery rules

1. retrieve every page and detect cursor cycles;
2. reject duplicate remote names;
3. validate all schemas;
4. find every allowlisted remote name exactly once;
5. verify input and optional output hashes;
6. construct every pending local definition using local description/capability;
7. check every Registry conflict;
8. only after all checks pass, register all pending tools.

Any failure leaves Registry byte-for-byte unchanged.

Remote annotations remain excluded. Remote description is retained only inside the untrusted descriptor object for diagnostics and never copied into ToolDefinition. Do not include mismatched schema bodies in exceptions; report remote name and expected/actual hash only.

### Required tests

- only allowlisted tools register;
- missing allowlisted tool fails atomically;
- extra remote tool is ignored;
- remote description containing prompt injection never appears in model spec;
- exact schema hash passes;
- changed property, required list or output schema fails;
- one bad binding prevents every registration;
- duplicate and cursor cycle behavior remains covered;
- annotations cannot change capability, retry or permission semantics.

## Task 5: Implement the official MCP SDK v2 transport

**Files:**

- Modify: `opinion_search_agent/pyproject.toml`
- Create: `opinion_search_agent/src/opinion_search/tools/adapters/mcp_sdk.py`
- Create: `opinion_search_agent/tests/contract/test_mcp_sdk_transport.py`
- Create: `opinion_search_agent/tests/fixtures/mcp/read_only_server.py`

### Dependency

Add plain `mcp>=2,<3`. Do not add the CLI extra. Record the exact resolved version in test output or lockfile if the repository adopts one; do not import v1 symbols.

### Transport configuration

Use a discriminated Pydantic union owned by app configuration, never Domain State:

```text
McpStdioConfig
  transport = "stdio"
  command: non-empty absolute executable or explicitly resolved executable name
  args: tuple[str, ...]
  cwd: optional Path
  env: explicit dict[str, SecretStr]

McpHttpConfig
  transport = "streamable_http"
  url: public HTTPS URL, or loopback HTTP only under explicit development flag
  headers: dict[str, SecretStr]
```

Never inherit the entire process environment into stdio config. Only the SDK's minimal safe environment plus explicitly named entries may reach the child. Never serialize SecretStr values into repr, checkpoint or errors.

### SdkMcpTransport behavior

Implement the existing `McpTransport` protocol using `mcp.Client`:

- each `list_tools(cursor=...)` opens a client context, calls `client.list_tools(cursor=cursor)`, maps one page, then closes;
- each `call_tool(name, arguments)` opens a client context, calls `client.call_tool`, maps result, then closes;
- this first implementation deliberately targets stateless read-only MCP tools; document that stateful session reuse is not supported;
- map `input_schema`, `output_schema`, `annotations`, `next_cursor`, `structured_content`, `content`, and `is_error` without provider objects escaping;
- content blocks are converted via Pydantic `model_dump(mode="json")` and validated as JsonValue;
- SDK connection/protocol errors become safe `McpToolDiscoveryError` during discovery or safe `ToolAdapterError` during call;
- error messages never include command env, headers, response body or exception repr;
- SDK timeout remains outer ToolExecutor responsibility; do not add a second retry loop.

### Local real transport fixture

`tests/fixtures/mcp/read_only_server.py` is a minimal official SDK v2 server exposing one read-only structured tool:

```text
search_fixture(query: str) -> {query: str, matches: list[str]}
```

It has deterministic output, no network, no filesystem mutation and no secrets. Launch it through stdio in the contract test. The test is not gated because it is local and deterministic.

### Required tests

- real stdio discovery maps name/description/input/output schema;
- real stdio call returns structured content;
- remote `is_error` becomes ToolAdapterError through McpToolAdapter;
- invalid arguments fail locally before stdio call;
- subprocess exits after client context;
- explicit env allowlist behavior;
- missing executable yields safe error without command internals beyond safe configured name;
- Streamable HTTP config rejects remote plain HTTP and accepts loopback only with development opt-in;
- fake transport contract suite remains green.

## Task 6: Demonstrate MCP through the same Registry and Executor

**Files:**

- Create or modify: `opinion_search_agent/tests/e2e/test_real_mcp_tool.py`
- Modify: app service only if a development composition is needed.

### Required e2e path

```text
local MCP stdio server
  -> SdkMcpTransport.list_tools
  -> allowlist/schema pin
  -> register_mcp_tools
  -> ToolRegistry model spec
  -> ToolExecutor ToolCall
  -> McpToolAdapter
  -> SdkMcpTransport.call_tool
  -> ToolResult
```

Assertions:

- only the stable qualified tool name reaches ToolCall;
- model spec contains local description, not remote description;
- Registry has one definition/provider;
- ToolInvocation action ID survives unchanged;
- structured result validates output schema;
- second exact ToolCall with same action ID is served by cache and does not spawn/call the MCP server again;
- a different ToolCall using the same action ID raises identity conflict;
- MCP content remains untrusted when compiled into Agent Context.

This Task does not make the OpinionSearch model dynamically choose arbitrary MCP tools. The purpose is proving transport interchangeability through the existing Tool Runtime.

## Task 7: Provider fallback composition for OpinionSearch

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/app/service.py`
- Modify: `opinion_search_agent/src/opinion_search/app/config.py`
- Test: app composition and e2e Tool fallback tests.

### Composition boundary

Do not require a second paid search API. Live default remains one Brave provider for `search.web` and one Jina provider for `read.web`. Add optional provider bindings only when explicitly configured by app composition.

Offline composition registers two deterministic fake providers to prove behavior:

- primary fake fails with configured retryable error;
- secondary fake succeeds with contract-equivalent SearchResults or ReadResult.

App config may expose provider chain order by stable local provider IDs, but provider SDK objects and secrets stay in builder code. Do not put provider chains in SearchRequest, Domain State, Context or checkpoint.

### Acceptance

- live single-provider behavior and model specs are unchanged;
- offline failure injection proves fallback;
- provider order is deterministic;
- execution profile changes when the live provider composition changes, preventing incompatible resume;
- execution profile remains opaque and reveals no provider names or keys;
- no Agent Decision names a provider.

## Task 8: Final verification and documentation

**Files:**

- Modify after verification: `docs/public-opinion-search-agent-design.md`
- Append facts only: `docs/opinion-search-agent-implementation-memory.md`
- Modify: `opinion_search_agent/README.md`

- [ ] Run all Tool, MCP, app composition and recovery tests.
- [ ] Run the local real stdio MCP e2e without network or secrets.
- [ ] Run existing Brave/Jina gated smoke only if credentials remain available; absence of credentials must not block offline acceptance.
- [ ] Run full ruff, pytest with warnings as errors, and compileall.
- [ ] Verify no SDK type is imported outside `tools/adapters/mcp_sdk.py` and tests.
- [ ] Verify no secret appears in checkpoint, ToolError, report or captured logs.
- [ ] Verify model specs stay identical when provider count changes.
- [ ] Record exact SDK version, local MCP smoke result, fallback call order, circuit semantics and stateful-session limitation.
- [ ] Request Critical/Important review and resolve all findings.

## Final acceptance

- official MCP SDK v2 stdio discovery and call pass locally;
- MCP tools are explicit allowlist/schema-pin registrations, not remote auto-trust;
- ToolExecutor owns retry, fallback, circuit and cache without nested adapter policies;
- action identity is constant across retries/providers;
- model-visible ToolDefinition is provider-independent;
- current Brave/Jina path remains operational;
- full suite remains green;
- documentation explicitly states that live default has no paid secondary provider and that stateful MCP session reuse is not implemented.
