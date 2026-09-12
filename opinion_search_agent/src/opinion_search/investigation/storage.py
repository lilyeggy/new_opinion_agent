from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from opinion_search.domain.investigation.models import Evidence, SourceVersion, uid
from opinion_search.tools.artifacts import LocalTextArtifactStore


def verify_evidence(evidence: Evidence, content: str) -> None:
    """Fail closed when an excerpt does not match the stored source text."""

    if evidence.end > len(content) or content[evidence.start:evidence.end] != evidence.excerpt:
        raise ValueError("evidence excerpt does not match the stored source text")


async def verify_state_integrity(state, corpus) -> None:
    """Re-verify committed sources and evidence against their immutable artifacts."""

    contents = {}
    for source in state.sources:
        content = await corpus.artifacts.get_text(source.artifact_ref)
        if sha256(content.encode()).hexdigest() != source.content_hash:
            raise ValueError("source content hash does not match its artifact")
        contents[source.version_id] = content
    for evidence in state.evidence:
        content = contents.get(evidence.version_id)
        if content is None:
            raise ValueError("evidence references an unknown source version")
        verify_evidence(evidence, content)


def atomic_json(path: Path, value: object) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class CaseBusy(ValueError):
    pass


class CaseLock:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+")
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.stream.close()
            raise CaseBusy("This event already has an active investigation.") from exc

    def close(self):
        if not self.stream.closed:
            fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()


def terms(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9]+", text.casefold())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(max(0, len(run) - 1)))
    return result


def chunks(text: str):
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        for start in range(match.start(), match.end(), 1000):
            end = min(start + 1200, match.end())
            if terms(text[start:end]):
                yield start, end, text[start:end]


class Corpus:
    """FTS is rebuilt from committed source versions, never an authority."""

    def __init__(self, root: Path):
        self.root = root
        self.artifacts = LocalTextArtifactStore(root / "artifacts")
        self.path = root / "corpus.sqlite3"

    async def retrieve(self, sources: tuple[SourceVersion, ...], query: str, version_id: str | None = None, limit: int = 5) -> tuple[Evidence, ...]:
        selected = [s for s in sources if version_id is None or s.version_id == version_id]
        records = []
        for source in selected:
            content = await self.artifacts.get_text(source.artifact_ref)
            records.extend((source.version_id, a, b, raw, " ".join(terms(raw))) for a, b, raw in chunks(content))
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            return self._search(records, query, limit)
        except sqlite3.DatabaseError:
            self.path.unlink(missing_ok=True)
            return self._search(records, query, limit)

    def _search(self, records, query, limit):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(version UNINDEXED, start UNINDEXED, end UNINDEXED, raw UNINDEXED, tokens)")
            db.execute("DELETE FROM chunks")
            db.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", records)
            tokens = list(dict.fromkeys(terms(query)))[:64]
            if not tokens:
                return ()
            expression = " OR ".join('"' + token + '"' for token in tokens)
            rows = db.execute("SELECT version, start, end, raw FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks), version, CAST(start AS INTEGER) LIMIT ?", (expression, limit)).fetchall()
        return tuple(Evidence(evidence_id=uid("evidence", version, str(a), str(b)), version_id=version, excerpt=raw, start=int(a), end=int(b), locator=f"Reader text chars {a}:{b}") for version, a, b, raw in rows)


class BudgetExceeded(ValueError):
    pass


class Budget:
    def __init__(self, path: Path, limits: dict | None = None):
        self.path = path
        self.limits = {"search": 20, "read": 24, "model": 80, "seconds": 1200, "consolidate_seconds": 900, **(limits or {})}
        if not path.exists():
            atomic_json(path, {"started_at": None, "accumulated_seconds": 0.0, "search": 0, "read": 0, "model": 0, "limits": self.limits})
        self.limits = read_json(path)["limits"]

    @staticmethod
    def _window_seconds(data) -> float:
        started = data.get("started_at")
        if not started:
            return 0.0
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())

    def start(self):
        data = read_json(self.path)
        if data.get("started_at") is None:
            data["started_at"] = datetime.now(timezone.utc).isoformat()
            atomic_json(self.path, data)

    def pause(self):
        """Stop the wall-clock clock without resetting consumed counters.

        Waiting for a user clarification must not consume the active budget, so
        the elapsed window is closed while spent search/read/model counts stay.
        Elapsed time is folded into ``accumulated_seconds`` first, otherwise a
        paused-and-resumed run would get a fresh full window after every pause.
        """

        data = read_json(self.path)
        if data.get("started_at") is not None:
            data["accumulated_seconds"] = data.get("accumulated_seconds", 0.0) + self._window_seconds(data)
            data["started_at"] = None
            atomic_json(self.path, data)

    def snapshot(self):
        data = read_json(self.path)
        data["elapsed_seconds"] = data.get("accumulated_seconds", 0.0) + self._window_seconds(data)
        return data

    def remaining_seconds(self):
        return max(0, self.limits["seconds"] - self.snapshot()["elapsed_seconds"])

    def charge(self, kind):
        data = read_json(self.path)
        if self.remaining_seconds() <= 0 or data[kind] >= self.limits[kind]:
            raise BudgetExceeded(f"{kind} investigation budget exhausted")
        data[kind] += 1
        atomic_json(self.path, data)
