"""Pure projection from a published report to the workbench snapshot.

The workbench never re-parses Markdown and never mutates domain state: it reads
the committed report projection and lays out whitelisted modules with explicit
availability states. Everything here is deterministic so a given report always
yields the same ``snapshot_id`` and the same module ordering.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256

from opinion_search.domain.investigation.models import SEARCH_DIRECTIONS, uid
from opinion_search.investigation import metrics
from opinion_search.investigation.presentation import facet_modules, highlights

FORMAT = "opinion-workbench/1"
PROJECTION_VERSION = "workbench-projection-2"
MODULE_STATES = ("ready", "provisional", "insufficient", "unavailable", "not_applicable")
TERMINAL_STATES = {"completed", "partial", "failed", "cancelled"}

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def workbench_revision(report) -> str:
    """Content and projection-policy bound reference for one published view.

    Status, material/evidence content and the projection policy participate in
    the id, so changing a partial to completed or changing projection rules
    produces a different reference instead of silently mutating the old page.
    """

    content_hash = sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return uid("workbench", report["run_id"], report["cutoff"], str(report.get("state_revision", "")),
               report.get("status", ""), FORMAT, PROJECTION_VERSION, content_hash)


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
        "projection_version": PROJECTION_VERSION,
        "snapshot_id": workbench_revision(report),
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "parent_id": report.get("parent_id"),
        "generated_at": report.get("generated_at") or report["cutoff"],
        "started_at": report.get("started_at"),
        "lookup_cutoff": report.get("lookup_cutoff") or report["cutoff"],
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
                "materials": _materials(sources, evidence, report.get("findings", []), issues),
                "known_date_count": sum(1 for s in sources if s.get("published_at")),
                "unknown_date_count": sum(1 for s in sources if not s.get("published_at")),
                "search_coverage": _search_coverage(report.get("searches", []), issues),
            },
            "issues": {
                "issues": [
                    {"issue_id": issue["issue_id"], "question": issue["question"],
                     "status": issue["status"], "note": issue.get("note", ""),
                     "origin_questions": list(issue.get("origin_questions", [])),
                     "components": [dict(component) for component in issue.get("components", [])],
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
    """Per-question coverage of attempted searches — scope, not recall.

    The projection names which search directions were attempted, which were
    never attempted, and which failed without producing a candidate. It does
    not treat direction counts as a completion quota.
    """

    coverage = {
        issue["issue_id"]: {"attempts": 0, "errors": 0, "targeted": 0, "purposes": {},
                            "target_gaps": [], "unattempted_directions": list(SEARCH_DIRECTIONS),
                            "failed_directions": []}
        for issue in issues
    }
    for attempt in searches:
        entry = coverage.setdefault(attempt["issue_id"], {
            "attempts": 0, "errors": 0, "targeted": 0, "purposes": {}, "target_gaps": [],
            "unattempted_directions": list(SEARCH_DIRECTIONS), "failed_directions": []})
        entry["attempts"] += 1
        entry["errors"] += 1 if attempt["outcome"] == "error" else 0
        entry["targeted"] += 1 if attempt.get("discovery_mode") == "targeted" else 0
        purpose = entry["purposes"].setdefault(attempt["purpose"], {"attempts": 0, "errors": 0, "candidates": 0})
        purpose["attempts"] += 1
        purpose["errors"] += 1 if attempt["outcome"] == "error" else 0
        purpose["candidates"] += 1 if attempt["outcome"] == "candidates" else 0
        if attempt.get("target_gap") and attempt["target_gap"] not in entry["target_gaps"]:
            entry["target_gaps"].append(attempt["target_gap"])
    questions = {issue["issue_id"]: issue["question"] for issue in issues}
    result = []
    for issue_id, entry in coverage.items():
        entry["unattempted_directions"] = [p for p in SEARCH_DIRECTIONS if p not in entry["purposes"]]
        entry["failed_directions"] = [p for p, stats in entry["purposes"].items()
                                      if stats["errors"] and not stats["candidates"]]
        result.append({"issue_id": issue_id, "question": questions.get(issue_id, issue_id), **entry})
    return result


def _materials(sources, evidence, findings, issues):
    """Coverage view: materials ordered by publication date, unknown last.

    Material cards carry only program-derived links to committed judgments and
    the cited excerpt as a fallback summary. No new model-authored claim is
    created for the list.
    """

    by_version: dict[str, list[str]] = {}
    by_evidence: dict[str, str] = {}
    for item in evidence:
        by_version.setdefault(item["version_id"], []).append(item["evidence_id"])
        by_evidence[item["evidence_id"]] = item["version_id"]
    issue_questions = {issue["issue_id"]: issue["question"] for issue in issues}
    known = [s for s in sources if s.get("published_at")]
    unknown = [s for s in sources if not s.get("published_at")]
    ordered = sorted(known, key=lambda s: str(s["published_at"])) + unknown
    material_evidence = {item["evidence_id"]: item for item in evidence}
    document_versions: dict[str, int] = {}
    for source in ordered:
        document_versions[source["url"]] = document_versions.get(source["url"], 0) + 1
    result = []
    for source in ordered:
        version_id = source["version_id"]
        citation_ids = by_version.get(version_id, [])
        linked = []
        citation_set = set(citation_ids)
        for finding in findings:
            linked_relations = []
            if set(finding.get("evidence_ids", [])) & citation_set:
                linked_relations.append("support")
            if set(finding.get("contradicting_ids", [])) & citation_set:
                linked_relations.append("contradict")
            for relation in linked_relations:
                linked.append({
                    "finding_id": finding["finding_id"], "text": finding["text"],
                    "kind": finding.get("kind", ""), "stakeholder": finding.get("stakeholder", ""),
                    "issue_id": finding.get("issue_id", ""),
                    "issue_question": issue_questions.get(finding.get("issue_id", ""), ""),
                    "review": finding.get("support", "unreviewed"), "relation": relation,
                    "citation_ids": list(finding.get("evidence_ids", [])),
                })
        unique_linked = list({(item["finding_id"], item["relation"]): item for item in linked}.values())
        summary = unique_linked[0]["text"] if unique_linked else ""
        summary_source = "judgment" if unique_linked else "excerpt"
        if not summary and citation_ids:
            summary = material_evidence.get(citation_ids[0], {}).get("excerpt", "")
        result.append({
            "version_id": version_id, "title": source["title"], "url": source["url"],
            "final_url": source["final_url"], "published_at": source.get("published_at"),
            "updated_at": source.get("updated_at"), "fetched_at": source.get("fetched_at"),
            "role": source.get("role", "unknown"), "discovery": source.get("discovery", ""),
            "relation": source.get("relation", "unverified"),
            "relation_status": source.get("relation_status", "unverified"),
            "relation_evidence_ids": list(source.get("relation_evidence_ids", [])),
            "relation_explanation": source.get("relation_explanation", ""),
            "duplicate_of": source.get("duplicate_of"),
            "document_key": uid("document", source["url"]),
            "document_version_count": document_versions.get(source["url"], 1),
            "citation_ids": citation_ids,
            "summary": summary, "summary_source": summary_source,
            "summary_kind": unique_linked[0].get("kind", "") if unique_linked else "",
            "subjects": list(dict.fromkeys(item["stakeholder"] for item in unique_linked if item["stakeholder"])),
            "issue_questions": list(dict.fromkeys(item["issue_question"] for item in unique_linked if item["issue_question"])),
            "judgments": unique_linked,
        })
    return result
