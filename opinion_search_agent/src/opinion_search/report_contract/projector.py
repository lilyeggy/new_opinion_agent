from __future__ import annotations

import re
from typing import Any

from opinion_search.investigation.workbench import build_workbench
from opinion_search.report_contract.contracts import (
    CitationRef,
    ContentDocument,
    ContentModule,
    ContentSection,
    DataShape,
    ModuleContract,
    ModuleState,
    PlannedModule,
    PlannedSection,
    PresentationPlan,
    VisualEncoding,
)
from opinion_search.report_contract.registry import registry_by_type


DATA_SHAPE_TO_VISUAL: dict[DataShape, VisualEncoding] = {
    DataShape.TEXT: VisualEncoding.TEXT,
    DataShape.CARDS: VisualEncoding.CARDS,
    DataShape.TIMELINE: VisualEncoding.TIMELINE,
    DataShape.COMPARISON: VisualEncoding.COMPARISON_TABLE,
    DataShape.MATRIX: VisualEncoding.POSITION_MATRIX,
    DataShape.CATEGORICAL: VisualEncoding.DISTRIBUTION_CHART,
    DataShape.TREND: VisualEncoding.TREND_CHART,
    DataShape.RELATION: VisualEncoding.RELATION_GRAPH,
    DataShape.EVIDENCE: VisualEncoding.EVIDENCE_DRAWER,
    DataShape.ACTION: VisualEncoding.ACTION_CARDS,
}

ROLE_LABELS: dict[str, str] = {
    "official": "官方与监管通报",
    "regulator": "监管与执法机构",
    "media": "媒体报道",
    "party": "当事主体与涉事方",
    "company": "涉事企业与品牌方",
    "expert": "专业人士与学者",
    "netizen": "公众与消费者反馈",
    "platform": "平台与渠道公告",
    "unknown": "其他公开材料",
}

STANCE_LABELS: dict[str, str] = {
    "support": "支持 / 辩护",
    "oppose": "质疑 / 反对",
    "skeptical": "质疑 / 审慎",
    "mixed": "双向 / 折中",
    "neutral": "中立陈述",
    "unclear": "事实核查",
}

RESPONSE_LABELS: dict[str, str] = {
    "direct": "正面实质回应",
    "partial": "部分针对回应",
    "non_substantive": "回避未实质回应",
    "not_found": "尚未公开回应",
}

FACET_TO_SEMANTIC_TYPE: dict[str, str] = {
    "rule-comparison": "claim-matrix",
    "service-availability": "actions-taken",
    "billing-remedy": "official-response",
    "investigation-progress": "actions-taken",
}


def choose_visual(
    contract: ModuleContract,
    data_shape: DataShape,
    preferred_visual: VisualEncoding | None = None,
) -> tuple[VisualEncoding, str]:
    if preferred_visual is not None and preferred_visual in contract.visual_encodings:
        return preferred_visual, f"preferred_visual={preferred_visual.value} is allowed by contract"

    preferred = DATA_SHAPE_TO_VISUAL[data_shape]

    if preferred in contract.visual_encodings:
        return preferred, f"data_shape={data_shape.value}; preferred visual is allowed"

    fallback = contract.fallback_visual
    if fallback in contract.visual_encodings:
        return fallback, f"preferred visual is not allowed; fallback={fallback.value}"

    selected = contract.visual_encodings[0]
    return selected, f"preferred and fallback are not allowed; first allowed visual={selected.value}"


def build_presentation_plan(
    content: ContentDocument,
    registry: dict[str, ModuleContract] | None = None,
) -> PresentationPlan:
    active_registry = registry if registry is not None else registry_by_type()
    planned_sections: list[PlannedSection] = []

    for section in sorted(content.sections, key=lambda item: item.order):
        planned_modules: list[PlannedModule] = []
        for module in section.modules:
            contract = active_registry.get(module.semantic_type)
            if contract is None:
                raise ValueError(f"unknown module semantic_type: {module.semantic_type}")

            selected_visual, reason = choose_visual(
                contract,
                module.data_shape,
                module.preferred_visual,
            )
            planned_modules.append(
                PlannedModule(
                    **module.model_dump(),
                    selected_visual=selected_visual,
                    selection_reason=reason,
                )
            )

        planned_sections.append(
            PlannedSection(
                section_id=section.section_id,
                title=section.title,
                order=section.order,
                view_id=section.view_id,
                view_title=section.view_title,
                modules=tuple(planned_modules),
            )
        )

    return PresentationPlan(
        source_content_revision=content.revision,
        report_id=content.report_id,
        subject=content.subject,
        status=content.status,
        generated_at=content.generated_at,
        sections=tuple(planned_sections),
    )


def _citation_badges(evidence_ids: list[str] | tuple[str, ...], citation_labels: dict[str, str]) -> str:
    badges = [citation_labels[eid] for eid in evidence_ids if eid in citation_labels]
    return " ".join(f"[{badge}]" for badge in dict.fromkeys(badges))


def _citations_for_ids(
    evidence_ids: list[str] | tuple[str, ...],
    citation_refs: dict[str, CitationRef],
) -> tuple[CitationRef, ...]:
    seen: list[CitationRef] = []
    seen_ids: set[str] = set()
    for eid in evidence_ids:
        if eid in citation_refs and eid not in seen_ids:
            seen.append(citation_refs[eid])
            seen_ids.add(eid)
    return tuple(seen)


def _excerpt_for_ids(
    evidence_ids: list[str] | tuple[str, ...],
    citation_refs: dict[str, CitationRef],
) -> str:
    excerpts = [
        f"{citation_refs[eid].label}：{citation_refs[eid].excerpt}"
        for eid in evidence_ids
        if eid in citation_refs and citation_refs[eid].excerpt
    ]
    return " ｜ ".join(excerpts[:2])


def _source_titles_for_ids(
    evidence_ids: list[str] | tuple[str, ...],
    workbench_citations: dict[str, dict[str, Any]],
) -> str:
    titles = [
        f"[{workbench_citations[eid]['label']}] {workbench_citations[eid]['source_title']}"
        for eid in evidence_ids
        if eid in workbench_citations
    ]
    return "；".join(dict.fromkeys(titles))


def _infer_actor_label(finding: dict[str, Any], index: int = 1) -> str:
    explicit = str(finding.get("stakeholder") or "").strip()
    if explicit:
        return explicit
    text = str(finding.get("text") or "").strip()
    if "：" in text:
        prefix = text.split("：", 1)[0].strip()
        prefix = re.sub(r"（[^）]*）|\([^\)]*\)", "", prefix).strip()
        if 2 <= len(prefix) <= 18:
            return prefix
    if finding.get("response"):
        return "当事方 / 官方回应"
    if finding.get("stance") in {"oppose", "skeptical"}:
        return "质疑 / 批评侧"
    if finding.get("stance") == "support":
        return "支持 / 肯定侧"
    return f"核心事实节点 {index}"


def _short_issue_label(question: str) -> str:
    cleaned = re.sub(r"^[0-9一二三四五六七八九十]+[、.．\s]*", "", str(question or "").strip())
    for sep in ("？", "?", "；", ";", "，", "："):
        if sep in cleaned:
            part = cleaned.split(sep, 1)[0].strip()
            if len(part) >= 4:
                cleaned = part
                break
    return cleaned[:22] + ("…" if len(cleaned) > 22 else "")


def _build_facet_content_modules(
    workbench_modules: list[dict[str, Any]],
    citation_labels: dict[str, str],
    citation_refs: dict[str, CitationRef],
) -> list[ContentModule]:
    result: list[ContentModule] = []
    for index, raw_mod in enumerate(workbench_modules):
        if not raw_mod.get("facet"):
            continue
        raw_type = str(raw_mod.get("module_type") or "")
        semantic_type = FACET_TO_SEMANTIC_TYPE.get(raw_type, "claim-matrix")
        state_str = str(raw_mod.get("state") or "insufficient")
        state = ModuleState(state_str) if state_str in ModuleState._value2member_map_ else ModuleState.INSUFFICIENT
        fields = raw_mod.get("fields") or []
        known_fields = [f for f in fields if f.get("state") in {"known", "multiple", "conflict"}]
        raw_items = raw_mod.get("items") or []

        items: list[dict[str, Any]] = []
        module_eids: list[str] = []
        table_cols: tuple[str, ...] = ()

        if known_fields:
            table_cols = ("专项维度", "核查内容", "核查状态", "证据索引")
            state_map = {"known": "已确认", "multiple": "多源并列", "conflict": "存在冲突"}
            for field in known_fields:
                cids = list(field.get("citations") or [])
                module_eids.extend(cids)
                values_text = " ｜ ".join(str(v) for v in (field.get("values") or [field.get("value", "")]) if v)
                items.append({
                    "专项维度": str(field.get("label") or field.get("key") or ""),
                    "核查内容": values_text,
                    "核查状态": state_map.get(str(field.get("state")), "已核查"),
                    "证据索引": _citation_badges(cids, citation_labels) or "—",
                })
        elif raw_items:
            table_cols = ("关联议题", "陈述主体", "核查判断", "证据索引")
            for group in raw_items:
                question = _short_issue_label(str(group.get("question") or ""))
                for f_idx, finding in enumerate(group.get("findings") or [], 1):
                    cids = list(finding.get("citation_ids") or [])
                    module_eids.extend(cids)
                    fid = str(finding.get("finding_id") or "")
                    stakeholder = _infer_actor_label(finding, f_idx)
                    badges = _citation_badges(cids, citation_labels)
                    items.append({
                        "关联议题": question,
                        "陈述主体": stakeholder,
                        "核查判断": str(finding.get("text") or ""),
                        "证据索引": badges or "—",
                        "title": f"{stakeholder} · {question}" if question else stakeholder,
                        "summary": f"{finding.get('text', '')} {badges}".strip(),
                        "detail": _excerpt_for_ids(cids, citation_refs),
                        "_finding_id": fid,
                        "_source_finding_ids": [fid] if fid else [],
                    })

        result.append(
            ContentModule(
                module_id=f"focus-facet-{index + 1}-{raw_type}",
                semantic_type=semantic_type,
                title=str(raw_mod.get("title") or "事件专项核查"),
                state=state,
                data_shape=DataShape.CARDS if len(items) <= 3 else DataShape.COMPARISON,
                preferred_visual=VisualEncoding.CARDS if len(items) <= 3 else VisualEncoding.COMPARISON_TABLE,
                summary=str(raw_mod.get("selection_rationale") or ""),
                table_columns=table_cols if items else (),
                items=tuple(items),
                citations=_citations_for_ids(module_eids, citation_refs),
                empty_reason=str(raw_mod.get("gap") or ""),
                view_id="focus",
            )
        )
    return result


def _build_source_cluster_map(
    sources: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, str]:
    parent: dict[str, str] = {}
    for src in sources:
        vid = str(src.get("version_id") or "")
        if vid:
            parent[vid] = vid

    def _find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for src in sources:
        vid = str(src.get("version_id") or "")
        dup = str(src.get("duplicate_of") or "")
        if vid and dup:
            _union(vid, dup)
    for rel in relations:
        if str(rel.get("relation") or "") in {"same_text", "repost", "excerpt"}:
            v1 = str(rel.get("source_version_id") or "")
            v2 = str(rel.get("related_version_id") or "")
            if v1 and v2:
                _union(v1, v2)
    return {vid: _find(vid) for vid in list(parent)}


def _independent_cluster_count(
    evidence_ids: list[str] | tuple[str, ...],
    citation_refs: dict[str, CitationRef],
    cluster_map: dict[str, str],
) -> int:
    clusters = {
        cluster_map.get(citation_refs[eid].source_version_id, citation_refs[eid].source_version_id)
        for eid in evidence_ids
        if eid in citation_refs and citation_refs[eid].source_version_id
    }
    return max(1, len(clusters)) if evidence_ids else 1


def _anchor_relative_time(
    raw_time: str,
    evidence_ids: list[str] | tuple[str, ...],
    citation_refs: dict[str, CitationRef],
    source_by_version: dict[str, dict[str, Any]],
    fallback_cutoff: str = "",
) -> str:
    from datetime import date, timedelta

    text = str(raw_time or "").strip()
    if not text:
        return "时间待定"
    if re.match(r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", text):
        return text

    anchor: date | None = None
    for eid in evidence_ids:
        cref = citation_refs.get(eid)
        if not cref:
            continue
        src = source_by_version.get(cref.source_version_id) or {}
        pub_str = str(src.get("published_at") or src.get("fetched_at") or "")
        m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", pub_str)
        if m_iso:
            try:
                anchor = date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
                break
            except ValueError:
                pass
    if anchor is None and fallback_cutoff:
        m_cut = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(fallback_cutoff))
        if m_cut:
            try:
                anchor = date(int(m_cut.group(1)), int(m_cut.group(2)), int(m_cut.group(3)))
            except ValueError:
                pass
    if anchor is None:
        return text

    m_md = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})[日号]", text)
    if m_md:
        month, day = int(m_md.group(1)), int(m_md.group(2))
        year = anchor.year if month <= anchor.month + 1 else anchor.year - 1
        try:
            resolved = date(year, month, day).isoformat()
            return f"{resolved}（{text}）"
        except ValueError:
            return text
    if any(k in text for k in ("前日", "前天")):
        return f"{(anchor - timedelta(days=2)).isoformat()}（{text}）"
    if any(k in text for k in ("昨日", "昨天")):
        return f"{(anchor - timedelta(days=1)).isoformat()}（{text}）"
    if any(k in text for k in ("当日", "当天", "今日", "今天")):
        return f"{anchor.isoformat()}（{text}）"
    return text


def _synthesize_focus_modules(
    subject: str,
    issues: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    citation_labels: dict[str, str],
    citation_refs: dict[str, CitationRef],
    terminal: bool,
    cluster_map: dict[str, str] | None = None,
) -> list[ContentModule]:
    issue_questions = {str(i.get("issue_id")): str(i.get("question") or "") for i in issues}
    active_findings = [f for f in findings if f.get("active", True)]
    ready_state = ModuleState.READY if terminal else ModuleState.PROVISIONAL
    active_clusters = cluster_map or {}
    synthesized: list[ContentModule] = []

    # 1. Interactive Stakeholder-Issue-Stance Relation Topology Graph
    if active_findings:
        graph_items: list[dict[str, Any]] = []
        graph_eids: list[str] = []
        for idx, f in enumerate(active_findings, 1):
            eids = list(f.get("evidence_ids") or [])
            graph_eids.extend(eids)
            fid = str(f.get("finding_id") or "")
            actor = _infer_actor_label(f, idx)
            raw_issue = issue_questions.get(str(f.get("issue_id") or ""), "核心争议")
            short_issue = _short_issue_label(raw_issue)
            stance = str(f.get("stance") or "unclear")
            resp = str(f.get("response") or "")
            if resp == "direct":
                relation_label = "正面回应"
            elif resp == "partial":
                relation_label = "冷处理 / 部分回应"
            elif resp == "non_substantive":
                relation_label = "回避质询"
            elif stance in {"oppose", "skeptical"}:
                relation_label = "质疑 / 批评"
            elif stance == "support":
                relation_label = "支持 / 辩护"
            else:
                relation_label = "事实披露"
            badges = _citation_badges(eids, citation_labels)
            indep_weight = _independent_cluster_count(eids, citation_refs, active_clusters)
            graph_items.append({
                "主体": actor,
                "关联议题": short_issue,
                "关系类型": relation_label,
                "立场": STANCE_LABELS.get(stance, stance),
                "核心主张": f"{f.get('text', '')} {badges}".strip(),
                "证据索引": badges or "—",
                "_hub": subject,
                "_actor": actor,
                "_issue": short_issue,
                "_relation": relation_label,
                "_stance": stance,
                "_response": resp,
                "_citation_count": indep_weight,
                "_finding_id": fid,
                "_source_finding_ids": [fid] if fid else [],
            })
        synthesized.append(
            ContentModule(
                module_id="focus-relation-graph",
                semantic_type="stakeholders",
                title="事件主体·议题·立场关系拓扑图",
                state=ready_state,
                data_shape=DataShape.RELATION,
                preferred_visual=VisualEncoding.RELATION_GRAPH,
                summary=f"可视化映射 {len(graph_items)} 组【参与主体 → 争议议题 → 核心事件】的立场传导与证据支撑关系（点击或悬停节点可查看关联证据链）。",
                table_columns=("主体", "关系类型", "关联议题", "核心主张", "证据索引"),
                items=tuple(graph_items),
                citations=_citations_for_ids(graph_eids, citation_refs),
                view_id="focus",
            )
        )

    # 2. Debate / Confrontation Visual Arena (DEBATE_VERSUS)
    debate_rows: list[dict[str, Any]] = []
    debate_eids: list[str] = []
    findings_by_issue: dict[str, list[dict[str, Any]]] = {}
    for f in active_findings:
        findings_by_issue.setdefault(str(f.get("issue_id") or ""), []).append(f)

    for issue_id, issue_findings in findings_by_issue.items():
        question = _short_issue_label(issue_questions.get(issue_id, "核心争议"))
        opposing = [
            f for f in issue_findings
            if f.get("stance") in {"oppose", "skeptical"} or f.get("contradicting_ids")
        ]
        supporting = [
            f for f in issue_findings
            if f.get("stance") in {"support", "mixed", "neutral", "unclear"} and f not in opposing
        ]
        stakeholders = list(dict.fromkeys(_infer_actor_label(f, i + 1) for i, f in enumerate(issue_findings)))
        if opposing and supporting:
            left = opposing[0]
            right = supporting[0]
        elif len(stakeholders) >= 2 and len(issue_findings) >= 2:
            left = issue_findings[0]
            right = next(
                (f for f in issue_findings[1:] if _infer_actor_label(f, 2) != _infer_actor_label(left, 1)),
                issue_findings[1],
            )
        else:
            continue

        left_eids = list(left.get("evidence_ids") or [])
        right_eids = list(right.get("evidence_ids") or [])
        row_eids = left_eids + right_eids
        debate_eids.extend(row_eids)
        left_actor = _infer_actor_label(left, 1)
        right_actor = _infer_actor_label(right, 2)
        left_badges = _citation_badges(left_eids, citation_labels)
        right_badges = _citation_badges(right_eids, citation_labels)
        debate_rows.append({
            "争议焦点": question,
            "质疑与批评主张": f"【{left_actor}】{left.get('text', '')} {left_badges}".strip(),
            "回应与抗辩主张": f"【{right_actor}】{right.get('text', '')} {right_badges}".strip(),
            "证据索引": _citation_badges(row_eids, citation_labels) or "—",
            "_left_actor": left_actor,
            "_left_claim": f"{left.get('text', '')} {left_badges}".strip(),
            "_left_count": _independent_cluster_count(left_eids, citation_refs, active_clusters),
            "_right_actor": right_actor,
            "_right_claim": f"{right.get('text', '')} {right_badges}".strip(),
            "_right_count": _independent_cluster_count(right_eids, citation_refs, active_clusters),
            "_source_finding_ids": [
                str(left.get("finding_id") or ""),
                str(right.get("finding_id") or ""),
            ],
        })

    if not debate_rows:
        cross_opposing = [
            f for f in active_findings
            if f.get("stance") in {"oppose", "skeptical"} or f.get("contradicting_ids")
        ]
        cross_responding = [
            f for f in active_findings
            if f not in cross_opposing and (f.get("response") or f.get("stance") in {"support", "mixed", "unclear"})
        ]
        if cross_opposing and cross_responding:
            left = cross_opposing[0]
            right = cross_responding[0]
            left_eids = list(left.get("evidence_ids") or [])
            right_eids = list(right.get("evidence_ids") or [])
            row_eids = left_eids + right_eids
            debate_eids.extend(row_eids)
            left_actor = _infer_actor_label(left, 1)
            right_actor = _infer_actor_label(right, 2)
            left_badges = _citation_badges(left_eids, citation_labels)
            right_badges = _citation_badges(right_eids, citation_labels)
            debate_rows.append({
                "争议焦点": _short_issue_label(issue_questions.get(str(left.get("issue_id") or ""), "核心争议与回应交锋")),
                "质疑与批评主张": f"【{left_actor}】{left.get('text', '')} {left_badges}".strip(),
                "回应与抗辩主张": f"【{right_actor}】{right.get('text', '')} {right_badges}".strip(),
                "证据索引": _citation_badges(row_eids, citation_labels) or "—",
                "_left_actor": left_actor,
                "_left_claim": f"{left.get('text', '')} {left_badges}".strip(),
                "_left_count": _independent_cluster_count(left_eids, citation_refs, active_clusters),
                "_right_actor": right_actor,
                "_right_claim": f"{right.get('text', '')} {right_badges}".strip(),
                "_right_count": _independent_cluster_count(right_eids, citation_refs, active_clusters),
                "_source_finding_ids": [
                    str(left.get("finding_id") or ""),
                    str(right.get("finding_id") or ""),
                ],
            })

    if debate_rows:
        synthesized.append(
            ContentModule(
                module_id="focus-debate-comparison",
                semantic_type="debate-comparison",
                title="核心争议正反阵营交锋图谱",
                state=ready_state,
                data_shape=DataShape.COMPARISON,
                preferred_visual=VisualEncoding.DEBATE_VERSUS,
                summary=f"提炼 {len(debate_rows)} 组核心矛盾进行正反证据权重对比与要点拆解。",
                table_columns=("争议焦点", "质疑与批评主张", "回应与抗辩主张", "证据索引"),
                items=tuple(debate_rows),
                citations=_citations_for_ids(debate_eids, citation_refs),
                view_id="focus",
            )
        )

    # 3. Stakeholder Stance Swimlane Spectrum (POSITION_MATRIX)
    if len(active_findings) >= 2:
        matrix_rows: list[dict[str, Any]] = []
        matrix_eids: list[str] = []
        for idx, f in enumerate(active_findings, 1):
            eids = list(f.get("evidence_ids") or [])
            matrix_eids.extend(eids)
            fid = str(f.get("finding_id") or "")
            raw_stance = str(f.get("stance") or ("mixed" if f.get("response") else "unclear"))
            stance_label = STANCE_LABELS.get(raw_stance, raw_stance)
            target = str(
                f.get("stance_target")
                or _short_issue_label(issue_questions.get(str(f.get("issue_id") or ""), "事件核心争议"))
            )
            badges = _citation_badges(eids, citation_labels)
            matrix_rows.append({
                "主体": _infer_actor_label(f, idx),
                "立场": stance_label,
                "目标": target,
                "依据": f"{f.get('text', '')} {badges}".strip(),
                "证据索引": badges or "—",
                "_stance_raw": raw_stance,
                "_finding_id": fid,
                "_source_finding_ids": [fid] if fid else [],
            })
        synthesized.append(
            ContentModule(
                module_id="focus-position-matrix",
                semantic_type="position-matrix",
                title="各方主体立场光谱与阵营看板",
                state=ready_state,
                data_shape=DataShape.MATRIX,
                preferred_visual=VisualEncoding.POSITION_MATRIX,
                summary=f"按【质疑批评 / 事实观察 / 支持回应】三大阵营分栏归类 {len(matrix_rows)} 项主体表态。",
                table_columns=("主体", "立场", "目标", "依据", "证据索引"),
                items=tuple(matrix_rows),
                citations=_citations_for_ids(matrix_eids, citation_refs),
                view_id="focus",
            )
        )

    # 4. Response Coverage Scorecard when findings have response assessment
    response_findings = [
        f for f in active_findings
        if f.get("response") or f.get("covered") or f.get("uncovered") or f.get("coverage_reason")
    ]
    if response_findings:
        resp_rows: list[dict[str, Any]] = []
        resp_eids: list[str] = []
        for idx, f in enumerate(response_findings, 1):
            eids = list(f.get("evidence_ids") or [])
            resp_eids.extend(eids)
            fid = str(f.get("finding_id") or "")
            question = _short_issue_label(issue_questions.get(str(f.get("issue_id") or ""), "公众质询要点"))
            stakeholder = _infer_actor_label(f, idx)
            raw_resp = str(f.get("response") or "partial")
            badges = _citation_badges(eids, citation_labels)
            uncovered_list = [str(u) for u in (f.get("uncovered") or []) if u]
            covered_list = [str(c) for c in (f.get("covered") or []) if c]
            reason = str(f.get("coverage_reason") or f.get("text") or "")
            resp_rows.append({
                "问题": f"{question}（{stakeholder}）" if stakeholder else question,
                "回应": RESPONSE_LABELS.get(raw_resp, raw_resp),
                "说明": f"{reason} {badges}".strip(),
                "已覆盖": "；".join(covered_list),
                "未覆盖": "；".join(uncovered_list),
                "证据索引": badges or "—",
                "_covered_list": covered_list,
                "_uncovered_list": uncovered_list,
                "_finding_id": fid,
                "_source_finding_ids": [fid] if fid else [],
            })
        synthesized.append(
            ContentModule(
                module_id="focus-response-coverage",
                semantic_type="response-coverage",
                title="官方与当事方回应覆盖度核查卡",
                state=ready_state,
                data_shape=DataShape.COMPARISON,
                preferred_visual=VisualEncoding.RESPONSE_SCORECARD,
                summary=f"针对 {len(resp_rows)} 项关键质询评估回应实质度、已覆盖要点与未决缺口。",
                table_columns=("问题", "回应", "说明", "未覆盖", "证据索引"),
                items=tuple(resp_rows),
                citations=_citations_for_ids(resp_eids, citation_refs),
                view_id="focus",
            )
        )

    return synthesized


def build_content_document_from_investigation(
    report: dict[str, Any],
    workbench: dict[str, Any] | None = None,
) -> ContentDocument:
    """Project an investigation report and workbench into a visual-first ContentDocument."""

    wb = workbench if workbench is not None else build_workbench(report)
    status = str(report.get("status") or wb.get("publication_state") or "completed")
    terminal = status in {"completed", "partial", "failed", "cancelled"}
    ready_state = ModuleState.READY if terminal else ModuleState.PROVISIONAL

    sources = list(report.get("sources") or [])
    evidence_list = list(report.get("evidence") or [])
    findings = [f for f in (report.get("findings") or []) if f.get("active", True)]
    issues = list(report.get("issues") or [])
    wb_citations: dict[str, dict[str, Any]] = wb.get("citations") or {}

    citation_labels: dict[str, str] = {}
    citation_refs: dict[str, CitationRef] = {}
    source_by_version = {str(s.get("version_id")): s for s in sources}
    for index, ev in enumerate(evidence_list, 1):
        eid = str(ev.get("evidence_id") or f"e-{index}")
        vid = str(ev.get("version_id") or "")
        wb_meta = wb_citations.get(eid) or {}
        short_label = str(wb_meta.get("label") or f"引{index}")
        source_title = str(
            wb_meta.get("source_title")
            or (source_by_version.get(vid) or {}).get("title")
            or "公开来源"
        )
        citation_labels[eid] = short_label
        citation_refs[eid] = CitationRef(
            evidence_id=eid,
            source_version_id=vid,
            label=f"[{short_label}] {source_title}",
            excerpt=str(ev.get("excerpt") or ""),
            locator=str(ev.get("locator") or ""),
        )

    issue_questions = {str(i.get("issue_id")): str(i.get("question") or "") for i in issues}
    findings_by_id = {str(f.get("finding_id")): f for f in findings}
    subject = str(report.get("subject") or wb.get("views", {}).get("overview", {}).get("subject") or "舆情深度调查")

    # --- Section 1: Overview ---
    overview_data = (wb.get("views") or {}).get("overview") or {}
    judgments = list(overview_data.get("judgments") or [])
    judgment_items: list[dict[str, Any]] = []
    judgment_eids: list[str] = []
    for idx, j in enumerate(judgments, 1):
        fid = str(j.get("finding_id") or "")
        f_obj = findings_by_id.get(fid) or {}
        cids = list(j.get("citation_ids") or f_obj.get("evidence_ids") or [])
        judgment_eids.extend(cids)
        stakeholder = _infer_actor_label(f_obj, idx)
        q_title = _short_issue_label(issue_questions.get(str(f_obj.get("issue_id") or ""), ""))
        card_title = f"{stakeholder} · {q_title}" if stakeholder and q_title and stakeholder != q_title else (stakeholder or q_title or f"核心判断 {idx}")
        badges = _citation_badges(cids, citation_labels)
        judgment_items.append({
            "title": card_title,
            "summary": f"{j.get('text', '')} {badges}".strip(),
            "detail": _excerpt_for_ids(cids, citation_refs),
            "meta": _source_titles_for_ids(cids, wb_citations),
            "_review_status": str(j.get("review") or "supported"),
            "_importance": float(len(cids) + (10 - idx)),
            "_finding_id": fid,
            "_source_finding_ids": [fid] if fid else [],
        })

    overview_modules: list[ContentModule] = [
        ContentModule(
            module_id="overview-current-judgments",
            semantic_type="current-judgments",
            title="核心核查研判结论",
            state=ready_state if judgment_items else ModuleState.INSUFFICIENT,
            data_shape=DataShape.CARDS,
            summary=f"基于 {len(sources)} 份公开归档材料与 {len(evidence_list)} 条原文证据交叉核验形成的核心判断。",
            items=tuple(judgment_items),
            citations=_citations_for_ids(judgment_eids, citation_refs),
            empty_reason="" if judgment_items else "尚无通过核查的核心判断。",
            view_id="overview",
        )
    ]

    timeline_data = overview_data.get("timeline") or {}
    timeline_nodes = list(timeline_data.get("events") or []) + list(timeline_data.get("unparsed") or [])
    timeline_items: list[dict[str, Any]] = []
    timeline_eids: list[str] = []
    fallback_cutoff = str(report.get("cutoff") or wb.get("lookup_cutoff") or "")
    for idx, node in enumerate(timeline_nodes, 1):
        fid = str(node.get("finding_id") or "")
        f_obj = findings_by_id.get(fid) or {}
        cids = list(node.get("citation_ids") or f_obj.get("evidence_ids") or [])
        timeline_eids.extend(cids)
        badges = _citation_badges(cids, citation_labels)
        stakeholder = _infer_actor_label(f_obj, idx)
        q_title = _short_issue_label(issue_questions.get(str(f_obj.get("issue_id") or ""), ""))
        anchored_time = _anchor_relative_time(
            str(node.get("event_time") or "时间待定"),
            cids,
            citation_refs,
            source_by_version,
            fallback_cutoff=fallback_cutoff,
        )
        timeline_items.append({
            "time": anchored_time,
            "title": stakeholder or q_title or "关键事件节点",
            "summary": f"{node.get('text', '')} {badges}".strip(),
            "detail": _excerpt_for_ids(cids, citation_refs),
            "meta": _source_titles_for_ids(cids, wb_citations),
            "_finding_id": fid,
            "_source_finding_ids": [fid] if fid else [],
        })

    overview_modules.append(
        ContentModule(
            module_id="overview-event-timeline",
            semantic_type="event-timeline",
            title="事件演进关键脉络图",
            state=ready_state if timeline_items else ModuleState.NOT_APPLICABLE,
            data_shape=DataShape.TIMELINE,
            summary=f"串联 {len(timeline_items)} 个已核实时间节点，展示从引发争议到各方回应的完整演进链条。",
            items=tuple(timeline_items),
            citations=_citations_for_ids(timeline_eids, citation_refs),
            empty_reason="" if timeline_items else "本轮材料中未提取到明确声明的事件时间节点。",
            view_id="overview",
        )
    )

    lim_data = wb.get("limitations") or {}
    lim_items: list[dict[str, Any]] = []
    if lim_data.get("stop_reason"):
        lim_items.append({"title": "收束原因与状态", "summary": str(lim_data["stop_reason"])})
    if lim_data.get("scope_limitation"):
        lim_items.append({"title": "调查范围与边界说明", "summary": str(lim_data["scope_limitation"])})
    if lim_data.get("search_failures") or lim_data.get("read_failures"):
        lim_items.append({
            "title": "检索与读取损耗",
            "summary": f"检索失败 {lim_data.get('search_failures', 0)} 次，页面读取受阻 {lim_data.get('read_failures', 0)} 次。",
        })
    if lim_items:
        overview_modules.append(
            ContentModule(
                module_id="overview-key-limitations",
                semantic_type="key-limitations",
                title="调查边界与限制说明",
                state=ready_state,
                data_shape=DataShape.CARDS,
                items=tuple(lim_items),
                view_id="overview",
            )
        )

    # --- Section 2: Focus (Visual Relation Graph + Confrontation + Stance Swimlane + Scorecard) ---
    cluster_map = _build_source_cluster_map(sources, list(report.get("source_relations") or []))
    focus_modules = _synthesize_focus_modules(
        subject,
        issues,
        findings,
        citation_labels,
        citation_refs,
        terminal=terminal,
        cluster_map=cluster_map,
    )
    focus_modules.extend(
        _build_facet_content_modules(
            list(wb.get("modules") or []),
            citation_labels,
            citation_refs,
        )
    )

    # --- Section 3: Issues (Zero-Drop Issue Map) ---
    issue_items: list[dict[str, Any]] = []
    issue_eids: list[str] = []
    for issue in issues:
        iid = str(issue.get("issue_id") or "")
        q_text = str(issue.get("question") or "")
        short_q = _short_issue_label(q_text)
        i_findings = [f for f in findings if str(f.get("issue_id") or "") == iid]
        if not i_findings:
            issue_items.append({
                "title": short_q,
                "summary": str(issue.get("note") or "当前公开材料中暂未发现可核实的直接结论。"),
                "detail": q_text,
                "meta": f"议题状态：{issue.get('status', 'open')}",
            })
            continue
        for f_idx, f in enumerate(i_findings, 1):
            fid = str(f.get("finding_id") or "")
            cids = list(f.get("evidence_ids") or [])
            issue_eids.extend(cids)
            stakeholder = _infer_actor_label(f, f_idx)
            badges = _citation_badges(cids, citation_labels)
            issue_items.append({
                "title": f"【{stakeholder}】{short_q}",
                "summary": f"{f.get('text', '')} {badges}".strip(),
                "detail": _excerpt_for_ids(cids, citation_refs),
                "meta": _source_titles_for_ids(cids, wb_citations),
                "_review_status": str(f.get("support") or "supported"),
                "_finding_id": fid,
                "_source_finding_ids": [fid] if fid else [],
            })

    issues_section = ContentSection(
        section_id="section-issues",
        title="分议题全量事实与证据核查",
        order=2,
        view_id="issues",
        view_title="分议题事实核查",
        modules=(
            ContentModule(
                module_id="issues-full-map",
                semantic_type="issue-map",
                title="调查议题与逐条核查判断",
                state=ready_state if issue_items else ModuleState.NOT_FOUND,
                data_shape=DataShape.CARDS,
                summary=f"覆盖全部 {len(issues)} 个调查子议题与 {len(findings)} 条有效判断（已自动提炼核心标题与要点，点击可展开原文引证）。",
                items=tuple(issue_items),
                citations=_citations_for_ids(issue_eids, citation_refs),
                view_id="issues",
            ),
        ),
    )

    # --- Section 4: Coverage & Source Structure ---
    coverage_modules: list[ContentModule] = []
    pub_dist = overview_data.get("publication_distribution")
    if pub_dist and pub_dist.get("buckets"):
        dist_items = tuple(
            {"label": str(b.get("date") or ""), "value": int(b.get("count") or 0)}
            for b in pub_dist["buckets"]
            if int(b.get("count") or 0) > 0
        )
        if dist_items:
            coverage_modules.append(
                ContentModule(
                    module_id="coverage-material-distribution",
                    semantic_type="material-distribution",
                    title="公开材料发布时间分布",
                    state=ready_state,
                    data_shape=DataShape.CATEGORICAL,
                    summary=f"已识别发布日期的材料共 {pub_dist.get('known_count', 0)} 份，未标注日期 {pub_dist.get('unknown_count', 0)} 份。",
                    items=dist_items,
                    view_id="coverage",
                )
            )

    role_counts: dict[str, int] = {}
    for s in sources:
        role = str(s.get("role") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
    if role_counts:
        role_items = tuple(
            {"label": ROLE_LABELS.get(role, role), "value": count}
            for role, count in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)
        )
        coverage_modules.append(
            ContentModule(
                module_id="coverage-source-structure",
                semantic_type="source-structure",
                title="归档信源角色结构分布",
                state=ready_state,
                data_shape=DataShape.CATEGORICAL,
                summary=f"共归档 {len(sources)} 份独立来源材料。",
                items=role_items,
                view_id="coverage",
            )
        )

    materials_list = list(((wb.get("views") or {}).get("coverage") or {}).get("materials") or [])
    if materials_list:
        mat_rows = []
        for m in materials_list:
            role_label = ROLE_LABELS.get(str(m.get("role") or "unknown"), str(m.get("role") or "unknown"))
            iq_list = [_short_issue_label(q) for q in (m.get("issue_questions") or []) if q]
            target_issue = iq_list[0] if iq_list else "背景与脉络核查"
            cids = list(m.get("citation_ids") or [])
            badges = _citation_badges(cids, citation_labels)
            mat_rows.append({
                "材料标题": str(m.get("title") or ""),
                "来源角色": role_label,
                "发布时间": str(m.get("published_at") or "日期未详")[:10],
                "来源关系": str(m.get("relation") or "独立信源"),
                "关联判断数": str(len(m.get("judgments") or [])),
                "_hub": subject,
                "_actor": str(m.get("title") or "")[:16],
                "_issue": target_issue,
                "_relation": f"{role_label} · 支撑 {len(m.get('judgments') or [])} 项判断",
                "_stance": "support" if m.get("role") in {"official", "regulator"} else ("media" if m.get("role") == "media" else "neutral"),
                "_citation_count": len(cids) or 1,
                "核心主张": f"{m.get('summary') or m.get('title') or ''} {badges}".strip(),
                "证据索引": badges or "—",
            })
        coverage_modules.append(
            ContentModule(
                module_id="coverage-source-relations",
                semantic_type="source-relations",
                title="信源传播路径与议题引证关系网络图",
                state=ready_state,
                data_shape=DataShape.RELATION,
                preferred_visual=VisualEncoding.RELATION_GRAPH,
                summary=f"展示 {len(mat_rows)} 份公开材料如何跨议题支撑核心判断（含交互式节点拓扑图与明细对照抽屉）。",
                table_columns=("材料标题", "来源角色", "发布时间", "来源关系", "关联判断数"),
                items=tuple(mat_rows),
                citations=tuple(citation_refs.values())[:1],
                view_id="coverage",
            )
        )

    # --- Section 5: Evidence & Diagnostics ---
    evidence_modules: list[ContentModule] = [
        ContentModule(
            module_id="evidence-full-index",
            semantic_type="evidence-index",
            title="原文证据卷宗与字符级定位",
            state=ready_state if citation_refs else ModuleState.UNAVAILABLE,
            data_shape=DataShape.EVIDENCE,
            summary=f"收录全部 {len(citation_refs)} 条经正文校验的原文摘录与字符区间。",
            citations=tuple(citation_refs.values()),
            view_id="evidence",
        )
    ]

    diag = report.get("diagnostics") or ((wb.get("views") or {}).get("diagnostics") or {})
    stages = list(diag.get("stages") or [])
    if stages:
        stage_rows = tuple(
            {
                "链路阶段": str(st.get("title") or st.get("stage") or ""),
                "状态": str(st.get("status") or ""),
                "核查摘要": str(st.get("summary") or ""),
            }
            for st in stages
        )
        evidence_modules.append(
            ContentModule(
                module_id="evidence-diagnostics",
                semantic_type="diagnostics",
                title="调查生产链路健康度诊断",
                state=ready_state,
                data_shape=DataShape.COMPARISON,
                table_columns=("链路阶段", "状态", "核查摘要"),
                items=stage_rows,
                view_id="evidence",
            )
        )

    sections: list[ContentSection] = [
        ContentSection(
            section_id="section-overview",
            title="事件核心研判与演进脉络",
            order=0,
            view_id="overview",
            view_title="核心研判与脉络",
            modules=tuple(overview_modules),
        ),
    ]
    if focus_modules:
        sections.append(
            ContentSection(
                section_id="section-focus",
                title="主体关系拓扑与正反阵营交锋图谱",
                order=1,
                view_id="focus",
                view_title="关系图谱与交锋",
                modules=tuple(focus_modules),
            )
        )
    sections.append(issues_section)
    if coverage_modules:
        sections.append(
            ContentSection(
                section_id="section-coverage",
                title="传播信源结构与引证网络",
                order=3,
                view_id="coverage",
                view_title="传播与来源网络",
                modules=tuple(coverage_modules),
            )
        )
    sections.append(
        ContentSection(
            section_id="section-evidence",
            title="证据卷宗与生产链路诊断",
            order=4,
            view_id="evidence",
            view_title="证据卷宗与诊断",
            modules=tuple(evidence_modules),
        )
    )

    return ContentDocument(
        report_id=str(report.get("run_id") or wb.get("run_id") or "report"),
        revision=int(report.get("state_revision") or 1),
        subject=subject,
        status=status,
        generated_at=str(report.get("generated_at") or report.get("cutoff") or ""),
        profile=dict(wb.get("profile") or {}),
        sections=tuple(sections),
    )
