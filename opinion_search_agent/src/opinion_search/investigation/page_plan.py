"""Deterministic page and investigation plan derived from committed state.

The plan is a shared contract between the investigation loop and presentation.
It is intentionally rebuilt from EventProfile, Issue and Finding records instead
of becoming another mutable authority in the checkpoint.  Models may propose
facets and evidence-bound fields; only this module chooses page sections,
required module slots and search targets.
"""

from __future__ import annotations

import json
from hashlib import sha256

from opinion_search.domain.investigation.models import (
    FACET_MODULE_TYPES,
    MODULE_FACET_FIELDS,
    REQUIRED_MODULE_FIELDS,
)

FORMAT = "opinion-page-plan/1"
POLICY_VERSION = "public-event-framework-1"

FACET_TITLES = {
    "rule_change": "规则与适用影响",
    "service_change": "服务影响与替代安排",
    "billing_remedy": "计费、复核与补救",
    "investigation_correction": "调查、整改与落实",
}

MODULE_TITLES = {
    "rule-comparison": "新旧规则对照",
    "service-availability": "服务可用性",
    "billing-remedy": "计费与补救",
    "investigation-progress": "调查与纠正",
}

FACET_ISSUE_TERMS = {
    "rule_change": ("规则", "新规", "标准", "上限", "生效", "实施", "适用", "调整", "提前", "延长"),
    "service_change": ("停运", "停用", "恢复", "关闭", "暂停", "班次", "服务", "时段", "替代"),
    "billing_remedy": ("计费", "费用", "收费", "水费", "水价", "票价", "退费", "退还",
                       "账单", "补缴", "复核", "缴费", "办理"),
    "investigation_correction": ("调查", "整改", "处置", "问责", "纠正", "更正", "承诺", "结果", "进展"),
}

FIELD_PURPOSES = {
    "old_value": ("original", "independent"),
    "new_value": ("original", "independent"),
    "applies_to": ("original", "independent"),
    "effective_time": ("original", "followup"),
    "transition": ("official_response", "followup"),
    "affected_service": ("original", "independent"),
    "time_window": ("original", "followup"),
    "alternative": ("official_response", "followup"),
    "recovery_status": ("followup", "independent"),
    "billing_basis": ("original", "independent"),
    "scope": ("original", "independent"),
    "handling_path": ("official_response", "original"),
    "deadline": ("official_response", "followup"),
    "remedy_commitment": ("official_response", "followup"),
    "execution_status": ("followup", "independent"),
    "actions_taken": ("official_response", "followup"),
    "results_and_commitments": ("official_response", "followup"),
    "judgment_changes": ("followup", "independent"),
}

# One anchor makes a selected specialty module meaningful. Other fields only
# become required when a linked, user-required issue actually asks for them.
MODULE_ANCHOR_FIELDS = {
    "rule-comparison": ("new_value",),
    "service-availability": ("affected_service",),
    "billing-remedy": ("billing_basis",),
    "investigation-progress": ("actions_taken",),
}

FIELD_REQUIREMENT_TERMS = {
    "rule-comparison": {
        "old_value": ("新旧", "旧规则", "原规则", "调整前", "此前", "之前", "对照"),
        "applies_to": ("适用", "对象", "范围", "人群", "线路", "用户", "谁"),
        "effective_time": ("生效", "实施", "执行", "何时", "时间", "日期", "开始"),
        "transition": ("过渡", "衔接", "临时", "替代"),
    },
    "service-availability": {
        "time_window": ("时间", "时段", "多久", "何时", "期间"),
        "alternative": ("替代", "接驳", "临时安排", "怎么办"),
        "recovery_status": ("恢复", "进展", "现状", "目前", "当前"),
    },
    "billing-remedy": {
        "scope": ("适用", "范围", "对象", "用户", "居民", "谁"),
        "handling_path": ("办理", "申请", "渠道", "路径", "复核", "申诉"),
        "deadline": ("期限", "时限", "多久", "几日", "截止"),
        "remedy_commitment": ("退费", "退款", "退还", "补偿", "整改", "补救"),
        "execution_status": ("到账", "实际执行", "执行情况", "执行结果", "落实", "完成退款", "完成退费"),
    },
    "investigation-progress": {
        "results_and_commitments": ("结果", "结论", "认定", "承诺", "整改"),
        "judgment_changes": ("变化", "修订", "更正", "撤回", "前后", "改变"),
    },
}


def _value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _profile_values(profile) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    if profile is None:
        return ("general",), (), "未确认事件侧重点，使用通用调查框架。"
    facets = tuple(f for f in (_value(profile, "facets", ()) or ()) if f in FACET_MODULE_TYPES)
    return facets or ("general",), tuple(_value(profile, "question_refs", ()) or ()), \
        str(_value(profile, "rationale", "") or "由调查计划确认并经程序校验。")


def _present_fields(findings, issue_ids: tuple[str, ...] = ()) -> dict[str, set[str]]:
    present: dict[str, set[str]] = {}
    allowed = set(issue_ids)
    for finding in findings:
        if not _value(finding, "active", True):
            continue
        if allowed and str(_value(finding, "issue_id", "")) not in allowed:
            continue
        for field in _value(finding, "module_fields", ()) or ():
            module = _value(field, "module", "")
            key = _value(field, "field", "")
            value = str(_value(field, "value", "") or "").strip()
            if module in MODULE_FACET_FIELDS and key in MODULE_FACET_FIELDS[module] and value:
                present.setdefault(module, set()).add(key)
    return present


def _issue_requirement_text(issue) -> str:
    values = [str(_value(issue, "question", "") or "")]
    values.extend(str(_value(component, "text", "") or "")
                  for component in (_value(issue, "components", ()) or ()))
    values.extend(str(item) for item in (_value(issue, "origin_questions", ()) or ()))
    return " ".join(value for value in values if value)


def _required_fields(module_type: str, linked_issues) -> tuple[tuple[str, ...], dict[str, list[str]]]:
    anchors = set(MODULE_ANCHOR_FIELDS.get(module_type, ()))
    basis: dict[str, list[str]] = {field: [] for field in anchors}
    rows = tuple(linked_issues)
    for field in anchors:
        basis[field] = [str(_value(issue, "issue_id", "")) for issue in rows]
    for field, terms in FIELD_REQUIREMENT_TERMS.get(module_type, {}).items():
        matched = [str(_value(issue, "issue_id", "")) for issue in rows
                   if any(term in _issue_requirement_text(issue) for term in terms)]
        if matched:
            basis[field] = matched
    ordered = tuple(field for field in MODULE_FACET_FIELDS[module_type] if field in basis)
    return ordered, {field: basis[field] for field in ordered}


def _facet_issue_ids(facet: str, issues, question_refs: tuple[str, ...], facet_count: int) -> tuple[str, ...]:
    allowed = set(question_refs)
    matched = tuple(
        str(_value(issue, "issue_id", "")) for issue in issues
        if (not allowed or str(_value(issue, "issue_id", "")) in allowed)
        and any(term in str(_value(issue, "question", "")) for term in FACET_ISSUE_TERMS.get(facet, ()))
    )
    # A single confirmed facet may use the confirmation step's broader link
    # when user wording does not contain one of the deterministic terms. With
    # multiple facets, falling back would bind every module to the same issue.
    if not matched and facet_count == 1:
        return tuple(ref for ref in question_refs
                     if any(str(_value(issue, "issue_id", "")) == ref for issue in issues))
    return matched


def build_page_plan(profile, issues, findings=(), *, terminal: bool = False,
                    include_report: bool = False) -> dict:
    """Compile the safe page skeleton and missing module acquisition targets."""

    facets, question_refs, rationale = _profile_values(profile)
    issue_rows = tuple(issues)
    issue_ids = {str(_value(issue, "issue_id", "")) for issue in issue_rows}
    required_issue_ids = {
        str(_value(issue, "issue_id", "")) for issue in issue_rows
        if bool(_value(issue, "required", True))
    }
    linked_ids = tuple(ref for ref in question_refs if ref in issue_ids)
    requirements = []
    targets = []
    facet_count = sum(facet in FACET_MODULE_TYPES for facet in facets)

    for facet in facets:
        module_type = FACET_MODULE_TYPES.get(facet)
        if module_type is None:
            continue
        facet_links = _facet_issue_ids(facet, issue_rows, linked_ids, facet_count)
        linked_required_issues = tuple(issue for issue in issue_rows
                                       if str(_value(issue, "issue_id", "")) in facet_links
                                       and bool(_value(issue, "required", True)))
        required = bool(linked_required_issues)
        required_fields, field_basis = _required_fields(module_type, linked_required_issues)
        if not required_fields:
            required_fields = tuple(MODULE_ANCHOR_FIELDS.get(module_type,
                                                             REQUIRED_MODULE_FIELDS[module_type][:1]))
            field_basis = {field: [] for field in required_fields}
        present = _present_fields(findings, facet_links)
        missing = tuple(field for field in required_fields if field not in present.get(module_type, set()))
        requirement = {
            "facet": facet,
            "module_type": module_type,
            "title": MODULE_TITLES[module_type],
            "required": required,
            "issue_ids": list(facet_links),
            "required_fields": list(required_fields),
            "required_field_basis": field_basis,
            "present_fields": sorted(present.get(module_type, set())),
            "missing_fields": list(missing),
            "state": "ready" if not missing else ("incomplete" if required else "optional_incomplete"),
        }
        requirements.append(requirement)
        if required:
            for field in missing:
                label = MODULE_FACET_FIELDS[module_type][field]
                basis_ids = field_basis.get(field) or [ref for ref in facet_links if ref in required_issue_ids]
                targets.append({
                    "issue_id": basis_ids[0] if basis_ids else "",
                    "basis_issue_ids": basis_ids,
                    "module_type": module_type,
                    "field": field,
                    "label": label,
                    "target_gap": f"{MODULE_TITLES[module_type]}缺少{label}",
                    "suggested_purposes": list(FIELD_PURPOSES.get(field, ("original", "followup"))),
                })

    focus_titles = [FACET_TITLES[facet] for facet in facets if facet in FACET_TITLES]
    focus_title = focus_titles[0] if len(focus_titles) == 1 else "事件专项分析"
    sections = [{
        "section_id": "overview", "view": "overview", "title": "事件总览",
        "purpose": "先呈现当前可核查判断、关键限制、时间线与材料时间分布。",
        "required": True,
        "module_types": ["current-judgments", "event-timeline", "publication-distribution"],
    }]
    if requirements:
        sections.append({
            "section_id": "focus", "view": "focus", "title": focus_title,
            "purpose": "围绕本事件类型展示结构化专项字段，并把缺失内容留为可补查目标。",
            "required": any(item["required"] for item in requirements),
            "module_types": [item["module_type"] for item in requirements],
        })
    sections.extend([
        {"section_id": "issues", "view": "issues", "title": "争议、主张与回应",
         "purpose": "按调查问题组织主体主张、支持或反驳证据以及回应覆盖。",
         "required": True, "module_types": ["issues-review"]},
        {"section_id": "coverage", "view": "coverage", "title": "材料与来源关系",
         "purpose": "核对材料角色、发布时间、重复或转述关系以及实际搜索范围。",
         "required": True, "module_types": ["coverage-comparison"]},
        {"section_id": "citations", "view": "citations", "title": "证据与原文",
         "purpose": "查看正文版本、原文定位和判断支持关系。",
         "required": True, "module_types": []},
        {"section_id": "diagnostics", "view": "diagnostics", "title": "链路诊断",
         "purpose": "暴露调查生产链路中的缺失、失败、审查和预算信号。",
         "required": False, "module_types": []},
    ])
    if include_report:
        sections.append({
            "section_id": "report", "view": "report", "title": "完整报告",
            "purpose": "阅读与当前结构化页面同源的中文 Markdown 报告。",
            "required": False, "module_types": [],
        })

    plan = {
        "format": FORMAT,
        "policy_version": POLICY_VERSION,
        "framework": "public-event-investigation",
        "terminal": terminal,
        "event_facets": list(facets),
        "rationale": rationale,
        "sections": sections,
        "module_requirements": requirements,
        "search_targets": targets,
        "summary": {
            "section_count": len(sections),
            "required_module_count": sum(1 for item in requirements if item["required"]),
            "missing_required_field_count": len(targets),
        },
    }
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["plan_id"] = "page-plan-" + sha256(canonical.encode()).hexdigest()[:20]
    return plan


def required_module_gaps(state) -> tuple[dict, ...]:
    """Return only gaps that are part of a user-required investigation issue."""

    plan = build_page_plan(state.profile, state.issues, state.findings)
    return tuple(plan["search_targets"])
