"""Local demo web server for OpinionSearch.

This module composes the existing OpinionSearch service behind a small stdlib
HTTP server. It adds no dependency: routing, JSON handling and Server-Sent
Events streaming are implemented with ``http.server`` and ``queue``.

Design rules:

- The Runtime and Domain layers are not modified. Progress is pushed through
  the existing ``LoopHook.after_checkpoint(boundary, state)`` boundary, so the
  browser observes real step transactions (open, deciding, action running,
  observation ready, reducing, committed, terminated).
- Cancellation reuses ``EventCancellationSignal``; the HTTP layer only wakes
  the run's event loop via ``call_soon_threadsafe``.
- Each run lives in its own daemon thread with its own event loop and writes
  its checkpoint to ``<runs_root>/<run_id>/run.json`` with the standard
  ``JsonCheckpointStore`` path.
- ``offline`` mode uses the deterministic fake providers and requires no API
  key. ``live`` mode uses the real Brave/Jina/OpenAI-compatible providers and
  reads ``LiveConfig`` from the environment (optionally seeded from ``.env``).
- No secret or config value is ever serialized into an HTTP response.

Run with: ``python -m opinion_search.web --port 8900``.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from opinion_search.app.config import LiveConfig
from opinion_search.app.contracts import SearchRequest
from opinion_search.app.run_bundle import RunBundleError, RunBundleWriter
from opinion_search.app.service import (
    build_live_service,
    build_offline_service,
)
from opinion_search.domain.opinion.brief import SearchOutcome
from opinion_search.runtime.cancellation import EventCancellationSignal
from opinion_search.runtime.loop import CheckpointBoundary
from opinion_search.runtime.transaction import RunState

_INDEX_FILE = (Path(__file__).parent / "index.html").resolve()
_DEV_FILE = (Path(__file__).parent / "dev.html").resolve()

_HEARTBEAT_SECONDS = 15.0
_HISTORY_LIMIT = 2000
_FIELD_LIMIT = 600
_RUN_ID_RE = re.compile(r"opinion-[0-9a-f]{32}")


class RunRecord:
    """One investigation run served by this process.

    The run executes in a background daemon thread with its own event loop.
    Progress events from the runtime hook are fanned out to every SSE
    subscriber and kept in a bounded history so late subscribers receive the
    full timeline.
    """

    def __init__(
        self,
        *,
        run_id: str,
        mode: str,
        request: SearchRequest,
        checkpoint_path: Path,
        env_file: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self.request = request
        self.checkpoint_path = checkpoint_path
        self._env_file = Path(env_file) if env_file is not None else None
        self.created_at = time.time()
        self._history: list[dict[str, Any]] = []
        self._subscribers: list[queue.Queue[dict[str, Any] | None]] = []
        self._terminal_event: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._signal: EventCancellationSignal | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.error: str | None = None
        self.latest_status = "created"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run_in_thread,
            name=f"opinion-search-{self.run_id}",
            daemon=True,
        )
        self._thread.start()

    def subscribe(self) -> queue.Queue[dict[str, Any] | None]:
        """Return a queue seeded with the run history, if any."""

        subscription: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self._lock:
            for event in self._history:
                subscription.put(event)
            terminal_already_replayed = (
                bool(self._history) and self._history[-1] is self._terminal_event
            )
            if (
                self._terminal_event is not None
                and not terminal_already_replayed
            ):
                subscription.put(self._terminal_event)
            if self._terminal_event is not None:
                subscription.put(None)
            self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    def cancel(self) -> None:
        signal = self._signal
        loop = self._loop
        if signal is None:
            return
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(signal.cancel)
        else:
            signal.cancel()

    @property
    def question(self) -> str:
        return self.request.question

    def _emit(self, event: dict[str, Any] | None) -> None:
        with self._lock:
            if event is not None:
                self._history.append(event)
                if len(self._history) > _HISTORY_LIMIT:
                    del self._history[: len(self._history) - _HISTORY_LIMIT]
                if event.get("type") == "terminal":
                    self._terminal_event = event
            subscribers = list(self._subscribers)
        for subscription in subscribers:
            subscription.put(event)

    def _run_in_thread(self) -> None:
        signal = EventCancellationSignal()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._signal = signal
        self._loop = loop
        try:
            loop.run_until_complete(self._investigate(signal))
        except Exception as exc:  # noqa: BLE001 - report any run failure to the UI
            self.error = f"{type(exc).__name__}: {exc}"
            self._emit(
                {
                    "type": "terminal",
                    "status": "failed",
                    "stop_reason": "The run crashed; see the server log.",
                    "error": self.error,
                }
            )
        finally:
            self._emit(None)
            loop.close()
            self._loop = None

    async def _investigate(self, signal: EventCancellationSignal) -> None:
        hook = _ProgressHook(self)
        if self.mode == "live":
            load_env_file(self._env_file)
            config = LiveConfig.from_env()
            service = build_live_service(
                self.checkpoint_path,
                config,
                hook=hook,
            )
        else:
            service = build_offline_service(
                self.checkpoint_path,
                hook=hook,
            )
        outcome = await service.investigate(
            self.request,
            run_id=self.run_id,
        )
        with self._lock:
            self.latest_status = outcome.status.value
        try:
            await RunBundleWriter(self.checkpoint_path).write_report(outcome)
        except RunBundleError:
            # The report is a convenience artifact; a failed run is terminal.
            pass
        self._emit(_terminal_event(outcome))


class RestoredRunRecord:
    """Read-only view of a terminal run restored from its on-disk bundle.

    Used after a server restart, when the in-memory registry is empty but the
    standard Run Bundle (report.md + meta.json + run.json) is still on disk.
    It satisfies the same attribute surface the HTTP handlers read; live
    operations (subscribe/cancel) degrade gracefully.
    """

    _HEADER_RE = r"^\*\*(.+?):\*\*\s*(.*)$"

    def __init__(
        self,
        *,
        runs_root: Path,
        run_id: str,
        report_text: str,
        meta: dict[str, Any],
        outcome: SearchOutcome | None = None,
    ) -> None:
        self.run_id = run_id
        self.mode = str(meta.get("mode") or "unknown")
        self.question = str(
            meta.get("question")
            or (outcome.report.question if outcome is not None else None)
            or self._header(report_text, "Question")
        )
        created_at = meta.get("created_at")
        if not isinstance(created_at, (int, float)):
            try:
                created_at = (runs_root / run_id / "report.md").stat().st_mtime
            except OSError:
                created_at = 0.0
        self.created_at = float(created_at)
        self.checkpoint_path = runs_root / run_id / "run.json"
        status = (
            outcome.status.value
            if outcome is not None
            else self._header(report_text, "Run status") or "completed"
        )
        self.latest_status = status.strip()
        self.error = None
        source_urls = re.findall(
            r"\]\((https?://[^)\\]+)\)",
            report_text,
        )
        self._terminal_event: dict[str, Any] | None = (
            _terminal_event(outcome)
            if outcome is not None
            else {
                "type": "terminal",
                "status": self.latest_status,
                "stop_reason": self._header(report_text, "Stop reason") or "",
                "report": None,
                "markdown": report_text,
                "source_urls": list(dict.fromkeys(source_urls)),
                "remaining_gap_ids": [],
            }
        )

    @classmethod
    def _header(cls, report_text: str, name: str) -> str | None:
        for line in report_text.splitlines():
            match = re.fullmatch(cls._HEADER_RE, line.strip())
            if match and match.group(1) == name:
                return match.group(2).strip()
        return None

    def subscribe(self) -> queue.Queue[dict[str, Any] | None]:
        subscription: queue.Queue[dict[str, Any] | None] = queue.Queue()
        subscription.put(self._terminal_event)
        subscription.put(None)
        return subscription

    def unsubscribe(self, subscription) -> None:
        return None

    def cancel(self) -> None:
        return None


class _ProgressHook:
    """LoopHook implementation pushing checkpoint boundaries to the record."""

    def __init__(self, record: RunRecord) -> None:
        self._record = record

    async def after_checkpoint(
        self,
        boundary: CheckpointBoundary,
        state: RunState,
    ) -> None:
        self._record.latest_status = state.status.value
        self._record._emit(_progress_event(boundary, state))


def _terminal_event(outcome: SearchOutcome) -> dict[str, Any]:
    return {
        "type": "terminal",
        "status": outcome.status.value,
        "stop_reason": outcome.stop_reason,
        "report": outcome.report.model_dump(mode="json"),
        "markdown": outcome.markdown,
        "source_urls": list(outcome.source_urls),
        "remaining_gap_ids": list(outcome.remaining_gap_ids),
    }


def _progress_event(
    boundary: CheckpointBoundary,
    state: RunState,
) -> dict[str, Any]:
    step = state.active_step
    return {
        "type": "progress",
        "boundary": boundary.value,
        "status": state.status.value,
        "run_id": state.run_id,
        "step_index": state.next_step_index,
        "phase": step.phase.value if step is not None else None,
        "step_id": step.step_id if step is not None else None,
        "attempt": step.attempt if step is not None else None,
        "decision": _compact_step_payload(step.decision.decision) if step is not None and step.decision else None,
        "action": _compact_step_payload(step.action.action) if step is not None and step.action else None,
        "observation": _compact_step_payload(step.observation.observation) if step is not None and step.observation else None,
        "committed_steps": len(state.committed_steps),
        "stop_reason": state.stop_reason,
    }


def _compact_step_payload(value: Any) -> Any:
    dumped = value.model_dump(mode="json")
    return _truncate(dumped)


def _truncate(value: Any, limit: int = _FIELD_LIMIT) -> Any:
    if isinstance(value, dict):
        return {key: _truncate(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value]
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + " [...]"
    return value


class _OpinionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        owner: OpinionSearchServer,
    ) -> None:
        self.owner = owner
        super().__init__(server_address, _OpinionRequestHandler)


class OpinionSearchServer:
    """Composes ``RunRecord`` state with the stdlib HTTP front end."""

    def __init__(
        self,
        *,
        runs_root: Path,
        env_file: Path | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.env_file = Path(env_file) if env_file is not None else None
        self._records: dict[str, RunRecord] = {}

    def httpd(self, address: tuple[str, int]) -> _OpinionHTTPServer:
        return _OpinionHTTPServer(address, self)

    def serve(self, *, host: str = "127.0.0.1", port: int = 8900) -> None:
        httpd = self.httpd((host, port))
        print(f"OpinionSearch web demo: http://{host}:{httpd.server_address[1]}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()

    def create_run(self, mode: str, request: SearchRequest) -> RunRecord:
        run_id = f"opinion-{uuid4().hex}"
        checkpoint_path = self.runs_root / run_id / "run.json"
        record = RunRecord(
            run_id=run_id,
            mode=mode,
            request=request,
            checkpoint_path=checkpoint_path,
            env_file=self.env_file,
        )
        self._records[run_id] = record
        self._write_meta(record)
        record.start()
        return record

    def _write_meta(self, record: RunRecord) -> None:
        """Best-effort sidecar so history survives a server restart."""

        try:
            meta_path = record.checkpoint_path.parent / "meta.json"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(
                json.dumps(
                    {
                        "run_id": record.run_id,
                        "mode": record.mode,
                        "question": record.request.question,
                        "created_at": record.created_at,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def get_run(self, run_id: str | None) -> RunRecord | None:
        if run_id is None:
            return None
        record = self._records.get(run_id)
        if record is not None:
            return record
        restored = self._restore_run(run_id)
        if restored is not None:
            self._records[run_id] = restored
        return restored

    def _restore_run(self, run_id: str) -> RestoredRunRecord | None:
        """Rebuild a terminal run from its on-disk bundle after a restart."""

        if not _RUN_ID_RE.fullmatch(run_id):
            return None
        report_path = self.runs_root / run_id / "report.md"
        if not report_path.is_file():
            return None
        try:
            report_text = report_path.read_text(encoding="utf-8")
            meta: dict[str, Any] = {}
            meta_path = self.runs_root / run_id / "meta.json"
            if meta_path.is_file():
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            outcome = None
            outcome_path = self.runs_root / run_id / "outcome.json"
            if outcome_path.is_file():
                outcome = SearchOutcome.model_validate_json(
                    outcome_path.read_text(encoding="utf-8")
                )
                if outcome.markdown.rstrip("\n") != report_text.rstrip("\n"):
                    # A process may stop between the two atomic replacements.
                    # Never combine typed data and Markdown from different runs.
                    outcome = None
        except (OSError, ValueError, ValidationError):
            return None
        return RestoredRunRecord(
            runs_root=self.runs_root,
            run_id=run_id,
            report_text=report_text,
            meta=meta,
            outcome=outcome,
        )

    def run_summaries(self) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for run_id, record in self._records.items():
            summaries[run_id] = {
                "run_id": run_id,
                "mode": record.mode,
                "question": record.question,
                "status": record.latest_status,
                "created_at": record.created_at,
                "error": record.error,
            }
        # Include terminal runs that only exist on disk (e.g. after a restart).
        if self.runs_root.is_dir():
            for run_dir in self.runs_root.iterdir():
                run_id = run_dir.name
                if run_id in summaries or not _RUN_ID_RE.fullmatch(run_id):
                    continue
                restored = self.get_run(run_id)
                if restored is None:
                    continue
                summaries[run_id] = {
                    "run_id": run_id,
                    "mode": restored.mode,
                    "question": restored.question,
                    "status": restored.latest_status,
                    "created_at": restored.created_at,
                    "error": None,
                }
        return sorted(summaries.values(), key=lambda item: item["created_at"])


class _OpinionRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OpinionSearchDemo/0.1"

    @property
    def owner(self) -> OpinionSearchServer:
        return self.server.owner  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:
        path = self.path
        if path == "/" or path == "/index.html":
            self._send_page(_INDEX_FILE)
            return
        if path == "/dev" or path == "/dev.html":
            self._send_page(_DEV_FILE)
            return
        if path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "runs": len(self.owner._records)},
            )
            return
        if path == "/api/runs":
            self._send_json(HTTPStatus.OK, {"runs": self.owner.run_summaries()})
            return
        match = self._match(r"/api/runs/([^/]+)$", path)
        if match:
            record = self.owner.get_run(match[0])
            if record is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                return
            self._send_snapshot(record)
            return
        match = self._match(r"/api/runs/([^/]+)/events$", path)
        if match:
            record = self.owner.get_run(match[0])
            if record is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                return
            self._stream_events(record)
            return
        match = self._match(r"/api/runs/([^/]+)/report$", path)
        if match:
            record = self.owner.get_run(match[0])
            if record is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                return
            self._send_report(record)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/api/runs":
            self._create_run()
            return
        match = self._match(r"/api/runs/([^/]+)/cancel$", self.path)
        if match:
            record = self.owner.get_run(match[0])
            if record is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                return
            record.cancel()
            self._send_json(HTTPStatus.OK, {"cancelled": True})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    @staticmethod
    def _match(pattern: str, path: str) -> tuple[str, ...] | None:
        match = re.fullmatch(pattern, path)
        return match.groups() if match is not None else None

    def _create_run(self) -> None:
        try:
            payload = json.loads(self._read_body())
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"invalid JSON body: {exc}"},
            )
            return
        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "body must be a JSON object"},
            )
            return
        fields = dict(payload)
        mode = fields.pop("mode", None)
        if mode not in ("offline", "live"):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": (
                        "mode must be one of 'offline' or 'live' "
                        f"(got {mode!r})"
                    )
                },
            )
            return
        try:
            request = SearchRequest.model_validate(fields)
        except ValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"invalid search request: {exc}"},
            )
            return
        if mode == "live":
            try:
                load_env_file(self.owner.env_file)
                LiveConfig.from_env()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc)},
                )
                return
        record = self.owner.create_run(mode, request)
        self._send_json(
            HTTPStatus.ACCEPTED,
            {
                "run_id": record.run_id,
                "mode": record.mode,
            },
        )

    def _send_snapshot(self, record: RunRecord) -> None:
        outcome = None
        terminal = record._terminal_event
        if terminal is not None:
            outcome = {
                "status": terminal.get("status"),
                "stop_reason": terminal.get("stop_reason"),
                "report": terminal.get("report"),
                "markdown": terminal.get("markdown"),
                "source_urls": terminal.get("source_urls", []),
                "remaining_gap_ids": terminal.get("remaining_gap_ids", []),
            }
        self._send_json(
            HTTPStatus.OK,
            {
                "run_id": record.run_id,
                "mode": record.mode,
                "question": record.question,
                "status": record.latest_status,
                "stop_reason": record._terminal_event.get("stop_reason")
                if record._terminal_event is not None
                else None,
                "created_at": record.created_at,
                "outcome": outcome,
                "error": record.error,
            },
        )

    def _send_report(self, record: RunRecord) -> None:
        report_path = record.checkpoint_path.parent / "report.md"
        if not report_path.is_file():
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "report is written when the run reaches a terminal state"},
            )
            return
        body = report_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self, record: RunRecord) -> None:
        subscription = record.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = False
        try:
            while True:
                try:
                    event = subscription.get(timeout=_HEARTBEAT_SECONDS)
                except queue.Empty:
                    self._write(b": keep-alive\n\n")
                    continue
                if event is None:
                    break
                payload = json.dumps(event, ensure_ascii=False)
                self._write(f"data: {payload}\n\n".encode())
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The browser went away; the record keeps its history for the next
            # subscriber.
            pass
        finally:
            record.unsubscribe(subscription)
            self.close_connection = True

    def _write(self, content: bytes) -> None:
        self.wfile.write(content)

    def _send_page(self, page: Path) -> None:
        if not page.is_file():
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"{page.name} is missing from the package"},
            )
            return
        content = page.read_text(encoding="utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        content = json.dumps(payload, ensure_ascii=False)
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> str:
        length_header = self.headers.get("Content-Length")
        length = int(length_header) if length_header else 0
        if length > 1024 * 1024:
            raise ValueError("request body too large")
        return self.rfile.read(length).decode("utf-8")


def load_env_file(path: Path | None) -> None:
    """Merge simple ``KEY=VALUE`` lines from a dotenv file into the process.

    Existing environment values win; keys with empty values count as unset so
    ``LiveConfig.from_env`` still reports them as missing. Values may be
    wrapped in one pair of single or double quotes, which is stripped.
    """

    if path is None or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
