"""Deterministic artifact fallbacks for terminal runs."""

from __future__ import annotations

from html import escape
from pathlib import Path

from opinion_search.domain.investigation.models import utcnow
from opinion_search.investigation.storage import atomic_json, atomic_text


def write_minimal_dossier(run_root: Path, report: dict) -> None:
    """Write a readable dossier when the presentation contract cannot render."""

    subject = str(report.get("subject") or report.get("question") or "OpinionSearch report")
    status = str(report.get("status") or "failed")
    reason = str(report.get("stop_reason") or "调查未能完成。")
    atomic_json(run_root / "presentation_plan.json", {
        "plan_version": "presentation-plan/1",
        "source_content_revision": int(report.get("state_revision") or 0),
        "report_id": str(report.get("run_id") or "unknown"),
        "subject": subject,
        "status": status,
        "generated_at": str(report.get("generated_at") or utcnow().isoformat()),
        "sections": [],
        "profile": {"fallback": "minimal-dossier"},
        "narrative": None,
    })
    doctype = "<" + chr(33) + "doctype html>"
    atomic_text(run_root / "dossier.html", (
        f"{doctype}<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{escape(subject)}</title></head><body><main>"
        f"<h1>{escape(subject)}</h1><p>状态：{escape(status)}</p>"
        f"<p>{escape(reason)}</p><p>本文件由兜底发布器生成。</p>"
        "</main></body></html>"
    ))
