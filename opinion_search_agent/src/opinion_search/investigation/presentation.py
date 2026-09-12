"""Deterministic presentation policy for the workbench.

Facets are product content policy, not agent types: the model may only propose
facet names, and module selection below is a pure function of the confirmed
profile and committed findings. Nothing here branches on concrete event names,
hardcodes answers, or lets model output widen the module whitelist.
"""

from __future__ import annotations

from opinion_search.domain.investigation.models import FACET_NAMES, EventProfile, PlanProposal

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


def confirmed_profile(plan: PlanProposal, issues) -> EventProfile | None:
    """Program-side confirmation of a model-proposed facet suggestion.

    Unknown facet names are dropped so a stray model value can never widen the
    whitelist; user questions are untouched by this confirmation. A plan with
    no usable facets leaves the profile unset, which renders the general view.
    """

    facets = tuple(dict.fromkeys(f for f in getattr(plan, "facets", ()) or () if f in FACET_NAMES))
    if not facets or "general" in facets and len(facets) == 1:
        return None
    return EventProfile(facets=facets, rationale=getattr(plan, "facet_rationale", "") or "",
                        config_version="workbench-modules-1")


def _facet_items(findings_by_issue):
    items = []
    for issue_id, entry in findings_by_issue.items():
        shown = [f for f in entry["findings"] if f.get("active", True)]
        if shown:
            items.append({"issue_id": issue_id, "question": entry["question"],
                          "findings": [{"finding_id": f["finding_id"], "text": f["text"],
                                        "review": f.get("support", "unreviewed"),
                                        "citation_ids": list(f.get("evidence_ids", []))} for f in shown]})
    return items


def facet_modules(profile: EventProfile, findings_by_issue: dict, *, terminal: bool) -> list[dict]:
    """Candidate modules for the confirmed facets with availability states.

    A module is data-backed only when its bound issues already carry active
    findings; otherwise it stays ``insufficient`` with an explicit gap. During
    an active run every data-backed module is ``provisional`` until review.
    """

    modules = []
    for facet in profile.facets:
        spec = FACET_MODULES.get(facet)
        if spec is None:
            continue
        items = _facet_items(findings_by_issue)
        state = "insufficient" if not items else ("provisional" if not terminal else "ready")
        modules.append({
            "module_type": spec["module_type"], "title": spec["title"], "facet": True, "state": state,
            "gap": None if items else spec["gap"],
            "selection_rationale": f"事件侧重点 {facet}：" + (profile.rationale or "由调查计划确认并经程序校验。"),
            "items": items,
        })
    return modules


def highlights(modules: list[dict]) -> list[dict]:
    """Overview picks at most a few business modules; the rest stay in views."""

    facet_only = [m for m in modules if m.get("facet")]
    ordered = [m for m in facet_only if m["state"] in {"ready", "provisional"}] + \
              [m for m in facet_only if m["state"] not in {"ready", "provisional"}]
    return ordered[:HIGHLIGHT_LIMIT]
