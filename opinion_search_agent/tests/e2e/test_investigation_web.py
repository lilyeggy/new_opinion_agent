"""End-to-end tests for the public-event investigation web API.

Each test boots the real stdlib server on an ephemeral port and drives the new
``/api/investigations`` surface. Offline runs are deterministic and need no key.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from opinion_search.web.server import OpinionSearchServer


@pytest.fixture
def base_url(tmp_path) -> Iterator[str]:
    server = OpinionSearchServer(runs_root=tmp_path / "runs", env_file=None)
    httpd = server.httpd(("127.0.0.1", 0))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


def create(client: httpx.Client, **payload) -> dict:
    response = client.post("/api/investigations", json={"mode": "offline", **payload})
    assert response.status_code == 201, response.text
    return response.json()


def wait_terminal(client: httpx.Client, run_id: str, timeout: float = 25) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        snapshot = client.get(f"/api/investigations/{run_id}").json()
        if snapshot["status"] in {"completed", "partial", "failed", "cancelled"}:
            return snapshot
        if time.monotonic() > deadline:
            raise AssertionError(f"investigation did not finish: {snapshot['status']}")
        time.sleep(0.05)


def test_full_investigation_chain(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=20) as client:
        created = create(client, question="某市公交夜班车调整的争议与回应")
        run_id = created["run_id"]
        assert created["status"] in {"planning", "running"}

        listed = client.get("/api/investigations").json()["investigations"]
        assert any(item["run_id"] == run_id for item in listed)

        snapshot = wait_terminal(client, run_id)
        assert snapshot["status"] in {"completed", "partial"}
        report = snapshot["report"]
        assert report["run_id"] == run_id
        evidence_id = report["evidence"][0]["evidence_id"]

        located = client.get(f"/api/investigations/{run_id}/evidence/{evidence_id}")
        assert located.status_code == 200
        body = located.json()
        assert body["excerpt"] and body["source"]["final_url"]
        assert body["locator"].startswith("Reader text chars")

        markdown = client.get(f"/api/investigations/{run_id}/report")
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert report["subject"] in markdown.text

        versions = client.get(f"/api/investigations/{run_id}/versions").json()["versions"]
        assert versions[0]["is_current"] is True


def test_events_stream_reconstructs_terminal_snapshot(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        run_id = create(client, question="某市公交夜班车调整的争议与回应")["run_id"]
        seen = None
        with client.stream("GET", f"/api/investigations/{run_id}/events") as stream:
            for line in stream.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[len("data:"):].strip())
                seen = payload["snapshot"]
                if seen["status"] in {"completed", "partial", "failed", "cancelled"}:
                    break
        assert seen is not None and seen["status"] in {"completed", "partial"}
        assert "report" in seen


def test_update_creates_child_version(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=25) as client:
        parent = wait_terminal(client, create(client, question="某市公交夜班车调整的争议与回应")["run_id"])
        child = client.post(f"/api/investigations/{parent['run_id']}/update", json={"focus": "补充机构最新回应"})
        assert child.status_code == 201, child.text
        child_snapshot = wait_terminal(client, child.json()["run_id"])
        assert child_snapshot["report"]["parent_id"] == parent["run_id"]

        diff = client.get(f"/api/investigations/{child_snapshot['run_id']}/diff").json()
        assert diff["base"] == parent["run_id"]
        assert diff["changes"]
        assert all(change["kind"] != "withdrawn" for change in diff["changes"])
        assert diff["comparability"]["same_case"] is True
        assert diff["comparability"]["base_cutoff"] == parent["report"]["cutoff"]


def test_error_codes_are_explicit(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        assert client.post("/api/investigations", json={"mode": "nope", "question": "x"}).status_code == 400
        assert client.post("/api/investigations", json={"mode": "offline"}).status_code == 400
        assert client.get("/api/investigations/" + "0" * 32).status_code == 404
        assert client.get("/api/investigations/not-an-id").status_code == 404

        run_id = create(client, question="某市公交夜班车调整的争议与回应")["run_id"]
        assert client.post(f"/api/investigations/{run_id}/clarify", json={"answer": "x"}).status_code == 409
        assert client.post(f"/api/investigations/{run_id}/clarify", json={}).status_code == 409


def test_workbench_endpoint_serves_a_consistent_projection(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=25, trust_env=False) as client:
        snapshot = wait_terminal(client, create(client, question="某市公交夜班车调整的争议与回应")["run_id"])
        run_id = snapshot["run_id"]

        body = client.get(f"/api/investigations/{run_id}/workbench").json()
        assert body["format"] == "opinion-workbench/1"
        assert body["run_id"] == run_id and body["publication_state"] in {"completed", "partial"}
        assert body["snapshot_id"] == snapshot["workbench_revision"]
        module_states = {item["module_type"]: item["state"] for item in body["modules"]}
        assert module_states["issues-review"] == "ready"
        assert module_states["rule-comparison"] == "ready", "offline fixture question implies rule_change facet"
        assert body["views"]["overview"]["highlights"][0]["module_type"] == "rule-comparison"
        assert body["views"]["issues"]["issues"]
        assert all(label.startswith("引") for label in
                   [citation["label"] for citation in body["citations"].values()])
        assert body["views"]["overview"]["source_relation_counts"]["version_count"] > 0

        assert body["snapshot_id"] == client.get(
            f"/api/investigations/{run_id}/workbench").json()["snapshot_id"]

        pinned = client.get(f"/api/investigations/{run_id}/workbench?snapshot_id={'f' * 20}")
        assert pinned.status_code == 409


def test_materials_endpoint_filters_inside_one_snapshot(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=25, trust_env=False) as client:
        snapshot = wait_terminal(client, create(client, question="某市公交夜班车调整的争议与回应")["run_id"])
        run_id, report = snapshot["run_id"], snapshot["report"]

        all_materials = client.get(f"/api/investigations/{run_id}/materials").json()
        assert all_materials["total"] == len(report["sources"])
        assert len(all_materials["materials"]) == all_materials["total"]
        assert all_materials["snapshot_id"] == snapshot["workbench_revision"]

        issue_id = report["issues"][0]["issue_id"]
        filtered = client.get(f"/api/investigations/{run_id}/materials?issue_id={issue_id}").json()
        assert filtered["total"] <= all_materials["total"]
        assert filtered["issue_id"] == issue_id

        paged = client.get(f"/api/investigations/{run_id}/materials?limit=1&offset=1").json()
        assert paged["limit"] == 1 and paged["offset"] == 1 and len(paged["materials"]) == min(1, paged["total"] - 1)

        unknown = client.get(f"/api/investigations/{run_id}/materials?issue_id={'x' * 32}")
        assert unknown.status_code == 409
        bad_page = client.get(f"/api/investigations/{run_id}/materials?limit=-3")
        assert bad_page.status_code == 400


def test_static_assets_and_legacy_route(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        page = client.get("/")
        assert page.status_code == 200 and "/assets/app.js" in page.text
        script = client.get("/assets/app.js")
        assert script.status_code == 200
        assert script.headers["content-type"].startswith("text/javascript")
        style = client.get("/assets/style.css")
        assert style.status_code == 200
        assert client.get("/assets/../server.py").status_code == 404
        legacy = client.get("/legacy")
        assert legacy.status_code == 200 and "<html" in legacy.text
