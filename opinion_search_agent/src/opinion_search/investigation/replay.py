"""Frozen-material replay harness for fixed-material semantic evaluation.

This is a developer/acceptance utility, not a web product mode. It runs the
normal investigation loop and live model against a local, hash-checked case
manifest, so web discovery can be frozen while content quality is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time

from opinion_search.app.config import LiveConfig
from opinion_search.investigation.manager import Manager
from opinion_search.investigation.service import build_loop
from opinion_search.tools.contracts import ToolAdapterResponse

TERMINAL = {"completed", "partial", "failed", "cancelled"}
ROLES = {"original", "reporting", "commentary", "unknown"}


@dataclass(frozen=True)
class ReplayMaterial:
    url: str
    final_url: str
    title: str
    content: str
    published_at: str | None = None
    updated_at: str | None = None
    role: str = "unknown"


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    request_question: str
    focus: str | None
    materials: tuple[ReplayMaterial, ...]
    clarification_answers: tuple[str, ...] = ()


def _material_content(item: dict, base: Path) -> str:
    content = item.get("content")
    if content is not None:
        return str(content)
    snapshot_path = item.get("snapshot_path")
    if not snapshot_path:
        raise ValueError("a replay material needs content or snapshot_path")
    text = (base / snapshot_path).read_text(encoding="utf-8")
    expected = item.get("sha256")
    if expected and sha256(text.encode("utf-8")).hexdigest() != expected:
        raise ValueError("replay material snapshot hash mismatch")
    return text


def load_replay_case(path: Path) -> ReplayCase:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    materials = []
    for item in data.get("materials", ()):
        role = item.get("role", "unknown")
        if role not in ROLES:
            raise ValueError("replay material has an unknown role")
        materials.append(ReplayMaterial(
            url=str(item["url"]),
            final_url=str(item.get("final_url") or item["url"]),
            title=str(item["title"]),
            content=_material_content(item, path.parent),
            published_at=item.get("published_at"),
            updated_at=item.get("updated_at"),
            role=role,
        ))
    if not materials:
        raise ValueError("a replay case needs at least one material")
    return ReplayCase(
        case_id=str(data.get("case_id") or path.stem),
        request_question=str(data["request_question"]),
        focus=data.get("focus"),
        materials=tuple(materials),
        clarification_answers=tuple(data.get("clarification_answers", ())),
    )


class ReplaySearchAdapter:
    """Return the frozen case materials for every search direction.

    The model still chooses queries, purposes and target gaps; the harness only
    fixes which public documents exist, so a paid web search cannot change the
    replay denominator between runs.
    """

    def __init__(self, case: ReplayCase):
        self.case = case

    async def invoke(self, invocation):
        return ToolAdapterResponse(payload={
            "query": invocation.arguments.query,
            "items": [{"url": material.url, "title": material.title, "snippet": material.content[:120]}
                      for material in self.case.materials],
        })


class ReplayReaderAdapter:
    """Read exactly the frozen text for a URL; no live page can be fetched."""

    def __init__(self, case: ReplayCase):
        self.case = case
        self.by_url = {material.url: material for material in case.materials}

    async def invoke(self, invocation):
        material = self.by_url.get(invocation.arguments.url)
        if material is None:
            raise ValueError("replay reader only serves frozen case URLs")
        return ToolAdapterResponse(payload={
            "url": material.url,
            "final_url": material.final_url,
            "title": material.title,
            "content": material.content,
            "published_at": material.published_at,
            "updated_at": material.updated_at,
        })


def replay_loop_builder(case: ReplayCase):
    """Build a normal investigation loop with frozen-friendly adapters."""

    def builder(run_root: Path, case_root: Path, mode, budget, hook, signal, config=None,
                update=False, fixture="bus"):
        return build_loop(run_root, case_root, mode, budget, hook, signal, config, update,
                          fixture=fixture, search_adapter=ReplaySearchAdapter(case),
                          reader_adapter=ReplayReaderAdapter(case))

    return builder


def run_replay_case(root: Path, case_path: Path, *, config: LiveConfig | None = None,
                    poll_seconds: float = 0.1, timeout_seconds: float = 2400) -> dict:
    """Run one frozen-material case with the configured live model.

    Web search and page reading are replaced by the frozen manifest; the
    planner, decisions, reviewer, evidence checks and report pipeline are the
    production ones. The caller is responsible for model budget and for
    treating a single run as mechanism evidence, not population quality.
    """

    case = load_replay_case(Path(case_path))
    config = config or LiveConfig.from_env()
    manager = Manager(Path(root), config_loader=lambda: config, loop_builder=replay_loop_builder(case))
    payload = {"mode": "live", "question": case.request_question}
    if case.focus:
        payload["focus"] = case.focus
    snapshot = manager.create(payload)
    answers = list(case.clarification_answers)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if snapshot["status"] == "needs_clarification":
            if not answers:
                raise ValueError("frozen replay needs a clarification answer for this request")
            snapshot = manager.clarify(snapshot["run_id"], {"answer": answers.pop(0)})
            continue
        if snapshot["status"] in TERMINAL:
            return snapshot
        time.sleep(poll_seconds)
        snapshot = manager.snapshot(snapshot["run_id"])
    raise TimeoutError("frozen replay did not reach a terminal state within the timeout")
