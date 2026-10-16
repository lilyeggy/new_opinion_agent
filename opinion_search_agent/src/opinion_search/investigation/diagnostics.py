"""Deterministic production-chain diagnostics for an investigation run.

The diagnostics explain which part of the investigation pipeline is weak or
unfinished. They intentionally do not emit a quality score: structural checks
cannot prove factual correctness, source representativeness, or user trust.
"""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

from opinion_search.domain.investigation.engine import completion
from opinion_search.domain.investigation.models import SEARCH_DIRECTIONS, State, accepted_review
from opinion_search.investigation.page_plan import required_module_gaps


FORMAT = "opinion-investigation-diagnostics/1"
STAGE_ORDER = ("scope", "discovery", "acquisition", "sources", "evidence", "analysis", "review", "completion", "runtime")
STAGE_LABELS = {
    "scope": "事件与问题", "discovery": "搜索与召回", "acquisition": "正文获取",
    "sources": "来源结构", "evidence": "证据定位", "analysis": "争议与回应分析",
    "review": "关键结论审查", "completion": "结束判断", "runtime": "运行与预算",
}
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
TERMINAL = {"completed", "partial", "failed", "cancelled"}


def _signal(code: str, stage: str, severity: str, message: str, action: str, **details) -> dict:
    return {"code": code, "stage": stage, "severity": severity, "message": message,
            "action": action, "details": details}


def _runtime_metrics(runtime) -> dict:
    if runtime is None:
        return {"available": False, "status": "unavailable", "checkpoint_boundary": None,
                "active_step_phase": None, "committed_steps": 0, "decision_retries": 0,
                "failure_kinds": {}, "actions": {}}
    committed = tuple(getattr(runtime, "committed_steps", ()) or ())
    active = getattr(runtime, "active_step", None)
    all_steps = (*committed, *((active,) if active else ()))
    failures = [failure for step in all_steps for failure in step.failures]
    actions = Counter()
    for step in committed:
        if step.decision is not None:
            actions[str(step.decision.decision.action)] += 1
    status = getattr(runtime, "status", "unknown")
    return {
        "available": True, "status": getattr(status, "value", str(status)), "checkpoint_boundary": None,
        "active_step_phase": getattr(getattr(active, "phase", None), "value", None),
        "committed_steps": len(committed),
        "decision_retries": sum(max(0, step.attempt - 1) for step in all_steps),
        "failure_kinds": dict(sorted(Counter(str(failure.kind.value) for failure in failures).items())),
        "actions": dict(sorted(actions.items())),
        "step_timing_available": False,
        "token_usage_available": False,
    }


def _budget_metrics(budget) -> dict:
    if not budget:
        return {"available": False, "resources": {}}
    limits = budget.get("limits") or {}
    resources = {}
    for key in ("search", "read", "model"):
        used = int(budget.get(key, 0) or 0)
        limit = int(limits.get(key, 0) or 0)
        resources[key] = {"used": used, "limit": limit, "ratio": round(used / limit, 4) if limit else None}
    seconds = float(budget.get("elapsed_seconds", budget.get("accumulated_seconds", 0.0)) or 0.0)
    second_limit = int(limits.get("seconds", 0) or 0)
    resources["seconds"] = {"used": round(seconds, 3), "limit": second_limit,
                            "ratio": round(seconds / second_limit, 4) if second_limit else None}
    return {"available": True, "resources": resources}


def _stage_status(stage: str, signals: list[dict], observed: bool) -> str:
    related = [item for item in signals if item["stage"] == stage]
    if any(item["severity"] == "critical" for item in related):
        return "blocked"
    if any(item["severity"] == "warning" for item in related):
        return "attention"
    return "observed" if observed else "pending"


def build_chain_diagnostics(state: State, *, runtime=None, budget: dict | None = None,
                            publication_status: str = "running", checkpoint_boundary: str | None = None) -> dict:
    """Build one compact, reproducible view of investigation pipeline health."""

    terminal = publication_status in TERMINAL
    active_findings = [item for item in state.findings if item.active]
    accepted = {item.finding_id: accepted_review(state, item) for item in active_findings}
    evidence_by_id = {item.evidence_id: item for item in state.evidence}
    cited_evidence = {identifier for item in active_findings for identifier in (*item.evidence_ids, *item.contradicting_ids)}
    cited_versions = {evidence_by_id[identifier].version_id for identifier in cited_evidence if identifier in evidence_by_id}
    candidate_urls = {str(item.get("url", "")).rstrip("/") for item in state.candidates if item.get("url")}
    attempted_urls = {str(item).rstrip("/") for item in state.read_attempts}
    unread_candidates = sorted(candidate_urls - attempted_urls)
    source_domains = Counter((urlsplit(item.final_url).hostname or "unknown").lower() for item in state.sources)
    source_roles = Counter(item.role for item in state.sources)
    search_outcomes = Counter(item.outcome for item in state.searches)
    search_purposes = Counter(item.purpose for item in state.searches)
    finding_kinds = Counter(item.kind for item in active_findings)
    response_classes = Counter(item.response or "not_assessed" for item in active_findings)
    stakeholders = sorted({item.stakeholder for item in active_findings if item.stakeholder})
    unresolved_issues = [item.issue_id for item in state.issues if item.required and item.status in {"open", "unavailable"}]
    unresolved_components = [{"issue_id": issue.issue_id, "text": component.text, "status": component.status}
                             for issue in state.issues if issue.required for component in issue.components
                             if component.status in {"open", "unavailable"}]
    module_gaps = required_module_gaps(state)
    signals: list[dict] = []

    if unresolved_issues:
        signals.append(_signal("required_issues_unresolved", "scope", "critical" if terminal else "warning",
                               f"{len(unresolved_issues)} 个必答问题仍未得到可用处置。",
                               "继续取证，或明确标为范围内未发现/无法判断。", issue_ids=unresolved_issues))
    if unresolved_components:
        signals.append(_signal("required_components_unresolved", "scope", "critical" if terminal else "warning",
                               f"{len(unresolved_components)} 个必答子项仍未解决。",
                               "逐项处置复合问题，避免父问题状态掩盖缺口。", components=unresolved_components))

    if not state.searches:
        signals.append(_signal("search_not_observed", "discovery", "critical" if terminal else "info",
                               "尚未观察到搜索尝试。", "检查规划器是否进入搜索动作。"))
    if search_outcomes.get("error"):
        signals.append(_signal("search_provider_errors", "discovery", "warning",
                               f"有 {search_outcomes['error']} 次搜索失败，缺失结果不能解释为没有材料。",
                               "核对 provider 错误并尝试其他查询或材料入口。", count=search_outcomes["error"]))
    missing_directions = [direction for direction in SEARCH_DIRECTIONS if direction not in search_purposes]
    if state.searches and missing_directions:
        signals.append(_signal("search_directions_unattempted", "discovery", "info",
                               f"有 {len(missing_directions)} 类调查方向未尝试；这不是固定完成配额。",
                               "根据具体问题判断是否需要补查。", directions=missing_directions))

    if state.read_errors:
        signals.append(_signal("reader_errors", "acquisition", "warning",
                               f"有 {len(state.read_errors)} 个页面读取失败。",
                               "重试、寻找原始出处或将对应结论降级为无法判断。", urls=list(state.read_errors)))
    if unread_candidates:
        signals.append(_signal("unread_candidates", "acquisition", "warning" if terminal else "info",
                               f"仍有 {len(unread_candidates)} 个已发现候选页未读取。",
                               "确认它们无关或重复，或继续读取后再结束。", urls=unread_candidates[:20]))
    if state.read_attempts and not state.sources:
        signals.append(_signal("reads_without_saved_source", "acquisition", "critical" if terminal else "warning",
                               "已有读取尝试，但没有保存可核查正文版本。",
                               "检查 Reader 结果、正文存储和 Processor 提交。"))

    if state.sources and len(source_domains) == 1:
        signals.append(_signal("single_source_domain", "sources", "warning",
                               "全部已保存材料来自同一域名，来源视角可能高度集中。",
                               "补查机构原文、独立报道或其他公开材料。", domains=dict(source_domains)))
    if state.sources and len(source_roles) == 1:
        signals.append(_signal("single_source_role", "sources", "warning",
                               "全部材料属于同一来源角色。", "补充与任务相关的其他来源角色。",
                               roles=dict(source_roles)))
    relation_sources = {version_id for relation in state.relations
                        for version_id in (relation.source_version_id, relation.related_version_id)}
    unverified_relations = sum(item.duplicate_of is None and item.version_id not in relation_sources for item in state.sources)
    if unverified_relations:
        signals.append(_signal("source_independence_unverified", "sources", "warning",
                               f"{unverified_relations} 个正文版本的来源关系尚未核实，不能据此声称独立验证。",
                               "识别原始出处、转载、摘录和后续跟进关系。", count=unverified_relations))
    unknown_dates = sum(item.published_at is None for item in state.sources)
    if unknown_dates:
        signals.append(_signal("publication_dates_unknown", "sources", "info",
                               f"{unknown_dates} 份材料缺少可确认的发布时间。",
                               "保留未知状态，不把 URL 或抓取时间写成发布时间。", count=unknown_dates))

    if terminal and not state.evidence:
        signals.append(_signal("evidence_missing", "evidence", "critical",
                               "终态结果没有可定位证据。", "不得发布事实性结论；检查正文检索与证据提取。"))
    uncited_versions = sorted(item.version_id for item in state.sources if item.version_id not in cited_versions)
    if uncited_versions:
        signals.append(_signal("saved_sources_uncited", "evidence", "info",
                               f"{len(uncited_versions)} 个已保存正文版本未支撑任何当前判断。",
                               "确认其为背景/无关材料，或补充证据绑定。", version_ids=uncited_versions))
    broad_locators = [item.evidence_id for item in state.evidence if len(item.excerpt) > 1200]
    if broad_locators:
        signals.append(_signal("evidence_excerpt_too_broad", "evidence", "warning",
                               f"{len(broad_locators)} 条证据摘录过长，人工核查成本较高。",
                               "重新提取到支持断言的最小段落或句子。", evidence_ids=broad_locators))

    if terminal and not active_findings:
        signals.append(_signal("findings_missing", "analysis", "critical",
                               "终态结果没有当前有效判断。", "继续分析，或将报告明确标记为无材料/无法判断。"))
    if active_findings and len(stakeholders) < 2:
        signals.append(_signal("stakeholder_diversity_low", "analysis", "warning",
                               "当前判断只识别到不足两个明确表达主体，多方观点结构不充分。",
                               "补查受影响主体、机构、独立核查者或专业观点。", stakeholders=stakeholders))
    response_issues = [item for item in state.issues if "回应" in item.question]
    if response_issues and not any(item.response for item in active_findings):
        signals.append(_signal("response_coverage_missing", "analysis", "critical" if terminal else "warning",
                               "调查问题要求分析回应，但当前判断没有回应覆盖分类。",
                               "建立诉求与回应的逐项对应，并保留未覆盖部分。",
                               issue_ids=[item.issue_id for item in response_issues]))
    if module_gaps:
        signals.append(_signal("required_page_modules_incomplete", "analysis",
                               "critical" if terminal else "warning",
                               f"事件专项页面仍缺 {len(module_gaps)} 个必需字段。",
                               "按 PagePlan 的问题与 target_gap 定向补查；材料未说明时保持 partial。",
                               targets=list(module_gaps)))

    unreviewed = [identifier for identifier, review in accepted.items() if review is None]
    rejected = {identifier: review.verdict for identifier, review in accepted.items()
                if review is not None and review.verdict != "supported"}
    if unreviewed:
        signals.append(_signal("active_findings_unreviewed", "review", "critical" if terminal else "warning",
                               f"{len(unreviewed)} 条当前判断没有与其当前文本匹配的审查记录。",
                               "完成独立审查，或从对外核心判断中移除。", finding_ids=unreviewed))
    if rejected:
        signals.append(_signal("active_findings_not_supported", "review", "critical" if terminal else "warning",
                               f"{len(rejected)} 条当前判断未通过支持性审查。",
                               "补取证、降低断言强度或撤回判断。", findings=rejected))

    verdict = completion(state)
    expected_status = ("completed" if verdict.disposition.value == "accept_complete" else
                       "partial" if verdict.disposition.value == "accept_partial" else "running")
    if publication_status == "completed" and expected_status != "completed":
        signals.append(_signal("completion_status_mismatch", "completion", "critical",
                               "发布状态为完成，但当前领域状态不满足完整结束条件。",
                               "阻止 latest-complete 指针更新并检查结束判定。",
                               expected_status=expected_status, reason=verdict.reason))
    if terminal and publication_status != "completed":
        signals.append(_signal("terminal_with_limitations", "completion", "warning" if publication_status == "partial" else "info",
                               f"本轮以 {publication_status} 结束，不能当作完整调查。",
                               "在页面对应位置展示未完成原因。", reason=verdict.reason))

    runtime_metrics = _runtime_metrics(runtime)
    runtime_metrics["checkpoint_boundary"] = checkpoint_boundary
    if not runtime_metrics["available"]:
        signals.append(_signal("runtime_telemetry_unavailable", "runtime", "info",
                               "当前投影没有 Runtime step 遥测。",
                               "生产运行应从 checkpoint 提供 step、重试与失败种类。"))
    elif runtime_metrics["decision_retries"]:
        signals.append(_signal("decision_retries", "runtime", "warning",
                               f"模型决策共发生 {runtime_metrics['decision_retries']} 次重试。",
                               "按失败种类检查提示词、输出契约或模型稳定性。",
                               failure_kinds=runtime_metrics["failure_kinds"]))
    if runtime_metrics["available"]:
        signals.append(_signal("fine_grained_cost_latency_unavailable", "runtime", "info",
                               "StepRecord 尚未保存分步耗时和 token 用量，当前只能定位动作、重试与预算计数。",
                               "后续在 model/tool 边界记录开始结束时间与安全的 usage 元数据。"))

    budget_metrics = _budget_metrics(budget)
    for name, item in budget_metrics["resources"].items():
        ratio = item.get("ratio")
        if ratio is not None and ratio >= 0.9:
            signals.append(_signal(f"budget_{name}_near_limit", "runtime", "warning",
                                   f"{name} 预算已使用 {ratio:.0%}。",
                                   "优先整理、审查并保留未完成边界。", resource=name, **item))

    metrics = {
        "scope": {"issues": len(state.issues), "required": sum(item.required for item in state.issues),
                  "unresolved_required": len(unresolved_issues), "unresolved_components": len(unresolved_components)},
        "discovery": {"attempts": len(state.searches), "outcomes": dict(sorted(search_outcomes.items())),
                      "purposes": dict(sorted(search_purposes.items())), "candidate_urls": len(candidate_urls)},
        "acquisition": {"read_attempts": len(state.read_attempts), "saved_versions": len(state.sources),
                        "read_errors": len(state.read_errors), "unread_candidates": len(unread_candidates)},
        "sources": {"documents": len({item.url for item in state.sources}), "versions": len(state.sources),
                    "domains": dict(sorted(source_domains.items())), "roles": dict(sorted(source_roles.items())),
                    "hash_duplicates": sum(item.duplicate_of is not None for item in state.sources),
                    "relations_recorded": len(state.relations), "relations_unverified": unverified_relations,
                    "unknown_publication_dates": unknown_dates},
        "evidence": {"items": len(state.evidence), "cited_items": len(cited_evidence),
                     "sources_with_cited_evidence": len(cited_versions), "uncited_source_versions": len(uncited_versions)},
        "analysis": {"active_findings": len(active_findings), "finding_kinds": dict(sorted(finding_kinds.items())),
                     "stakeholders": stakeholders, "response_classes": dict(sorted(response_classes.items())),
                     "required_module_gaps": len(module_gaps),
                     "stance_distribution_eligible": False,
                     "stance_distribution_reason": "材料集没有代表性抽样框，来源关系也未全部核实；只能展示材料内主张构成，不能解释为公众观点占比。"},
        "review": {"active_findings": len(active_findings),
                   "supported": sum(review is not None and review.verdict == "supported" for review in accepted.values()),
                   "unreviewed": len(unreviewed), "not_supported": len(rejected),
                   "review_models": dict(sorted(Counter(review.model for review in accepted.values()
                                                        if review is not None).items()))},
        "completion": {"publication_status": publication_status, "policy_disposition": verdict.disposition.value,
                       "policy_reason": verdict.reason, "conclusions": len(state.conclusion_ids)},
        "runtime": {**runtime_metrics, "budget": budget_metrics},
    }
    observed = {
        "scope": bool(state.issues), "discovery": bool(state.searches), "acquisition": bool(state.read_attempts or state.sources),
        "sources": bool(state.sources), "evidence": bool(state.evidence), "analysis": bool(active_findings),
        "review": bool(state.reviews), "completion": terminal, "runtime": runtime_metrics["available"],
    }
    stages = [{"id": stage, "label": STAGE_LABELS[stage], "status": _stage_status(stage, signals, observed[stage]),
               "metrics": metrics[stage], "signal_codes": [item["code"] for item in signals if item["stage"] == stage]}
              for stage in STAGE_ORDER]
    worst = max((SEVERITY_RANK[item["severity"]] for item in signals), default=0)
    summary_status = "blocked" if worst == 2 else "attention" if worst == 1 else "clear"
    return {
        "format": FORMAT,
        "summary": {"status": summary_status,
                    "critical": sum(item["severity"] == "critical" for item in signals),
                    "warnings": sum(item["severity"] == "warning" for item in signals),
                    "informational": sum(item["severity"] == "info" for item in signals),
                    "disclaimer": "这些是确定性的链路完整性信号，不是事实正确率、公众代表性或报告质量分数。"},
        "stages": stages,
        "signals": sorted(signals, key=lambda item: (-SEVERITY_RANK[item["severity"]],
                                                      STAGE_ORDER.index(item["stage"]), item["code"])),
    }


def empty_chain_diagnostics(publication_status: str, reason: str = "", budget: dict | None = None) -> dict:
    """Diagnostics for a run that ended before a domain checkpoint existed."""

    stages = [{"id": stage, "label": STAGE_LABELS[stage],
               "status": "blocked" if stage == "runtime" else "pending", "metrics": {},
               "signal_codes": ["domain_checkpoint_missing"] if stage == "runtime" else []}
              for stage in STAGE_ORDER]
    signal = _signal("domain_checkpoint_missing", "runtime", "critical",
                     "运行在形成可诊断的领域 checkpoint 前结束。",
                     "检查规划、模型配置和首个 checkpoint 写入。",
                     publication_status=publication_status, reason=reason)
    return {
        "format": FORMAT,
        "summary": {"status": "blocked", "critical": 1, "warnings": 0, "informational": 0,
                    "disclaimer": "这些是确定性的链路完整性信号，不是事实正确率、公众代表性或报告质量分数。"},
        "stages": stages, "signals": [signal], "budget": _budget_metrics(budget),
    }
