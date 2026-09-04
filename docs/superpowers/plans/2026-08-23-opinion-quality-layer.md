# OpinionSearch Quality Layer Plan

## Why this work exists

The live run `opinion-66a7c3fb747b41cb9242d2d1ab4b2748` exposed a workload-quality failure that the existing Harness intentionally does not solve by itself:

- a request phrased as "过去一周" reached `SearchRequest` with no executable time constraint;
- sources from late June were accepted for an August run and the model described them as current;
- `FinishDecision.answer_candidate` was checkpointed inside a committed decision but discarded before `SearchOutcome` and report rendering;
- every extracted evidence block was rendered, including page chrome and promoted content;
- completion proved structural coverage, not that the answer respected the requested scope.

This plan strengthens the OpinionSearch domain pack and the existing Context/Memory boundary. It does not add a new Agent framework, multi-agent orchestration, a database, an evaluation platform, or long-term user memory.

## Outcome

For a time-sensitive public-opinion request, the agent must either produce a concise, cited conclusion within the requested scope or return a partial investigation that clearly explains why the available sources cannot support that conclusion.

The final product has two separate views:

1. a reader-facing synthesis with a headline, qualified assessment, three to five cited findings, disagreement, and limitations;
2. an evidence appendix that remains available for audit but is not the default main result.

## Invariants

- A relative time phrase is anchored once at run creation and persisted in domain state. Resume must not recompute it from the current clock.
- User-provided explicit constraints override inferred framing. The model must not silently replace a user time range, topic, language, or domain constraint.
- A source cannot satisfy a time-bound gap unless its publication time is known and lies within the frame, or the gap is explicitly marked blocked/partial.
- A model-proposed task frame and final synthesis remain untrusted prose. Only validated structural IDs, scope fields, and evidence links become trusted context metadata.
- The final synthesis cannot cite invented source numbers. Each finding must carry known Evidence IDs that are validated against committed state.
- Context compaction may omit an excerpt from a model call, but never deletes full state, artifact references, or provenance links.
- Completion distinguishes `coverage complete` from `answer complete`; a time-scope violation must not yield `completed`.

## Design

### A. Task framing before the investigation loop

Introduce a typed `TaskFrame` owned by the OpinionSearch domain. It is persisted in `OpinionSearchState`, not treated as a prompt-only planning artifact.

The frame contains:

- investigation intents selected from a closed domain ontology: event snapshot, claim investigation, narrative comparison, stakeholder position, or mixed;
- the primary subject and optional focal claims;
- a normalized temporal scope with an anchor date and explicit/inferred provenance;
- explicit request constraints copied from `SearchRequest`;
- bounded ambiguity notes;
- required investigation dimensions.

Task framing has a deterministic fallback: when no model framing client is configured, preserve the four existing core dimensions and use only explicit request fields. A small deterministic parser handles unambiguous relative Chinese expressions needed by the supported UI, such as `过去一周`, `最近7天`, `过去一个月`, and explicit ISO date ranges. Unsupported natural-language dates remain unspecified rather than guessed.

The model may later propose a structured frame, but a validator must reject out-of-ontology intent values, altered explicit constraints, invalid windows, and excessive custom dimensions. The first implementation does not permit arbitrary new gaps during `reflect`; `GapFactory` derives stable initial gaps from the validated frame.

### B. Source time and document-quality boundary

Extend normalized search/read results with optional publication-time metadata and a confidence/availability marker. A model label is never sufficient proof of date or source quality.

For a bounded time frame:

- search may retrieve candidates without dates;
- a read result must expose a verified or unavailable publication date;
- evidence from unknown/out-of-window sources is retained for audit but cannot close a required in-window gap;
- if adequate in-window evidence cannot be found, completion returns partial with a precise scope limitation.

Before evidence extraction, normalize reader text into content blocks and remove obvious boilerplate: promoted blocks, navigation-only blocks, social-share blocks, image-only blocks, and repeated site chrome. Retain the original Reader artifact; normalization is an extraction view, not destructive rewriting.

Evidence extraction becomes bounded and quality-aware:

- do not create eight evidence records merely because a page has eight blocks;
- only retain blocks that pass minimum semantic relevance and content checks;
- preserve block locator and artifact reference for audit;
- record rejection reasons in transient observation/result metadata where useful, without turning them into model instructions.

### C. Structured final synthesis

Replace the discarded free-text-only `FinishDecision.answer_candidate` with a typed `FinalSynthesisProposal`. Its data is committed only after the existing completion policy accepts the finish proposal.

The proposal contains:

- a concise headline;
- an overall assessment with calibrated wording;
- three to five key findings, each linked to one or more known Evidence IDs;
- stakeholder and narrative comparison entries linked to Evidence IDs;
- unresolved questions and scope limitations;
- a confidence label derived from deterministic coverage facts plus the model's qualified explanation.

The final renderer produces the reader-facing summary from this validated structure. It must not render arbitrary model prose as fact without linked evidence. The original `answer_candidate` can be removed or repurposed only after migration tests prove no checkpoint compatibility break.

### D. Report and web view model

`SearchOutcome` gains a typed report view model in addition to Markdown. The web server returns that view model directly; the UI must not reverse-parse Markdown headings with regular expressions to construct the primary result page.

Main UI order:

1. scope and status;
2. core conclusion;
3. key findings with clickable evidence/source citations;
4. stakeholder positions and competing narratives;
5. what cannot be concluded;
6. collapsed evidence appendix and source list.

The current raw Markdown brief remains downloadable and auditable. Evidence excerpts move to an appendix rather than occupying the reader's first screen.

### E. Completion policy changes

Completion retains existing structural checks, then applies frame-aware checks:

- required dimensions are derived from `TaskFrame`;
- time-bounded requests require at least the configured number of semantically linked in-window sources for each required dimension;
- unverified-date or out-of-window evidence cannot satisfy those checks;
- incomplete scope returns a partial verdict with machine-readable limitation codes;
- final synthesis must cover all required dimensions and cite only committed evidence.

## Delivery order

### 1. Preserve and expose the final result

Implement `FinalSynthesis` state/output contracts and deterministic renderer support first. This makes the existing investigation legible without falsely improving its quality.

Acceptance: a completed fake run has a concise cited conclusion before its appendix; a finish proposal with unknown evidence IDs is rejected; checkpoint/resume produces byte-identical synthesized output.

### 2. Frame task intent and time scope

Introduce `TaskFrame`, deterministic relative-date parsing, stable anchor persistence, and intent-derived initial gaps. Keep the initial ontology bounded.

Acceptance: `过去一周` gets a persisted anchor and window; resume preserves it; unsupported date language is explicitly unspecified; explicit CLI/UI range overrides inference.

### 3. Enforce scope in acquisition and completion

Add publication-date handling and prevent out-of-window evidence from resolving time-bound dimensions. Extend fake providers with dated and undated fixtures.

Acceptance: a run containing only June sources cannot complete an August `过去一周` request; it ends partial with a specific limitation. Equivalent in-window evidence can complete.

### 4. Clean and select evidence

Create reader normalization and relevance filtering before evidence construction. Add fixtures containing promoted content, navigation, and relevant blocks.

Acceptance: promoted content never becomes Evidence; a five-source run no longer prints forty raw excerpts by default; original artifacts remain retrievable and locators still resolve.

### 5. Build the typed web presentation

Serve typed report data and render the reader-facing summary plus an expandable audit appendix. Preserve the developer timeline and raw Markdown download.

Acceptance: the browser page renders the structured summary without parsing Markdown and clearly labels partial/time-insufficient outcomes.

## Required tests

- task-frame parser and explicit-constraint precedence;
- checkpoint/resume time-anchor stability;
- unknown/out-of-window publication date cannot close a required gap;
- time-sensitive stale-source run ends partial;
- final synthesis evidence-ID and dimension validation;
- renderer never presents a runtime stop reason as the substantive conclusion;
- boilerplate/promoted content rejection;
- evidence-to-artifact locator round trip;
- web API returns typed report data and the UI can render it;
- existing offline demo, recovery, MCP, context, security, and web-server tests remain green.

## Risks and decisions deliberately deferred

- This is not population-level sentiment measurement. The product must continue to describe results as observations from accessible public-Web sources.
- Publication dates from arbitrary pages are imperfect. Unknown date is safer than a model guess.
- This plan does not add publisher/entity-level ownership verification, WARC/HTML forensic archiving, social-platform collection, or a general benchmark.
- Adding subagents is deferred until the single-agent quality layer has evidence that context isolation or parallel research materially improves results and a merge protocol exists.
