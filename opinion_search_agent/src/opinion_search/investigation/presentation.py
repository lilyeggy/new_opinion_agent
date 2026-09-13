"""Deterministic presentation policy for the workbench.

Facets are product content policy, not agent types: the model may only propose
facet names and whitelisted module fields, and module selection below is a pure
function of the confirmed profile and committed findings. Nothing here branches
on concrete event names, hardcodes answers, or lets model output widen the
module whitelist.
"""

from __future__ import annotations

from opinion_search.domain.investigation.models import (
    FACET_MODULE_TYPES,
    MODULE_FACET_FIELDS,
    REQUIRED_MODULE_FIELDS,
    EventProfile,
    PlanProposal,
)

FACET_MODULES = {
    "rule_change": {"module_type": "rule-comparison", "title": "新旧规则对照",
                    "gap": "适用边界、过渡安排或旧规则文本待查；旧规则缺失时保持未知，不补写。"},
    "service_change": {"module_type": "service-availability", "title": "服务可用性",
                       "gap": "受影响服务、时间段、替代安排或恢复进展待查；计划恢复与已经恢复分开。"},
    "billing_remedy": {"module_type": "billing-remedy", "title": "计费与补救",
                       "gap": "计费口径、办理路径、补救范围与时限待查；受理渠道不等于已退费，金额不明不填 0。"},
    "investigation_correction": {"module_type": "investigation-progress", "title": "调查与纠正",
                                 "gap": "已采取行动、结果与承诺待查；启动调查、作出结论与措施落地区分。"},
}
HIGHLIGHT_LIMIT = 3

FACET_ISSUE_TERMS = {
    "rule_change": ("规则", "新规", "标准", "上限", "生效", "实施", "适用", "调整", "提前", "延长"),
    "service_change": ("停运", "停用", "恢复", "关闭", "暂停", "班次", "服务", "时段", "替代"),
    "billing_remedy": ("计费", "费用", "收费", "水费", "水价", "票价", "退费", "退还",
                       "账单", "补缴", "复核", "缴费", "办理"),
    "investigation_correction": ("调查", "整改", "处置", "问责", "纠正", "更正", "承诺", "结果", "进展"),
}

MODULE_TERMS = {
    "rule-comparison": FACET_ISSUE_TERMS["rule_change"],
    "service-availability": FACET_ISSUE_TERMS["service_change"],
    "billing-remedy": FACET_ISSUE_TERMS["billing_remedy"],
    "investigation-progress": FACET_ISSUE_TERMS["investigation_correction"],
}


def confirmed_profile(plan: PlanProposal, issues) -> EventProfile | None:
    """Program-side confirmation of a model-proposed facet suggestion.

    Unknown facet names are dropped so a stray model value can never widen the
    whitelist; user questions are untouched by this confirmation. Explicit
    question references are derived from issue wording, not model prose, so a
    later module cannot pull in every finding in the event by default.
    """

    facets = tuple(dict.fromkeys(f for f in getattr(plan, "facets", ()) or () if f in FACET_MODULES))
    if not facets or "general" in facets and len(facets) == 1:
        return None
    question_refs = []
    for issue in issues:
        question = getattr(issue, "question", "")
        if any(any(term in question for term in FACET_ISSUE_TERMS.get(facet, ())) for facet in facets):
            question_refs.append(issue.issue_id)
    return EventProfile(facets=facets, rationale=getattr(plan, "facet_rationale", "") or "",
                        question_refs=tuple(question_refs), config_version="workbench-modules-1")


def _finding_module_fields(finding: dict, module_type: str) -> list[dict]:
    return [field for field in finding.get("module_fields") or ()
            if field.get("module") == module_type]


def _text_matches_module(text: str, module_type: str) -> bool:
    return any(term in text for term in MODULE_TERMS.get(module_type, ()))


def _finding_is_relevant(finding: dict, module_type: str, issue_id: str, question_refs: tuple[str, ...]) -> bool:
    """A module only shows findings that either carry its structured fields or
    discuss its specific subject. Generic event facts never fill a facet card.
    """

    if _finding_module_fields(finding, module_type):
        return True
    if not _text_matches_module(finding.get("text", ""), module_type):
        return False
    if question_refs and issue_id not in question_refs:
        return False
    return True


def _facet_items(profile: EventProfile, module_type: str, findings_by_issue: dict) -> list[dict]:
    question_refs = tuple(profile.question_refs or ())
    items = []
    for issue_id, entry in findings_by_issue.items():
        shown = []
        for finding in entry["findings"]:
            if not finding.get("active", True):
                continue
            if not _finding_is_relevant(finding, module_type, issue_id, question_refs):
                continue
            shown.append({
                "finding_id": finding["finding_id"], "text": finding["text"],
                "kind": finding.get("kind", ""), "stakeholder": finding.get("stakeholder", ""),
                "review": finding.get("support", "unreviewed"),
                "citation_ids": list(finding.get("evidence_ids", [])),
                "module_fields": list(finding.get("module_fields", [])),
            })
        if shown:
            items.append({"issue_id": issue_id, "question": entry["question"], "findings": shown})
    return items


def _facet_fields(module_type: str, findings: list[dict]) -> tuple[list[dict], list[str], list[str], bool]:
    """Return fields, missing required labels, conflict labels and review state."""

    entries: dict[str, list[tuple[str, dict]]] = {}
    reviews_ok = True
    for finding in findings:
        if finding.get("support", finding.get("review", "unreviewed")) != "supported":
            reviews_ok = False
        for module_field in _finding_module_fields(finding, module_type):
            key = module_field.get("field", "")
            value = (module_field.get("value") or "").strip()
            if not value or key not in MODULE_FACET_FIELDS.get(module_type, {}):
                continue
            entries.setdefault(key, []).append((value, finding))

    fields, missing, conflicts = [], [], []
    for key, label in MODULE_FACET_FIELDS[module_type].items():
        rows = entries.get(key, [])
        if not rows:
            fields.append({"key": key, "label": label, "state": "unknown", "values": []})
            if key in REQUIRED_MODULE_FIELDS.get(module_type, ()):
                missing.append(label)
            continue
        unique_values = list(dict.fromkeys(value for value, _ in rows))
        citations = []
        for _, finding in rows:
            for evidence_id in finding.get("citation_ids", finding.get("evidence_ids", [])):
                if evidence_id not in citations:
                    citations.append(evidence_id)
        if len(unique_values) > 1:
            fields.append({"key": key, "label": label, "state": "conflict",
                           "values": unique_values, "citations": citations})
            conflicts.append(label)
        else:
            fields.append({"key": key, "label": label, "state": "known",
                           "value": unique_values[0], "values": unique_values, "citations": citations})
    return fields, missing, conflicts, reviews_ok


def facet_modules(profile: EventProfile, findings_by_issue: dict, *, terminal: bool) -> list[dict]:
    """Candidate modules for confirmed facets with availability states.

    A module is ``ready`` only when its required structured fields are present,
    the values come from relevant reviewed findings, and the result is terminal.
    During a run it is ``provisional``; missing fields or unreviewed findings
    never become a publishable card.
    """

    modules = []
    for facet in profile.facets:
        spec = FACET_MODULES.get(facet)
        if spec is None:
            continue
        module_type = spec["module_type"]
        items = _facet_items(profile, module_type, findings_by_issue)
        findings = [finding for item in items for finding in item["findings"]]
        fields, missing, conflicts, reviews_ok = _facet_fields(module_type, findings)
        has_fields = any(any(_finding_module_fields(finding, module_type) for finding in item["findings"])
                         for item in items)

        if not items:
            state, gap = "insufficient", spec["gap"]
        elif terminal and conflicts:
            state, gap = "insufficient", "字段存在冲突：" + "、".join(conflicts) + "；未用一侧说法填充。"
        elif terminal and missing:
            state, gap = "insufficient", "缺少专项字段：" + "、".join(missing) + "；未用通用摘录填充。"
        elif terminal and not has_fields:
            state, gap = "insufficient", "尚未形成专项字段；未用通用摘录填充。"
        elif terminal and not reviews_ok:
            state, gap = "provisional", "专项字段所依据的判断尚未全部通过证据核查，暂不标为可查看。"
        elif terminal:
            state, gap = "ready", None
        elif has_fields:
            state, gap = "provisional", None if not missing and not conflicts else "专项字段仍待补齐或消除冲突。"
        else:
            state, gap = "provisional", "专项字段仍待从已提交材料中形成。"

        modules.append({
            "module_type": module_type, "title": spec["title"], "facet": True, "state": state,
            "gap": gap,
            "selection_rationale": (f"事件侧重点 {facet}：" + (profile.rationale or "由调查计划确认并经程序校验。")
                                    + f" 命中 {len(items)} 个相关问题的专项字段。"),
            "fields": fields,
            "items": items,
        })
    return modules


def highlights(modules: list[dict]) -> list[dict]:
    """Overview picks at most a few business modules; the rest stay in views."""

    facet_only = [m for m in modules if m.get("facet")]
    ordered = [m for m in facet_only if m["state"] in {"ready", "provisional"}] + \
              [m for m in facet_only if m["state"] not in {"ready", "provisional"}]
    return ordered[:HIGHLIGHT_LIMIT]
