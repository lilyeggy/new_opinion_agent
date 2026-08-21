# Opinion Context V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic fact-gap context with an opinion-specific investigation map that separates source acquisition intent from semantic evidence coverage and makes stakeholder, narrative, counter-narrative, and factual-baseline coverage explicit.

**Architecture:** Keep the existing Agent Loop, transaction, checkpoint, Tool Runtime, and four-action space unchanged. Refactor only the OpinionSearch domain pack and its deterministic Working Memory/Context projection: read produces source-backed Evidence with acquisition provenance; reflect proposes semantic Gap assessments, Claims, Stakeholder Positions, and Narratives; Reducer commits those links; Completion evaluates opinion coverage and source diversity.

**Tech Stack:** Python 3.12+, Pydantic 2, custom async Agent Loop, pytest.

---

## Scope and file map

- Modify `opinion_search_agent/src/opinion_search/domain/opinion/state.py`: opinion-specific domain primitives, Narrative, semantic Gap evidence links, acquisition provenance.
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/decisions.py`: structured Gap assessment and Narrative proposals, state-aware repair feedback.
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/processor.py`: read no longer asserts semantic gap coverage; reflect produces semantic deltas.
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/reducer.py`: validate and commit Gap assessments and Narratives deterministically.
- Modify `opinion_search_agent/src/opinion_search/memory/models.py`: compact opinion investigation view and coverage cells.
- Modify `opinion_search_agent/src/opinion_search/memory/projector.py`: deterministic Gap→Evidence/Source coverage projection.
- Modify `opinion_search_agent/src/opinion_search/context/compiler.py`: render an explicit opinion coverage matrix before individual Evidence.
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/completion.py`: opinion-specific completion gates.
- Modify `opinion_search_agent/src/opinion_search/domain/opinion/brief.py`: render narratives and semantic gap coverage.
- Modify `opinion_search_agent/src/opinion_search/app/service.py` and `models/fake.py`: new default investigation dimensions and deterministic scenario.
- Update relevant unit, integration, contract, recovery, and end-to-end tests mechanically after core semantics are fixed.
- Update `docs/public-opinion-search-agent-design.md`, `docs/opinion-search-agent-5-day-plan.md`, and `docs/opinion-search-agent-implementation-memory.md` after verified implementation.

## Frozen domain decisions

- `SearchDecision.target_gap_id` and `ReadDecision.target_gap_id` record why the Agent acquired a candidate/source; they do not prove what the retrieved text semantically covers.
- `Evidence` contains source ID, excerpt, locator, and acquisition gap ID. It does not close a Gap by existence alone.
- `GapAssessmentProposal` explicitly names one Gap, its outcome (`open`, `resolved`, or `blocked`), the Evidence IDs supporting that assessment, and a rationale.
- Resolved Gap assessment requires at least one known Evidence ID. Blocked Gap assessment requires a rationale and may have no Evidence. Open assessment may link partial Evidence without closing the Gap.
- `Narrative` records an observed public framing, its kind (`dominant`, `counter`, or `emerging`), attributed stakeholders, and Evidence IDs. It is not treated as a factual Claim.
- Source diversity is a completion-quality property. It is not an investigation Gap.
- Default opinion dimensions are factual baseline, stakeholder positions, dominant narratives, and counter-narratives.
- Runtime remains domain-agnostic and the action set remains `search`, `read`, `reflect`, `finish`.

## Task 1: Domain contracts

**Files:** `state.py`, `decisions.py`, their unit tests.

- [x] Add Narrative and narrative-kind contracts with stable ID and Evidence provenance rules.
- [x] Add Evidence acquisition provenance and remove automatic semantic coverage meaning from read-time fields.
- [x] Add Gap evidence links to committed InvestigationGap state.
- [x] Replace parallel resolved/blocked arrays in Reflect with explicit Gap assessments.
- [x] Make state-aware validation report missing Gap IDs, eligible Gap IDs, and unknown Evidence IDs without including Evidence text.
- [x] Verify structural and state-aware contract tests fail before implementation and pass afterward.

## Task 2: Processor and Reducer

**Files:** `processor.py`, `reducer.py`, their unit tests.

- [x] Make read create Evidence whose acquisition provenance is the accepted ReadDecision target.
- [x] Make reflect convert Gap, Claim, Position, and Narrative proposals into one OpinionSearchDelta.
- [x] Make Reducer validate every semantic link against committed Evidence and every stakeholder/narrative identity deterministically.
- [x] Preserve pure, immutable, idempotent replay behavior and closed-Gap replay protection.
- [x] Verify invalid semantic links cannot mutate State.

## Task 3: Opinion Working Memory and Context

**Files:** `memory/models.py`, `memory/projector.py`, `context/compiler.py`, Context/Memory tests.

- [x] Project one deterministic coverage cell per Gap containing status, linked Evidence IDs, and distinct Source IDs.
- [x] Project Claims, Stakeholder Positions, and Narratives separately.
- [x] Render the compact coverage map before individual source/evidence sections.
- [x] Preserve all trust boundaries: only Runtime-derived structural IDs/status/relations are trusted; model prose and externally derived statements remain untrusted across commit/resume.
- [x] Verify a retry prompt names the exact missing and eligible Gap IDs and never includes rejected model reasoning.
- [x] Verify resume reconstructs byte-identical opinion context.

## Task 4: Opinion completion and output

**Files:** `completion.py`, `brief.py`, their unit tests.

- [x] Require a resolved factual baseline linked to source-backed Evidence and at least one factual Claim.
- [x] Require committed Stakeholder Positions for the stakeholder dimension.
- [x] Require at least one evidence-linked dominant or emerging Narrative for the narrative dimension.
- [x] Require an evidence-linked counter Narrative or an explicitly blocked counter-narrative dimension; blocked completion is partial.
- [x] Require at least two distinct Source records actually linked into semantic coverage; never accept model-proposed `source_kind` as verified quality.
- [x] Render an opinion brief with facts, stakeholder positions, narrative map, contested claims, remaining dimensions, and citations.

## Task 5: Scenario migration and verification

**Files:** `app/service.py`, `models/fake.py`, integration/e2e fixtures and tests.

- [x] Replace default generic Gap IDs with the four opinion dimensions.
- [x] Update the deterministic scenario so it performs search/read/reflect over baseline, stakeholder, dominant narrative, and counter-narrative coverage.
- [x] Keep search/read/reflect/finish and Runtime step semantics unchanged.
- [x] Run targeted domain, memory, Context, Completion, and recovery suites.
- [x] Run `pytest -q -W error` and `python -m compileall -q src tests`.
- [x] Run offline CLI and resume verification.
- [x] Run one gated live Agent task and record whether it commits reflect and reaches finish or a meaningful partial.

## Risk controls and acceptance

- Existing checkpoint schema becomes semantically incompatible; bump schema/profile compatibility before live resume.
- Do not infer narrative popularity, reach, sentiment percentage, or whole-network prevalence from public-Web sources.
- Narrative text must always retain Evidence provenance and Markdown escaping.
- Completion must never accept an unsupported Claim, Position, Narrative, or resolved Gap.
- No Runtime, Tool Registry/Executor, provider adapter, MCP, Environment, Control Plane, Trace, Eval, or Model Infra expansion is allowed in this migration.
- Acceptance requires deterministic offline completion, checkpoint/resume parity, all tests green, and one real live run proving the new opinion Context reaches a valid reflect or reports a precise evidence-coverage deficit.
