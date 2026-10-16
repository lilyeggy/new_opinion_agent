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

_STOP_BIGRAMS = frozenset({
    "表示", "目前", "相关", "情况", "进行", "可以", "一个", "我们", "没有",
    "已经", "工作", "通过", "或者", "因为", "所以", "如果", "虽然", "但是",
})
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^\)]*\)")
_URL_RE = re.compile(r"https?://\S+")
_DATA_URI_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;\n”」』]")
_QUOTE_RE = re.compile(r"[“「『\"][^”」』\"]{4,160}[”」』\"]")
_DATE_OR_NUM_RE = re.compile(
    r"(?:\d{4}年|\d{1,2}月\d{1,2}[日号]|\d{4}-\d{1,2}-\d{1,2}|\d+(?:\.\d+)?\s*(?:%|％|元|万元|亿元|人|户|条|件))"
)


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


def _is_noise_chunk(raw: str) -> bool:
    """Reject chunks dominated by Markdown images, bare URLs, or base64 blobs."""

    has_markup_noise = (
        "![" in raw
        or "http://" in raw
        or "https://" in raw
        or "data:image/" in raw
    )
    if not has_markup_noise:
        return False
    cleaned = _DATA_URI_RE.sub("", raw)
    cleaned = _MD_IMAGE_RE.sub("", cleaned)
    cleaned = _URL_RE.sub("", cleaned)
    prose_chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", cleaned)
    if len(prose_chars) < 12:
        return True
    if len(cleaned.strip()) < len(raw.strip()) * 0.25 and len(cjk_chars) < 18:
        return True
    return False


def terms(text: str) -> list[str]:
    cleaned = _DATA_URI_RE.sub(" ", text)
    cleaned = _MD_IMAGE_RE.sub(" ", cleaned)
    cleaned = _URL_RE.sub(" ", cleaned)
    raw_tokens = re.findall(r"[a-z0-9]+", cleaned.casefold())
    cjk_bigrams: list[str] = []
    cjk_trigrams: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", cleaned):
        if len(run) == 1:
            cjk_bigrams.append(run)
        else:
            cjk_bigrams.extend(run[i : i + 2] for i in range(len(run) - 1))
            if len(run) >= 3:
                cjk_trigrams.extend(run[i : i + 3] for i in range(len(run) - 2))
    filtered_bigrams = [bg for bg in cjk_bigrams if bg not in _STOP_BIGRAMS]
    active_bigrams = filtered_bigrams if (filtered_bigrams or raw_tokens or cjk_trigrams) else cjk_bigrams
    return raw_tokens + active_bigrams + cjk_trigrams


def chunks(text: str):
    yielded = False
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        p_start, p_end = match.start(), match.end()
        cursor = p_start
        while cursor < p_end:
            if p_end - cursor <= 1200:
                end = p_end
                next_cursor = p_end
            else:
                max_end = min(cursor + 1200, p_end)
                window = text[cursor + 600 : max_end]
                boundaries = list(_SENTENCE_END_RE.finditer(window))
                if boundaries:
                    end = cursor + 600 + boundaries[-1].end()
                    next_cursor = max(cursor + 200, end - 100)
                else:
                    end = max_end
                    next_cursor = cursor + 1000
            raw = text[cursor:end]
            if not _is_noise_chunk(raw) and terms(raw):
                yielded = True
                yield cursor, end, raw
            cursor = next_cursor
    if not yielded and text.strip():
        for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
            for start in range(match.start(), match.end(), 1000):
                end = min(start + 1200, match.end())
                if terms(text[start:end]):
                    yield start, end, text[start:end]


def _rerank_Bonus(raw: str, query_runs: list[str]) -> float:
    bonus = 0.0
    if _QUOTE_RE.search(raw):
        bonus += 0.85
    if _DATE_OR_NUM_RE.search(raw):
        bonus += 0.55
    for q_run in query_runs:
        if len(q_run) >= 2 and q_run in raw:
            bonus += 0.35
    return bonus


class Corpus:
    """FTS is rebuilt or incrementally updated from committed source versions, never an authority."""

    def __init__(self, root: Path):
        self.root = root
        self.artifacts = LocalTextArtifactStore(root / "artifacts")
        self.path = root / "corpus.sqlite3"

    async def retrieve(self, sources: tuple[SourceVersion, ...], query: str, version_id: str | None = None, limit: int = 5) -> tuple[Evidence, ...]:
        selected = [s for s in sources if version_id is None or s.version_id == version_id]
        if not selected:
            return ()
        self.root.mkdir(parents=True, exist_ok=True)
        by_version: dict[str, list[tuple[str, int, int, str, str]]] = {}
        for source in selected:
            content = await self.artifacts.get_text(source.artifact_ref)
            by_version[source.version_id] = [
                (source.version_id, a, b, raw, " ".join(terms(raw)))
                for a, b, raw in chunks(content)
            ]
        try:
            return self._search(by_version, query, limit)
        except sqlite3.DatabaseError:
            self.path.unlink(missing_ok=True)
            return self._search(by_version, query, limit)

    def _search(
        self,
        by_version: dict[str, list[tuple[str, int, int, str, str]]],
        query: str,
        limit: int,
    ) -> tuple[Evidence, ...]:
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(version, start UNINDEXED, end UNINDEXED, raw UNINDEXED, tokens)")
            db.execute("CREATE TABLE IF NOT EXISTS chunks_meta (version TEXT PRIMARY KEY, chunk_count INTEGER)")
            existing_versions = {
                row[0]
                for row in db.execute("SELECT version FROM chunks_meta").fetchall()
            }
            for ver_id, records in by_version.items():
                if ver_id not in existing_versions:
                    db.execute("DELETE FROM chunks WHERE version = ?", (ver_id,))
                    if records:
                        db.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", records)
                    db.execute("INSERT OR REPLACE INTO chunks_meta VALUES (?, ?)", (ver_id, len(records)))

            tokens = list(dict.fromkeys(terms(query)))[:64]
            if not tokens:
                return ()
            expression = " OR ".join('"' + token + '"' for token in tokens)
            candidate_pool = max(limit * 4, 20)
            rows = db.execute(
                "SELECT version, start, end, raw, bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks), version, CAST(start AS INTEGER) LIMIT ?",
                (expression, candidate_pool),
            ).fetchall()

        target_versions = set(by_version.keys())
        filtered = [r for r in rows if r[0] in target_versions]
        query_runs = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", query.casefold())
        scored = sorted(
            filtered,
            key=lambda r: (
                float(r[4]) - _rerank_Bonus(str(r[3]), query_runs),
                str(r[0]),
                int(r[1]),
            ),
        )[:limit]
        return tuple(
            Evidence(
                evidence_id=uid("evidence", version, str(a), str(b)),
                version_id=version,
                excerpt=raw,
                start=int(a),
                end=int(b),
                locator=f"Reader text chars {a}:{b}",
            )
            for version, a, b, raw, _score in scored
        )


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
