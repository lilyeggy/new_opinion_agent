"""Normalize a frozen run into a single shape the metrics can consume.

Two domain shapes exist in this repository: the OpinionSearch opinion run
(``claims`` + ``sources`` keyed by ``source_id``) and the investigation run
(``findings`` + ``reviews`` + ``sources`` keyed by ``version_id``). Both are
reduced here to the same :class:`RunBundle`, so every metric is written once.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse whitespace so snapshot offsets survive rendering differences."""
    return _WHITESPACE.sub("", text)


@dataclass(frozen=True)
class Source:
    source_id: str
    url: str
    title: str
    role: str
    material_sha256: str | None
    text: str | None

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower()


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    excerpt: str
    locator: str
    start: int | None
    end: int | None


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    kind: str
    status: str | None
    support_ids: tuple[str, ...]
    contradict_ids: tuple[str, ...]
    review_verdict: str | None


@dataclass(frozen=True)
class RunBundle:
    case_id: str
    domain: str
    run_dir: Path
    sources: tuple[Source, ...]
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    candidates: tuple[tuple[str, str], ...]
    read: tuple[tuple[str, str], ...]
    refs: tuple[tuple[str, tuple[str, ...]], ...]
    report_text: str
    narrative_text: str
    fingerprint: str

    @property
    def candidate_urls(self) -> tuple[str, ...]:
        return tuple(url for url, _ in self.candidates)

    def source_for(self, source_id: str) -> Source | None:
        return next((item for item in self.sources if item.source_id == source_id), None)

    def title_for_url(self, url: str) -> str:
        for candidate_url, title in (*self.candidates, *self.read):
            if candidate_url == url:
                return title
        return ""


def _material_index(case: dict[str, Any], root: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Return ``(by_sha256, by_url)`` lookups for a case's frozen snapshots.

    A run's ``content_hash`` is the digest of the text the reader produced, which
    is not always the digest of the snapshot file on disk. Matching by the
    material's URL as well keeps planted material verifiable.
    """
    by_hash: dict[str, Path] = {}
    by_url: dict[str, Path] = {}
    manifest = case.get("materials_manifest")
    if manifest:
        payload = json.loads(_load_text(root / manifest))
        base = (root / manifest).parent
        for item in payload.get("materials", []):
            path = base / item["snapshot_path"]
            if item.get("sha256"):
                by_hash[item["sha256"]] = path
            if item.get("url"):
                by_url[item["url"]] = path
    directory = case.get("materials_dir")
    if directory:
        for path in sorted((root / directory).glob("*.txt")):
            by_hash.setdefault(path.stem, path)
    return by_hash, by_url


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _report_text(run_dir: Path, case: dict[str, Any]) -> tuple[str, str]:
    """Return ``(full_text, narrative_text)``.

    ``narrative_text`` is the judgment layer of the markdown report: everything
    before the raw evidence appendix. A planted number may legitimately appear as
    a quoted excerpt there, so the two scopes must be checked separately.
    """
    parts: list[str] = []
    narrative = ""
    report_md = run_dir / case.get("report_markdown", "report.md")
    if report_md.is_file():
        markdown = _load_text(report_md)
        parts.append(markdown)
        narrative = markdown.split("\n## 来源与证据", 1)[0]
    report_json = run_dir / case.get("report_json", "report.json")
    if report_json.is_file():
        parts.append(json.dumps(json.loads(_load_text(report_json)), ensure_ascii=False))
    if not narrative:
        narrative = "\n".join(parts)
    return "\n".join(parts), narrative


def load_bundle(case: dict[str, Any], root: Path) -> RunBundle:
    """Load one corpus case. ``case`` is a single entry of ``evaluation/corpus.json``."""
    run_dir = root / case["run_dir"]
    checkpoint = json.loads(_load_text(run_dir / "run.json"))
    domain_state: dict[str, Any] = checkpoint["state"]["domain_state"]
    by_hash, by_url = _material_index(case, root)
    domain = case.get("domain") or ("investigation" if "findings" in domain_state else "opinion")

    sources: list[Source] = []
    for raw in domain_state.get("sources", []):
        reference = raw.get("artifact_ref") or ""
        digest = raw.get("content_hash") or (reference.rsplit("/", 1)[-1] if reference else None)
        path = by_url.get(raw.get("url") or "") or by_url.get(raw.get("final_url") or "")
        if path is None and digest:
            path = by_hash.get(digest)
        if path is None and digest:
            local = run_dir / "artifacts" / f"{digest}.txt"
            path = local if local.is_file() else None
        sources.append(Source(
            source_id=raw.get("source_id") or raw.get("version_id") or raw["url"],
            url=raw.get("final_url") or raw["url"],
            title=raw.get("title") or "",
            role=raw.get("source_kind") or raw.get("role") or "",
            material_sha256=digest,
            text=_load_text(path) if path is not None else None,
        ))

    evidence: list[Evidence] = []
    for raw in domain_state.get("evidence", []):
        evidence.append(Evidence(
            evidence_id=raw["evidence_id"],
            source_id=raw.get("source_id") or raw.get("version_id") or "",
            excerpt=raw.get("excerpt") or "",
            locator=raw.get("locator") or "",
            start=raw.get("start"),
            end=raw.get("end"),
        ))

    verdicts = {item.get("finding_id"): item.get("verdict") for item in domain_state.get("reviews", [])}
    claims: list[Claim] = []
    if domain == "investigation":
        for raw in domain_state.get("findings", []):
            if raw.get("active") is False:
                continue
            claims.append(Claim(
                claim_id=raw["finding_id"],
                text=raw.get("text") or "",
                kind=raw.get("kind") or "",
                status=None,
                support_ids=tuple(raw.get("evidence_ids") or ()),
                contradict_ids=tuple(raw.get("contradicting_ids") or ()),
                review_verdict=verdicts.get(raw["finding_id"]),
            ))
    else:
        for raw in domain_state.get("claims", []):
            claims.append(Claim(
                claim_id=raw["claim_id"],
                text=raw.get("text") or "",
                kind=raw.get("kind") or "",
                status=raw.get("status"),
                support_ids=tuple(raw.get("supporting_evidence_ids") or ()),
                contradict_ids=tuple(raw.get("contradicting_evidence_ids") or ()),
                review_verdict=None,
            ))

    refs: list[tuple[str, tuple[str, ...]]] = []
    synthesis = domain_state.get("final_synthesis")
    if isinstance(synthesis, dict):
        refs.append(("final_synthesis", tuple(synthesis.get("evidence_ids") or ())))
    for key in ("gaps",):
        for raw in domain_state.get(key, []):
            refs.append((key, tuple(raw.get("evidence_ids") or ())))
    for key in ("narratives", "stakeholder_positions"):
        for raw in domain_state.get(key, []):
            refs.append((key, tuple(raw.get("evidence_ids") or ())))

    candidates = tuple(
        (raw.get("url") or raw.get("final_url") or "", raw.get("title") or "")
        for raw in domain_state.get("candidates", [])
    )
    if domain == "investigation":
        read = tuple((url, "") for url in domain_state.get("read_attempts", []))
    else:
        read = tuple((item.url, item.title) for item in sources)

    report_text, narrative_text = _report_text(run_dir, case)
    return RunBundle(
        case_id=case["case_id"],
        domain=domain,
        run_dir=run_dir,
        sources=tuple(sources),
        evidence=tuple(evidence),
        claims=tuple(claims),
        candidates=candidates,
        read=read,
        refs=tuple(refs),
        report_text=report_text,
        narrative_text=narrative_text,
        fingerprint=sha256((run_dir / "run.json").read_bytes()).hexdigest()[:16],
    )
