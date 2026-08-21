# Context and Run-scoped Memory Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> If those skills are unavailable in the execution environment, follow the numbered Task, test-first sequence, stop conditions, and review handoff in this document directly; missing a skill is not permission to redesign the Task.

**Goal:** Make OpinionSearch Context and run-scoped Memory bounded, provenance-aware, trust-safe, deterministic across resume, and demonstrably stable over long Agent trajectories.

**Architecture:** Full OpinionSearchState remains authoritative. A pure ProvenanceIndex derives semantic relations, WorkingMemory projects a compact cognitive view, and OpinionContextCompiler partitions that view into origin-tagged sections. Required Context becomes bounded around the current investigation; historical evidence remains optional and degradable; every compiled prompt carries a deterministic content hash and section measurements.

**Tech Stack:** Python 3.12+, Pydantic 2, deterministic pure projections, SHA-256, pytest.

---

## Scope and authority

Read first:

1. `docs/agent-infra-interview-deepening.md`
2. `docs/public-opinion-search-agent-design.md`, especially Context, Memory and Opinion Domain sections
3. `opinion_search_agent/src/opinion_search/domain/opinion/state.py`
4. `opinion_search_agent/src/opinion_search/memory/models.py`
5. `opinion_search_agent/src/opinion_search/memory/projector.py`
6. `opinion_search_agent/src/opinion_search/context/models.py`
7. `opinion_search_agent/src/opinion_search/context/selector.py`
8. `opinion_search_agent/src/opinion_search/context/compactor.py`
9. `opinion_search_agent/src/opinion_search/context/compiler.py`
10. existing Context injection, growth and resume tests.

Do not add:

- model-generated Memory summary;
- embeddings or vector retrieval;
- cross-run memory;
- database-backed memory service;
- observability event store;
- evaluation framework;
- provider-specific tokenizer as a hard dependency;
- new Domain actions.

## Frozen conceptual boundaries

```text
OpinionSearchState
  authoritative, committed, checkpointed
        |
        | pure derivation
        v
ProvenanceIndex + WorkingMemory
  complete enough for cognition, never independently written
        |
        | collect/select/compact/render
        v
CompiledContext
  one model call, bounded, hashed, not checkpointed
```

Trust answers “who produced this content?” Priority answers “how useful is it now?” They are independent.

## Content origin and trust matrix

| Origin | Examples | Required trust |
|---|---|---|
| runtime | state revision, Gap status, IDs, counts, retry directive | trusted |
| app_config | immutable instructions, locally reviewed Tool description/schema | trusted |
| user_task | SearchRequest question/topic/focus/domain filters | trusted |
| model | query, Decision prose, reflection, next focus, rationale | untrusted |
| tool | ToolResult payload, MCP content | untrusted |
| provider | provider/MCP error message, remote metadata/description | untrusted |

“Trusted” here means structurally produced by the application, not permission to override L0. Model/tool/provider origin can never be marked trusted, including after commit/checkpoint/resume.

## Provenance semantics

For each Evidence, distinguish:

```text
acquired_for_gap_id
  why the Agent read the source

semantic_gap_ids
  which GapAssessment committed this Evidence as coverage

claim links
  which Claim it supports or contradicts

position links
  which StakeholderPosition cites it

narrative links
  which Narrative cites it
```

Selection relevance uses semantic relations first. Acquisition intent is a fallback hint, never proof of relevance.

## Bounded catalog policy

Current implementation makes the complete Evidence ID catalog required and non-compactable. That eventually makes required Context grow with the run. Replace it with two tiers:

```text
required current catalog
  bounded
  current-gap semantic evidence
  latest candidate evidence that may fill current gap

optional history catalog chunks
  all remaining exact Evidence IDs
  droppable from oldest/least relevant chunks first
```

Default policy:

```text
required_evidence_limit = 64
history_chunk_size = 64
coverage_sample_limit_per_gap = 16
```

These are Context compiler configuration, not SearchRequest or Domain State.

## File map

Create:

- `opinion_search_agent/src/opinion_search/domain/opinion/provenance.py` — pure deterministic relation index.
- `opinion_search_agent/src/opinion_search/context/catalog.py` — bounded Evidence catalog partitioning.
- `opinion_search_agent/tests/unit/domain/opinion/test_provenance.py`
- `opinion_search_agent/tests/unit/context/test_catalog.py`
- `opinion_search_agent/tests/integration/test_context_long_trajectory.py`
- `opinion_search_agent/tests/security/test_context_injection_matrix.py`

Modify:

- `opinion_search_agent/src/opinion_search/memory/models.py`
- `opinion_search_agent/src/opinion_search/memory/projector.py`
- `opinion_search_agent/src/opinion_search/context/models.py`
- `opinion_search_agent/src/opinion_search/context/compiler.py`
- `opinion_search_agent/src/opinion_search/context/selector.py` only if semantic provenance ranking cannot remain provenance-ref based;
- Context/Memory/checkpoint tests.

## Task 1: Add explicit Context content origin and enforce trust

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/context/models.py`
- Modify: `opinion_search_agent/src/opinion_search/context/compiler.py`
- Modify: all ContextSection test fixtures.

### Required enum and validation

Add:

```text
ContextContentOrigin
  runtime
  app_config
  user_task
  model
  tool
  provider
```

Add `origin` to ContextSection. Keep `trust` serialized because rendered Context and tests need the explicit boundary, but validate the matrix:

- runtime/app_config/user_task may be trusted or, when deliberately mixed with unsafe text, untrusted;
- model/tool/provider must be untrusted;
- L0 is app_config + trusted + required + never;
- L1 ToolDefinition/schema is app_config + trusted only when locally defined or MCP allowlist/schema-pinned;
- SearchRequest task section is user_task + trusted + required + never;
- model/tool/provider origin is never allowed in L0 or L1 because those layers require trusted.

### Split mixed sections

Current sections containing both Runtime structure and potentially unsafe prose must be split:

#### Active decision failure

Trusted control section:

```text
kind
recovery directive
attempt number
```

Untrusted message section:

```text
failure.message
```

#### Tool error

Trusted control section:

```text
tool name
kind
attempt count
retryable
action ID as provenance only
```

Untrusted provider-message section:

```text
ToolError.message
```

#### Completion rejection

Trusted control section:

```text
disposition = reject_and_continue
```

Untrusted policy-reason section:

```text
verdict.reason
```

Treat the reason conservatively because it may interpolate task or model-derived identifiers.

### Required tests

- [ ] Every compiler-created section has an expected origin.
- [ ] Constructing trusted model/tool/provider section fails validation.
- [ ] L0/L1 origin and trust combinations are enforced.
- [ ] Malicious failure message appears only in untrusted section after JSON resume.
- [ ] Trusted control section still carries kind/directive/attempt without prose.
- [ ] Existing malicious webpage/query/reflection tests remain green.
- [ ] Renderer includes origin in the opening marker in addition to layer and trust.
- [ ] Embedded fake origin/trust markers are escaped like existing section markers.

Rendered header becomes conceptually:

```text
[CONTEXT_SECTION id=... layer=... origin=... trust=...]
```

Changing rendered bytes is expected; update deterministic fixture expectations in this Task only.

## Task 2: Build a pure ProvenanceIndex

**Files:**

- Create: `opinion_search_agent/src/opinion_search/domain/opinion/provenance.py`
- Create: `opinion_search_agent/tests/unit/domain/opinion/test_provenance.py`

### Required model

Define one immutable record per Evidence:

```text
EvidenceProvenance
  evidence_id
  source_id
  acquired_for_gap_id
  semantic_gap_ids
  supporting_claim_ids
  contradicting_claim_ids
  position_ids
  narrative_ids
```

Define:

```text
ProvenanceIndex
  evidence: tuple[EvidenceProvenance, ...]

  record(evidence_id) -> EvidenceProvenance
  evidence_ids_for_gap(gap_id) -> tuple[str, ...]
  source_ids_for_gap(gap_id) -> tuple[str, ...]
  unlinked_evidence_ids() -> tuple[str, ...]
```

Build function:

```text
build_provenance_index(state: OpinionSearchState) -> ProvenanceIndex
```

### Determinism and identity

- record order equals committed `state.evidence` order so later code can treat the tail as recent acquisition;
- every tuple is unique and follows corresponding State object order;
- no dict insertion order is exposed as a serialized contract;
- unknown Evidence references raise a provenance invariant error even though OpinionSearchState should already prevent them;
- `unlinked` means no semantic Gap, Claim, Position or Narrative reference; acquisition alone does not make it semantically linked;
- SourceKind is not part of provenance because it is an untrusted analytic label.

### Required tests

- one Evidence linked through every relation type;
- supporting and contradicting Claim links remain distinct;
- one Evidence can cover multiple Gaps;
- acquisition gap differs from semantic gap;
- unlinked Evidence detection;
- duplicate-free deterministic order;
- model dump/JSON round trip;
- unknown link fail closed.

Do not modify CompletionPolicy or Brief in this Task. First establish the relation view and review its semantics.

## Task 3: Project semantic relevance into Working Memory

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/memory/models.py`
- Modify: `opinion_search_agent/src/opinion_search/memory/projector.py`
- Test: `opinion_search_agent/tests/unit/memory/test_projector.py`

### WorkingEvidence additions

Add:

```text
semantic_gap_ids
supporting_claim_ids
contradicting_claim_ids
position_ids
narrative_ids
```

Keep existing `acquired_for_gap_id` separately.

### Projector rules

- build ProvenanceIndex exactly once per projection;
- use it for WorkingEvidence and OpinionCoverageCell source IDs;
- do not recalculate reverse links in multiple comprehensions;
- current gap remains highest-priority open Gap;
- semantic relations are full committed relations, not bounded here;
- no Context policy or token limit enters WorkingMemory.

### Tests

- source acquired for factual baseline but semantically linked to counter narrative projects both fields correctly;
- WorkingMemory JSON round trip preserves order;
- deleting WorkingMemory and re-projecting returns equality;
- projector does not mutate State;
- one State revision produces one consistent provenance view.

## Task 4: Partition the Evidence catalog into bounded required and optional history

**Files:**

- Create: `opinion_search_agent/src/opinion_search/context/catalog.py`
- Create: `opinion_search_agent/tests/unit/context/test_catalog.py`
- Modify: `opinion_search_agent/src/opinion_search/context/compiler.py`
- Modify: Context compiler tests.

### Required configuration

Define immutable `EvidenceCatalogPolicy`:

```text
required_evidence_limit: int >= 8, default 64
history_chunk_size: int >= 8, default 64
coverage_sample_limit_per_gap: int >= 1, default 16
```

OpinionContextCompiler accepts this policy with a default. It is app configuration and not checkpointed.

### Required selection order

When a current open Gap exists, rank Evidence IDs in this order, preserving committed recency within a group by newest first:

1. Evidence semantically linked to current Gap;
2. unlinked Evidence from the most recently added records;
3. Evidence acquired for current Gap but not already selected;
4. Evidence referenced by unresolved/contested Claim or counter Narrative;
5. remaining Evidence newest first.

Take the first `required_evidence_limit`, then restore committed State order inside the required catalog for deterministic readability. All remaining entries are partitioned in committed order into history chunks.

When there is no open Gap, required catalog contains only Evidence referenced by unresolved/contested Claims, capped by the same limit. A terminal report does not need Context compilation; this rule exists for a rejected Finish that continues.

### Catalog entry content

Each catalog entry contains only:

```text
evidence_id
source_id
acquired_for_gap_id
semantic_gap_ids
```

No excerpt, locator, Source title, URL query text, Claim text or Narrative text enters trusted catalog sections. IDs and structural relations use runtime origin; Source IDs remain identifiers, not instructions.

### Compiler sections

- `memory.evidence-catalog.current`: required, trusted runtime origin, never compacted, bounded;
- `memory.evidence-catalog.history.<n>`: optional, trusted runtime origin, drop mode, lower priority;
- individual Evidence excerpt sections remain untrusted tool origin and truncatable;
- replace the existing unbounded required catalog completely; do not keep both.

### Bounded coverage rendering

WorkingMemory keeps full OpinionCoverageCell evidence IDs. Compiler renders a bounded structural coverage view:

```text
gap_id
status
evidence_count
source_ids
sample_evidence_ids (max policy limit)
```

For current Gap, sample uses the catalog relevance order; for other Gaps, sample uses the first committed IDs up to the per-gap limit. Do not render full Evidence ID arrays in a required coverage section.

### Required tests

- zero Evidence omits both catalog tiers safely;
- fewer than limit: all IDs required, no history;
- more than limit: exact bounded required count and complete non-overlapping history;
- latest unlinked Evidence remains required even when acquired for another Gap;
- semantic current-gap Evidence outranks acquisition-only Evidence;
- every State Evidence ID appears exactly once across required/history;
- no excerpt/prose appears in trusted catalog;
- required section token size is bounded as total Evidence grows from 64 to 640;
- same State produces byte-identical partition.

## Task 5: Make Context selection semantic-gap aware

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/context/compiler.py`
- Modify only if needed: `opinion_search_agent/src/opinion_search/context/selector.py`
- Test: Context selector/compiler tests.

### Required provenance refs

For each untrusted Evidence section, `provenance_refs` must include:

```text
evidence_id
source_id
acquired_for_gap_id
all semantic_gap_ids
all linked Claim/Position/Narrative IDs
```

This lets the existing current-gap ranking recognize semantic relevance without teaching the generic selector OpinionSearch types.

Claim, Position and Narrative sections already include Evidence IDs; add their semantic Gap IDs when available. Candidate sections remain acquisition-gap relevant because they have not been read.

### Priority policy

Within L2:

1. current Gap coverage and current catalog;
2. counter/contested Evidence linked to current Gap;
3. other current-gap semantic Evidence;
4. latest unlinked Evidence;
5. pending Candidates for current Gap;
6. resolved historical objects;

Do not put priority logic into Domain State. Compiler assigns priority; selector remains stable and generic.

### Tests

- Evidence acquired for baseline but semantically linked to current counter Gap ranks as current-gap relevant;
- acquisition-only Evidence does not outrank semantic current-gap Evidence;
- counter and contradiction survive before ordinary resolved evidence under pressure;
- trust remains untrusted regardless of high priority;
- selector semantic dedup never merges across trust/layer.

## Task 6: Add deterministic Context hash and section measurements

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/context/models.py`
- Modify: `opinion_search_agent/src/opinion_search/context/compiler.py`
- Test: `opinion_search_agent/tests/unit/context/test_models.py`
- Test: `opinion_search_agent/tests/unit/context/test_compiler.py`

### Required contracts

Add:

```text
ContextSectionMeasure
  section_id
  estimated_tokens

ContextPlan.section_measures

CompiledContext.content_sha256
```

Hash is lowercase SHA-256 of the final rendered UTF-8 bytes. It is computed after selection, compaction and rendering. Section measurement is estimator output for `render_sections((section,))`, not raw content only.

Validation:

- one measure per selected section in selected order;
- section IDs equal selected IDs;
- every estimate is positive;
- content hash exactly matches rendered bytes;
- re-validation rejects changed rendered content, changed hash or changed measure;
- total estimate remains the estimator output of full rendered Context; do not require section estimates to sum exactly because inter-section newline serialization can differ.

This metadata stays inside CompiledContext and model-call diagnostics. It is not added to Domain State or checkpoint.

### Tests

- deterministic hash across repeated compile;
- typed JSON round trip;
- one-character trusted or untrusted content change changes hash;
- resume of identical typed RunState yields identical hash and measures;
- different token estimator may change measures but not content hash;
- Context remains within input limit.

## Task 7: Add a 100-step long-trajectory stress test

**Files:**

- Create: `opinion_search_agent/tests/integration/test_context_long_trajectory.py`
- Add focused fixture helpers under `tests/fixtures/` only if reused.

### Fixture requirements

Build valid typed states without network or model calls:

- four default opinion Gaps;
- at least 100 committed StepRecords;
- at least 80 Sources and Candidates;
- at least 640 Evidence records;
- Claim, Position and Narrative relations across all four Gaps;
- one open current Gap;
- recent unlinked Evidence capable of filling it;
- old irrelevant Evidence;
- contested Claim and counter Narrative;
- malicious section-marker text in at least one old and one recent Evidence excerpt.

All Source/Evidence/Gap identities must satisfy current State validators. Do not bypass validation with unsafe `model_construct`.

### Assertions

- compilation succeeds under the same fixed ContextBudget at 10, 50 and 100 steps;
- estimated tokens never exceed input limit;
- selected recent interaction count never exceeds configured recent step limit;
- required catalog count never exceeds policy limit;
- coverage sample count never exceeds per-gap limit;
- latest unlinked Evidence ID is visible;
- contested/counter Evidence remains visible under pressure;
- old irrelevant Evidence may be dropped;
- L0/L1 remain unchanged;
- malicious content appears only in untrusted sections and cannot forge a marker;
- typed JSON resume produces identical rendered bytes, plan and hash;
- WorkingMemory can be discarded/rebuilt with equality;
- growth from step 50 to 100 does not force required overflow.

Do not assert wall-clock performance in CI. If useful, print local timing manually, but acceptance is deterministic bounded behavior.

## Task 8: Add a complete Context injection matrix

**Files:**

- Create: `opinion_search_agent/tests/security/test_context_injection_matrix.py`
- Reuse: `tests/fixtures/context/prompt_injection_page.json`

### Injection sources

Parameterize only the assertion helper; keep setup explicit for each path:

1. Search snippet;
2. Reader content/Evidence excerpt;
3. MCP structured content;
4. MCP unstructured content block;
5. model Search query persisted through Reducer;
6. model current focus;
7. model reflection;
8. Gap assessment rationale/resolution note;
9. accepted Decision prose;
10. ToolError provider message;
11. DecisionValidationError message containing model-proposed ID;
12. completion rejection reason;
13. checkpoint JSON resume;
14. fake `[CONTEXT_SECTION ...]` and closing markers.

### Universal assertion

For a unique malicious sentinel:

- every selected section containing the sentinel is untrusted;
- its origin is model, tool or provider as appropriate;
- no L0/L1 section contains it;
- rendered output contains escaped fake boundary markers;
- trusted structural control section still exists without the sentinel;
- JSON resume does not change origin/trust;
- compaction cannot merge sentinel content into a trusted section;
- semantic dedup does not merge same text across different origins/trust.

For MCP schema/description injection, the Tool/MCP plan's allowlist/schema pin must reject or replace remote prose before compiler input. If that plan is not yet complete, mark this test as dependent and do not weaken the assertion.

## Task 9: Use ProvenanceIndex in report/completion without reversing dependency

**Files:**

- Modify: `opinion_search_agent/src/opinion_search/domain/opinion/completion.py`
- Modify: `opinion_search_agent/src/opinion_search/domain/opinion/brief.py`
- Modify: their unit tests.

Because ProvenanceIndex lives in `domain/opinion/provenance.py`, Completion and Brief may import it without Domain depending on Memory/Context.

Replace duplicated ad hoc maps only where behavior stays identical:

- Evidence ID to Source ID;
- Gap semantic source IDs;
- Claim/Position/Narrative provenance lookups;
- report coverage source citations.

Do not change completion thresholds, source-kind policy, Markdown wording or source numbering in this Task. Add regression assertions that old and refactored output are byte-identical for current fixtures.

## Task 10: Final verification and documentation

**Files:**

- Modify after verification: `docs/public-opinion-search-agent-design.md`
- Append facts only: `docs/opinion-search-agent-implementation-memory.md`
- Modify: `opinion_search_agent/README.md`

- [ ] Run provenance, Memory, Context, injection, completion and brief tests.
- [ ] Run the 100-step stress test twice and compare hash output.
- [ ] Run checkpoint/resume integration tests.
- [ ] Run full ruff, pytest with warnings as errors, and compileall.
- [ ] Run one offline CLI after Context contract migration.
- [ ] If CompiledContext serialization changes only transient model input, confirm checkpoint schema does not change.
- [ ] If WorkingMemory changes, confirm it is still not checkpointed.
- [ ] Record catalog limits, stress fixture size, content hashes, injection paths and known heuristic-token limitation.
- [ ] Request Critical/Important review and fix every finding.

## Final acceptance

- every Context section has explicit origin and validated trust;
- mixed control/prose sections are split;
- ProvenanceIndex represents every Evidence relation deterministically;
- current semantic Gap, not only acquisition intent, drives relevance;
- required Evidence catalog and coverage are bounded;
- 100-step/640-Evidence Context compiles inside a fixed budget;
- resume produces identical Context bytes and hash;
- injection matrix proves no commit/checkpoint laundering;
- Completion and Brief behavior remain compatible;
- no vector DB, model summary, trace platform or cross-run memory was introduced.
