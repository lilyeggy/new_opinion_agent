from __future__ import annotations

from opinion_search.domain.investigation.models import State, accepted_review
from opinion_search.domain.opinion.brief import _escape_markdown, _safe_markdown_destination

LABELS = {
    "open": "待调查", "answered": "已有材料回答", "disputed": "证据存在分歧", "not_found": "范围内未发现", "unavailable": "无法判断",
    "direct": "直接回答", "partial": "部分回答", "non_substantive": "涉及但未实质回答", "unknown": "无法判断",
    "supported": "引用支持", "contradicted": "与引用矛盾", "insufficient": "证据不足", "unreviewed": "尚未完成核查",
    "completed": "调查完成", "failed": "调查失败", "cancelled": "已取消",
    "added": "新增判断", "revised": "修订判断", "withdrawn": "撤回判断", "strengthened": "支持加强", "weakened": "支持减弱",
    "unchanged": "判断未变", "evidence_added": "补充依据", "pending_reevaluation": "尚未重新评估",
}


def _classify(before, after, *, known_before, retired_ids):
    """Classify how one issue's findings changed between two published versions."""

    before_text = {f["text"] for f in before}
    after_text = {f["text"] for f in after}
    old_support = bool(before) and all(f["support"] == "supported" for f in before)
    new_support = bool(after) and all(f["support"] == "supported" for f in after)
    withdrawn = bool(before) and not after and all(f["finding_id"] in retired_ids for f in before)
    if not known_before:
        return "added"
    if withdrawn:
        return "withdrawn"
    if before and not after:
        return "pending_reevaluation"
    if new_support and not old_support:
        return "strengthened"
    if old_support and not new_support:
        return "weakened"
    if before_text != after_text:
        return "revised"
    if {i for f in before for i in f["evidence_ids"]} != {i for f in after for i in f["evidence_ids"]}:
        return "evidence_added"
    return "unchanged"


def _retired_map(report) -> dict:
    return {item["finding_id"]: item.get("reason", "") for item in report.get("retired", [])}


def diff_reports(current, base):
    """Compare two published report projections of the same case."""

    previous = {q["issue_id"] for q in base["issues"]}
    retired = _retired_map(current)
    changes = []
    for issue in current["issues"]:
        before = [f for f in base["findings"] if f["issue_id"] == issue["issue_id"]]
        after = [f for f in current["findings"] if f["issue_id"] == issue["issue_id"]]
        kind = _classify(before, after, known_before=issue["issue_id"] in previous, retired_ids=set(retired))
        changes.append({"issue_id": issue["issue_id"], "question": issue["question"], "kind": kind,
                        "before": before, "after": after,
                        "retired_reasons": {f["finding_id"]: retired[f["finding_id"]] for f in before if f["finding_id"] in retired}})
    return changes


def build_report(state: State, status: str, reason: str, *, case_id, run_id, parent_id=None, parent=None, mode="live", budget=None, scope_notes=()):
    findings = []
    for finding in state.findings:
        if not finding.active:
            continue
        review = accepted_review(state, finding)
        findings.append({**finding.model_dump(mode="json"), "review": review.model_dump(mode="json") if review else None, "support": review.verdict if review else "unreviewed"})
    old_sources = {s["version_id"] for s in parent.get("sources", [])} if parent else set()
    old_cutoff = parent.get("cutoff") if parent else None
    sources = []
    for source in state.sources:
        if source.version_id in old_sources:
            classification = "existing"
        elif not parent:
            classification = "initial"
        elif any(s["url"] == source.url for s in parent.get("sources", [])):
            classification = "changed_page"
        elif source.published_at is None:
            classification = "publication_unknown"
        else:
            from datetime import datetime
            classification = "new_publication" if source.published_at.replace(tzinfo=source.published_at.tzinfo or state.cutoff.tzinfo) > datetime.fromisoformat(old_cutoff) else "newly_found_old_material"
        # ``relation`` keeps duplication observable without claiming independence:
        # a saved source with no dependency marker is "unverified", never proven
        # independent, so raw saved counts must not back independence statistics.
        # A model-proposed relation is shown as proposed, not as verified truth.
        proposal = next((relation for relation in state.relations
                         if relation.source_version_id == source.version_id), None)
        if proposal is not None:
            relation = proposal.relation
            relation_status = "model_proposed"
        elif source.duplicate_of:
            relation = "duplicate"
            relation_status = "program_hash_duplicate"
        else:
            relation = "unverified"
            relation_status = "unverified"
        sources.append({**source.model_dump(mode="json"), "discovery": classification, "relation": relation,
                        "relation_status": relation_status,
                        "relation_evidence_ids": list(proposal.basis_evidence_ids) if proposal else [],
                        "relation_explanation": proposal.explanation if proposal else "",
                        "independent": source.duplicate_of is None and proposal is None})
    relation_counts = {
        "document_count": len({s["url"] for s in sources}),
        "version_count": len(sources),
        "identified_duplicate_count": sum(1 for s in sources if s["relation"] in {"duplicate", "same_text"}),
        "unverified_relation_count": sum(1 for s in sources if s["relation"] == "unverified"),
        "repost_count": sum(1 for s in sources if s["relation"] == "repost"),
        "excerpt_count": sum(1 for s in sources if s["relation"] == "excerpt"),
        "followup_count": sum(1 for s in sources if s["relation"] == "followup"),
        "model_relation_count": sum(1 for s in sources if s["relation_status"] == "model_proposed"),
    }
    changes = []
    retired_ids = {r.finding_id for r in state.retired}
    retired_reasons = {r.finding_id: r.reason for r in state.retired}
    if parent:
        previous = {q["issue_id"] for q in parent["issues"]}
        for issue in state.issues:
            before = [f for f in parent["findings"] if f["issue_id"] == issue.issue_id]
            after = [f for f in findings if f["issue_id"] == issue.issue_id]
            kind = _classify(before, after, known_before=issue.issue_id in previous, retired_ids=retired_ids)
            changes.append({"issue_id": issue.issue_id, "question": issue.question, "kind": kind,
                            "before": before, "after": after,
                            "retired_reasons": {f["finding_id"]: retired_reasons[f["finding_id"]] for f in before if f["finding_id"] in retired_ids}})
    no_change = bool(parent) and bool(changes) and all(c["kind"] == "unchanged" for c in changes) and bool(state.searches) and not any(s.outcome == "error" for s in state.searches) and not state.read_errors and status == "completed"
    report = {
        "schema_version": 2, "case_id": case_id, "run_id": run_id, "parent_id": parent_id,
        "mode": mode, "subject": state.subject, "question": state.request.question,
        "status": status, "stop_reason": reason, "cutoff": state.cutoff.isoformat(),
        "lookup_cutoff": state.cutoff.isoformat(),
        "generated_at": state.cutoff.isoformat(),
        "started_at": None,
        "state_revision": state.revision,
        "profile": state.profile.model_dump(mode="json") if state.profile else None,
        "required_questions": list(state.required_questions),
        "issues": [q.model_dump(mode="json") for q in state.issues], "findings": findings,
        "retired": [r.model_dump(mode="json") for r in state.retired],
        "conclusions": [f for f in findings if f["finding_id"] in state.conclusion_ids and f["support"] == "supported"],
        "sources": sources, "independent_source_count": sum(1 for s in sources if s["independent"]),
        "source_relation_counts": relation_counts,
        "relations": [relation.model_dump(mode="json") for relation in state.relations],
        "evidence": [e.model_dump(mode="json") for e in state.evidence],
        "searches": [s.model_dump(mode="json") for s in state.searches], "read_errors": state.read_errors,
        "checks": [c.model_dump(mode="json") for c in state.checks],
        "search_failures": sum(s.outcome == "error" for s in state.searches),
        "read_failures": len(state.read_errors),
        "changes": changes, "no_material_change": no_change, "budget": budget,
        "scope_limitation": " ".join(("仅分析本次可获得的公开文件与报道，不代表公众整体态度。回应覆盖不等于问题已解决。证据审查是模型辅助判断，不是真值证明。", *scope_notes)),
    }
    return report


def markdown(report):
    esc = _escape_markdown
    lines = [f"# {esc(report['subject'])}", "", f"调查状态：{LABELS.get(report['status'], report['status'])}",
             f"调查开始：{report.get('started_at') or '未知'}",
             f"查找截止：{report.get('lookup_cutoff') or report['cutoff']}",
             f"报告生成：{report.get('generated_at') or report['cutoff']}", ""]
    if report["mode"] == "offline":
        lines.extend(["> 虚构材料演示，不代表真实事件或实时搜索结果。", ""])
    if report.get("search_failures") or report.get("read_failures"):
        lines.extend(["> 注意：本轮存在供应商搜索或读取失败；缺失材料不代表没有新进展。", ""])
    for heading, rows in (("核心回答", report["conclusions"]), ("事件时间线", [f for f in report["findings"] if f["event_time"]])):
        lines += [f"## {heading}", ""]
        lines += [f"- {esc((f.get('event_time') or '') + ' ' + f['text'])} {refs(f['evidence_ids'])}" for f in rows] or ["- 尚无完成核查的结论。"]
    lines += ["", "## 争议与回应", ""]
    for issue in report["issues"]:
        lines += [f"### {esc(issue['question'])}", "", f"{LABELS[issue['status']]}：{esc(issue['note'])}"]
        for f in report["findings"]:
            if f["issue_id"] == issue["issue_id"]:
                response = f"；回应：{LABELS[f['response']]}" if f["response"] else ""
                if f.get("response") in {"direct", "partial", "non_substantive"}:
                    coverage = "覆盖：" + ("、".join(f.get("covered") or []) or "未标注")
                    if f.get("uncovered"):
                        coverage += "；未覆盖：" + "、".join(f["uncovered"])
                    if f.get("coverage_reason"):
                        coverage += f"（{esc(f['coverage_reason'])}）"
                    response += " " + coverage
                lines.append(f"- {esc(f['text'])} [{LABELS[f['support']]}{response}] {refs(f['evidence_ids'])}")
    if report["changes"]:
        lines += ["", "## 版本变化", ""]
        lines += [f"- {esc(c['question'])}：{LABELS[c['kind']]}" for c in report["changes"]]
    lines += ["", "## 来源与证据", ""]
    if report.get("checks"):
        lines += ["### 本轮来源复查记录", ""]
        lines += [f"- {c['checked_at']} 复查 {c['url']} → 版本 {c['version_id']}" + ("（正文已变化，新增版本）" if c["changed"] else "（正文未变）") for c in report["checks"]]
        lines += [""]
    sources = {s["version_id"]: s for s in report["sources"]}
    for e in report["evidence"]:
        s = sources[e["version_id"]]
        duplicate = "；与已有版本正文重复，不作为独立证据" if not s.get("independent", True) else ""
        lines += [f"- **{e['evidence_id']}**：{esc(e['excerpt'])}", f"  来源：[{esc(s['title'])}]({_safe_markdown_destination(s['final_url'])})；{esc(e['locator'])}；获取时间 {s['fetched_at']}{duplicate}"]
    lines += ["", "## 调查限制", "", report["scope_limitation"]]
    return "\n".join(lines) + "\n"


def refs(ids):
    return " ".join(f"[{i}]" for i in ids)
