# Agent Infra Deepening Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> If those skills are unavailable, follow this document directly. Missing a skill is not permission to redesign the tasks.

**Goal:** Close every Important finding from the post-deepening review without expanding OpinionSearch beyond Harness/Runtime and Tool/MCP/Context/run-scoped Memory.

**Architecture:** Preserve the explicit Agent Loop, reducer-only Domain State writes, provider-neutral Tool Runtime, pure Working Memory projection, and origin-tagged Context Compiler. Repair only the proven boundary defects: post-observation cancellation, MCP metadata/schema/endpoint/client safety, half-open circuit completion, semantic coverage bounding, origin-preserving deduplication, and hermetic MCP lifecycle verification.

**Tech Stack:** Python 3.12+, asyncio, Pydantic 2, official MCP Python SDK v2 (`mcp>=2,<3`), httpx2 through MCP SDK, pytest.

---

## 0. Authority, scope and execution rules

Working directory:

```text
/Users/mac/Documents/codex_project/public_opinion_agent/agent_code
```

Read completely before editing:

1. `CLAUDE.md`
2. `docs/public-opinion-search-agent-design.md`
3. `docs/agent-infra-interview-deepening.md`
4. `docs/superpowers/plans/2026-08-21-runtime-recovery-hardening.md`
5. `docs/superpowers/plans/2026-08-21-tool-mcp-reliability.md`
6. `docs/superpowers/plans/2026-08-21-context-memory-hardening.md`
7. this remediation plan.

This document supersedes the affected acceptance claims in sections 14–16 of `docs/opinion-search-agent-implementation-memory.md` until every task below passes final verification.

### Frozen boundaries

- Do not read, copy, import or modify `archive/`.
- Do not change `RunStatus`, `StepPhase`, the four Domain actions, checkpoint schema version or execution profile. This plan does not require any of them.
- Do not introduce LangGraph, a database, queue, vector store, cross-run memory, Web UI, trace platform or evaluation platform.
- Do not add a second MCP abstraction or a second cancellation mechanism.
- Do not weaken trust rules, schema pins, URL security, cache identity or reducer invariants to make tests pass.
- Do not run `git add`, commit, push, create a branch or open a PR.
- Perform tasks in the numbered order. Each task must pass its targeted tests before the next task begins.
- Production code must not contain test-only branches.

### Baseline evidence

The review observed:

```text
permissive environment: 520 passed, 2 skipped
managed sandbox:        519 passed, 1 failed, 2 skipped
ruff:                   passed
compileall:             passed
offline CLI:            completed and wrote run.json/report.md/action_results/
```

The sandbox failure is the direct `ps` dependency in the MCP subprocess lifecycle test. Passing tests do not waive the missing negative scenarios below.

### Required per-task workflow

For every task:

- [ ] Add the exact negative/regression test first.
- [ ] Run it and record the expected failure against current production code.
- [ ] Implement the smallest production change that satisfies the frozen contract.
- [ ] Run the targeted test file.
- [ ] Run the adjacent component test group.
- [ ] Inspect the diff and remove unrelated changes.
- [ ] Continue only when the current task is green.

---

## Task 1: Preserve an OBSERVATION_READY step when cancellation arrives

### Problem

`AgentLoop.run()` checks cancellation before handling the classified resume action. If cancellation becomes visible immediately after the `OBSERVATION_READY` checkpoint, `terminate_run()` clears the active step. The successfully observed action is never reduced or committed.

Observed reproduction:

```text
hook cancels at CheckpointBoundary.OBSERVATION_READY
result.status = cancelled
domain revision = 0
committed steps = 0
active observation discarded
```

This violates the frozen recovery rule: an already checkpointed Observation must complete reduction before cancellation can terminate the run.

### Files

- Modify: `opinion_search_agent/src/opinion_search/runtime/loop.py`
- Modify: `opinion_search_agent/tests/unit/runtime/test_cancellation.py`

### Required tests

Add a hook that calls `signal.cancel()` when it observes `CheckpointBoundary.OBSERVATION_READY`. Assert:

```text
final status = cancelled
the observed step is committed exactly once
domain revision includes that step's Delta exactly once
the committed action ID is present exactly once
the tool is not called again
active_step is None only after commit
terminal checkpoint reload has the same committed Domain State
```

Add the same scenario beginning from a checkpoint whose active phase is already `REDUCING`; cancellation must not discard it. Tests must exercise `AgentLoop.run()`, not `commit_step()` directly.

### Required implementation semantics

Use the already computed `resume_action`:

```text
if resume_action == REDUCE_OBSERVATION:
    finish processor/reducer/commit even when cancellation is set
else if run is running and cancellation is set:
    terminate cancelled
```

Both `OBSERVATION_READY` and `REDUCING` classify as `REDUCE_OBSERVATION`, so no new phase or flag is required. After `STEP_COMMITTED`, the next iteration may honor cancellation before opening another step. Do not change `terminate_run()` to retain arbitrary active steps; the scheduling fix belongs in the Loop.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/unit/runtime/test_cancellation.py tests/integration/test_offline_loop.py -q
/Users/mac/miniconda3/bin/python -m pytest tests/unit/runtime tests/integration/test_checkpoint_resume.py tests/e2e/test_recovery_matrix.py -q
```

### Acceptance

- cancellation before/during model and tool await still works;
- cancellation after Observation checkpoint commits exactly once;
- cancellation does not open the next step;
- checkpoint schema remains version 4.

---

## Task 2: Complete every half-open circuit probe

### Problem

`ProviderCircuitBreaker.record_failure()` returns immediately for non-poisoning failures. When the record is half-open and `probe_in_flight=True`, authentication/permission/not-found failures never clear the probe. Every future `allow_request()` returns false.

### Files

- Modify: `opinion_search_agent/src/opinion_search/tools/circuit.py`
- Modify: `opinion_search_agent/tests/unit/tools/test_circuit.py`
- Modify if executor behavior needs assertion: `opinion_search_agent/tests/unit/tools/test_executor.py`

### Required tests

Exercise the real sequence:

```text
1. open a provider circuit with poisoning failures;
2. advance the injected clock past cooldown;
3. assert one half-open probe is allowed;
4. record AUTHENTICATION for that probe;
5. assert probe_in_flight no longer blocks future requests;
6. assert AUTHENTICATION did not increment/reopen poisoning health.
```

Repeat with `PERMISSION` or parameterize both. Add an Executor-level test proving that a later ToolCall reaches the provider/fallback chain instead of receiving “all providers unavailable” forever.

### Required transition table

```text
probe success
  -> CLOSED; consecutive_failures=0; probe_in_flight=False

probe poisoning failure
  -> OPEN; opened_at=now; probe_in_flight=False

probe non-poisoning failure
  -> CLOSED; consecutive_failures=0; probe_in_flight=False
```

Closing after a non-poisoning probe is correct because auth/permission/not-found are request/configuration outcomes, not provider-health evidence. ToolExecutor still returns/falls back according to the existing failure table. Do not add async locks or checkpoint circuit state.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/unit/tools/test_circuit.py tests/unit/tools/test_executor.py -q
```

### Acceptance

- half-open allows at most one concurrent probe;
- every probe outcome releases the probe;
- non-poisoning errors never increase poisoning counters;
- circuit remains process-local.

---

## Task 3: Strip MCP content-block metadata and enforce output-schema presence

### Problems

1. `_dump_content()` serializes the complete SDK Pydantic content block. Remote `_meta` becomes `meta` and enters `McpCallResult`, ToolResult, cache/checkpoint and model Context.
2. `McpToolAdapter.invoke()` validates an output schema only when `structured_content` is present. A server can declare and pin an output schema, omit structured content, return text blocks and still receive a successful ToolResult.

### Files

- Modify: `opinion_search_agent/src/opinion_search/tools/adapters/mcp_sdk.py`
- Modify: `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`
- Modify: `opinion_search_agent/tests/contract/test_mcp_sdk_transport.py`
- Modify: `opinion_search_agent/tests/contract/test_mcp_adapter.py`
- Modify if the full path needs proof: `opinion_search_agent/tests/e2e/test_real_mcp_tool.py`

### Metadata regression test

Construct a real SDK content block equivalent to:

```text
TextContent(type="text", text="public", _meta={"secret": "do-not-forward"})
```

Pass it through the production SDK mapping. Assert recursively that neither `_meta`, `meta`, nor `do-not-forward` appears in:

- `McpCallResult.model_dump(mode="json")`;
- `ToolAdapterResponse.payload`;
- the final `ToolResult.payload` after Registry/Executor;
- a compiled recent ToolResult Context section if the fixture carries it that far.

Do not assert only that model-visible ToolDefinition is clean; this finding concerns call content.

### Required content projection

Replace raw complete-object serialization with an intentional JSON projection:

```text
dump the supported SDK content block to JSON-compatible data
remove top-level SDK metadata fields by field name and alias: meta and _meta
validate the remaining value is JsonValue
never forward SDK internal/private attributes
```

Prefer explicit fields for supported text/image/audio/resource/link variants. Unknown non-JSON block types must become a safe `ToolAdapterError`, not raw SDK/Pydantic exceptions containing remote data.

Do not delete ordinary `structured_content` keys named `meta` when they are part of a pinned application output schema. This rule applies to MCP protocol content-block metadata, not arbitrary domain payload fields.

### Output-schema regression test

Create a descriptor with this output schema:

```json
{
  "type": "object",
  "properties": {"count": {"type": "integer"}},
  "required": ["count"],
  "additionalProperties": false
}
```

Return `structured_content=None`, one text content block and `is_error=false`. Expected result: safe `ToolAdapterError(UNKNOWN_PROVIDER_ERROR, ...)`; content text and schema body must not appear in the safe message.

Required table:

| Descriptor output schema | structured_content | Result |
|---|---|---|
| present | absent | fail closed |
| present | present and valid | success |
| present | present and invalid | fail closed |
| absent | absent | unstructured content success |
| absent | present | structured content success |

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/contract/test_mcp_adapter.py tests/contract/test_mcp_sdk_transport.py tests/e2e/test_real_mcp_tool.py -q
```

### Acceptance

- remote `_meta` cannot reach ToolResult or Context;
- a declared output schema cannot be bypassed with unstructured content;
- errors remain safe and credential/body free;
- pinned valid structured content still succeeds.

---

## Task 4: Harden MCP HTTP endpoints and close the caller-owned HTTP client

### Problems

`McpHttpConfig` accepts any string with scheme `https`, including missing hosts, userinfo, loopback and link-local/private IP literals. Secret headers can therefore be sent to unintended targets. `SdkMcpTransport._client()` also creates an `httpx2.AsyncClient` and passes it to `streamable_http_client`; the SDK treats a supplied client as caller-owned and does not close it.

### Files

- Modify: `opinion_search_agent/src/opinion_search/tools/adapters/mcp_sdk.py`
- Reuse, do not duplicate: `opinion_search_agent/src/opinion_search/tools/url.py`
- Modify: `opinion_search_agent/tests/contract/test_mcp_sdk_transport.py`

### Endpoint tests

Add parameterized rejection tests for:

```text
https:///missing-host
https://user:password@example.com/mcp
https://127.0.0.1/mcp
https://[::1]/mcp
https://169.254.169.254/latest/meta-data
https://10.0.0.1/mcp
https://192.168.1.1/mcp
```

Add acceptance tests for:

```text
https://mcp.example.com/mcp
http://127.0.0.1:8080/mcp with allow_insecure_loopback=true
http://localhost:8080/mcp with allow_insecure_loopback=true
```

Plain HTTP public/private addresses remain rejected even when the development flag is true. HTTPS loopback/private endpoints are not silently treated as production-safe; only the explicit development loopback branch may allow loopback.

### Required validation approach

For production, reuse `normalize_secure_provider_endpoint()` from `tools/url.py`. Do not reimplement IP parsing or legacy IPv4 detection in `mcp_sdk.py`.

For development loopback HTTP, require all of:

- `allow_insecure_loopback=True`;
- scheme exactly `http`;
- hostname exactly localhost, 127.0.0.1 or ::1;
- no username/password;
- valid authority and port;
- no whitespace/control characters.

Store or use a normalized endpoint so execution and validation cannot disagree.

### HTTP client lifecycle test

Add a deterministic contract test proving the client created for a streamable HTTP operation is closed after both normal operation and SDK/transport exception.

The implementation must own the supplied client explicitly:

```text
async with httpx2.AsyncClient(headers=...) as http_client:
    transport = streamable_http_client(..., http_client=http_client)
    async with Client(transport) as client:
        yield client
```

Keep the stdio branch separate so it does not reference an HTTP client. Do not depend on garbage collection or ResourceWarning for closure.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/contract/test_mcp_sdk_transport.py -q
```

### Acceptance

- production MCP HTTP accepts only normalized public HTTPS;
- development allowance is loopback-only and explicit;
- userinfo/missing host/private/link-local targets are rejected before a request;
- secret header values never appear in validation errors;
- every created HTTP client is closed.

---

## Task 5: Make trusted Opinion coverage semantically correct and truly bounded

### Problems

For the current Gap, `_bounded_coverage()` uses the complete catalog relevance ranking as `sample_evidence_ids`. That ranking intentionally includes unlinked and acquisition-only evidence, so the trusted coverage cell falsely presents them as semantic coverage.

Observed reproduction:

```json
{
  "gap_id": "gap-current",
  "evidence_count": 1,
  "sample_evidence_ids": ["ev-semantic", "ev-unlinked"]
}
```

The same trusted required section emits every distinct `source_id`, so it remains linear in trajectory size despite bounded Evidence samples.

### Files

- Modify: `opinion_search_agent/src/opinion_search/context/compiler.py`
- Modify if a reusable bounded view belongs there: `opinion_search_agent/src/opinion_search/context/catalog.py`
- Modify: `opinion_search_agent/tests/unit/context/test_catalog.py`
- Modify: `opinion_search_agent/tests/unit/context/test_compiler.py`
- Modify: `opinion_search_agent/tests/integration/test_context_long_trajectory.py`

### Semantic correctness test

Build a current open Gap with:

```text
cell.evidence_ids = (ev-semantic,)
catalog relevance = (ev-semantic, ev-unlinked, ev-acquisition-only)
```

Compile through `OpinionContextCompiler`, parse `memory.opinion-coverage`, and assert:

```text
sample_evidence_ids is a subset of cell.evidence_ids
ev-unlinked absent
ev-acquisition-only absent
evidence_count == len(cell.evidence_ids)
```

This must exercise the full compiler, not `_bounded_coverage()` alone.

### Required bounded payload

Each cell must contain only bounded structural data:

```text
gap_id
status
evidence_count
source_count
sample_evidence_ids   length <= coverage_sample_limit_per_gap
sample_source_ids     length <= coverage_sample_limit_per_gap
```

Remove the unbounded `source_ids` field from this required rendered section. `WorkingMemory.OpinionCoverageCell.source_ids` may remain complete because Working Memory is a pure projection; rendered Context must be bounded.

Sampling rules:

- `sample_evidence_ids` only from `cell.evidence_ids`;
- `sample_source_ids` only from Sources behind semantic Evidence in that cell;
- preserve deterministic State/Provenance order;
- never use `acquired_for_gap_id` as semantic membership;
- counts remain exact when samples are truncated.

### Growth test

Create two states under the same fixed realistic input budget:

```text
state A: 300 semantic Evidence, 300 distinct Sources
state B: 3,000 semantic Evidence, 3,000 distinct Sources
```

Use short IDs so the fixture measures structural growth rather than artificial prose. Assert:

- required coverage does not overflow because of Source/Evidence lists;
- coverage section size remains within a constant bound from 300 to 3,000;
- Evidence/Source counts are exact;
- sample limits are honored;
- repeated compilation and JSON resume produce identical bytes/hash.

Keep this deterministic and offline. Do not weaken it to the existing 80-Source fixture.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/unit/context/test_catalog.py tests/unit/context/test_compiler.py tests/integration/test_context_long_trajectory.py -q
```

### Acceptance

- trusted coverage contains only true semantic Gap links;
- acquisition-only/unlinked Evidence is never represented as coverage;
- required coverage size is constant-bounded;
- 300→3,000 Sources cannot linearly grow required coverage;
- catalog limits and deterministic hash remain intact.

---

## Task 6: Preserve content origin through deduplication and freeze L0/L1 origins

### Problems

`select_context_sections()` deduplicates using trust, layer and normalized content but omits origin. Identical untrusted model and tool sections collapse into one section carrying only one producer origin. Provenance refs are merged even though the surviving origin describes only one producer.

`ContextSection` also permits `USER_TASK` origin in L0, although L0 is immutable app configuration and user task belongs in L1.

### Files

- Modify: `opinion_search_agent/src/opinion_search/context/selector.py`
- Modify: `opinion_search_agent/src/opinion_search/context/models.py`
- Modify: `opinion_search_agent/tests/unit/context/test_selector.py`
- Modify: `opinion_search_agent/tests/unit/context/test_models.py`
- Modify: `opinion_search_agent/tests/security/test_context_injection_matrix.py`

### Origin-preserving dedup test

Construct two sections with identical normalized text and the same untrusted trust/layer, but:

```text
section A origin = model
section B origin = tool
```

After selection, both must remain. Their section IDs, origins and provenance refs must remain attached to the correct producer.

Also prove:

- identical same-origin sections may still deduplicate under existing stable rules;
- trusted and untrusted sections never deduplicate;
- different layers never deduplicate;
- provider and tool origins do not merge;
- JSON roundtrip does not change selection.

### Required dedup key

Include all of:

```text
trust
origin
layer
normalized content
```

Do not invent a synthetic `mixed` origin; merging would still lose attribution.

### L0/L1 validation matrix

| Layer | Allowed origin |
|---|---|
| L0 immutable instructions | app_config only |
| L1 stable task | app_config or user_task |
| L2/L3 | any origin subject to trust rules |

Keep existing constraints: L0/L1 are required, trusted and `compaction=NEVER`; model/tool/provider can never be trusted anywhere. Constructing `L0 + USER_TASK` must fail. Existing compiler-created sections must remain valid without changing their content.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/unit/context/test_models.py tests/unit/context/test_selector.py tests/security/test_context_injection_matrix.py -q
```

### Acceptance

- dedup never changes producer origin;
- provenance refs never merge across origins;
- L0 is app-config-only;
- task request remains L1/user_task/trusted;
- injection matrix remains green.

---

## Task 7: Replace the MCP subprocess `ps` assertion with a hermetic lifecycle proof

### Problem

`tests/contract/test_mcp_sdk_transport.py::_count_fixture_processes()` executes `ps`. In the managed workspace it raises `PermissionError`, producing one failed test. Catching the error and returning `-1` would make the test pass without proving subprocess exit, so that is not an acceptable primary fix.

### Files

- Modify: `opinion_search_agent/tests/fixtures/mcp/read_only_server.py`
- Modify: `opinion_search_agent/tests/contract/test_mcp_sdk_transport.py`

### Required lifecycle signal

Allow the fixture to receive one test-only lifecycle path through an explicitly allowlisted environment variable:

```text
MCP_FIXTURE_LIFECYCLE_PATH=/tmp/.../lifecycle.json
```

The fixture must:

```text
on start: write a small started marker containing only a generated test instance ID
run the MCP stdio server
in finally: atomically replace the marker with a closed marker
```

Do not write environment contents, tokens, commands or credentials. The path exists only in `tmp_path`. Preserve the existing test proving the parent process environment is not inherited.

The client test must:

- use a unique `tmp_path` lifecycle file;
- call the real SDK stdio transport twice;
- wait with a short bounded deadline for `closed` after each client context;
- assert the expected unique instance reached `closed`;
- fail deterministically if closure never arrives;
- not call `ps`, `pgrep`, shell utilities or the network.

If the MCP library terminates the child before Python `finally` can run, expose lifecycle ownership through a narrow injectable stdio transport factory and assert its async context exits. Do not fall back to an unconditional skip. Keep at least one real stdio discovery/call e2e test.

Update the fixture docstring because it will now perform an explicitly test-scoped lifecycle-file mutation.

### Commands

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m pytest tests/contract/test_mcp_sdk_transport.py -q
/Users/mac/miniconda3/bin/python -m pytest tests/e2e/test_real_mcp_tool.py -q
```

Run inside the managed environment; no escalation should be required.

### Acceptance

- no test invokes `ps` or inspects the global process table;
- real stdio discovery and call still run;
- lifecycle exit is positively proven;
- the full suite is green in the managed workspace.

---

## Task 8: Final integration verification and truthful documentation

### Files

- Modify only after all verification passes: `docs/opinion-search-agent-implementation-memory.md`
- Modify if behavior wording changed: `opinion_search_agent/README.md`
- Do not modify canonical scope unless an implemented contract truly changed: `docs/public-opinion-search-agent-design.md`

### Targeted verification

```bash
cd opinion_search_agent

/Users/mac/miniconda3/bin/python -m pytest \
  tests/unit/runtime/test_cancellation.py \
  tests/integration/test_offline_loop.py \
  tests/e2e/test_recovery_matrix.py \
  tests/unit/tools/test_circuit.py \
  tests/unit/tools/test_executor.py \
  tests/contract/test_mcp_adapter.py \
  tests/contract/test_mcp_sdk_transport.py \
  tests/e2e/test_real_mcp_tool.py \
  tests/unit/context/test_models.py \
  tests/unit/context/test_selector.py \
  tests/unit/context/test_catalog.py \
  tests/unit/context/test_compiler.py \
  tests/integration/test_context_long_trajectory.py \
  tests/security/test_context_injection_matrix.py -q -W error
```

### Full verification

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m ruff check src tests
/Users/mac/miniconda3/bin/python -m pytest -q -W error
/Users/mac/miniconda3/bin/python -m compileall -q src tests
```

Run the full suite in the managed environment, not only outside its sandbox.

### Offline/resume smoke

Use a fresh temporary directory:

```bash
cd opinion_search_agent
PYTHONPATH=src /Users/mac/miniconda3/bin/python -m opinion_search offline \
  --question "What happened in the example event?" \
  --topic "Example event" \
  --focus "Compare event facts and causal accounts" \
  --run-id remediation-offline \
  --checkpoint /tmp/opinion-remediation/run.json

PYTHONPATH=src /Users/mac/miniconda3/bin/python -m opinion_search resume \
  --mode offline \
  --checkpoint /tmp/opinion-remediation/run.json
```

Assert:

- `run.json`, `report.md` and `action_results/` exist;
- original and resume reports are byte-identical;
- no provider credential or MCP metadata is present;
- checkpoint schema remains 4.

### Documentation correction

After all tests pass, append a remediation subsection to implementation memory. Do not rewrite history. Record:

- cancellation defers terminal cancellation through protected reduction;
- half-open non-poisoning probes are released;
- MCP content-block metadata is stripped;
- declared output schemas require structured content;
- MCP HTTP endpoint and client lifecycle contracts;
- coverage sample/count fields and constant bounds;
- dedup includes origin and L0 is app-config-only;
- the hermetic MCP lifecycle mechanism;
- exact commands and actual pass counts;
- unchanged limitations: read-only retry window, in-memory circuit, stateless MCP sessions and heuristic token estimator.

Do not retain a final claim of “no residual Important findings” unless this remediation has passed a second review.

### Final acceptance checklist

- [ ] Cancellation after `OBSERVATION_READY` commits exactly once before stopping.
- [ ] Cancellation after `REDUCING` commits exactly once before stopping.
- [ ] Half-open circuit cannot remain permanently probe-locked.
- [ ] MCP `_meta` is absent from ToolResult, cache/checkpoint and Context.
- [ ] Declared output schema cannot be bypassed with text-only output.
- [ ] MCP production HTTP accepts only normalized public HTTPS.
- [ ] MCP development HTTP allows only explicit loopback.
- [ ] Every caller-created MCP HTTP client is closed.
- [ ] Trusted coverage samples are subsets of semantic Gap evidence.
- [ ] Trusted coverage Source/Evidence lists are constant-bounded with exact counts.
- [ ] 300→3,000 source growth does not linearly grow required coverage.
- [ ] Context dedup never merges different origins.
- [ ] L0 accepts app_config only.
- [ ] MCP lifecycle tests require no process-table permission.
- [ ] Full pytest/ruff/compileall and offline/resume smoke pass.
- [ ] Checkpoint schema and action space remain unchanged.
- [ ] Implementation memory contains only verified facts.

---

## Direct handoff prompt

Give the implementing Agent this prompt:

```text
Work in /Users/mac/Documents/codex_project/public_opinion_agent/agent_code.

Completely read CLAUDE.md, docs/public-opinion-search-agent-design.md,
docs/agent-infra-interview-deepening.md, and
docs/superpowers/plans/2026-08-21-deepening-review-remediation.md.

Implement every Task in the remediation plan in order. Treat each Task as a
separate test-first checkpoint: add the negative test, prove it fails against
the current code, implement the minimum fix, run targeted and adjacent tests,
then continue. Do not skip a failing Task and do not redesign the architecture.

Do not read or modify archive/. Do not change RunStatus, StepPhase, the four
Domain actions, checkpoint schema version or execution profile. Do not add
plan-external dependencies or infrastructure. Do not run git add, commit,
push, create a branch or PR.

Only update implementation memory after every remediation test, the managed
full suite, ruff, compileall, and offline/resume smoke pass. If any frozen
contract must change, or a Task cannot pass after three focused attempts,
stop and report the exact file/symbol/conflict instead of changing direction.

At completion report: Task-by-Task status, files changed, first failing-test
evidence, final commands/results, checkpoint/profile status, remaining limits,
and a git diff summary. Then stop for review.
```
