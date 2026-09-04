# OpinionSearch Agent

OpinionSearch Agent is an explicit single-agent Harness for public-Web opinion investigation. Its Runtime owns lifecycle, step transactions, checkpoint/resume, structured decisions, tool execution, deterministic state reduction, bounded context, run-scoped memory, and completion control.

The model proposes exactly one `search`, `read`, `reflect`, or `finish` decision. Runtime validation resolves accepted decisions into internal actions. Search and reader adapters return untrusted observations; only the OpinionSearch processor and pure reducer can add candidates, normalized sources, evidence, claims, stakeholder positions, or gap outcomes to authoritative state.

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

## Web demo console

The demo website runs the same service from the browser: it accepts a
question, executes a real investigation in the background, streams every
step-transaction checkpoint over Server-Sent Events, supports cancellation,
and renders the terminal brief. The server is stdlib-only (no new
dependency): `http.server` for routing, `queue` for fan-out, and the existing
`LoopHook` boundary for progress push.

```bash
python -m opinion_search.web --port 8900
```

Open `http://127.0.0.1:8900`. Pick a mode:

- **offline** — keyless, deterministic fake providers, finishes in seconds;
  ideal for rehearsing a demo or an interview walkthrough.
- **live** — real Brave search, Jina reader, and model via `.env`
  (`OPINION_MODEL_API_KEY`, `BRAVE_SEARCH_API_KEY`, optional `JINA_API_KEY`
  and `OPINION_MODEL_BASEURL`); one dotenv file is merged into `--env-file`,
  defaulting to `.env`. Live runs consume API quota.

HTTP surface:

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

A dedicated developer console lives at **`/dev`**: it lists all runs in this
process with live status polling, replays the full CheckpointBoundary event
timeline per run, shows the snapshot JSON, exposes cancel, and links to the
terminal `report.md`. The user-facing page stays product-shaped; raw runtime
detail is confined to the developer console.

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
- Invalid decisions receive one repair attempt; repeated queries or reads stop with a meaningful partial result.
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
