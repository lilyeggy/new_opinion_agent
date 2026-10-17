# OpinionSearch Agent

OpinionSearch Agent is an explicit single-agent Harness for public-Web opinion investigation. Its Runtime owns lifecycle, step transactions, checkpoint/resume, structured decisions, tool execution, deterministic state reduction, bounded context, run-scoped memory, and completion control.

The model proposes exactly one `search`, `read`, `reflect`, or `finish` decision. Runtime validation resolves accepted decisions into internal actions. Search and reader adapters return untrusted observations; only the OpinionSearch processor and pure reducer can add candidates, normalized sources, evidence, claims, stakeholder positions, or gap outcomes to authoritative state.

> **Design decision (2026-09-21).** This Runtime AgentLoop is the single harness.
> An experimental multi-role planner/research/analyst/reviewer pipeline was
> evaluated and archived to `archive/harness-pipeline/`: it duplicated
> capabilities the production path already provides (skeleton-driven rendering
> via PagePlan plus targeted search) and bypassed the Runtime's reliability
> mechanisms. See the archive README for the full decision record.

## Project status (2026-10-17, frozen)

Feature-complete and frozen. The investigation workload is the verification
vehicle; the technical substance is the Harness/Runtime and Tool/Context
layers.

**Closeout (2026-10-17).** Three things landed and the runtime was frozen:

- **Deterministic replay verified against a live provider.** Two real runs
  (Brave + Jina + `deepseek-flash` over `https://api.deepseek.com/v1`, 9 and 13
  committed steps) replay `matched` three times each with an unchanged journal
  md5; see `artifacts/live-run-deepseek-20261017` and
  `artifacts/live-run-deepseek-envcheck-20261017`. Replay substitutes only the
  model client and the action executor — context compilation, decision
  validation, reduction and completion run exactly as in production.
- **An offline quality gate.** `python scripts/quality_gate.py --check`
  recomputes the published numbers from four frozen runs with zero model calls
  and zero network requests, and exits non-zero on any drift.
- **`record --report`** writes `report.md` and `outcome.json` through the same
  `RunBundleWriter` the served entry point uses, so a journaled run reads
  without a separate export step.
- **A numeric conflict detector (mechanism layer).**
  `src/opinion_search/domain/numeric.py` flags the same money metric stated a
  power of ten apart in two documents: 5 conflicts over 4 metrics across the
  frozen adversarial corpus, zero false positives on two live evidence sets.
  It is offline evidence only — not yet wired into the investigation loop — so
  the report-level adversarial score stays 2/3 while the mechanism check is 3/4.

**Verified end-to-end (live):** a real Chinese public-opinion event ran the
full loop — 60 steps, 17 searches, 17 reads, 14 findings, 92 evidence
citations, review phase executed (6 supported / 8 partial), and the
completion gate rejected `finish` 18 times rather than close with unanswered
required questions (honest `partial`).

**Measured quality (see `../docs/舆情agent-质量三数字-D4-2026-09-21.html`; recomputable offline via `python scripts/quality_gate.py --check`):**

- Retrieval recall 60% (6/10 human-labeled must-hit items; shortfall traced
  to aggregator-domain bias — 66% of candidates from one portal — and
  anti-scraping read failures).
- Faithfulness 71% fully supported, 100% non-fabricated (14 findings
  hand-checked; all 4 partials are excerpt-recall misses, not inventions).
- Adversarial replay (7 real + 3 planted documents): correction adopted,
  counter-narrative read but unused, wrong numbers did not propagate.

**Known limitations:** single search engine (Brave). The legacy opinion path
fixes 5 results per query; it passes the TaskFrame time window (`freshness`)
and language (`search_lang`) to Brave, while domain scope is enforced by a
post-acquisition candidate filter. The investigation workbench uses 10 results
and prepends domain scope as `site:` operators. `country` is not used;
evidence excerpt selection is the recall bottleneck; the model does not
close evidence-starved questions as `not_found`; numeric claims are
provenance-checked but not cross-checked for conflicts. Fix directions are
documented and deliberately deferred. The earlier limitation "replay was only
validated on the offline fake assembly" no longer holds — see the closeout
block above.

## Requirements

- Python 3.12+
- The package dependencies declared in `pyproject.toml`

From this directory:

```bash
python -m pip install -e '.[dev]'
pytest -q -W error
```

## Deterministic offline demo

The offline path uses the same Agent Loop, Tool Registry/Executor, Context Compiler, Working Memory, CompletionPolicy, checkpoint format, and brief renderer as live mode. It requires no API key.

```bash
python -m opinion_search offline \
  --question "What happened in the example event?" \
  --topic "Example event" \
  --focus "Compare event facts and causal accounts" \
  --run-id offline-demo \
  --checkpoint .opinion_search/offline-demo.json
```

Resume the persisted run with:

```bash
python -m opinion_search resume \
  --mode offline \
  --checkpoint .opinion_search/offline-demo.json
```

Every terminal run writes a Run Bundle next to the checkpoint: `run.json`
(checkpoint), `report.md` (atomic Markdown brief), `action_results/`
(cross-process success cache), and — when the reader produces artifacts —
`artifacts/`.

## Web server

The server is stdlib-only (no new dependency): `http.server` for routing,
`queue` for fan-out, and the existing `LoopHook` boundary for progress push.
It serves three pages and two API surfaces.

```bash
python -m opinion_search.web --port 8900
```

| Page | Served at | What it is |
|---|---|---|
| Investigation workbench | `/` (also `/investigation`) | The main product page: clarification, live investigation progress, workbench modules, evidence drawer, page export, diagnostics |
| Legacy opinion console | `/legacy` (also `/index.html`) | The earlier single-question demo console |
| Developer console | `/dev` | Lists every run in this process, replays the full `CheckpointBoundary` timeline, shows snapshot JSON, exposes cancel |

Both surfaces accept a **mode**:

- **offline** — keyless, deterministic fake providers, finishes in seconds;
  ideal for rehearsing a demo or an interview walkthrough.
- **live** — real Brave search, Jina reader, and model via `.env`
  (`OPINION_MODEL_API_KEY`, `BRAVE_SEARCH_API_KEY`, optional `JINA_API_KEY`
  and `OPINION_MODEL_BASEURL`); one dotenv file is merged into `--env-file`,
  defaulting to `.env`. Live runs consume API quota.

The two surfaces are **different domain compositions over the same Runtime**:
the workbench runs `domain/investigation` (6 actions, via
`investigation/manager.py`), the legacy console runs `domain/opinion`
(4 actions, via `app/service.py`). They share the AgentLoop, the Tool
Registry/Executor, the checkpoint format, and the `ContextSection` model —
but not the domain rules, and not the Context Compiler.

Investigation API (`/api/investigations`):

- `POST /api/investigations` creates a run and returns its id;
- `POST /api/investigations/{id}/clarify` answers the planner's clarifying
  questions (at most three per round);
- `GET /api/investigations/{id}` returns the snapshot; `GET .../events`
  streams progress as SSE, rebuilt from the persisted snapshot so late or
  reconnecting subscribers create no new work;
- `GET .../workbench`, `.../page`, `.../materials`, `.../diff`,
  `.../versions`, `.../diagnostics` and `.../evidence/{evidence_id}` serve
  the projections and evidence locators;
- `POST .../cancel`, `.../resume` and `.../update` cancel the run, resume it
  from its checkpoint, and start a targeted follow-up update.

Legacy opinion API (`/api/runs`):

- `POST /api/runs` `{mode, question, topic, focus, time_range, language}`
  validates a `SearchRequest` and returns `run_id`;
- `GET /api/runs/{run_id}/events` streams progress events, each one a
  `CheckpointBoundary` with the current step decision/action/observation;
  late subscribers receive the full replayed history;
- `POST /api/runs/{run_id}/cancel` wakes the run's event loop through the
  existing `EventCancellationSignal`, so the Runtime terminates at a safe
  boundary with status `cancelled`;
- `GET /api/runs/{run_id}` returns a snapshot and the terminal brief;
- `GET /api/runs/{run_id}/report` serves the terminal `report.md` as
  `text/markdown` (404 until the run reaches a terminal state);
- every run writes its standard Run Bundle under
  `<runs-dir>/<run_id>/` (default `.opinion_search_web/`).

Nothing in the Runtime or Domain layer is modified by the web front end;
progress and cancellation use the same seams as the CLI. No secret is ever
returned by the API.

## Context and memory safety

Every compiled context section records an explicit content origin; model, tool,
and provider content can never be marked trusted even after commit/checkpoint/
resume. A deterministic `ProvenanceIndex` separates why a source was acquired
from which investigation dimensions it semantically covers. The Evidence ID
catalog is bounded into a required current window plus droppable history
chunks (default 64 each, coverage sample 16 per gap), so required context does
not grow with the run. Trusted coverage cells sample only true semantic Gap
links (acquisition-only or unlinked evidence is never shown as coverage) and
carry exact counts plus bounded Evidence/Source samples. Each compiled context
carries a content SHA-256 and per-section token measures that are transient
model input, never checkpointed. Context deduplication preserves each
section's producer origin, and L0 immutable instructions accept only
app-config content. A 100-step / 640-Evidence stress test and a 14-path
prompt-injection matrix verify bounded, deterministic, resume-identical
context with no trust laundering.

## Runtime recovery

- An accepted decision whose action resolution fails is repaired on the same
  step (attempt increments) before any external action starts; only
  processor/reducer invariant errors fail closed.
- Successful tool results are cached by action identity under
  `action_results/`. If the process dies after the cache write but before the
  observation checkpoint, resume reuses the cached result from a fresh process
  without invoking the provider again. This is at-most-once reuse of persisted
  successes; it is not a universal exactly-once guarantee, and opinion-search
  tools are read-only and safe to retry.
- Async cancellation can interrupt an in-flight model or tool await; a winning
  cancellation terminates the run as `cancelled` without committing a partial
  delta. Cancellation that arrives after an Observation checkpoint (or while
  reducing) does not discard that step: the observed action is reduced and
  committed exactly once before the cancelled state is persisted.

## Live model and public-Web tools

Live mode uses OpenCode Go's OpenAI-compatible endpoint with `deepseek-v4-flash`, Brave Search, and Jina Reader. Keep credentials in the process environment; never write them to source or checkpoint files. A Jina API key is optional.

```bash
export OPINION_MODEL_API_KEY="..."
export OPINION_MODEL_BASE_URL="https://opencode.ai/zen/go/v1"
export OPINION_MODEL_NAME="deepseek-v4-flash"
export BRAVE_SEARCH_API_KEY="..."
# Optional for higher Jina limits:
export JINA_API_KEY="..."

python -m opinion_search live \
  --question "What happened, what is disputed, and who said what?" \
  --topic "A bounded public-Web event" \
  --time-range "2026-08-01/2026-08-20" \
  --focus "Original account, independent reporting, and corrections" \
  --include-domain example.org \
  --exclude-domain spam.example.org \
  --run-id live-demo \
  --checkpoint .opinion_search/live-demo.json
```

`--include-domain` and `--exclude-domain` are repeatable. They are enforced on normalized result hosts before a search hit can become a candidate. Credentialed provider endpoints require public HTTPS. For a local development model only, loopback HTTP additionally requires `OPINION_ALLOW_INSECURE_MODEL_ENDPOINT=true`.

Live reader bodies are bounded in transit, persisted in `.opinion_search/artifacts/` by SHA-256 content identity, and represented in checkpoints by an artifact reference plus bounded inline content. Evidence locators retain the normalized source block number and character offsets.

Resume live mode with the same environment and checkpoint. Checkpoints carry an opaque execution-profile ID, so selecting a different mode or changing the live model/tool composition is rejected before an action can be replayed:

```bash
python -m opinion_search resume \
  --mode live \
  --checkpoint .opinion_search/live-demo.json
```

## Failure behavior

- Empty, refused, malformed, timed-out, rate-limited, and server-error model responses receive a bounded retry on the same stable step ID.
- Authentication failures fail safely without exposing credentials.
- Invalid decisions are retried on the same `step_id` with an incremented
  `attempt`, bounded by `max_decision_attempts` (default 3, so up to two
  repairs; the offline composition pins it to 2); repeated queries or reads
  stop with a meaningful partial result.
- Tool timeout/rate-limit/server errors are retried by `ToolExecutor`; normalized failures are committed as control feedback, not domain evidence.
- Required context overflow, cancellation, and the hard step limit preserve committed work as partial or cancelled output.
- Checkpoints persist active step phase, attempt, typed failure feedback, observations, committed actions, and authoritative domain state.
- Markdown report fields derived from users, models, and pages are escaped before rendering; link destinations are separately percent-encoded.

The final Markdown brief distinguishes evidence-linked claims, attributed stakeholder positions, contradictions, remaining gaps, sources, and the limits of a public-Web sample. It does not claim whole-network sentiment or reach.

## Tool provider fallback and circuit breaking

`ToolExecutor` owns argument validation, the success cache, same-provider retry,
cross-provider fallback, timeout, safe error construction, and a per-
tool/provider in-memory circuit breaker. `ToolInvocation.attempt` is a global
physical count; `action_id` stays constant across retries and providers; an
`asyncio.CancelledError` always propagates. Mock consumers can build a
multi-provider registry with `registry.register_provider(...)` — provider ids
and adapters never appear in model-visible specs.

## MCP (official SDK v2)

MCP tools are registered explicitly through an app-owned allowlist whose local
description and canonical schema SHA-256 hashes pin the reviewed remote
contract. Discovery registers only after every allowlisted tool matches and
every Registry conflict is checked, so a mismatch leaves the Registry
unchanged. The official MCP Python SDK v2 (`mcp>=2,<3`) transport opens a
client per list/call operation over stdio or streamable HTTP. Call content
blocks are recursively projected: SDK `_meta`/`meta`/`annotations` metadata
is removed at every nesting level before JSON validation, and content that is
not JSON-representable becomes a safe tool error with a fixed message. A
declared output schema requires structured content. Production MCP HTTP
endpoints must be normalized public HTTPS; loopback HTTP is allowed only under
an explicit development flag, and every caller-created HTTP client is closed
by the transport. Stateful session reuse is not implemented; MCP content is
untrusted input, never a trusted directive.
