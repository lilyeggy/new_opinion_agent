# Agent Infra Computer Foundations Learning Map

This map is derived from the current `opinion_search_agent` implementation. It intentionally does not cover Redis, Docker, or subprocess as if they already exist in this repository: those are later experiments for understanding the next execution boundary.

## Project facts

- `runtime/loop.py`: explicit async Agent Loop, checkpoint boundaries, cancellation races, decision/action/observation/reduction lifecycle.
- `runtime/transaction.py`: immutable `RunState`, phase transitions, correlation checks, commit invariants, resume classification.
- `tools/executor.py`: async timeout, retry, provider fallback, circuit breaker, result cache.
- `web/server.py`: threaded HTTP server; one daemon thread and one asyncio event loop per run; queue-based SSE fan-out; thread-safe cancellation.
- `app/run_bundle.py`: filesystem run bundle and atomic `os.replace` writes.

## Experiments

1. **Thread + event loop + cancellation** — `web/server.py:RunRecord.start`, `_run_in_thread`, `cancel`; understand who owns a run and why cancellation is scheduled into the loop.
2. **Blocking vs non-blocking async work** — compare `time.sleep` and `await asyncio.sleep`; map to model/tool awaits and event-loop starvation.
3. **Timeout, cancellation, cleanup** — observe `asyncio.timeout`, `CancelledError`, `finally`, and unfinished tasks; map to tool execution and safe terminal states.
4. **FD, pipe, subprocess, wait/zombie** — introduce an external worker boundary; compare inherited descriptors and explicit reaping with the current in-process adapters.
5. **Checkpoint atomicity and crash recovery** — use temporary files and `os.replace`; map to `JsonCheckpointStore`, run bundles, and resume after a crash.
6. **Socket, HTTP, SSE, connection lifecycle** — inspect ports, listening sockets, client connections, queue fan-out, and late replay in `web/server.py`.
7. **Namespace, cgroup, container, sandbox** — show what the current process/thread design does not isolate; map to a future worker/sandbox boundary and resource limits.

## Implementation status

All seven experiments are implemented as standalone pages in `agent_infra_lab/` (single-page site: `index.html` + `app.js` + `styles.css`), with runnable code under `agent_infra_lab/experiments/`:

- `01_thread_event_loop.py` — process vs thread vs own event loop (verified: PID identical, thread id different)
- `02_blocking_vs_async.py` — blocking `time.sleep` vs cooperative `await asyncio.sleep` (verified: ticks wait for the blocking sleep)
- `03_timeout_cleanup.py` — timeout cancels the in-flight task, `finally` still runs; falls back to `asyncio.wait_for` on Python < 3.11 (system macOS python3 is 3.9)
- `04_fork_wait.py` — fork + zombie window + `waitpid` reaping (macOS/Linux only)
- `05_atomic_write.py` — temp file + `os.fsync` + `os.replace` atomic pattern
- 06 and 07 reuse the real web server / Docker and need no standalone script

Progress, per-experiment predictions, conclusions and problems are stored in `localStorage` under `agent-infra-lab-v1`; every lab section has its own complete button. Serve with `python3 -m http.server` from `agent_infra_lab/`.

## Learning invariant

For every experiment: observe a real system fact first, then explain only the minimum OS/runtime principle needed, then return to an exact project symbol and failure mode.
