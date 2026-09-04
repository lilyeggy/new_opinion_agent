"""End-to-end tests for the web demo server.

Each test boots a real stdlib HTTP server on an ephemeral port and drives it
with httpx, including consuming the Server-Sent Events stream until the
terminal event. Offline runs are deterministic and require no API key.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import httpx
import pytest

from opinion_search.app.config import LiveConfig
from opinion_search.web.server import OpinionSearchServer, load_env_file


def test_load_env_file_strips_quotes_and_keeps_existing(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "OPINION_MODEL_BASEURL=\"https://example.com/v1\"\n"
        "TOKEN='secret-value'\n"
        "EMPTY_KEY=\n"
        "PLAIN=https://plain.example\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPINION_MODEL_BASEURL", raising=False)
    monkeypatch.delenv("TOKEN", raising=False)
    monkeypatch.delenv("EMPTY_KEY", raising=False)
    monkeypatch.setenv("PLAIN", "https://already-set.example")
    monkeypatch.setenv("OPINION_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    load_env_file(env_file)

    import os

    assert os.environ["OPINION_MODEL_BASEURL"] == "https://example.com/v1"
    assert os.environ["TOKEN"] == "secret-value"
    assert os.environ["EMPTY_KEY"] == ""
    # Existing environment values win over the file.
    assert os.environ["PLAIN"] == "https://already-set.example"
    config = LiveConfig.from_env()
    assert str(config.model_base_url) == "https://example.com/v1"


@pytest.fixture
def base_url(tmp_path) -> Iterator[str]:
    server = OpinionSearchServer(
        runs_root=tmp_path / "runs",
        env_file=None,
    )
    httpd = server.httpd(("127.0.0.1", 0))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _start_offline_run(client: httpx.Client) -> str:
    response = client.post(
        "/api/runs",
        json={"mode": "offline", "question": "What happened in the example event?"},
    )
    assert response.status_code == 202
    return response.json()["run_id"]


def _collect_terminal(client: httpx.Client, run_id: str) -> tuple[dict, list[dict]]:
    events: list[dict] = []
    terminal: dict | None = None
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            if event["type"] == "terminal":
                assert terminal is None, "terminal event must appear exactly once"
                terminal = event
                break
            events.append(event)
    assert terminal is not None, "stream ended without a terminal event"
    return terminal, events


def test_index_and_healthz(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "<html" in index.text
        dev = client.get("/dev")
        assert dev.status_code == 200
        assert "Dev Console" in dev.text
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"


def test_offline_run_streams_progress_and_terminal(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        terminal, events = _collect_terminal(client, run_id)

    assert terminal["status"] == "completed"
    assert terminal["stop_reason"]
    assert "# OpinionSearch Brief" in terminal["markdown"]
    assert terminal["source_urls"]
    assert terminal["remaining_gap_ids"] == []
    assert terminal["report"]["question"] == "What happened in the example event?"
    assert terminal["report"]["conclusion"]["summary"]
    assert terminal["report"]["sources"][0]["source_ref"] == "S1"

    boundaries = [event["boundary"] for event in events]
    assert "run_started" in boundaries
    assert "step_opened" in boundaries
    assert "decision_accepted" in boundaries
    assert "action_running" in boundaries
    assert "observation_ready" in boundaries
    assert "step_committed" in boundaries
    assert "continuation_applied" in boundaries
    # The offline script commits ten steps (search/read/reflect x3, finish).
    assert len([b for b in boundaries if b == "step_committed"]) == 10

    decision_with_payload = next(
        event for event in events if event["decision"] is not None
    )
    assert decision_with_payload["decision"]["action"] == "search"
    assert decision_with_payload["decision"]["query"]

    observation_with_payload = next(
        event for event in events if event["observation"] is not None
    )
    assert observation_with_payload["observation"]["action"] == "search"


def test_snapshot_and_run_list_after_terminal(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        _collect_terminal(client, run_id)

        snapshot = client.get(f"/api/runs/{run_id}")
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["run_id"] == run_id
        assert body["mode"] == "offline"
        assert body["status"] == "completed"
        assert body["outcome"]["markdown"]
        assert body["outcome"]["report"]["conclusion"]["summary"]

        listing = client.get("/api/runs")
        assert listing.status_code == 200
        runs = listing.json()["runs"]
        assert any(run["run_id"] == run_id for run in runs)


def test_sse_replay_serves_the_full_timeline_after_termination(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        _collect_terminal(client, run_id)
        _terminal, events = _collect_terminal(client, run_id)

    # A second subscriber receives the same replayed timeline from history.
    assert len(events) >= 12


def test_run_request_validation(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        assert (
            client.post(
                "/api/runs",
                json={"mode": "bogus", "question": "x"},
            ).status_code
            == 400
        )
        assert (
            client.post("/api/runs", json={"mode": "offline"}).status_code == 400
        )
        assert (
            client.post(
                "/api/runs",
                json={"mode": "offline", "question": "   "},
            ).status_code
            == 400
        )
        assert (
            client.post("/api/runs", content="not json").status_code == 400
        )
        assert client.get("/api/runs/does-not-exist").status_code == 404
        assert (
            client.post("/api/runs/does-not-exist/cancel").status_code == 404
        )


def test_cancel_endpoint_accepts_and_run_terminates(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        cancel = client.post(f"/api/runs/{run_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json() == {"cancelled": True}
        terminal, _events = _collect_terminal(client, run_id)
        # The offline script is fast, so the run may finish before the cancel
        # signal wins the race; both endings are legal.
        assert terminal["status"] in {"completed", "cancelled"}


def test_live_mode_reports_missing_keys_without_network(base_url, monkeypatch) -> None:
    monkeypatch.delenv("OPINION_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(
            "/api/runs",
            json={"mode": "live", "question": "What happened?"},
        )
        assert response.status_code == 400
        assert "OPINION_MODEL_API_KEY" in response.json()["error"]
        assert "BRAVE_SEARCH_API_KEY" in response.json()["error"]


def test_checkpoint_bundle_is_written_next_to_run(tmp_path, base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        _collect_terminal(client, run_id)

    checkpoint = tmp_path / "runs" / run_id / "run.json"
    report = tmp_path / "runs" / run_id / "report.md"
    outcome = tmp_path / "runs" / run_id / "outcome.json"
    assert checkpoint.is_file()
    assert report.is_file()
    assert outcome.is_file()
    assert "# OpinionSearch Brief" in report.read_text(encoding="utf-8")


def test_report_endpoint_serves_terminal_markdown(base_url) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = _start_offline_run(client)
        # Before the terminal event the report may not exist yet; both a 404
        # (race) and a 200 are acceptable, but after the terminal event the
        # report must be served.
        _collect_terminal(client, run_id)
        response = client.get(f"/api/runs/{run_id}/report")
        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
        assert "# OpinionSearch Brief" in response.text
        assert client.get("/api/runs/unknown/report").status_code == 404


def test_history_survives_server_restart(tmp_path) -> None:
    runs_root = tmp_path / "runs"

    def start_server() -> tuple[str, ThreadingHTTPServer]:
        server = OpinionSearchServer(runs_root=runs_root, env_file=None)
        httpd = server.httpd(("127.0.0.1", 0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{httpd.server_address[1]}", httpd

    base_url_first, httpd_first = start_server()
    with httpx.Client(base_url=base_url_first, timeout=30) as client:
        run_id = _start_offline_run(client)
        _collect_terminal(client, run_id)
    httpd_first.shutdown()
    httpd_first.server_close()

    # A fresh server process shares only the on-disk bundles.
    base_url_second, httpd_second = start_server()
    try:
        with httpx.Client(base_url=base_url_second, timeout=30) as client:
            listing = client.get("/api/runs").json()["runs"]
            restored = next(run for run in listing if run["run_id"] == run_id)
            assert restored["status"] == "completed"
            assert restored["question"]

            snapshot = client.get(f"/api/runs/{run_id}").json()
            assert snapshot["outcome"]["markdown"]
            assert snapshot["outcome"]["source_urls"]
            assert snapshot["outcome"]["report"]["sources"]

            # The SSE replay of a restored run ends with the terminal event.
            terminal, _events = _collect_terminal(client, run_id)
            assert terminal["status"] == "completed"
            assert terminal["report"]["conclusion"]["summary"]
    finally:
        httpd_second.shutdown()
        httpd_second.server_close()
