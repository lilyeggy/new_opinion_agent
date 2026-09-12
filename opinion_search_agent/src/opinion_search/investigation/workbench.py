"""Pure projection from a published report to the workbench snapshot.

The workbench never re-parses Markdown and never mutates domain state: it reads
the committed report projection and lays out whitelisted modules with explicit
availability states. Everything here is deterministic so a given report always
yields the same ``snapshot_id`` and the same module ordering.
"""

from __future__ import annotations

import json
import re

from opinion_search.domain.investigation.models import uid
from opinion_search.investigation import metrics
from opinion_search.investigation.presentation import facet_modules, highlights

FORMAT = "opinion-workbench/1"
MODULE_STATES = ("ready", "provisional", "insufficient", "unavailable", "not_applicable")
TERMINAL_STATES = {"completed", "partial", "failed", "cancelled"}

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def workbench_revision(report) -> str:
    """Cheap, deterministic reference so SSE clients can detect new snapshots."""

    return uid("workbench", report["run_id"], report["cutoff"], str(report.get("state_revision", "")))


def build_workbench(report) -> dict:
    report_json = json.dumps(report, ensure_ascii=False, sort_keys=True)
    sources = report.get("sources", [])
    evidence = report.get("evidence", [])
    findings = [f for f in report.get("findings", []) if f.get("active", True)]
    issues = report.get("issues", [])
    terminal = report["status"] in TERMINAL_STATES
    citations = {
        item["evidence_id"]: {"index": index + 1, "label": f"引{index + 1}",
                              "source_title": _source_title(sources, item["version_id"]),
                              "version_id": item["version_id"]}
        for index, item in enumerate(evidence)
    }
    timeline = _timeline(findings)
    distribution = metrics.publication_distribution(sources)
    involvement = {entry["issue_id"]: entry for entry in metrics.issue_involvement(sources, evidence, findings, issues)}
    modules = [
        _module("current-judgments", bool(report.get("conclusions")),
                "尚无可核查的核心判断。", terminal=terminal),
        _module("event-timeline", bool(timeline["events"]),
                "本轮材料中没有可定位的事件时间。", terminal=terminal),
        _module("publication-distribution", distribution is not None,
                "缺少可靠发布日期，不绘制材料发布时间分布。", terminal=terminal),
        _module("coverage-comparison", bool(sources),
                "本轮没有可展示的公开材料。", terminal=terminal),
        _module("issues-review", bool(issues),
                "尚未形成可展示的调查问题。", terminal=terminal),
    ]
    profile = report.get("profile")
    if profile and profile.get("facets"):
        findings_by_issue = {issue["issue_id"]: {"question": issue["question"], "findings":
                             [f for f in report.get("findings", []) if f["issue_id"] == issue["issue_id"]]}
                             for issue in issues}
        modules.extend(facet_modules(_Profile(**profile), findings_by_issue, terminal=terminal))
    overview = {
        "subject": report["subject"],
        "question": report["question"],
        "mode": report.get("mode", "live"),
        "required_questions": list(report.get("required_questions", [])),
        "judgments": [
            {"finding_id": f["finding_id"], "text": f["text"],
             "review": f.get("support", "unreviewed"),
             "citation_ids": list(f.get("evidence_ids", []))}
            for f in report.get("conclusions", [])
        ],
        "timeline": timeline,
        "publication_distribution": distribution,
        "source_relation_counts": report.get("source_relation_counts", {}),
        "highlights": highlights(modules),
    }
    return {
        "format": FORMAT,
        "snapshot_id": workbench_revision(report),
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "parent_id": report.get("parent_id"),
        "generated_at": report["cutoff"],
        "publication_state": report["status"],
        "profile": profile if profile else {"facets": ["general"], "config_version": "workbench-modules-1",
                                            "rationale": "未确认事件侧重点，使用通用视图。"},
        "limitations": {
            "stop_reason": report.get("stop_reason", ""),
            "scope_limitation": report.get("scope_limitation", ""),
            "search_failures": report.get("search_failures", 0),
            "read_failures": report.get("read_failures", 0),
            "no_material_change": bool(report.get("no_material_change")),
        },
        "citations": citations,
        "modules": modules,
        "views": {
            "overview": overview,
            "coverage": {
                "materials": _materials(sources, evidence),
                "known_date_count": sum(1 for s in sources if s.get("published_at")),
                "unknown_date_count": sum(1 for s in sources if not s.get("published_at")),
                "search_coverage": _search_coverage(report.get("searches", []), issues),
            },
            "issues": {
                "issues": [
                    {"issue_id": issue["issue_id"], "question": issue["question"],
                     "status": issue["status"], "note": issue.get("note", ""),
                     "origin_questions": list(issue.get("origin_questions", [])),
                     "involved_materials": _involvement(involvement, issue["issue_id"]),
                     "findings": [
                         {"finding_id": f["finding_id"], "text": f["text"], "kind": f["kind"],
                          "stakeholder": f.get("stakeholder", ""), "stance": f.get("stance", "unclear"),
                          "stance_target": f.get("stance_target", ""), "response": f.get("response"),
                          "covered": list(f.get("covered", [])), "uncovered": list(f.get("uncovered", [])),
                          "coverage_reason": f.get("coverage_reason", ""),
                          "review": f.get("support", "unreviewed"),
                          "citations": {"support": list(f.get("evidence_ids", [])),
                                        "contradict": list(f.get("contradicting_ids", []))}}
                         for f in findings if f["issue_id"] == issue["issue_id"]
                     ]}
                    for issue in issues
                ],
            },
        },
    }


def _source_title(sources, version_id):
    for source in sources:
        if source["version_id"] == version_id:
            return source["title"]
    return "未知来源"


def _module(module_type: str, ready: bool, gap: str | None, *, terminal: bool) -> dict:
    """Availability of a base module; unreviewed in-run data stays provisional."""

    if not ready:
        return {"module_type": module_type, "state": "insufficient",
                "gap": gap or "现有材料不足以呈现该模块。"}
    return {"module_type": module_type, "state": "ready" if terminal else "provisional", "gap": None}


class _Profile:
    """Duck-typed view over a serialised EventProfile for presentation."""

    def __init__(self, facets=None, rationale="", question_refs=None, config_version="", **_):
        self.facets = tuple(facets or ())
        self.rationale = rationale
        self.question_refs = tuple(question_refs or ())
        self.config_version = config_version or "workbench-modules-1"


def _timeline(findings):
    """Event nodes keep their declared time; unparsable values are never ordered.

    Timeline order must not be guessed from raw strings: entries whose
    ``event_time`` starts with an ISO date are ordered, everything else is
    listed separately in its original finding order.
    """

    dated, unparsed = [], []
    for finding in findings:
        time_value = finding.get("event_time")
        if not time_value:
            continue
        node = {"event_time": time_value, "text": finding["text"],
                "finding_id": finding["finding_id"], "citation_ids": list(finding.get("evidence_ids", []))}
        (dated if _DATE_PREFIX.match(str(time_value)) else unparsed).append(node)
    return {"events": sorted(dated, key=lambda node: str(node["event_time"])), "unparsed": unparsed}


def _involvement(involvement, issue_id):
    """Per-issue material count bound to the drill-down membership (P4-3)."""

    entry = involvement.get(issue_id)
    if not entry:
        return {"count": 0, "members": [], "members_hash": None, "inclusion": metrics.INVOLVEMENT_INCLUSION}
    return {"count": entry["count"], "members": entry["members"],
            "members_hash": entry["members_hash"], "inclusion": entry["inclusion"]}


def _search_coverage(searches, issues):
    """Per-question coverage of attempted searches — scope, not recall."""

    coverage = {}
    for attempt in searches:
        entry = coverage.setdefault(attempt["issue_id"], {"attempts": 0, "errors": 0, "targeted": 0})
        entry["attempts"] += 1
        entry["errors"] += 1 if attempt["outcome"] == "error" else 0
        entry["targeted"] += 1 if attempt.get("discovery_mode") == "targeted" else 0
    questions = {issue["issue_id"]: issue["question"] for issue in issues}
    return [{"issue_id": issue_id, "question": questions.get(issue_id, issue_id), **entry}
            for issue_id, entry in sorted(coverage.items())]


def _materials(sources, evidence):
    """Coverage view: materials ordered by publication date, unknown last."""

    by_version: dict[str, list[str]] = {}
    for item in evidence:
        by_version.setdefault(item["version_id"], []).append(item["evidence_id"])
    known = [s for s in sources if s.get("published_at")]
    unknown = [s for s in sources if not s.get("published_at")]
    ordered = sorted(known, key=lambda s: str(s["published_at"])) + unknown
    return [
        {"version_id": s["version_id"], "title": s["title"], "url": s["url"], "final_url": s["final_url"],
         "published_at": s.get("published_at"), "updated_at": s.get("updated_at"),
         "fetched_at": s.get("fetched_at"), "role": s.get("role", "unknown"),
         "discovery": s.get("discovery", ""), "relation": s.get("relation", "unverified"),
         "duplicate_of": s.get("duplicate_of"),
         "citation_ids": by_version.get(s["version_id"], [])}
        for s in ordered
    ]
