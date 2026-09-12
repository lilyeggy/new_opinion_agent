"""Shared fixtures for the public-event investigation test suite."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from opinion_search.investigation.manager import Manager

TERMINAL = {"completed", "partial", "failed", "cancelled"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "investigations"


@pytest.fixture
def manager(root: Path) -> Manager:
    return Manager(root)


@pytest.fixture
def wait_for_terminal():
    def wait(manager: Manager, run_id: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        snapshot = manager.snapshot(run_id)
        while snapshot["status"] not in TERMINAL:
            if time.monotonic() > deadline:
                raise AssertionError(f"run {run_id} did not reach a terminal state: {snapshot['status']}")
            time.sleep(0.02)
            snapshot = manager.snapshot(run_id)
        return snapshot

    return wait


@pytest.fixture
def run_offline(wait_for_terminal):
    def run(manager: Manager, payload: dict, timeout: float = 20.0) -> dict:
        snapshot = manager.create({"mode": "offline", **payload})
        return wait_for_terminal(manager, snapshot["run_id"], timeout)

    return run
