# Runtime Recovery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> If those skills are unavailable in the execution environment, follow the numbered Task, test-first sequence, stop conditions, and review handoff in this document directly; missing a skill is not permission to redesign the Task.

**Goal:** Deepen the existing single-Agent Harness so pre-action failures are repairable, successful tool results survive process restart, cancellation interrupts in-flight awaits, and every terminal run produces a recoverable Run Bundle.

**Architecture:** Keep the current explicit `AgentLoop`, `RunState`, Step lifecycle, Domain Reducer, and checkpoint schema. Add only mechanisms consumed by the current OpinionSearch workload: an accepted-decision repair transition, a local persistent `ToolResultCache`, an async cancellation signal, terminal report persistence, and recovery tests for every checkpoint boundary.

**Tech Stack:** Python 3.12+, asyncio, Pydantic 2, atomic local JSON files, pytest.

---

## Scope and authority

Read first:

1. `docs/agent-infra-interview-deepening.md`
2. `docs/public-opinion-search-agent-design.md`
3. `opinion_search_agent/src/opinion_search/runtime/lifecycle.py`
4. `opinion_search_agent/src/opinion_search/runtime/protocols.py`
5. `opinion_search_agent/src/opinion_search/runtime/transaction.py`
6. `opinion_search_agent/src/opinion_search/runtime/loop.py`
7. `opinion_search_agent/src/opinion_search/tools/cache.py`
8. `opinion_search_agent/src/opinion_search/tools/executor.py`

Do not change:

- RunStatus or StepPhase values;
- search/read/reflect/finish action space;
- OpinionSearch domain contracts;
- checkpoint payload shape or schema version unless a review proves serialization changed;
- ToolAdapter protocol;
- provider adapters;
- `archive/`.

## Frozen recovery semantics

### Decision and ActionResolver failure

```text
DECIDING model/validation failure
  -> same step_id
  -> attempt + 1
  -> DECIDING

DECISION_ACCEPTED ActionResolver failure
  -> no external action has started
  -> same step_id
  -> attempt + 1
  -> clear accepted Decision
  -> DECIDING

ACTION_RUNNING and later processor/reducer invariant
  -> never rewind Decision
  -> fail closed
```

### Tool result persistence

```text
ToolAdapter returns success
  -> ToolExecutor creates ToolResult
  -> persistent result cache atomically stores call + result
  -> ToolExecutor returns result
  -> OpinionActionExecutor creates ToolObservation
  -> AgentLoop checkpoints OBSERVATION_READY
```

If the process dies after the cache write but before `OBSERVATION_READY`, resume from `ACTION_RUNNING` executes the same ToolCall with the same action ID and receives the cached ToolResult without invoking the provider again.

This is not a universal exactly-once guarantee. If the process dies after a remote provider performs work but before the client receives and persists the response, the Runtime cannot know the result. OpinionSearch tools are read-only and may be retried. The implementation must document this boundary rather than claim exactly once.

### Cancellation

- cancellation before a model/tool await terminates the run without starting that await;
- cancellation during model/tool await cancels the local task and checkpoints `cancelled`;
- cancellation never commits a partial Delta;
- cancellation after `OBSERVATION_READY` does not discard the already checkpointed Observation; resume classification continues reduction before any new run is possible because terminal cancellation clears active work only when cancellation wins before that checkpoint;
- this project only invokes read-only tools, so cancelling a local await does not claim remote rollback.

## File map

Create:

- `opinion_search_agent/src/opinion_search/runtime/cancellation.py` — async cancellation contract and event implementation.
- `opinion_search_agent/src/opinion_search/tools/persistent_cache.py` — local atomic cross-process ToolResult cache.
- `opinion_search_agent/src/opinion_search/app/run_bundle.py` — atomic terminal Markdown report writer.
- `opinion_search_agent/tests/unit/runtime/test_cancellation.py`
- `opinion_search_agent/tests/unit/tools/test_persistent_cache.py`
- `opinion_search_agent/tests/unit/app/test_run_bundle.py`
- `opinion_search_agent/tests/e2e/test_action_running_recovery.py`

Modify:

- `opinion_search_agent/src/opinion_search/runtime/transaction.py`
- `opinion_search_agent/src/opinion_search/runtime/loop.py`
- `opinion_search_agent/src/opinion_search/app/service.py`
- `opinion_search_agent/src/opinion_search/__main__.py`
- existing Runtime recovery and CLI tests.

## Task 1: Repair an accepted Decision when Action resolution fails

**Problem:** `AgentLoop` currently converts any `ActionResolver.resolve()` `ValueError` into terminal `FAILED`, even though no external action has started. This contradicts the Runtime error table, where invalid action is repairable feedback.

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/runtime/transaction.py`
- Modify: `opinion_search_agent/src/opinion_search/runtime/loop.py`
- Test: `opinion_search_agent/tests/unit/runtime/test_transaction.py`
- Test: `opinion_search_agent/tests/e2e/test_recovery_matrix.py`

### Required contract

Add one transaction function with this semantic signature:

```text
repair_accepted_decision(
    state: RunState,
    failure: RuntimeFailure,
) -> RunState
```

Preconditions:

- run status is `running`;
- active step exists;
- active phase is `decision_accepted`;
- accepted Decision exists;
- Action and Observation do not exist.

Postconditions:

- same run ID and step ID;
- attempt increases by exactly one;
- phase becomes `deciding`;
- decision/action/observation are cleared by constructing a new StepRecord, not by unsafe partial model copy;
- prior failures plus the new failure are preserved in order;
- Domain State, committed steps and committed action IDs are unchanged.

### Implementation sequence

- [ ] Add a unit test that constructs a `DECISION_ACCEPTED` state and asserts all postconditions above.
- [ ] Add negative tests for calling the function from `DECIDING`, `ACTION_RUNNING`, and a terminal RunState.
- [ ] Run only the new transaction tests and confirm failure because the function does not exist.
- [ ] Implement the transaction function using the same typed reconstruction pattern as `retry_decision`.
- [ ] Refactor the ActionResolver error branch in `AgentLoop` to create `RuntimeFailureKind.INVALID_ACTION` and use the same maximum decision-attempt policy as model/validation repair.
- [ ] If repair attempts are exhausted, terminate `partial` when at least one step is committed; otherwise terminate `failed` with the RuntimeFailure.
- [ ] Do not retry processor or Reducer errors; add an assertion test proving they remain terminal.
- [ ] Run `tests/unit/runtime/test_transaction.py` and `tests/e2e/test_recovery_matrix.py`.

### Required e2e scenario

The scripted model returns:

1. a structurally valid Decision that a test ActionResolver rejects;
2. a corrected Decision on attempt two.

Acceptance:

- one committed step;
- committed step attempt is 2;
- first failure kind is `invalid_action`;
- provider/tool executor was not called for attempt one;
- run is not `failed`.

## Task 2: Add a persistent action-result cache

**Problem:** `InMemoryActionResultCache` prevents duplicate successful calls only within one process. `ACTION_RUNNING` resume in a new process loses this cache and calls the provider again.

**Files:**

- Create: `opinion_search_agent/src/opinion_search/tools/persistent_cache.py`
- Test: `opinion_search_agent/tests/unit/tools/test_persistent_cache.py`
- Modify: `opinion_search_agent/src/opinion_search/app/service.py`
- Modify: relevant app composition tests.

### Required public object

```text
JsonActionResultCache(directory: Path)
  async get(call: ToolCall) -> ToolResult | None
  async put(call: ToolCall, result: ToolResult) -> None
```

It must implement the existing `ToolResultCache` protocol; do not change `ToolExecutor.execute()` or `ToolAdapter` signatures.

### File identity and payload

- one cache entry per action ID;
- filename is `sha256(action_id UTF-8).hexdigest() + ".json"` so arbitrary action IDs never become paths;
- payload fields are exactly:

```text
schema_version: 1
action_id: string
call: ToolCall JSON
result: ToolResult JSON
```

- JSON serialization uses UTF-8, sorted keys, compact separators;
- write into the destination directory using a temporary file, flush, `fsync`, then `os.replace`;
- directory creation happens before writing;
- a read validates root object, schema version, action ID, ToolCall and ToolResult using Pydantic;
- malformed/truncated cache entries raise a typed cache read error and never look like a cache miss;
- a stored call different from the requested call raises `ToolCacheConflictError`;
- a stored result whose action/tool identity differs from the stored call raises `ToolCacheConflictError`;
- putting the exact same entry is idempotent;
- putting a different entry for an existing action ID raises conflict and does not overwrite.

### Explicit concurrency boundary

Use an in-process `asyncio.Lock` around get/put. Atomic replace protects readers from partial files after a crash. This Task does not promise distributed locking or prevention of two independent processes invoking the same not-yet-cached action concurrently; document that limitation in the class docstring and implementation memory after verification.

### Composition rule

Both `build_offline_service()` and `build_live_service()` construct:

```text
JsonActionResultCache(checkpoint_path.parent / "action_results")
```

and pass it to ToolExecutor. Tests that explicitly need ephemeral behavior may continue using `InMemoryActionResultCache`.

### Implementation sequence

- [ ] Add unit tests for miss, put/get round trip, process-reconstruction round trip, exact idempotent put, identity conflict, malformed JSON, unsupported schema, truncated temporary file being ignored, and arbitrary action ID path safety.
- [ ] Confirm the tests fail before implementation.
- [ ] Implement typed cache errors without importing Runtime or Domain modules.
- [ ] Integrate the cache in offline/live service builders.
- [ ] Assert `.env`, checkpoint and cache payload never contain provider credentials.
- [ ] Run unit Tool tests and app composition tests.

## Task 3: Prove ACTION_RUNNING recovery reuses the persistent result

**Files:**

- Create: `opinion_search_agent/tests/e2e/test_action_running_recovery.py`
- Reuse: `opinion_search_agent/tests/e2e/test_recovery_matrix.py` fixtures where suitable.

### Required test construction

Do not add a production-only hook between ToolExecutor and Observation. Construct the crash state explicitly:

1. Build a valid running `RunState` whose active step is `ACTION_RUNNING` and contains the deterministic ToolCall identity.
2. Execute that ToolCall once through a ToolExecutor using `JsonActionResultCache`; assert the counting FakeAdapter was called once.
3. Do not record the returned Observation in RunState, simulating death after cache write and before `OBSERVATION_READY` checkpoint.
4. Persist the `ACTION_RUNNING` RunState with `JsonCheckpointStore`.
5. Construct a fresh Registry, fresh counting FakeAdapter, fresh ToolExecutor, fresh cache object pointed at the same directory, and fresh AgentLoop.
6. Resume from the checkpoint.

### Acceptance

- the fresh adapter invocation count remains zero;
- the resumed step records an Observation containing the cached ToolResult;
- the ToolResult action ID equals the ACTION_RUNNING action ID;
- reduction commits once;
- Domain State revision increments once;
- cache entry remains unchanged;
- resume outcome matches an uninterrupted control run.

Also add the negative case: same action ID with different arguments fails as cache identity conflict and does not invoke the adapter.

## Task 4: Add asynchronous cancellation of in-flight work

**Files:**

- Create: `opinion_search_agent/src/opinion_search/runtime/cancellation.py`
- Modify: `opinion_search_agent/src/opinion_search/runtime/loop.py`
- Create: `opinion_search_agent/tests/unit/runtime/test_cancellation.py`
- Modify: Runtime integration tests.

### Required contracts

Define:

```text
CancellationSignal Protocol
  is_cancelled() -> bool
  wait_cancelled() -> Awaitable[None]

NeverCancelledSignal
EventCancellationSignal
  cancel() -> None
```

`EventCancellationSignal` owns one `asyncio.Event`. `cancel()` is idempotent.

Replace the synchronous `CancellationCheck` dependency in AgentLoop with `CancellationSignal`. Do not keep two independent cancellation mechanisms.

### Await race algorithm

AgentLoop needs one private helper used around both model and ActionExecutor awaits:

```text
if already cancelled:
    return cancellation outcome
create operation task
create cancellation wait task
wait FIRST_COMPLETED
if cancellation wins:
    cancel operation task
    await its termination while suppressing CancelledError only
    terminate run as cancelled
else:
    cancel cancellation-wait task
    await its termination
    return operation result or propagate its typed exception
```

Do not catch arbitrary `BaseException`. `KeyboardInterrupt` and `SystemExit` are not ToolError.

### Required tests

- cancellation before model call: model call count zero;
- cancellation while model is blocked: model task receives cancellation; no Decision accepted;
- cancellation while ToolAdapter is blocked: adapter task receives cancellation; no Observation/Delta committed;
- normal completion when cancellation never fires;
- cancellation after a committed step preserves committed Domain State;
- terminal checkpoint reload returns `cancelled` with the same stop reason;
- no pending asyncio task warnings under `-W error`.

This Task does not claim remote cancellation or rollback. The local coroutine is cancelled; remote service semantics remain provider-specific.

## Task 5: Persist the terminal Markdown Run Bundle

**Problem:** `build_search_outcome()` already produces Markdown, but CLI only prints it; users see `run.json` and artifacts without a durable report file.

**Files:**

- Create: `opinion_search_agent/src/opinion_search/app/run_bundle.py`
- Create: `opinion_search_agent/tests/unit/app/test_run_bundle.py`
- Modify: `opinion_search_agent/src/opinion_search/__main__.py`
- Modify: CLI tests and `opinion_search_agent/README.md`.

### Required contract

```text
RunBundleWriter(checkpoint_path: Path)
  async write_report(outcome: SearchOutcome) -> Path
```

Destination is always `checkpoint_path.parent / "report.md"`. Existing reader artifacts remain at `checkpoint_path.parent / "artifacts"`; do not copy them.

Write semantics match checkpoint atomicity:

- UTF-8;
- temporary file in destination directory;
- flush and fsync;
- `os.replace`;
- no secret/config serialization;
- overwrite is allowed only because report is a deterministic projection of the latest terminal Domain State;
- return the absolute/normalized report Path.

CLI behavior:

1. run or resume service;
2. obtain terminal SearchOutcome;
3. atomically write `report.md`;
4. print Markdown to stdout as before;
5. print report path to stderr or a final concise stdout line only if existing CLI tests freeze the choice;
6. return the existing exit code semantics.

### Required tests

- offline run creates `run.json`, `report.md`, and `artifacts/` when reader artifacts exist;
- resume rewrites byte-identical report;
- report content equals `SearchOutcome.markdown` exactly plus one terminal newline if standardized;
- write failure returns a typed app error and does not corrupt an existing report;
- no `.tmp` remains after success;
- live config secrets never appear in report.

## Task 6: Complete the Runtime recovery matrix

**Files:**

- Modify: `opinion_search_agent/tests/e2e/test_recovery_matrix.py`
- Modify: `opinion_search_agent/tests/integration/test_checkpoint_resume.py`
- Modify: `opinion_search_agent/tests/integration/test_loop_with_tools.py`

### Matrix to implement

| Checkpoint state | Expected next operation | Forbidden duplicate |
|---|---|---|
| CREATED | start run | no model/tool |
| RUNNING, no active step | open step | no prior action replay |
| OPENED | mark deciding and call model | no tool |
| DECIDING | call model | no new step ID |
| DECISION_ACCEPTED | resolve action | no second model call unless resolver fails |
| ACTION_RUNNING, cached success | reuse cached result | no adapter invocation |
| ACTION_RUNNING, cache miss | execute read-only tool | no new action ID |
| OBSERVATION_READY | build Delta | no tool invocation |
| REDUCING | replay processor/Reducer | no tool invocation |
| COMMITTED + continuation pending | evaluate completion | no reducer replay |
| terminal | return result | no component invocation |

For every row assert component call counts, step ID, attempt, action ID, revision and final status. Avoid one giant parameterized fixture that hides setup; use explicit helper builders and readable assertions.

## Task 7: Final verification and documentation

**Files:**

- Modify after tests pass: `docs/public-opinion-search-agent-design.md`
- Append verified facts only: `docs/opinion-search-agent-implementation-memory.md`
- Modify: `opinion_search_agent/README.md`

- [ ] Run Runtime/Tool/app targeted tests.
- [ ] Run full ruff, pytest with warnings as errors, and compileall.
- [ ] Run offline CLI into a fresh temporary directory.
- [ ] Kill/reconstruct between cached action success and observation recording using the e2e test.
- [ ] Resume the offline run and compare report bytes.
- [ ] Confirm checkpoint schema version remains unchanged; if it changed, stop and request design review rather than silently bumping.
- [ ] Record exact test counts, recovery evidence, known single-host cache limitation, and Run Bundle layout in implementation memory.
- [ ] Request Critical/Important code review and fix all findings.

## Final acceptance

The plan is complete only when all are true:

- ActionResolver invalid output repairs on the same step before any Action starts;
- successful ToolResult survives a new Python process and prevents duplicate provider invocation;
- the ACTION_RUNNING crash test demonstrates identity preservation;
- in-flight model and tool awaits can be cancelled without State mutation;
- every terminal CLI run has `run.json`, `report.md`, and any `artifacts/`;
- recovery matrix call counts prove no forbidden duplicate;
- all existing Opinion Context V1 tests remain green;
- documentation states at-most-once reuse of persisted successes without claiming universal exactly once.
