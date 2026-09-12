"""Deterministic chart metrics for the workbench (implementation plan P4-3).

Every chart ships with its metric definition version, the material-set
reference it was computed from, and the exact members behind each count, so a
click-through can always reproduce the displayed number from the same snapshot.
Values here are program-computed only: the model never writes counts,
percentages or membership.
"""

from __future__ import annotations

from opinion_search.domain.investigation.models import uid

METRIC_DEF_VERSION = "workbench-metrics-1"

DISTRIBUTION_INCLUSION = ("当前材料集中已知发布日期的文档（同 URL 多个正文版本按一个文档计）；"
                          "发布时间未知的单列，不计入柱形。")
INVOLVEMENT_INCLUSION = ("该议题判断引用（支持/反驳）到的正文版本；同一版本在同一议题只计一次，"
                         "同一版本可同时涉及多个议题。")


def material_set_version(sources) -> str:
    """Stable reference for the material set a metric was computed over."""

    return uid("material-set", *(s["version_id"] for s in sorted(sources, key=lambda s: s["version_id"])))


def members_hash(members) -> str:
    return uid("metric-members", *sorted(members))


def publication_distribution(sources) -> dict | None:
    """Document count by known publication date; unknown dates stay separate.

    Multiple body versions of one URL count as one document: each bucket is a
    set of documents with the member version ids bound in, so a click-through
    can list exactly the members behind the displayed count.
    """

    known = [s for s in sources if s.get("published_at")]
    if not known:
        return None
    buckets: dict[str, dict[str, list[str]]] = {}
    for source in known:
        day = str(source["published_at"])[:10]
        by_url = buckets.setdefault(day, {})
        by_url.setdefault(source["url"], []).append(source["version_id"])
    return {
        "metric_def_version": METRIC_DEF_VERSION,
        "material_set_version": material_set_version(sources),
        "inclusion": DISTRIBUTION_INCLUSION,
        "buckets": [{"date": day, "count": len(by_url),
                     "members": [{"url": url, "version_ids": versions} for url, versions in sorted(by_url.items())]}
                    for day, by_url in sorted(buckets.items())],
        "unknown_count": sum(1 for s in sources if not s.get("published_at")),
        "unknown_documents": len({s["url"] for s in sources if not s.get("published_at")}),
    }


def issue_involvement(sources, evidence, findings, issues) -> list[dict]:
    """How many saved materials touch each issue — scope, not stance share.

    Membership mirrors the issue drill-down exactly: a version counts for an
    issue when evidence saved on it is cited (support or contradict) by an
    active finding of that issue, so the displayed count always equals the
    list the issue's materials filter shows. Counts are per-version on
    purpose; the document-level view is the publication distribution.
    """

    version_of_evidence = {e["evidence_id"]: e["version_id"] for e in evidence}
    linked: dict[str, set[str]] = {}
    for finding in findings:
        if not finding.get("active", True):
            continue
        cited = set(finding.get("evidence_ids", [])) | set(finding.get("contradicting_ids", []))
        for evidence_id in cited:
            version_id = version_of_evidence.get(evidence_id)
            if version_id:
                linked.setdefault(finding["issue_id"], set()).add(version_id)
    questions = {issue["issue_id"]: issue["question"] for issue in issues}
    return [
        {"issue_id": issue_id, "question": questions.get(issue_id, issue_id),
         "metric_def_version": METRIC_DEF_VERSION, "material_set_version": material_set_version(sources),
         "inclusion": INVOLVEMENT_INCLUSION,
         "count": len(members), "members": sorted(members), "members_hash": members_hash(members)}
        for issue_id, members in sorted(linked.items())
    ]
