"""HTTP server for the investigation workbench."""

from __future__ import annotations

import json
import os
import re
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import ValidationError


from opinion_search.config import LiveConfig
from opinion_search.investigation.manager import Manager

_INVESTIGATION_FILE = (Path(__file__).parent / "investigation.html").resolve()
_ASSETS_DIR = (Path(__file__).parent / "assets").resolve()

_INVESTIGATION_ID_RE = re.compile(r"[0-9a-f]{32}")
_POLL_SECONDS = 1.0


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
    """Serve investigation requests through the stdlib HTTP front end."""

    def __init__(
        self,
        *,
        runs_root: Path,
        env_file: Path | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.env_file = Path(env_file) if env_file is not None else None
        self.investigations = Manager(self.runs_root / "investigations", config_loader=self._live_config)

    def _live_config(self) -> LiveConfig:
        load_env_file(self.env_file)
        return LiveConfig.from_env()

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

    def investigation_summaries(self) -> list[dict[str, Any]]:
        summaries = []
        for data in self.investigations.list_runs():
            request = data.get("request") or {}
            summaries.append({
                "run_id": data["run_id"], "case_id": data["case_id"], "parent_id": data.get("parent_id"),
                "mode": data.get("mode"), "question": request.get("question"), "status": data.get("status"),
                "phase": data.get("phase"), "created_at": data.get("created_at"), "updated_at": data.get("updated_at"),
            })
        return summaries

class _OpinionRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OpinionSearchDemo/0.1"

    @property
    def owner(self) -> OpinionSearchServer:
        return self.server.owner  # type: ignore[attr-defined]

    def _request_target(self) -> str:
        """Accept both origin-form and absolute-form request targets.

        RFC 7230 requires servers to accept absolute-form, which clients send
        when an HTTP proxy sits in front of the local loopback request.
        """

        target = self.path
        if "://" in target:
            target = "/" + target.partition("://")[2].partition("/")[2]
        return target or "/"

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:
        path, _, query = self._request_target().partition("?")
        if path == "/" or path == "/investigation" or path == "/investigation.html":
            self._send_page(_INVESTIGATION_FILE)
            return
        if path.startswith("/assets/"):
            self._send_asset(path)
            return
        if path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "investigations": len(self.owner.investigations.list_runs())},
            )
            return
        if self._investigation_get(path, query):
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _investigation_get(self, path: str, query: str) -> bool:
        """Return True when the path belongs to the investigation API."""

        manager = self.owner.investigations
        if path == "/api/investigations":
            self._send_json(HTTPStatus.OK, {"investigations": self.owner.investigation_summaries()})
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/evidence/([^/]+)$", path)
        if match:
            self._investigation_call(lambda: manager.evidence(match[0], match[1]))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/versions$", path)
        if match:
            self._investigation_call(lambda: {"versions": manager.versions(match[0])})
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/diagnostics$", path)
        if match:
            self._investigation_call(lambda: manager.diagnostics(match[0]))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/workbench$", path)
        if match:
            requested = self._query_value(query, "snapshot_id")
            self._investigation_call(lambda: manager.workbench(match[0], requested))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/page$", path)
        if match:
            snapshot_id = self._query_value(query, "snapshot_id")
            download = self._query_value(query, "download") == "1"
            self._investigation_call(lambda: manager.page(match[0], snapshot_id), page=True, download=download)
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/dossier$", path)
        if match:
            snapshot_id = self._query_value(query, "snapshot_id")
            download = self._query_value(query, "download") == "1"
            self._investigation_call(
                lambda: manager.dossier_page(match[0], snapshot_id),
                page=True,
                download=download,
                filename="event-dossier.html",
            )
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/presentation-plan$", path)
        if match:
            snapshot_id = self._query_value(query, "snapshot_id")
            self._investigation_call(
                lambda: manager.dossier_plan(match[0], snapshot_id).model_dump(mode="json")
            )
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/materials$", path)
        if match:
            issue_id = self._query_value(query, "issue_id")
            snapshot_id = self._query_value(query, "snapshot_id")
            offset = self._int_query(query, "offset", 0)
            limit = self._int_query(query, "limit", 50)
            if offset is None or limit is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "offset 和 limit 必须是非负整数。"})
                return True
            self._investigation_call(lambda: manager.materials(match[0], issue_id=issue_id, snapshot_id=snapshot_id, offset=offset, limit=limit))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/diff$", path)
        if match:
            base = self._query_value(query, "base")
            self._investigation_call(lambda: manager.diff(match[0], base))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/events$", path)
        if match:
            if not _INVESTIGATION_ID_RE.fullmatch(match[0]):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "调查不存在。"})
                return True
            try:
                manager.snapshot(match[0])
            except FileNotFoundError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "调查不存在。"})
                return True
            self._stream_investigation(match[0])
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/report$", path)
        if match:
            self._investigation_call(lambda: manager.markdown(match[0]), markdown=True)
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})$", path)
        if match:
            self._investigation_call(lambda: manager.snapshot(match[0]))
            return True
        if path.startswith("/api/investigations"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "调查不存在。"})
            return True
        return False

    def _investigation_call(
        self,
        call,
        *,
        markdown: bool = False,
        page: bool = False,
        download: bool = False,
        filename: str = "event-workbench.html",
    ) -> None:
        try:
            result = call()
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc) or "调查不存在。"})
            return
        except KeyError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "证据不存在。"})
            return
        except ValueError as exc:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        if page:
            body = result.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if markdown:
            body = result.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="report.md"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(HTTPStatus.OK, result)

    @staticmethod
    def _query_value(query: str, name: str) -> str | None:
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == name and value:
                from urllib.parse import unquote
                return unquote(value)
        return None

    @staticmethod
    def _int_query(query: str, name: str, default: int) -> int | None:
        raw = _OpinionRequestHandler._query_value(query, name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value >= 0 else None

    def _stream_investigation(self, identifier: str) -> None:
        manager = self.owner.investigations
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = False
        last_token = None
        try:
            while True:
                try:
                    snapshot = manager.snapshot(identifier)
                except FileNotFoundError:
                    self._write(b'data: {"type": "gone"}\n\n')
                    break
                token = (snapshot.get("updated_at"), snapshot.get("status"), snapshot.get("revision"))
                if token != last_token:
                    payload = json.dumps({"type": "snapshot", "snapshot": snapshot}, ensure_ascii=False)
                    self._write(f"data: {payload}\n\n".encode())
                    last_token = token
                if snapshot.get("status") in {"completed", "partial", "failed", "cancelled"}:
                    break
                self._write(b": keep-alive\n\n")
                time.sleep(_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def do_POST(self) -> None:
        path, _, _ = self._request_target().partition("?")
        if self._investigation_post(path):
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _investigation_post(self, path: str) -> bool:
        manager = self.owner.investigations
        if path == "/api/investigations":
            self._create_investigation()
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/clarify$", path)
        if match:
            self._investigation_post_call(lambda body: manager.clarify(match[0], body))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/cancel$", path)
        if match:
            self._investigation_post_call(lambda body: manager.cancel(match[0]))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/resume$", path)
        if match:
            self._investigation_post_call(lambda body: manager.resume(match[0]))
            return True
        match = self._match(r"/api/investigations/([0-9a-f]{32})/update$", path)
        if match:
            self._investigation_post_call(lambda body: manager.create(body, parent_id=match[0]), created=True)
            return True
        if path.startswith("/api/investigations"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "调查不存在。"})
            return True
        return False

    def _investigation_post_call(self, call, *, created: bool = False) -> None:
        try:
            body = json.loads(self._read_body() or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求体必须是合法的 JSON 对象。"})
            return
        if not isinstance(body, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求体必须是 JSON 对象。"})
            return
        try:
            result = call(body)
        except FileNotFoundError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "调查不存在。"})
            return
        except ValueError as exc:
            self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, result)

    def _create_investigation(self) -> None:
        try:
            body = json.loads(self._read_body() or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求体必须是合法的 JSON 对象。"})
            return
        if not isinstance(body, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求体必须是 JSON 对象。"})
            return
        try:
            snapshot = self.owner.investigations.create(body)
        except ValidationError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"调查输入不合法：{exc.errors()[:1]}"})
            return
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.CREATED, snapshot)

    @staticmethod
    def _match(pattern: str, path: str) -> tuple[str, ...] | None:
        match = re.fullmatch(pattern, path)
        return match.groups() if match is not None else None

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

    _ASSET_TYPES = {
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json; charset=utf-8",
    }

    def _send_asset(self, path: str) -> None:
        name = path[len("/assets/"):]
        if not name or "/" in name or "\\" in name or name.startswith("."):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        target = (_ASSETS_DIR / name).resolve()
        if _ASSETS_DIR.resolve() not in target.parents or not target.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", self._ASSET_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
