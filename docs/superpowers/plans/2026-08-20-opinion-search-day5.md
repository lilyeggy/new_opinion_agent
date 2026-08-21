# OpinionSearch Day 5 Implementation Plan

> **For agentic workers:** execute this plan inline in small, independently verified changes. Do not touch or import archived code.

**Goal:** Complete the OpinionSearch domain vertical slice, recovery behavior, OpenAI-compatible model boundary, application composition, CLI, and offline/live/resume demonstrations.

**Architecture:** Preserve the existing explicit async loop and transaction boundary. Search and reader results become typed domain proposals through the Observation processor; only the pure reducer mutates authoritative state. The model receives `CompiledContext` and returns one validated `AgentDecision`; it never executes tools directly.

**Tech Stack:** Python 3.12, Pydantic 2, httpx, pytest.

---

### Task 1: Rich OpinionSearch domain contracts

**Files:**
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/state.py`
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/decisions.py`
- Test `opinion_search_agent/tests/unit/domain/opinion/`

**Scope:** Define the minimum stable contracts for gaps, candidates, normalized sources, evidence, claims, stakeholder positions, and their state/delta relationships. Stable IDs remain deterministic and provider-neutral. Search snippets remain candidates rather than evidence.

**Risks:** Duplicate authority between legacy ID tuples and rich objects; model-provided IDs overriding runtime identity; evidence without source provenance.

**Acceptance:** Contract tests reject duplicates, dangling references, illegal status combinations, and provider fields; state JSON round-trips through Pydantic.

### Task 2: Observation processing and pure reduction

**Files:**
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/processor.py`
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/reducer.py`
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/action_resolver.py`
- Test corresponding unit and integration modules

**Scope:** Normalize search results into candidates, successful reads into sources and source-backed evidence, and reflections into claim/gap updates. Tool errors remain committed control feedback and do not create domain facts.

**Risks:** Treating snippets as evidence; storing full page bodies in state; resolving gaps without evidence; non-idempotent replay.

**Acceptance:** Reducer is deterministic, immutable, idempotent, and rejects dangling references; existing checkpoint crash-window tests remain green.

### Task 3: Working Memory, Context, Completion, and brief

**Files:**
- Modify `opinion_search_agent/src/opinion_search/memory/`
- Modify `opinion_search_agent/src/opinion_search/context/compiler.py`
- Create `opinion_search_agent/src/opinion_search/domain/opinion/completion.py`
- Create `opinion_search_agent/src/opinion_search/domain/opinion/brief.py`
- Test memory, context, completion, and brief behavior

**Scope:** Project rich state into bounded memory, preserve contradictions and provenance in context, reject premature finish proposals, and render a cited Markdown brief with remaining gaps and stop reason.

**Risks:** Memory becoming a second source of truth; model finish bypassing policy; unsupported claims appearing in output.

**Acceptance:** Context remains bounded, resume rebuilds it deterministically, completion requires source-backed evidence, and every brief claim/evidence item links to a normalized source.

### Task 4: Model adapter and runtime recovery

**Files:**
- Modify `opinion_search_agent/src/opinion_search/models/contracts.py`
- Create `opinion_search_agent/src/opinion_search/models/openai_compatible.py`
- Modify `opinion_search_agent/src/opinion_search/runtime/loop.py` only where required by typed model/context failures
- Test model contract and recovery paths

**Scope:** Call the OpenAI-compatible chat completions endpoint with `deepseek-v4-flash`, parse one structured decision, classify timeout/auth/rate-limit/server/refusal/empty/malformed failures, and apply bounded same-step model retry or terminal recovery.

**Risks:** Leaking credentials, trusting provider payloads, retrying configuration errors, changing action identity during resume.

**Acceptance:** Fake HTTP contract tests cover success and every typed failure; no API key is required for the default test suite; model retries retain the same step identity.

### Task 5: Application composition, CLI, and demos

**Files:**
- Create `opinion_search_agent/src/opinion_search/app/config.py`
- Create `opinion_search_agent/src/opinion_search/app/service.py`
- Create `opinion_search_agent/src/opinion_search/__main__.py`
- Create `opinion_search_agent/tests/fixtures/opinion_case/`
- Add offline, resume, recovery, and gated live tests
- Update `opinion_search_agent/README.md`

**Scope:** Compose fake or live adapters through the same registry/executor, initialize a domain run, run or resume from checkpoint, render the final brief, and expose stable CLI commands.

**Risks:** A separate demo-only execution path; secrets in files; live tests becoming mandatory; CLI hiding checkpoint semantics.

**Acceptance:** Offline and resume commands work without keys, live mode fails safely when configuration is absent, and all modes use the same Runtime/Tool/Context/Memory stack.

### Task 6: Final verification and implementation memory

**Files:**
- Update `docs/opinion-search-agent-implementation-memory.md`
- Update canonical/execution docs only for decisions actually changed

**Verification:** Run the full pytest suite with warnings as errors, compile all source/tests, check whitespace, inspect the final diff, and confirm no new project import references `archive/`.

**Acceptance:** All deterministic tests pass; gated live tests report explicit skips without credentials; implementation memory records verified facts, limitations, failure behavior, and interview explanations.
