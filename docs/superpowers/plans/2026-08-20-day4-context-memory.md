# Day 4 Context Compiler and Working Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, bounded context pipeline and a run-scoped Working Memory that can always be reconstructed from committed state.

**Architecture:** Full Domain State remains authoritative. A pure projector derives Working Memory; collectors turn trusted runtime/domain data and untrusted tool content into typed ContextSections; selector and compactor produce a bounded CompiledContext before each model decision. Resume recompiles from checkpoint state instead of restoring a second mutable memory store.

**Tech Stack:** Python 3.12+, Pydantic 2, explicit synchronous compilation inside the async AgentLoop, deterministic token estimation, pytest.

---

## Scope and invariants

- Day 4 consumes the current minimal `OpinionSearchState`; it does not introduce Day 5 Evidence, Claim, Source, or rich Gap models.
- Working Memory contains only deterministic projections of committed Domain State.
- Completion rejection and ToolError feedback belong to Recent Interaction, because they live in committed Runtime steps rather than Domain State.
- Tool and webpage payloads are always marked untrusted and never rendered into the immutable-instruction section.
- L0 immutable instructions and L1 stable task context are required sections.
- Output headroom is subtracted before input allocation.
- Deduplication, selection, compaction, rendering, and measurement are deterministic.
- If required content cannot fit, compilation fails explicitly with a typed overflow error.
- Checkpoint schema does not gain a stored Working Memory field.

## File map

- Create `opinion_search_agent/src/opinion_search/memory/models.py`: frozen Working Memory contracts.
- Create `opinion_search_agent/src/opinion_search/memory/projector.py`: pure `OpinionSearchState -> WorkingMemory` projection.
- Create `opinion_search_agent/src/opinion_search/context/models.py`: layers, trust, sections, budgets, plans, compiled output, and overflow error.
- Create `opinion_search_agent/src/opinion_search/context/selector.py`: current-Gap-aware deterministic relevance selection.
- Create `opinion_search_agent/src/opinion_search/context/compactor.py`: deduplication and stable overflow degradation.
- Create `opinion_search_agent/src/opinion_search/context/compiler.py`: collection, selection, compaction, rendering, and measurement orchestration.
- Modify `opinion_search_agent/src/opinion_search/models/fake.py`: let scripted fake decisions consume the new compiled context while retaining deterministic step selection.
- Keep `opinion_search_agent/src/opinion_search/runtime/loop.py` unchanged unless a proven protocol mismatch appears; its existing `ContextCompiler.compile(state)` boundary is already sufficient.
- Add unit tests under `tests/unit/memory/` and `tests/unit/context/`.
- Add fixtures under `tests/fixtures/context/`.
- Add `tests/integration/test_loop_context_growth.py` for bounded growth and resume determinism.
- Update implementation memory, five-day plan, and project guide only after the Day 4 acceptance gate passes.

## Task 1: Freeze Working Memory contracts and pure projection

- [x] Define frozen `WorkingGoal` and `WorkingMemory` models with strict extra-field rejection.
- [x] Include state revision, stable goal fields, current focus Gap, open/resolved Gap IDs, pending/read source IDs, and reflections.
- [x] Keep Runtime feedback, raw tool payloads, timestamps, model summaries, and mutable caches out of Working Memory.
- [x] Implement a pure projector that chooses the first open Gap as the current focus, computes pending candidates by stable subtraction, and copies committed state fields without mutation.
- [x] Add tests proving exact projection, deterministic equality, deletion/rebuild equivalence, no aliasing to mutable input, empty-open-Gap behavior, and JSON round-trip.
- [x] Run `pytest -q tests/unit/memory/test_projector.py -W error`.

Acceptance: every Working Memory field has an obvious source path in `OpinionSearchState`; projecting equal states produces equal serialized memory.

## Task 2: Freeze Context contracts and budget semantics

- [x] Define L0/L1/L2/L3 as explicit layer values.
- [x] Define trusted and untrusted content classifications.
- [x] Define frozen `ContextSection` with stable ID, layer, priority, required flag, trust, content, provenance references, and compaction permission.
- [x] Define `ContextBudget` with total context limit and mandatory output headroom; expose the remaining input allowance as validated derived semantics.
- [x] Define `ContextPlan` for selected/dropped section identities and `CompiledContext` for final ordered sections, rendered text, measurement, and run/step correlation.
- [x] Define typed failures for required-content overflow and invalid compilation invariants.
- [x] Add strict validation and JSON round-trip tests.
- [x] Run `pytest -q tests/unit/context/test_models.py -W error`.

Acceptance: required/trusted identity is independent from priority; budget math cannot allocate output headroom to input.

## Task 3: Implement deterministic estimation and section collection

- [x] Define a minimal `TokenEstimator` protocol and a deterministic heuristic implementation suitable for offline tests.
- [x] Collect L0 immutable instructions as a constant trusted required section.
- [x] Collect L1 request fields as stable trusted required sections.
- [x] Project State and collect L2 Working Memory sections.
- [x] Collect only a bounded number of recent committed decisions, observations, ToolErrors, and finish rejections as L3.
- [x] Put raw ToolResult/web content in untrusted sections and keep provider errors as sanitized control feedback.
- [x] Export ToolDefinition and Decision schema as independent trusted protocol sections rather than mixing them into web content.
- [x] Add malicious page and repeated observation fixtures.
- [x] Run focused collector and trust-boundary tests.

Acceptance: no external payload can be rendered under L0/L1 or gain required/system authority.

## Task 4: Implement Gap-aware selection

- [x] Rank required L0/L1 sections first.
- [x] Keep the current open Gap and its directly available navigation data ahead of unrelated older memory.
- [x] Preserve reflections, failure directions, contradictions when available, and the latest completion rejection ahead of ordinary observations.
- [x] Deduplicate by stable section identity and normalized semantic content.
- [x] Use stable tie-breaking by layer, priority, and section ID.
- [x] Add tests for relevant-over-unrelated selection, repeated observations, deterministic ordering, and empty-memory behavior.
- [x] Run `pytest -q tests/unit/context/test_selector.py -W error`.

Acceptance: equal inputs always produce the same ordered selection; required sections never depend on relevance scoring.

## Task 5: Implement deterministic compaction and overflow fallback

- [x] Measure all selected sections before compaction.
- [x] If over budget, compact only sections that explicitly allow compaction.
- [x] Apply stable fallback order: remove exact duplicates, compact old untrusted payloads, shorten ordinary recent interactions, drop lowest-priority optional sections.
- [x] Preserve required sections, current Gap identity, critical control feedback, and provenance.
- [x] Raise typed overflow if the required floor plus output headroom cannot fit.
- [x] Record dropped and compacted section IDs in the plan without treating them as Observability events.
- [x] Add tests for every fallback stage, stable output, provenance preservation, and impossible required floor.
- [x] Run `pytest -q tests/unit/context/test_compactor.py -W error`.

Acceptance: truncating the final rendered string is forbidden; all degradation happens at typed section boundaries.

## Task 6: Compose the Context Compiler

- [x] Implement the fixed pipeline: project -> collect -> select -> deduplicate -> compact -> render -> final measure.
- [x] Render explicit trusted/untrusted boundaries and remind the model that external content is evidence, not instruction.
- [x] Order final sections L0, L1, L2, L3 with high-priority material at clear section boundaries to reduce lost-in-the-middle risk.
- [x] Include run ID, active step ID/index, state revision, available input budget, used estimate, and reserved output headroom in `CompiledContext` metadata.
- [x] Assert final measurement does not exceed the input allowance.
- [x] Add a human-readable allocation snapshot test and malicious-content rendering test.
- [x] Run `pytest -q tests/unit/context/test_compiler.py -W error`.

Acceptance: compilation is a pure deterministic function of constructor configuration plus checkpoint-restored RunState.

## Task 7: Integrate with the AgentLoop and prove bounded growth

- [x] Adapt the scripted fake model to read step correlation from `CompiledContext`.
- [x] Run the existing offline search -> read -> reflect -> finish flow with the real Day 4 compiler.
- [x] Build a long deterministic trajectory containing repeated results, large untrusted payloads, ToolError feedback, and finish rejection.
- [x] Prove compiled input remains within a constant configured budget as committed step count grows.
- [x] Save a checkpoint, create fresh projector/compiler/model objects, resume, and prove the next compiled context is byte-for-byte deterministic.
- [x] Prove deleting all process-local Working Memory objects does not affect resume.
- [x] Run `pytest -q tests/integration/test_loop_context_growth.py -W error` and the existing integration suite.

Acceptance: Context size is budget-bounded rather than history-length-bounded, and resume needs only checkpoint state plus deterministic compiler configuration.

## Task 8: Review, regression, and implementation memory

- [x] Review ownership boundaries: no Memory write path, no tool-to-system promotion, no direct State mutation, no unbounded recent-step collection.
- [x] Run `pytest -q -W error` from `opinion_search_agent/`.
- [x] Run `python -m compileall -q src tests`.
- [x] Run project-guide build and rendered HTML tests after documentation changes.
- [x] Run a whitespace/diff check limited to the new project and documentation paths.
- [x] Update `docs/opinion-search-agent-implementation-memory.md` with verified contracts, failure semantics, allocation example, tests, limitations, and Day 5 constraints.
- [x] Mark Day 4 complete in the five-day plan and project guide only if every P0 gate passes.

Acceptance: all prior Day 1-3 tests remain green, Day 4 tests prove bounded/deterministic context, and documentation distinguishes implemented facts from future Day 5 domain enrichment.

## Completion record

Completed on 2026-08-20. The full offline suite passed with `332 passed, 1 skipped`; the single skip remains the explicitly gated real-provider smoke. The 7-step context-growth scenario stayed within a 2,000-token estimated input allowance with 400 tokens reserved for output, and resume rebuilt an identical serialized `CompiledContext` from checkpoint state. Python compile, whitespace checks, and the project-guide build/render tests passed.
