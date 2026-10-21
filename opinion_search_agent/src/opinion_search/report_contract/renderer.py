from __future__ import annotations

from html import escape
import re
from typing import Any

from opinion_search.report_contract.contracts import (
    ModuleState,
    PlannedModule,
    PresentationPlan,
    VisualEncoding,
)


DOC_TYPE = "<" + chr(33) + "doctype html>"

STATE_LABELS = {
    ModuleState.READY: "已核实",
    ModuleState.PROVISIONAL: "阶段性",
    ModuleState.INSUFFICIENT: "证据不足",
    ModuleState.UNAVAILABLE: "不可用",
    ModuleState.NOT_APPLICABLE: "不适用",
    ModuleState.NOT_FOUND: "未发现",
    ModuleState.PENDING: "待核查",
    ModuleState.OMITTED: "已省略",
}

EMPTY_STATES = {
    ModuleState.INSUFFICIENT,
    ModuleState.UNAVAILABLE,
    ModuleState.NOT_APPLICABLE,
    ModuleState.NOT_FOUND,
    ModuleState.PENDING,
    ModuleState.OMITTED,
}


def _audit_badges(plan: PresentationPlan) -> dict[str, str]:
    """Turn the run's own counts into the masthead claims.

    The masthead used to assert "authority verified" and "cross-verified" as
    fixed strings, which contradicted the body of partial runs. Every claim here
    now comes from the report; when nothing was reviewed it says so.
    """

    audit = dict((plan.profile or {}).get("audit") or {})
    total = int(audit.get("findings_total") or 0)
    reviewed = int(audit.get("findings_reviewed") or 0)
    supported = int(audit.get("findings_supported") or 0)
    issues_total = int(audit.get("issues_total") or 0)
    issues_closed = int(audit.get("issues_closed") or 0)
    relations_total = int(audit.get("relations_total") or 0)
    relations_unverified = int(audit.get("relations_unverified") or 0)

    if not total:
        rating = "未评级"
        mechanism = "本轮没有可核查的判断"
    elif not reviewed:
        rating = f"未评级 · {total} 条判断待核查"
        mechanism = f"{total} 条判断尚未送审"
    else:
        rating = f"核查评级：{supported}/{total} 条过审"
        mechanism = (
            f"需人工核对：{supported}/{total} 条判断过审 · "
            f"{issues_closed}/{issues_total} 个议题已收口"
        )
    ledger = (
        f"来源关系：{relations_unverified}/{relations_total} 个未核实"
        if relations_total else "来源关系：未核验"
    )
    return {"rating": rating, "mechanism": mechanism, "ledger": ledger}


def _render_narrative(plan: PresentationPlan) -> str:
    """The prose layer: headline plus paragraphs, each clause carrying its proof."""

    narrative = getattr(plan, "narrative", None)
    if narrative is None:
        return ""
    parts: list[str] = ['<section class="narrative-block">']
    if narrative.headline:
        count = len(dict.fromkeys(narrative.headline_finding_ids))
        parts.append(
            f'<h2 class="narrative-headline">{escape(narrative.headline)}'
            f'<sup class="narrative-chip" title="{escape(", ".join(narrative.headline_finding_ids))}">'
            f'核对 {count} 条判断</sup></h2>'
        )
    for paragraph in narrative.paragraphs:
        parts.append(f'<p class="narrative-para"><span class="narrative-role">{escape(paragraph.role)}</span>')
        for clause in paragraph.clauses:
            count = len(dict.fromkeys(clause.finding_ids))
            parts.append(
                f'{escape(clause.text)}'
                f'<sup class="narrative-chip" title="{escape(", ".join(clause.finding_ids))}">'
                f'核对 {count} 条判断</sup>'
            )
        parts.append("</p>")
    parts.append("</section>")
    return "".join(parts)


def render_html(plan: PresentationPlan) -> str:
    nav, panels = _render_views(plan)
    badges = _audit_badges(plan)
    narrative_html = _render_narrative(plan)
    state_counts: dict[str, int] = {}
    for section in plan.sections:
        for module in section.modules:
            state_counts[module.state.value] = state_counts.get(module.state.value, 0) + 1
    state_labels = {
        "ready": "完整就绪",
        "provisional": "阶段性",
        "insufficient": "证据不足",
        "unavailable": "不可用",
        "not_applicable": "不适用",
        "not_found": "未发现",
        "pending": "待调查",
        "omitted": "已省略",
    }
    status_strip = "".join(
        f'<span class="summary-pill summary-{key}"><span class="summary-dot"></span>{escape(label)} <strong>{value}</strong></span>'
        for key, value in state_counts.items()
        for label in (state_labels.get(key, key),)
    )
    return f'''{DOC_TYPE}
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(plan.subject)} · 舆情调查报告</title>
<script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
<style>{_css()}{_extra_css()}</style>
</head>
<body>
<header class="page-header">
  <div class="masthead-top">
    <div class="masthead-meta">
      <span class="masthead-vol">{escape(plan.report_id[:8])}</span>
      <span class="masthead-sep">/</span>
      <span class="masthead-dept">OPINION RESEARCH & INVESTIGATION BUREAU</span>
      <span class="masthead-sep">/</span>
      <span class="masthead-sec">公开调查档案</span>
    </div>
    <div class="masthead-controls">
      <button type="button" class="theme-toggle-btn" onclick="toggleTheme()" title="切换纸墨报刊 / 暗室读档模式">🌓 纸墨 / 暗夜</button>
      <button type="button" class="print-btn" onclick="window.print()" title="导出打印版式">🖨️ 打印排版</button>
    </div>
  </div>

  <div class="masthead-brand-wrap">
    <div class="masthead-title-sub">OPINIONSEARCH DEEP INVESTIGATION DOSSIER</div>
    <div class="masthead-title">舆情深度调查与事实链核查报告</div>
  </div>

  <div class="editorial-divider-double"></div>

  <div class="headline-wrap headline-card">
    <div class="headline-kicker-wrap">
      <span class="headline-kicker">专项研判档案 · 核心事件</span>
      <span class="headline-badge">{escape(badges["rating"])}</span>
    </div>
    <h1 class="headline-main">{escape(plan.subject)}</h1>
    <div class="meta dateline-bar">
      <span class="meta-item"><strong class="dateline-label">调查状态</strong><span class="meta-status status-tag status-{plan.status}">{_status_label(plan.status)}</span></span>
      <span class="dateline-sep">|</span>
      <span class="meta-item"><strong class="dateline-label">档案版本</strong>REVISION v{plan.source_content_revision}</span>
      <span class="dateline-sep">|</span>
      <span class="meta-item"><strong class="dateline-label">归档时间</strong>{escape(plan.generated_at)}</span>
      <span class="dateline-sep">|</span>
      <span class="meta-item"><strong class="dateline-label">核查机制</strong>{escape(badges["mechanism"])}</span>
    </div>
  </div>

  <div class="status-strip-wrap audit-panel">
    <div class="status-strip-label audit-panel-header">
      <span class="audit-panel-title">事实链完整度与证据核查评级</span>
      <span class="audit-panel-badge">{escape(badges["ledger"])}</span>
    </div>
    <div class="status-strip">{status_strip}</div>
  </div>
</header>
<main>
{narrative_html}
{nav}
{panels}
</main>
<footer class="page-footer">本报告只基于上述公开材料；事实需由读者对照来源复核。</footer>
{_view_script()}
</body>
</html>'''


def _status_label(status: str) -> str:
    labels = {
        "completed": "已结案",
        "partial": "阶段性完成",
        "failed": "核查失败",
        "cancelled": "已终止",
        "finalizing": "证据收束中",
        "running": "调查进行中",
    }
    return labels.get(status, status)


def _render_views(plan: PresentationPlan) -> tuple[str, str]:
    order: list[str] = []
    groups: dict[str, dict] = {}
    for section in plan.sections:
        view_id = section.view_id or "overview"
        if view_id not in groups:
            groups[view_id] = {
                "title": section.view_title or section.title,
                "sections": [],
            }
            order.append(view_id)
        groups[view_id]["sections"].append(section)

    tabs = []
    panels = []
    roman_numerals = ["一", "二", "三", "四", "五", "六", "七", "八"]
    for index, view_id in enumerate(order):
        active = " active" if index == 0 else ""
        title = groups[view_id]["title"]
        roman = roman_numerals[index % len(roman_numerals)]
        tabs.append(
            f'<button class="view-tab{active}" data-view-target="{escape(view_id)}">'
            f'<span class="tab-index">{roman}</span>'
            f'<span class="tab-title">{escape(title)}</span>'
            f'</button>'
        )
        sections_html = "".join(_render_section(section) for section in groups[view_id]["sections"])
        panel_active = " active" if index == 0 else ""
        panels.append(
            f'<div class="view-panel{panel_active}" id="panel-{escape(view_id)}">{sections_html}</div>'
        )
    actions = (
        '<div class="view-actions">'
        '<button type="button" data-expand-all title="展开当前视图所有折叠项">展开全部</button>'
        '<button type="button" data-collapse-all title="收起当前视图所有折叠项">收起全部</button>'
        '</div>'
    )
    return (
        f'<div class="nav-sticky-wrap"><div class="nav-inner"><nav class="view-tabs" aria-label="报告视图">{"".join(tabs)}</nav>{actions}</div></div>',
        f'<div class="view-panels">{"".join(panels)}</div>',
    )


def _view_script() -> str:
    return '''<script>
function activateView(target){
  document.querySelectorAll(".view-panel").forEach(function(panel){ panel.classList.remove("active"); });
  document.querySelectorAll(".view-tab").forEach(function(tab){ tab.classList.remove("active"); });
  var panel = document.getElementById("panel-" + target);
  if (panel) { panel.classList.add("active"); }
  document.querySelectorAll(".view-tab").forEach(function(tab){
    if (tab.getAttribute("data-view-target") == target) { tab.classList.add("active"); }
  });
}
document.querySelectorAll(".view-tab").forEach(function(button){
  button.addEventListener("click", function(){
    var target = button.getAttribute("data-view-target");
    activateView(target);
    if (history.replaceState) { history.replaceState(null, "", "#" + target); }
  });
});
document.querySelectorAll("[data-expand-all]").forEach(function(button){
  button.addEventListener("click", function(){
    document.querySelectorAll("details.item-details").forEach(function(item){ item.open = true; });
  });
});
document.querySelectorAll("[data-collapse-all]").forEach(function(button){
  button.addEventListener("click", function(){
    document.querySelectorAll("details.item-details").forEach(function(item){ item.open = false; });
  });
});
function selectGraphNode(el) {
  var wrap = el.closest(".relation-graph-wrap");
  if (!wrap) return;
  var nodeId = el.getAttribute("data-node-id") || "";
  wrap.querySelectorAll(".rg-node").forEach(function(n){
    n.classList.toggle("rg-node-active", n === el);
  });
  wrap.querySelectorAll(".rg-edge").forEach(function(edge){
    var fromId = edge.getAttribute("data-from") || "";
    var toId = edge.getAttribute("data-to") || "";
    var matched = !nodeId || fromId === nodeId || toId === nodeId;
    edge.style.opacity = matched ? "1" : "0.18";
  });
  var title = el.getAttribute("data-node-title") || "";
  var role = el.getAttribute("data-node-role") || "";
  var summary = el.getAttribute("data-node-summary") || "";
  var cites = el.getAttribute("data-node-cites") || "";
  var inspector = wrap.querySelector(".rg-inspector");
  if (inspector && title) {
    inspector.querySelector(".rg-insp-title").textContent = title;
    inspector.querySelector(".rg-insp-role").textContent = role;
    inspector.querySelector(".rg-insp-summary").textContent = summary;
    inspector.querySelector(".rg-insp-cites").textContent = cites ? ("证据锚点：" + cites) : "";
  }
}
function toggleTheme() {
  document.body.classList.toggle("theme-dark");
  try {
    var isDark = document.body.classList.contains("theme-dark");
    localStorage.setItem("os_theme_mode", isDark ? "dark" : "light");
  } catch(e) {}
}
(function() {
  try {
    var saved = localStorage.getItem("os_theme_mode");
    if (saved === "dark") {
      document.body.classList.add("theme-dark");
    } else if (!saved && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.body.classList.add("theme-dark");
    }
  } catch(e) {}
})();
if (window.location.hash.length > 1) { activateView(window.location.hash.slice(1)); }
</script>'''


def _render_section(section) -> str:
    modules = "\n".join(_render_module(module) for module in section.modules)
    return f'''<section class="section" id="{escape(section.section_id)}">
<div class="section-head-wrap">
  <div class="section-kicker">SECTION REPORT</div>
  <h2 class="section-title">{escape(section.title)}</h2>
</div>
<div class="module-grid">{modules}</div>
</section>'''


def _render_module(module: PlannedModule) -> str:
    state = STATE_LABELS.get(module.state, module.state.value)
    module_summary = (
        f'<div class="module-summary"><span class="summary-label">核心事实提要</span>{escape(module.summary)}</div>'
        if module.summary else ""
    )
    body = _render_module_body(module)
    limitations = ""
    if module.limitations:
        items = "".join(f"<li>{escape(item)}</li>" for item in module.limitations)
        limitations = f'<div class="limitations"><div class="limitations-head">调查边界与局限说明</div><ul>{items}</ul></div>'
    empty_reason = ""
    if module.empty_reason:
        empty_reason = f'<div class="empty-reason"><span class="empty-tag">核查说明</span>{escape(module.empty_reason)}</div>'
    return f'''<article class="card module" data-module="{escape(module.semantic_type)}">
<header class="module-head">
  <div class="module-title-group">
    <h3>{escape(module.title)}</h3>
  </div>
  <span class="state state-{module.state.value}">{escape(state)}</span>
</header>
{module_summary}
{body}
{empty_reason}
{limitations}
</article>'''


def _render_module_body(module: PlannedModule) -> str:
    if module.state in EMPTY_STATES:
        return _render_empty_state(module)
    visual = module.selected_visual
    if visual is VisualEncoding.RELATION_GRAPH:
        return _render_relation_graph(module)
    if visual is VisualEncoding.RESPONSE_SCORECARD:
        return _render_response_coverage(module)
    if visual is VisualEncoding.DEBATE_VERSUS:
        return _render_debate_versus(module)
    if module.semantic_type == "response-coverage" and visual not in {
        VisualEncoding.COMPARISON_TABLE,
        VisualEncoding.CARDS,
    }:
        return _render_response_coverage(module)
    if module.semantic_type == "response-coverage" and visual is VisualEncoding.COMPARISON_TABLE:
        return _render_response_coverage(module)
    if visual is VisualEncoding.CARDS:
        return _render_cards(module)
    if visual is VisualEncoding.TIMELINE:
        return _render_timeline(module)
    if visual is VisualEncoding.COMPARISON_TABLE:
        return _render_table(module)
    if visual is VisualEncoding.POSITION_MATRIX:
        return _render_matrix(module)
    if visual is VisualEncoding.DISTRIBUTION_CHART:
        return _render_distribution(module)
    if visual is VisualEncoding.EVIDENCE_DRAWER:
        return _render_evidence(module)
    if visual is VisualEncoding.ACTION_CARDS:
        return _render_cards(module)
    return _render_text(module)


def _render_empty_state(module: PlannedModule) -> str:
    if module.summary:
        return f'<p class="summary">{escape(module.summary)}</p>'
    return f'<div class="empty-state"><span class="empty-tag">调查状态</span>当前模块状态：{escape(STATE_LABELS.get(module.state, module.state.value))}</div>'


def _review_badge(item: dict[str, Any]) -> str:
    status = str(item.get("_review_status") or "")
    if status == "partial":
        return '<span class="review-badge review-partial">部分支持</span>'
    if status == "insufficient":
        return '<span class="review-badge review-insufficient">证据不足</span>'
    if status == "contradicted":
        return '<span class="review-badge review-contradicted">存在矛盾</span>'
    return ""


def _review_reason_html(item: dict[str, Any]) -> str:
    reason = str(item.get("_review_reason") or "").strip()
    if not reason:
        return ""
    return f'<div class="review-reason"><span class="review-tag">审查备忘</span>{escape(reason)}</div>'


_CITE_BADGE_RE = re.compile(r"\[(引\d+)\]")


def _style_inline_citations(escaped_text: str) -> str:
    return _CITE_BADGE_RE.sub(r'<span class="cite-pill">\1</span>', escaped_text)


def _extract_structured_summary(summary: str) -> str:
    """Turn long dense finding prose into a bold headline + 2-3 scannable key-point chips."""

    raw = str(summary or "").strip()
    if not raw:
        return ""
    if len(raw) <= 68:
        return f'<div class="item-summary">{_style_inline_citations(escape(raw))}</div>'

    # Strip trailing citation badges into a badge suffix so we split clauses cleanly
    cites = _CITE_BADGE_RE.findall(raw)
    body = _CITE_BADGE_RE.sub("", raw).strip()
    clauses = [c.strip(" ；;。，,") for c in re.split(r"[；;。]+", body) if c.strip(" ；;。，,")]

    if not clauses:
        return f'<div class="item-summary">{_style_inline_citations(escape(raw))}</div>'

    first = clauses[0]
    kicker = ""
    headline = first
    if "：" in first and first.index("：") <= 28:
        kicker, headline = [part.strip() for part in first.split("：", 1)]

    rest = clauses[1:4]
    cite_html = "".join(f'<span class="cite-pill">{escape(c)}</span>' for c in dict.fromkeys(cites[:6]))

    kicker_html = f'<span class="kp-kicker">{escape(kicker)}</span>' if kicker else ""
    bullets_html = ""
    if rest:
        li_items = "".join(f'<li class="kp-bullet">{escape(part)}</li>' for part in rest)
        bullets_html = f'<ul class="kp-list">{li_items}</ul>'

    # Keep the full verbatim raw string inside a hidden/collapsible details block when truncated
    verbatim_drawer = (
        f'<details class="item-details"><summary><span class="details-toggle">展开完整判断原句</span></summary>'
        f'<div class="details-content"><p>{escape(raw)}</p></div></details>'
        if len(clauses) > 4 or len(raw) > 140
        else f'<span class="sr-only" style="display:none">{escape(raw)}</span>'
    )

    return (
        f'<div class="item-summary kp-box">'
        f'<div class="kp-headline-row">{kicker_html}<strong class="kp-headline">{escape(headline)}</strong>{cite_html}</div>'
        f'{bullets_html}'
        f'</div>'
        f'{verbatim_drawer}'
    )


def _detail_html(item: dict[str, Any], summary: str) -> str:
    detail = str(item.get("detail") or item.get("text") or "").strip()
    if not detail or detail == summary:
        return ""
    return (
        '<details class="item-details">'
        '<summary><span class="details-toggle">查看事实引证及核查原文</span></summary>'
        f'<div class="details-content"><p>{_style_inline_citations(escape(detail))}</p></div>'
        '</details>'
    )


def _render_text(module: PlannedModule) -> str:
    paragraphs = []
    for item in module.items:
        summary = str(item.get("summary") or item.get("text") or "")
        if not summary:
            _, summary, _ = _adapt_card_fields(item)
        if summary:
            paragraphs.append(f'<p class="item-summary">{_style_inline_citations(escape(summary))}</p>')
        paragraphs.append(_detail_html(item, summary))
    return "".join(paragraphs)


def _importance(item: dict[str, Any]) -> float:
    try:
        return float(item.get("_importance", 0))
    except (TypeError, ValueError):
        return 0.0


_CARD_TITLE_KEYS = (
    "title",
    "label",
    "问题",
    "议题",
    "争议焦点",
    "专项维度",
    "维度",
    "主体",
    "陈述主体",
    "关联议题",
)
_CARD_SUMMARY_KEYS = (
    "summary",
    "text",
    "note",
    "核查判断",
    "核查内容",
    "依据",
    "说明",
    "判断",
    "核心主张",
)
_CARD_META_KEYS = (
    "meta",
    "time",
    "event_time",
    "证据索引",
    "核查状态",
    "立场",
    "回应",
)


def _adapt_card_fields(item: dict[str, Any]) -> tuple[str, str, str]:
    """Schema adapter so arbitrary table/matrix row dicts render rich cards without blank fields."""

    title = ""
    for k in _CARD_TITLE_KEYS:
        val = str(item.get(k) or "").strip()
        if val:
            title = val
            break

    summary = ""
    for k in _CARD_SUMMARY_KEYS:
        val = str(item.get(k) or "").strip()
        if val and val != title:
            summary = val
            break

    meta_parts: list[str] = []
    for k in _CARD_META_KEYS:
        val = str(item.get(k) or "").strip()
        if val and val not in {title, summary}:
            label_prefix = "" if k in {"meta", "time", "event_time"} else f"{k}："
            meta_parts.append(f"{label_prefix}{val}")

    if not summary:
        extra_pairs = [
            f"{k}：{v}"
            for k, v in item.items()
            if not str(k).startswith("_")
            and k not in {"title", "label", "detail", "meta", "time"}
            and str(v or "").strip()
            and str(v or "").strip() != title
        ]
        summary = " ｜ ".join(extra_pairs)

    if not title and summary:
        title = "核查要点"

    return title, summary, " · ".join(dict.fromkeys(meta_parts))


def _render_cards(module: PlannedModule) -> str:
    if not module.items:
        return _render_text(module)
    cards = []
    ordered_items = sorted(module.items, key=_importance, reverse=True)
    for index, item in enumerate(ordered_items, 1):
        title, summary, meta = _adapt_card_fields(item)
        detail = _detail_html(item, summary)
        meta_html = (
            f'<div class="item-meta"><span class="meta-source-label">出处文献</span>{_style_inline_citations(escape(str(meta)))}</div>'
            if meta else ""
        )
        cards.append(
            '<div class="item-card">'
            f'<div class="item-head">'
            f'<span class="item-badge-index">ITEM {index:02d}</span>'
            f'<div class="item-title">{escape(str(title))}{_review_badge(item)}</div>'
            f'</div>'
            f'{_review_reason_html(item)}'
            f'{_extract_structured_summary(summary)}'
            f'{detail}'
            f'{meta_html}'
            '</div>'
        )
    return f'<div class="cards">{"".join(cards)}</div>'


def _node_palette(stance: str, relation: str = "") -> tuple[str, str, str]:
    raw = f"{stance} {relation}".lower()
    if any(k in raw for k in ("oppose", "skeptical", "质疑", "批评", "反对")):
        return "#8b1e1e", "#fdf2f2", "#fca5a5"
    if any(k in raw for k in ("support", "direct", "支持", "辩护", "正面")):
        return "#14532d", "#f0fdf4", "#86efac"
    if any(k in raw for k in ("partial", "mixed", "冷处理", "部分", "回应", "当事")):
        return "#b45309", "#fefce8", "#fde047"
    return "#0d2d44", "#edf4f9", "#9ec3de"


def _short_node_text(text: str, limit: int = 13) -> str:
    cleaned = re.sub(r"（[^）]*）|\([^\)]*\)", "", str(text or "")).strip()
    if not cleaned:
        cleaned = str(text or "").strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _render_relation_graph(module: PlannedModule) -> str:
    """Render an interactive 3-tier SVG Node-Link Topology Graph (Actors/Sources -> Issues -> Event Hub)."""

    if not module.items:
        return _render_text(module)

    actors: list[dict[str, Any]] = []
    actor_map: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    edges: list[dict[str, Any]] = []
    hub_label = "核心舆情事件"

    for idx, item in enumerate(module.items, 1):
        hub_label = str(item.get("_hub") or module.title or hub_label)
        actor_name = str(
            item.get("_actor")
            or item.get("主体")
            or item.get("材料标题")
            or item.get("title")
            or f"节点 {idx}"
        ).strip()
        issue_name = str(
            item.get("_issue")
            or item.get("关联议题")
            or item.get("来源角色")
            or "核心争议焦点"
        ).strip()
        relation = str(
            item.get("_relation")
            or item.get("关系类型")
            or item.get("来源关系")
            or item.get("立场")
            or "关联核查"
        ).strip()
        stance = str(item.get("_stance") or item.get("立场") or "neutral")
        claim = str(
            item.get("核心主张")
            or item.get("依据")
            or item.get("summary")
            or item.get("材料标题")
            or ""
        ).strip()
        cites = str(item.get("证据索引") or item.get("关联判断数") or "").strip()
        weight = int(item.get("_citation_count") or 1)

        if actor_name not in actor_map:
            node_entry = {
                "id": f"actor-{len(actors) + 1}",
                "name": actor_name,
                "stance": stance,
                "relation": relation,
                "claim": claim,
                "cites": cites,
                "weight": weight,
            }
            actor_map[actor_name] = node_entry
            actors.append(node_entry)
        else:
            actor_map[actor_name]["weight"] += weight
            if claim and claim not in actor_map[actor_name]["claim"]:
                actor_map[actor_name]["claim"] = (actor_map[actor_name]["claim"] + " ｜ " + claim)[:260]

        if issue_name not in issues:
            issues.append(issue_name)

        edges.append({
            "actor_id": actor_map[actor_name]["id"],
            "actor_name": actor_name,
            "issue_id": f"issue-{issues.index(issue_name) + 1}",
            "issue_name": issue_name,
            "relation": relation,
            "stance": stance,
        })

    actors = actors[:10]
    issues = issues[:6]
    max_rows = max(len(actors), len(issues), 3)
    svg_h = max(340, min(640, max_rows * 62 + 64))
    svg_w = 960

    actor_y: dict[str, float] = {}
    for i, act in enumerate(actors):
        step = (svg_h - 80) / max(len(actors), 1)
        actor_y[act["id"]] = 48 + step * (i + 0.5)

    issue_y: dict[str, float] = {}
    for i, iss in enumerate(issues):
        iid = f"issue-{i + 1}"
        step = (svg_h - 90) / max(len(issues), 1)
        issue_y[iid] = 52 + step * (i + 0.5)

    hub_y = svg_h / 2.0
    x_actor = 155.0
    x_issue = 525.0
    x_hub = 835.0

    svg_Paths: list[str] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        aid = edge["actor_id"]
        iid = edge["issue_id"]
        if aid not in actor_y or iid not in issue_y or (aid, iid) in seen_edges:
            continue
        seen_edges.add((aid, iid))
        y1 = actor_y[aid]
        y2 = issue_y[iid]
        stroke, fill_bg, _ = _node_palette(edge["stance"], edge["relation"])
        x_start = x_actor + 108
        x_end = x_issue - 108
        cx1 = x_start + (x_end - x_start) * 0.45
        cx2 = x_start + (x_end - x_start) * 0.55
        mid_x = (x_start + x_end) / 2.0
        mid_y = (y1 + y2) / 2.0 - 6.0
        rel_short = _short_node_text(edge["relation"], 8)
        svg_Paths.append(
            f'<g class="rg-edge" data-from="{escape(aid)}" data-to="{escape(iid)}">'
            f'<path d="M {x_start:.1f} {y1:.1f} C {cx1:.1f} {y1:.1f}, {cx2:.1f} {y2:.1f}, {x_end:.1f} {y2:.1f}" '
            f'fill="none" stroke="{stroke}" stroke-width="2.2" stroke-opacity="0.68" marker-end="url(#rg-arrow)"/>'
            f'<rect x="{mid_x - 38:.1f}" y="{mid_y - 9:.1f}" width="76" height="18" rx="9" fill="{fill_bg}" stroke="{stroke}" stroke-width="1"/>'
            f'<text x="{mid_x:.1f}" y="{mid_y + 3.5:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="{stroke}">{escape(rel_short)}</text>'
            f'</g>'
        )

    for i, iss in enumerate(issues):
        iid = f"issue-{i + 1}"
        y1 = issue_y[iid]
        x_start = x_issue + 108
        x_end = x_hub - 88
        cx1 = x_start + (x_end - x_start) * 0.48
        cx2 = x_start + (x_end - x_start) * 0.52
        svg_Paths.append(
            f'<g class="rg-edge" data-from="{escape(iid)}" data-to="hub-main">'
            f'<path d="M {x_start:.1f} {y1:.1f} C {cx1:.1f} {y1:.1f}, {cx2:.1f} {hub_y:.1f}, {x_end:.1f} {hub_y:.1f}" '
            f'fill="none" stroke="#575047" stroke-width="1.8" stroke-dasharray="4 3" stroke-opacity="0.55" marker-end="url(#rg-arrow)"/>'
            f'</g>'
        )

    svg_nodes: list[str] = []
    for act in actors:
        aid = act["id"]
        y = actor_y[aid]
        stroke, fill_bg, border_c = _node_palette(act["stance"], act["relation"])
        label = _short_node_text(act["name"], 11)
        rel_tag = _short_node_text(act["relation"], 7)
        summary_clean = re.sub(r"\s+", " ", act["claim"])[:160]
        svg_nodes.append(
            f'<g class="rg-node" data-node-id="{escape(aid)}" '
            f'data-node-title="{escape(act["name"])}" '
            f'data-node-role="{escape(act["relation"])}" '
            f'data-node-summary="{escape(summary_clean)}" '
            f'data-node-cites="{escape(act["cites"])}" '
            f'onclick="selectGraphNode(this)" onmouseenter="selectGraphNode(this)" style="cursor:pointer">'
            f'<rect x="{x_actor - 104:.1f}" y="{y - 21:.1f}" width="208" height="42" rx="6" fill="{fill_bg}" stroke="{stroke}" stroke-width="2"/>'
            f'<circle cx="{x_actor - 86:.1f}" cy="{y:.1f}" r="9" fill="{stroke}"/>'
            f'<text x="{x_actor - 86:.1f}" y="{y + 3.5:.1f}" text-anchor="middle" font-size="9.5" font-weight="800" fill="#fff">{escape(label[:1])}</text>'
            f'<text x="{x_actor - 70:.1f}" y="{y - 3:.1f}" font-size="12" font-weight="800" fill="#1c1917">{escape(label)}</text>'
            f'<text x="{x_actor - 70:.1f}" y="{y + 12:.1f}" font-size="10" font-weight="700" fill="{stroke}">{escape(rel_tag)} · 权重 {act["weight"]}</text>'
            f'</g>'
        )

    for i, iss in enumerate(issues):
        iid = f"issue-{i + 1}"
        y = issue_y[iid]
        label = _short_node_text(iss, 13)
        svg_nodes.append(
            f'<g class="rg-node" data-node-id="{escape(iid)}" '
            f'data-node-title="{escape(iss)}" '
            f'data-node-role="核心争议子议题" '
            f'data-node-summary="汇集各方在该议题下的交锋主张与核查事实。" '
            f'data-node-cites="" '
            f'onclick="selectGraphNode(this)" onmouseenter="selectGraphNode(this)" style="cursor:pointer">'
            f'<rect x="{x_issue - 106:.1f}" y="{y - 20:.1f}" width="212" height="40" rx="18" fill="#faf5ff" stroke="#581c87" stroke-width="2"/>'
            f'<text x="{x_issue:.1f}" y="{y - 2:.1f}" text-anchor="middle" font-size="11.5" font-weight="800" fill="#1c1917">{escape(label)}</text>'
            f'<text x="{x_issue:.1f}" y="{y + 12:.1f}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#581c87">议题节点 #{i + 1}</text>'
            f'</g>'
        )

    hub_short = _short_node_text(hub_label, 10)
    svg_nodes.append(
        f'<g class="rg-node" data-node-id="" '
        f'data-node-title="{escape(hub_label)}" '
        f'data-node-role="事件中心枢纽（点击重置全图高亮）" '
        f'data-node-summary="共汇集 {len(actors)} 个参与主体/信源节点与 {len(issues)} 个核心争议子议题。" '
        f'data-node-cites="" '
        f'onclick="selectGraphNode(this)" style="cursor:pointer">'
        f'<rect x="{x_hub - 86:.1f}" y="{hub_y - 34:.1f}" width="172" height="68" rx="8" fill="#0d2d44" stroke="#1c1917" stroke-width="2.5"/>'
        f'<text x="{x_hub:.1f}" y="{hub_y - 8:.1f}" text-anchor="middle" font-size="10" font-weight="800" fill="#9ec3de" letter-spacing="1">CORE EVENT HUB</text>'
        f'<text x="{x_hub:.1f}" y="{hub_y + 11:.1f}" text-anchor="middle" font-size="12.5" font-weight="900" fill="#ffffff">{escape(hub_short)}</text>'
        f'</g>'
    )

    first_actor = actors[0]
    first_summary = re.sub(r"\s+", " ", first_actor["claim"])[:160]
    table_drawer = (
        '<details class="item-details" style="margin-top:12px">'
        '<summary><span class="details-toggle">展开节点关系结构化明细表</span></summary>'
        f'<div class="details-content">{_render_table(module)}</div>'
        '</details>'
    )

    return (
        f'<div class="relation-graph-wrap">'
        f'<div class="rg-legend-bar">'
        f'<span class="rg-legend-item"><span class="rg-dot" style="background:#8b1e1e"></span>质疑 / 批评节点</span>'
        f'<span class="rg-legend-item"><span class="rg-dot" style="background:#b45309"></span>当事方 / 回应节点</span>'
        f'<span class="rg-legend-item"><span class="rg-dot" style="background:#14532d"></span>支持 / 辩护节点</span>'
        f'<span class="rg-legend-item"><span class="rg-dot" style="background:#0d2d44"></span>媒体 / 事实核查节点</span>'
        f'<span class="rg-legend-item"><span class="rg-dot" style="background:#581c87"></span>争议议题枢纽</span>'
        f'<span class="rg-legend-tip">💡 悬停或点击图中任意节点可高亮传导路径并查看核心主张</span>'
        f'</div>'
        f'<div class="rg-canvas-box">'
        f'<svg class="relation-graph-svg" viewBox="0 0 {svg_w} {svg_h}" width="100%" height="auto" role="img" aria-label="主体与议题关系拓扑图">'
        f'<defs>'
        f'<marker id="rg-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 1 L 10 5 L 0 9 z" fill="#575047"/>'
        f'</marker>'
        f'</defs>'
        f'<text x="{x_actor:.1f}" y="22" text-anchor="middle" font-size="11" font-weight="800" fill="#575047">参与主体 / 信源节点 ({len(actors)})</text>'
        f'<text x="{x_issue:.1f}" y="22" text-anchor="middle" font-size="11" font-weight="800" fill="#581c87">核心争议子议题 ({len(issues)})</text>'
        f'<text x="{x_hub:.1f}" y="22" text-anchor="middle" font-size="11" font-weight="800" fill="#0d2d44">事件总枢纽</text>'
        f'{"".join(svg_Paths)}'
        f'{"".join(svg_nodes)}'
        f'</svg>'
        f'</div>'
        f'<div class="rg-inspector">'
        f'<div class="rg-insp-head">'
        f'<span class="rg-insp-badge">节点穿透详情</span>'
        f'<strong class="rg-insp-title">{escape(first_actor["name"])}</strong>'
        f'<span class="rg-insp-role">{escape(first_actor["relation"])}</span>'
        f'</div>'
        f'<div class="rg-insp-summary">{escape(first_summary)}</div>'
        f'<div class="rg-insp-cites">{escape("证据锚点：" + first_actor["cites"] if first_actor["cites"] else "")}</div>'
        f'</div>'
        f'{table_drawer}'
        f'</div>'
    )


def _render_debate_versus(module: PlannedModule) -> str:
    if not module.items:
        return _render_text(module)
    blocks = []
    for index, item in enumerate(module.items, 1):
        topic = str(
            item.get("争议焦点")
            or item.get("议题")
            or item.get("问题")
            or item.get("title")
            or f"焦点交锋 {index}"
        )
        left_actor = str(item.get("_left_actor") or item.get("正方主体") or "质疑 / 披露方")
        right_actor = str(item.get("_right_actor") or item.get("反方主体") or "回应 / 抗辩方")
        left_claim = str(
            item.get("_left_claim")
            or item.get("质疑与批评主张")
            or item.get("正方主张")
            or item.get("summary")
            or ""
        )
        right_claim = str(
            item.get("_right_claim")
            or item.get("回应与抗辩主张")
            or item.get("反方主张")
            or item.get("detail")
            or ""
        )
        left_w = max(1, int(item.get("_left_count") or len(_CITE_BADGE_RE.findall(left_claim)) or 1))
        right_w = max(1, int(item.get("_right_count") or len(_CITE_BADGE_RE.findall(right_claim)) or 1))
        left_pct = left_w / (left_w + right_w) * 100.0
        right_pct = 100.0 - left_pct

        citations = str(item.get("证据索引") or item.get("meta") or "")
        cite_html = (
            f'<div class="item-meta"><span class="meta-source-label">证据锚点</span>{_style_inline_citations(escape(citations))}</div>'
            if citations else ""
        )
        blocks.append(
            '<div class="item-card debate-versus-card">'
            f'<div class="item-head">'
            f'<span class="item-badge-index">VS {index:02d}</span>'
            f'<div class="item-title">{escape(topic)}</div>'
            f'</div>'
            f'<div class="vs-tug-wrap">'
            f'<div class="vs-tug-labels">'
            f'<span class="vs-side-left">⚡ {escape(left_actor)}（{left_w} 处引证）</span>'
            f'<span class="vs-center-tag">正反证据权重比 {left_pct:.0f}% : {right_pct:.0f}%</span>'
            f'<span class="vs-side-right">🛡️ {escape(right_actor)}（{right_w} 处引证）</span>'
            f'</div>'
            f'<div class="vs-tug-bar">'
            f'<div class="vs-tug-fill-left" style="width:{left_pct:.1f}%"></div>'
            f'<div class="vs-tug-fill-right" style="width:{right_pct:.1f}%"></div>'
            f'</div>'
            f'</div>'
            f'<div class="coverage-grid" style="margin-top:12px">'
            f'<div class="coverage-card coverage-card-non_substantive">'
            f'<div class="coverage-head"><span class="matrix-stance stance-oppose">质疑 / 批评侧 · {escape(left_actor)}</span></div>'
            f'<div style="margin-top:8px">{_extract_structured_summary(left_claim)}</div>'
            f'</div>'
            f'<div class="coverage-card coverage-card-direct">'
            f'<div class="coverage-head"><span class="matrix-stance stance-support">回应 / 辩护侧 · {escape(right_actor)}</span></div>'
            f'<div style="margin-top:8px">{_extract_structured_summary(right_claim)}</div>'
            f'</div>'
            f'</div>'
            f'{cite_html}'
            '</div>'
        )
    return f'<div class="cards">{"".join(blocks)}</div>'


def _timeline_key(item: dict[str, Any]) -> tuple[int, str]:
    raw = str(item.get("time") or item.get("event_time") or "")
    if not raw:
        raw = str(item.get("title") or "")
    match = re.search(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})?", raw)
    if match is None:
        return (1, raw)
    year, month, day = match.group(1), match.group(2), match.group(3) or "1"
    return (0, f"{int(year):04d}-{int(month):02d}-{int(day):02d}")


def _render_timeline(module: PlannedModule) -> str:
    if not module.items:
        return _render_text(module)
    items = sorted(module.items, key=_timeline_key)

    # Render a horizontal milestone flow diagram at the top so the causal chain is visible at a glance
    flow_steps = []
    for idx, item in enumerate(items[:8], 1):
        t_val = str(item.get("time") or item.get("event_time") or f"节点 {idx}")
        t_title = _short_node_text(str(item.get("title") or "关键节点"), 11)
        flow_steps.append(
            f'<div class="tl-flow-step">'
            f'<div class="tl-flow-badge">{escape(t_val)}</div>'
            f'<div class="tl-flow-title">{escape(t_title)}</div>'
            f'</div>'
        )
    flow_html = (
        '<div class="tl-flow-track">'
        + '<div class="tl-flow-arrow">──▶</div>'.join(flow_steps)
        + '</div>'
        if len(flow_steps) >= 2 else ""
    )

    nodes = []
    for index, item in enumerate(items):
        time_value = item.get("time") or item.get("event_time") or ""
        title = item.get("title") or ""
        summary = str(item.get("summary") or item.get("text") or "")
        detail = _detail_html(item, summary)
        meta = item.get("source_title") or item.get("meta") or ""
        meta_html = f'<div class="timeline-meta"><span class="meta-source-label">核验来源</span>{_style_inline_citations(escape(str(meta)))}</div>' if meta else ""
        nodes.append(
            f'<div class="timeline-item">'
            f'<div class="timeline-dot-wrap"><div class="timeline-dot"></div></div>'
            f'<div class="timeline-card">'
            f'<div class="timeline-header">'
            f'<span class="timeline-time">{escape(str(time_value))}</span>'
            f'<div class="timeline-title">{escape(str(title))}{_review_badge(item)}</div>'
            f'</div>'
            f'{_review_reason_html(item)}'
            f'<div class="timeline-text">{_extract_structured_summary(summary)}</div>'
            f'{detail}'
            f'{meta_html}'
            f'</div>'
            f'</div>'
        )
    return f'{flow_html}<div class="timeline">{"".join(nodes)}</div>'


def _coverage_badge(value: str) -> str:
    normalized = str(value or "unknown").strip().lower()
    label_map = {
        "direct": "正面实质回应",
        "partial": "部分针对回应",
        "non_substantive": "回避未实质回应",
        "not_found": "尚未公开回应",
        "unknown": "尚无法判断",
        "直接": "正面实质回应",
        "部分": "部分针对回应",
        "未实质": "回避未实质回应",
        "未找到": "尚未公开回应",
    }
    label = label_map.get(normalized, str(value or "尚无法判断"))
    if "直接" in normalized or normalized == "direct":
        badge_type = "direct"
    elif "部分" in normalized or normalized == "partial":
        badge_type = "partial"
    elif "未找到" in normalized or normalized == "not_found":
        badge_type = "not_found"
    else:
        badge_type = "non_substantive"
    return f'<span class="coverage-badge coverage-{badge_type}">{escape(label)}</span>'


def _render_response_coverage(module: PlannedModule) -> str:
    items = [item for item in module.items if "回应" in item or "问题" in item]
    if not items:
        return _render_table(module)
    cards = []
    for item in items:
        question = item.get("问题") or item.get("议题") or item.get("title") or ""
        response = item.get("回应") or "unknown"
        covered = item.get("已覆盖") or ""
        uncovered = item.get("未覆盖") or ""
        reason = item.get("说明") or item.get("summary") or item.get("判断") or ""

        covered_parts = [p.strip() for p in re.split(r"[；;、]+", str(covered)) if p.strip()]
        uncovered_parts = [p.strip() for p in re.split(r"[；;、]+", str(uncovered)) if p.strip()]

        covered_pills = "".join(
            f'<span class="cov-pill cov-pill-ok">✓ {escape(p)}</span>' for p in covered_parts
        )
        uncovered_pills = "".join(
            f'<span class="cov-pill cov-pill-gap">✗ {escape(p)}</span>' for p in uncovered_parts
        )
        pills_row = (
            f'<div class="cov-pills-wrap">{covered_pills}{uncovered_pills}</div>'
            if (covered_pills or uncovered_pills) else ""
        )

        uncovered_html = (
            f'<div class="coverage-uncovered">'
            f'<div class="uncovered-title">待查缺口与未决要点</div>'
            f'<div class="uncovered-text">{escape(str(uncovered))}</div>'
            f'</div>'
            if uncovered else ""
        )
        raw_resp = str(response or "unknown").strip().lower()
        if "直接" in raw_resp or raw_resp == "direct":
            card_type = "direct"
        elif "部分" in raw_resp or raw_resp == "partial":
            card_type = "partial"
        elif "未找到" in raw_resp or raw_resp == "not_found":
            card_type = "not_found"
        else:
            card_type = "non_substantive"

        reason_html = (
            f'<div class="coverage-reason-wrap">'
            f'<span class="coverage-r-label">核查研判结论</span>'
            f'<div class="coverage-reason">{_extract_structured_summary(str(reason))}</div>'
            f'</div>'
            if reason else ""
        )
        cards.append(
            f'<div class="coverage-card coverage-card-{card_type}">'
            f'<div class="coverage-head">'
            f'<div class="coverage-question-wrap">'
            f'<span class="coverage-q-label">公众与媒体核心质询</span>'
            f'<h4 class="coverage-question">{escape(str(question))}</h4>'
            f'</div>'
            f'{_coverage_badge(str(response))}'
            f'</div>'
            f'{pills_row}'
            f'{reason_html}'
            f'{uncovered_html}'
            f'</div>'
        )
    return f'<div class="coverage-grid">{"".join(cards)}</div>'


_ENGLISH_HEADER_LABELS: dict[str, str] = {
    "title": "核心事项",
    "label": "分类标签",
    "summary": "核查结论与摘要",
    "text": "事实陈述",
    "detail": "原文摘录依据",
    "meta": "来源与出处",
    "time": "时间节点",
    "event_time": "事件时间",
    "source_title": "来源文献",
    "note": "备注说明",
    "value": "数值",
}

_INTERNAL_ITEM_KEYS = {"source_finding_ids", "finding_id"}


def _table_keys(
    items: tuple[dict[str, Any], ...],
    preferred_columns: tuple[str, ...] = (),
) -> list[str]:
    available: list[str] = []
    for item in items:
        for key in item:
            if key.startswith("_") or key in _INTERNAL_ITEM_KEYS:
                continue
            if key not in available:
                available.append(key)
    if preferred_columns:
        matched = [col for col in preferred_columns if col in available]
        if matched:
            return matched
    chinese_keys = [k for k in available if k not in _ENGLISH_HEADER_LABELS]
    if chinese_keys:
        return chinese_keys
    return available


def _render_table(module: PlannedModule, keys: list[str] | None = None) -> str:
    if not module.items:
        return _render_text(module)
    keys = keys if keys is not None else _table_keys(module.items, module.table_columns)
    head = "".join(f"<th>{escape(_ENGLISH_HEADER_LABELS.get(str(key), str(key)))}</th>" for key in keys)
    rows = []
    for item in module.items:
        cells = []
        for key in keys:
            raw_val = str(item.get(key, ""))
            escaped_val = _style_inline_citations(escape(raw_val))
            if key == "立场":
                if any(x in raw_val for x in ("支持", "积极", "赞成", "肯定", "理解")):
                    cells.append(f'<td><span class="matrix-stance stance-support">{escaped_val}</span></td>')
                elif any(x in raw_val for x in ("反对", "质疑", "担忧", "不满", "批评", "异议")):
                    cells.append(f'<td><span class="matrix-stance stance-oppose">{escaped_val}</span></td>')
                elif any(x in raw_val for x in ("中立", "客观", "观察", "观望")):
                    cells.append(f'<td><span class="matrix-stance stance-neutral">{escaped_val}</span></td>')
                else:
                    cells.append(f'<td><span class="matrix-stance">{escaped_val}</span></td>')
            elif key in {"主体", "陈述主体"}:
                cells.append(f'<td><span class="matrix-actor">{escaped_val}</span></td>')
            else:
                cells.append(f"<td>{escaped_val}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table class="data-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _render_matrix(module: PlannedModule) -> str:
    """Render a 3-Column Visual Stance Spectrum Swimlane Board + collapsible comparison table."""

    if not module.items:
        return _render_text(module)

    oppose_cards: list[str] = []
    neutral_cards: list[str] = []
    support_cards: list[str] = []

    for item in module.items:
        actor = str(item.get("主体") or item.get("title") or "关联主体")
        stance = str(item.get("立场") or "事实陈述")
        target = str(item.get("目标") or item.get("关联议题") or "")
        basis = str(item.get("依据") or item.get("summary") or item.get("核查判断") or "")
        raw_stance = f"{stance} {item.get('_stance_raw', '')}"

        if any(x in raw_stance for x in ("反对", "质疑", "批评", "oppose", "skeptical")):
            bucket = "oppose"
            badge_cls = "stance-oppose"
        elif any(x in raw_stance for x in ("支持", "辩护", "肯定", "support")):
            bucket = "support"
            badge_cls = "stance-support"
        else:
            bucket = "neutral"
            badge_cls = "stance-neutral"

        target_html = f'<span class="swimlane-target">针对：{escape(_short_node_text(target, 16))}</span>' if target else ""
        card_html = (
            f'<div class="swimlane-card swimlane-card-{bucket}">'
            f'<div class="swimlane-card-head">'
            f'<span class="matrix-actor">{escape(actor)}</span>'
            f'<span class="matrix-stance {badge_cls}">{escape(stance)}</span>'
            f'</div>'
            f'{target_html}'
            f'<div class="swimlane-card-body">{_extract_structured_summary(basis)}</div>'
            f'</div>'
        )
        if bucket == "oppose":
            oppose_cards.append(card_html)
        elif bucket == "support":
            support_cards.append(card_html)
        else:
            neutral_cards.append(card_html)

    total = max(len(module.items), 1)
    p_opp = len(oppose_cards) / total * 100.0
    p_neu = len(neutral_cards) / total * 100.0
    p_sup = len(support_cards) / total * 100.0

    table_keys = list(module.table_columns) if module.table_columns else ["主体", "立场", "目标", "依据", "证据索引"]
    raw_table = _render_table(module, keys=[k for k in table_keys if any(k in it for it in module.items)])

    return (
        f'<div class="stance-spectrum-wrap">'
        f'<div class="stance-spectrum-bar">'
        f'<div class="ss-seg ss-oppose" style="width:{max(p_opp, 8.0):.1f}%">质疑/反对 ({len(oppose_cards)})</div>'
        f'<div class="ss-seg ss-neutral" style="width:{max(p_neu, 8.0):.1f}%">事实/观察 ({len(neutral_cards)})</div>'
        f'<div class="ss-seg ss-support" style="width:{max(p_sup, 8.0):.1f}%">支持/辩护 ({len(support_cards)})</div>'
        f'</div>'
        f'<div class="stance-swimlanes">'
        f'<div class="stance-lane stance-lane-oppose">'
        f'<div class="stance-lane-head"><span>⚡ 质疑与批评阵营</span><strong>{len(oppose_cards)}</strong></div>'
        f'{"".join(oppose_cards) or "<div class=swimlane-empty>暂无显式反对表态</div>"}'
        f'</div>'
        f'<div class="stance-lane stance-lane-neutral">'
        f'<div class="stance-lane-head"><span>⚖️ 事实核查与回应跟进</span><strong>{len(neutral_cards)}</strong></div>'
        f'{"".join(neutral_cards) or "<div class=swimlane-empty>暂无中立观察条目</div>"}'
        f'</div>'
        f'<div class="stance-lane stance-lane-support">'
        f'<div class="stance-lane-head"><span>🛡️ 支持与辩护阵营</span><strong>{len(support_cards)}</strong></div>'
        f'{"".join(support_cards) or "<div class=swimlane-empty>暂无显式支持表态</div>"}'
        f'</div>'
        f'</div>'
        f'<details class="item-details" style="margin-top:12px">'
        f'<summary><span class="details-toggle">展开完整主体立场矩阵对照表</span></summary>'
        f'<div class="details-content">{raw_table}</div>'
        f'</details>'
        f'</div>'
    )


def _aggregate_distribution(items: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    totals: dict[str, float] = {}
    order: list[str] = []
    for item in items:
        label = str(item.get("label") or item.get("title") or "").strip()
        if not label:
            continue
        try:
            value = float(item.get("value", 0))
        except (TypeError, ValueError):
            value = 0.0
        if label not in totals:
            totals[label] = 0.0
            order.append(label)
        totals[label] += value

    aggregated = []
    for label in order:
        value = totals[label]
        aggregated.append(
            {
                "label": label,
                "value": value,
                "display": f"{value:g}",
            }
        )
    return tuple(aggregated)


def _render_distribution(module: PlannedModule) -> str:
    items = _aggregate_distribution(module.items)
    if not items:
        return _render_text(module)

    total = sum(float(item["value"]) for item in items)
    if 2 <= len(items) <= 5 and total > 0:
        # Rich Editorial Paper Palette (Oxford Navy, Crimson, Forest Emerald, Amber, Plum)
        colors = ("#0d2d44", "#8b1e1e", "#14532d", "#b45309", "#581c87")
        segments = []
        start = 0.0
        for index, item in enumerate(items):
            end = start + (float(item["value"]) / total * 100.0)
            segments.append(f'{colors[index % len(colors)]} {start:.2f}% {end:.2f}%')
            start = end
        donut = (
            f'<div class="donut-wrap">'
            f'<div class="donut-chart-box">'
            f'<div class="donut" style="background:conic-gradient({",".join(segments)})">'
            f'<div class="donut-hole"><span class="donut-total">{int(total)}</span><span class="donut-total-label">样本总量</span></div>'
            f'</div>'
            f'</div>'
            f'<div class="donut-legend">'
            + "".join(
                f'<div class="donut-legend-row">'
                f'<span class="donut-dot" style="background:{colors[index % len(colors)]}"></span>'
                f'<span class="donut-label">{escape(str(item["label"]))}</span>'
                f'<span class="donut-pct">{(float(item["value"]) / total * 100.0):.1f}%</span>'
                f'<span class="donut-value">{escape(str(item["display"]))} 份</span>'
                f'</div>'
                for index, item in enumerate(items)
            )
            + '</div></div>'
        )
        return donut

    max_value = max(float(item["value"]) for item in items) if items else 0.0
    bars = []
    for item in items:
        value = float(item["value"])
        width = 0.0 if max_value == 0 else value / max_value * 100.0
        bars.append(
            f'<div class="bar-row">'
            f'<div class="bar-label">{escape(str(item["label"]))}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div>'
            f'<div class="bar-value">{escape(str(item["display"]))}</div>'
            f'</div>'
        )
    return f'<div class="distribution">{"".join(bars)}</div>'


IMAGE_PATTERN = chr(33) + r"\[[^\]]*\]\([^\)]*\)"


def _clean_evidence_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(IMAGE_PATTERN, "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"[#*_>`~]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _render_evidence(module: PlannedModule) -> str:
    if not module.citations:
        return _render_text(module)
    cards = []
    for index, citation in enumerate(module.citations, 1):
        cleaned = _clean_evidence_text(citation.excerpt)
        if not cleaned:
            continue
        summary = cleaned[:220].rstrip()
        if len(cleaned) > 220:
            summary += "…"
        source_label = citation.label or "公开来源材料"
        locator = citation.locator or ""
        locator_html = f'<span class="evidence-locator">{escape(locator)}</span>' if locator else ""
        cards.append(
            '<article class="evidence-card">'
            f'<div class="evidence-head">'
            f'<div class="evidence-source"><span class="evidence-source-tag">卷宗出处</span>{escape(source_label)}</div>'
            f'{locator_html}'
            f'</div>'
            f'<div class="evidence-excerpt">{escape(summary)}</div>'
            f'<details class="item-details">'
            f'<summary><span class="details-toggle">展开卷宗核查原文</span></summary>'
            f'<div class="details-content"><p>{escape(cleaned)}</p></div>'
            f'</details>'
            '</article>'
        )
    return f'<div class="evidence-grid">{"".join(cards)}</div>'


def _css() -> str:
    return '''
:root {
  /* Classic Warm Newsprint Paper Palette (FT / Wall Street Journal Broadsheet) */
  --bg: #f4efe6;
  --bg-page: #fbf8f1;
  --card: #ffffff;
  --card-subtle: #f7f3ea;
  --card-border: #1c1917;
  --card-border-subtle: #c4b8a5;

  --ink: #1c1917;
  --ink-secondary: #38332e;
  --ink-tertiary: #575047;
  --muted: #736b61;

  --line: #ded5c5;
  --line-light: #eae2d3;
  --line-strong: #1c1917;

  /* High-Contrast Editorial Block Colors */
  --navy: #0d2d44;
  --navy-soft: #edf4f9;
  --navy-border: #9ec3de;

  --crimson: #8b1e1e;
  --crimson-soft: #fdf2f2;
  --crimson-border: #fca5a5;

  --green: #14532d;
  --green-soft: #f0fdf4;
  --green-border: #86efac;

  --amber: #92400e;
  --amber-soft: #fefce8;
  --amber-border: #fde047;

  --orange: #9a3412;
  --orange-soft: #fff7ed;
  --orange-border: #fdba74;

  --purple: #581c87;
  --purple-soft: #faf5ff;
  --purple-border: #d8b4fe;

  --font-serif: "Songti SC", "SimSun", "Noto Serif SC", "Source Serif Pro", Georgia, serif;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* Darkroom Dossier Palette (Terminal / Intelligence Dark Mode) */
body.theme-dark {
  --bg: #0c1017;
  --bg-page: #111722;
  --card: #151d2a;
  --card-subtle: #1a2434;
  --card-border: #70a4e8;
  --card-border-subtle: #243248;

  --ink: #f0f4fc;
  --ink-secondary: #d4deee;
  --ink-tertiary: #9ab0ce;
  --muted: #8298b6;

  --line: #243248;
  --line-light: #182232;
  --line-strong: #70a4e8;

  --navy: #70a4e8;
  --navy-soft: #172844;
  --navy-border: #23406e;

  --crimson: #f87171;
  --crimson-soft: #381212;
  --crimson-border: #7f1d1d;

  --green: #4ade80;
  --green-soft: #082813;
  --green-border: #14532d;

  --amber: #fbbf24;
  --amber-soft: #382405;
  --amber-border: #78350f;

  --orange: #fb923c;
  --orange-soft: #3c1505;
  --orange-border: #7c2d12;

  --purple: #c084fc;
  --purple-soft: #28143c;
  --purple-border: #6b21a8;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  line-height: 1.72;
  -webkit-font-smoothing: antialiased;
  transition: background .2s ease, color .2s ease;
}

/* Masthead Header */
.page-header {
  max-width: 1200px;
  margin: 0 auto;
  padding: 34px 32px 20px;
}

.masthead-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
}

.masthead-meta {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.masthead-vol {
  color: var(--navy);
  font-weight: 850;
}

.masthead-dept {
  color: var(--ink);
  font-weight: 800;
  letter-spacing: .12em;
}

.masthead-sec {
  background: var(--navy-soft);
  color: var(--navy);
  border: 1px solid var(--navy-border);
  padding: 1px 7px;
  border-radius: 2px;
  font-weight: 800;
  font-size: 10.5px;
}

.masthead-sep { color: var(--line); }

.masthead-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.theme-toggle-btn, .print-btn {
  background: var(--card);
  border: 1.5px solid var(--card-border-subtle);
  color: var(--ink);
  padding: 4px 11px;
  font-size: 11.5px;
  font-weight: 750;
  cursor: pointer;
  border-radius: 2px;
  transition: all .15s ease;
}

.theme-toggle-btn:hover, .print-btn:hover {
  background: var(--ink);
  color: #ffffff;
  border-color: var(--ink);
}

.masthead-brand-wrap {
  text-align: center;
  padding: 6px 0 14px;
}

.masthead-title-sub {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .28em;
  text-transform: uppercase;
  color: var(--navy);
  font-weight: 850;
  margin-bottom: 4px;
}

.masthead-title {
  font-family: var(--font-serif);
  font-size: 32px;
  font-weight: 900;
  letter-spacing: .08em;
  color: var(--ink);
}

.editorial-divider-double {
  border-top: 3px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
  height: 5px;
  margin-bottom: 22px;
}

/* High-Contrast Headline Hero Block on Paper */
.headline-wrap.headline-card {
  background: #ffffff;
  border: 1.5px solid var(--card-border-subtle);
  border-left: 6px solid var(--navy);
  border-radius: 2px;
  padding: 26px 30px;
  box-shadow: 0 4px 14px rgba(40, 32, 20, 0.08);
  margin-bottom: 22px;
}

.headline-kicker-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.headline-kicker {
  font-size: 11px;
  font-weight: 850;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: #ffffff;
  background: var(--crimson);
  padding: 3px 8px;
  border-radius: 2px;
  display: inline-block;
}

.headline-badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 800;
  color: var(--navy);
  background: var(--navy-soft);
  border: 1px solid var(--navy-border);
  padding: 2px 7px;
  border-radius: 2px;
}

.headline-main {
  font-family: var(--font-serif);
  font-size: 34px;
  line-height: 1.25;
  margin: 0 0 16px;
  font-weight: 900;
  letter-spacing: -0.015em;
  color: var(--ink);
}

.dateline-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: var(--ink-secondary);
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.dateline-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dateline-label {
  font-weight: 800;
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .05em;
}

.dateline-sep { color: var(--line); }

.status-tag {
  font-weight: 850;
  padding: 2px 9px;
  border-radius: 2px;
  font-size: 11.5px;
}

.status-completed { color: #ffffff; background: var(--green); }
.status-partial { color: #ffffff; background: var(--amber); }
.status-failed, .status-cancelled { color: #ffffff; background: var(--crimson); }
.status-running, .status-finalizing { color: #ffffff; background: var(--navy); }

/* High-Contrast Audit Fact-Check Radar Panel on Paper */
.audit-panel {
  background: #ffffff;
  border: 1.5px solid var(--line-strong);
  border-radius: 2px;
  padding: 18px 22px;
  box-shadow: 0 4px 14px rgba(40, 32, 20, 0.06);
  margin-top: 20px;
}

.audit-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 850;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--ink);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1.5px solid var(--line);
}

.audit-panel-badge {
  font-family: var(--font-mono);
  color: #ffffff;
  background: var(--navy);
  font-size: 10.5px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 2px;
}

.status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.summary-pill {
  font-size: 12px;
  font-weight: 800;
  padding: 5px 12px;
  border-radius: 2px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

.summary-pill strong {
  background: rgba(0, 0, 0, 0.25);
  padding: 1px 7px;
  border-radius: 2px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  margin-left: 4px;
}

.summary-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ffffff;
}

.summary-ready { background: var(--green); }
.summary-provisional { background: var(--amber); }
.summary-insufficient { background: var(--crimson); }
.summary-unavailable { background: #5f1515; }
.summary-pending { background: var(--navy); }
.summary-not_found, .summary-not_applicable, .summary-omitted { background: #57534e; }

/* Newsprint Sticky Navigation Bar */
.nav-sticky-wrap {
  position: sticky;
  top: 0;
  z-index: 40;
  background: var(--bg-page);
  border-top: 1px solid var(--line);
  border-bottom: 2px solid var(--line-strong);
  margin-bottom: 30px;
  box-shadow: 0 4px 12px rgba(40, 32, 20, 0.08);
}

.nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.view-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 8px 0;
}

.view-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1.5px solid transparent;
  background: transparent;
  color: var(--ink-secondary);
  padding: 7px 14px;
  font-size: 13.5px;
  font-weight: 750;
  cursor: pointer;
  white-space: nowrap;
  border-radius: 2px;
  transition: all .15s ease;
}

.view-tab:hover {
  color: var(--ink);
  background: var(--card-subtle);
  border-color: var(--card-border-subtle);
}

.view-tab.active {
  color: #ffffff;
  background: var(--ink);
  border-color: var(--ink);
  font-weight: 850;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2);
}

.tab-index {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 850;
  color: var(--muted);
}

.view-tab.active .tab-index {
  color: #fde047;
  font-weight: 900;
}

.view-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.view-actions button {
  border: 1.5px solid var(--card-border-subtle);
  background: var(--card);
  color: var(--ink-secondary);
  border-radius: 2px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
  transition: all .15s ease;
}

.view-actions button:hover {
  background: var(--ink);
  color: #ffffff;
  border-color: var(--ink);
}

.view-panel { display: none; }
.view-panel.active { display: block; }

main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px 80px;
}

.section {
  margin-top: 36px;
}

.section-head-wrap {
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 2px solid var(--line-strong);
  padding-bottom: 8px;
}

.section-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: .12em;
  text-transform: uppercase;
  background: var(--line-strong);
  color: #ffffff;
  padding: 3px 8px;
  border-radius: 2px;
}

.section-title {
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 900;
  color: var(--ink);
  margin: 0;
  letter-spacing: -0.01em;
}

.module-grid {
  display: grid;
  gap: 24px;
}

/* High-Contrast Module Card with Category Top Borders on Paper */
.card.module {
  background: #ffffff;
  border: 1.5px solid var(--card-border-subtle);
  border-top: 4px solid var(--ink);
  border-radius: 2px;
  padding: 26px 28px;
  box-shadow: 0 4px 14px rgba(40, 32, 20, 0.06);
}

.card.module[data-module="event-summary"] { border-top: 5px solid var(--navy); }
.card.module[data-module="current-judgments"] { border-top: 5px solid var(--purple); }
.card.module[data-module="opinion-topics"],
.card.module[data-module="public-debate"] { border-top: 5px solid var(--crimson); }
.card.module[data-module="response-coverage"] { border-top: 5px solid var(--green); }
.card.module[data-module="evidence"] { border-top: 5px solid var(--ink); }

.module-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1.5px solid var(--line);
}

.module-title-group h3 {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 850;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.state {
  display: inline-flex;
  align-items: center;
  font-size: 11.5px;
  font-weight: 850;
  padding: 2px 8px;
  border-radius: 2px;
  border: 1.5px solid;
  white-space: nowrap;
}

.state-ready { color: var(--green); background: var(--green-soft); border-color: var(--green); }
.state-provisional { color: var(--amber); background: var(--amber-soft); border-color: var(--amber); }
.state-insufficient { color: var(--crimson); background: var(--crimson-soft); border-color: var(--crimson); }
.state-unavailable { color: var(--crimson); background: var(--crimson-soft); border-color: var(--crimson); }
.state-pending { color: var(--navy); background: var(--navy-soft); border-color: var(--navy); }
.state-not_found, .state-not_applicable, .state-omitted { color: var(--muted); background: var(--card-subtle); border-color: var(--line); }

.module-summary {
  margin: 18px 0;
  padding: 14px 18px;
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-left: 4px solid var(--navy);
  border-radius: 0 2px 2px 0;
  color: var(--ink);
  font-size: 14.5px;
  line-height: 1.7;
}

.summary-label {
  display: block;
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
  color: var(--navy);
  letter-spacing: .08em;
  margin-bottom: 4px;
}

.empty-state, .empty-reason {
  margin-top: 14px;
  padding: 12px 16px;
  background: var(--card-subtle);
  border: 1px dashed var(--line);
  color: var(--muted);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 2px;
}

.empty-tag {
  font-size: 11px;
  font-weight: 800;
  color: var(--muted);
  text-transform: uppercase;
  border: 1px solid var(--line);
  padding: 1px 6px;
  border-radius: 2px;
}

.limitations {
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--amber-soft);
  border: 1px solid var(--amber-border);
  border-left: 4px solid var(--amber);
  border-radius: 0 2px 2px 0;
  color: var(--amber);
  font-size: 12.5px;
}

.limitations-head {
  font-weight: 850;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: .05em;
  font-size: 11.5px;
}

.limitations ul {
  margin: 4px 0 0 18px;
  padding: 0;
}
'''


def _extra_css() -> str:
    return '''
/* Cards & Briefing Items */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-top: 18px;
}

.item-card {
  border: 1.5px solid var(--card-border-subtle);
  border-radius: 2px;
  padding: 22px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  box-shadow: 0 3px 10px rgba(40, 32, 20, 0.05);
  transition: transform .15s ease, box-shadow .15s ease;
}

.item-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(40, 32, 20, 0.09);
  border-color: var(--line-strong);
}

.item-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.item-badge-index {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 850;
  color: #ffffff;
  background: var(--navy);
  padding: 2px 7px;
  border-radius: 2px;
  letter-spacing: .06em;
}

.item-title {
  font-size: 16px;
  font-weight: 850;
  color: var(--ink);
  line-height: 1.45;
  flex: 1;
}

.item-summary {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink-secondary);
  margin: 8px 0;
}

.review-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 850;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1.5px solid;
  margin-left: 6px;
  vertical-align: middle;
}

.review-partial { color: var(--amber); background: var(--amber-soft); border-color: var(--amber); }
.review-insufficient { color: var(--orange); background: var(--orange-soft); border-color: var(--orange); }
.review-contradicted { color: var(--crimson); background: var(--crimson-soft); border-color: var(--crimson); }

.review-reason {
  margin: 10px 0;
  padding: 10px 14px;
  background: var(--amber-soft);
  border: 1px solid var(--amber-border);
  border-left: 4px solid var(--amber);
  font-size: 12.5px;
  color: var(--amber);
  line-height: 1.6;
  border-radius: 0 2px 2px 0;
}

.review-tag {
  font-weight: 900;
  margin-right: 6px;
}

.item-details {
  margin-top: 10px;
  border-top: 1px dashed var(--line);
  padding-top: 8px;
}

.item-details summary {
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 800;
  color: var(--navy);
  list-style: none;
}

.item-details summary::-webkit-details-marker { display: none; }
.item-details summary:before { content: "＋ "; font-weight: 900; }
.item-details[open] summary:before { content: "－ "; font-weight: 900; }

.details-content {
  margin-top: 10px;
  padding: 14px 16px;
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-left: 4px solid var(--line-strong);
  font-family: var(--font-serif);
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ink-secondary);
  border-radius: 0 2px 2px 0;
}

.details-content p { margin: 0; }

.item-meta {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--line-light);
  font-size: 11.5px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-source-label {
  font-weight: 850;
  text-transform: uppercase;
  letter-spacing: .05em;
  font-size: 10.5px;
  color: var(--muted);
  border: 1px solid var(--line);
  padding: 1px 5px;
  border-radius: 2px;
}

/* Timeline: Chronological Dossier */
.timeline {
  position: relative;
  margin-top: 20px;
  padding-left: 10px;
}

.timeline:before {
  content: "";
  position: absolute;
  left: 18px;
  top: 14px;
  bottom: 14px;
  width: 2px;
  background: var(--line-strong);
}

.timeline-item {
  position: relative;
  margin-bottom: 22px;
}

.timeline-dot-wrap {
  position: absolute;
  left: 13px;
  top: 18px;
}

.timeline-dot {
  width: 12px;
  height: 12px;
  background: var(--navy);
  border: 2px solid #ffffff;
  box-shadow: 0 0 0 2px var(--navy);
  border-radius: 2px;
}

.timeline-card {
  margin-left: 42px;
  border: 1.5px solid var(--card-border-subtle);
  border-left: 5px solid var(--navy);
  border-radius: 2px;
  padding: 20px 22px;
  background: #ffffff;
  box-shadow: 0 3px 10px rgba(40, 32, 20, 0.05);
}

.timeline-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.timeline-time {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 850;
  color: #ffffff;
  background: var(--line-strong);
  padding: 3px 9px;
  border-radius: 2px;
}

.timeline-title {
  font-size: 16px;
  font-weight: 850;
  color: var(--ink);
}

.timeline-text {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink-secondary);
  margin-top: 6px;
}

.timeline-meta {
  margin-top: 12px;
  border-top: 1px solid var(--line-light);
  padding-top: 8px;
  font-size: 11.5px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.timeline-arrow { display: none; }

/* Fact-Check Response Coverage Matrix - Distinct High-Contrast Block Palette */
.coverage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  margin-top: 18px;
}

.coverage-card {
  border: 1.5px solid var(--card-border-subtle);
  border-radius: 2px;
  padding: 22px;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 3px 10px rgba(40, 32, 20, 0.05);
}

.coverage-card-direct {
  background: var(--green-soft);
  border-color: var(--green-border);
  border-left: 6px solid var(--green);
}

.coverage-card-partial {
  background: var(--amber-soft);
  border-color: var(--amber-border);
  border-left: 6px solid var(--amber);
}

.coverage-card-not_found {
  background: var(--crimson-soft);
  border-color: var(--crimson-border);
  border-left: 6px solid var(--crimson);
}

.coverage-card-non_substantive, .coverage-card-unknown {
  background: var(--card-subtle);
  border-color: var(--line);
  border-left: 6px solid var(--muted);
}

.coverage-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.coverage-q-label {
  font-size: 10.5px;
  font-weight: 850;
  text-transform: uppercase;
  color: var(--muted);
  letter-spacing: .08em;
  display: block;
  margin-bottom: 4px;
}

.coverage-question {
  font-family: var(--font-serif);
  font-size: 16.5px;
  font-weight: 850;
  color: var(--ink);
  margin: 0;
  line-height: 1.45;
}

.coverage-badge {
  font-size: 11.5px;
  font-weight: 850;
  padding: 3px 10px;
  border-radius: 2px;
  border: 1.5px solid transparent;
  white-space: nowrap;
  color: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

.coverage-direct { background: var(--green); }
.coverage-partial { background: var(--amber); }
.coverage-not_found { background: var(--crimson); }
.coverage-non_substantive, .coverage-unknown { background: var(--muted); }

.coverage-r-label {
  font-size: 10.5px;
  font-weight: 850;
  color: var(--navy);
  text-transform: uppercase;
  letter-spacing: .06em;
  display: block;
  margin-bottom: 4px;
}

.coverage-reason {
  font-size: 13.5px;
  line-height: 1.68;
  color: var(--ink-secondary);
  margin: 0;
}

.coverage-uncovered {
  padding: 14px 16px;
  background: var(--orange-soft);
  border: 1.5px solid var(--orange-border);
  border-left: 5px solid var(--orange);
  border-radius: 2px;
  margin-top: auto;
}

.uncovered-title {
  font-size: 11.5px;
  font-weight: 900;
  color: var(--orange);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-bottom: 4px;
}

.uncovered-text {
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--orange);
}

/* High-Contrast Data Tables & Matrix on Paper */
.table-wrap {
  border: 1.5px solid var(--line-strong);
  border-radius: 2px;
  overflow-x: auto;
  margin-top: 18px;
  background: #ffffff;
  box-shadow: 0 3px 10px rgba(40, 32, 20, 0.05);
}

table.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
  line-height: 1.6;
}

th {
  background: var(--ink);
  color: var(--bg-page);
  font-weight: 850;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
  padding: 13px 16px;
  border: none;
  text-align: left;
}

td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  color: var(--ink-secondary);
  font-variant-numeric: tabular-nums;
}

tr:nth-child(even) td { background: var(--card-subtle); }
tr:hover td { background: rgba(13, 45, 68, 0.05); }

.matrix-actor {
  font-weight: 850;
  color: var(--ink);
}

.matrix-stance {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 2px;
  font-size: 11.5px;
  font-weight: 850;
  color: #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

.stance-support { background: var(--green); }
.stance-oppose { background: var(--crimson); }
.stance-neutral { background: var(--navy); }

/* Distribution Graphics (Editorial Chart) */
.donut-wrap {
  display: flex;
  align-items: center;
  gap: 32px;
  margin-top: 18px;
  flex-wrap: wrap;
}

.donut-chart-box {
  position: relative;
}

.donut {
  width: 150px;
  height: 150px;
  border-radius: 50%;
  position: relative;
  box-shadow: 0 2px 8px rgba(40, 32, 20, 0.12);
}

.donut-hole {
  position: absolute;
  inset: 34px;
  background: #ffffff;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.08);
}

.donut-total {
  font-family: var(--font-mono);
  font-size: 26px;
  font-weight: 850;
  color: var(--ink);
  line-height: 1;
}

.donut-total-label {
  font-size: 10.5px;
  font-weight: 850;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
  margin-top: 3px;
}

.donut-legend {
  display: grid;
  gap: 10px;
  flex: 1;
  min-width: 220px;
}

.donut-legend-row {
  display: grid;
  grid-template-columns: 10px 1fr auto auto;
  gap: 12px;
  align-items: center;
  font-size: 13.5px;
  padding: 8px 14px;
  background: #ffffff;
  border: 1.5px solid var(--line);
  border-radius: 2px;
  transition: all .15s ease;
}

.donut-legend-row:hover {
  border-color: var(--line-strong);
  background: var(--card-subtle);
}

.donut-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.donut-label {
  font-weight: 750;
  color: var(--ink);
}

.donut-pct {
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-weight: 850;
  color: var(--navy);
}

.donut-value {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.distribution { margin-top: 16px; }
.bar-row {
  display: grid;
  grid-template-columns: 140px 1fr 60px;
  gap: 12px;
  align-items: center;
  margin: 12px 0;
  font-size: 13px;
}

.bar-label {
  font-weight: 750;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bar-track {
  height: 10px;
  background: var(--card-subtle);
  border: 1px solid var(--card-border-subtle);
  border-radius: 2px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--navy);
}

.bar-value {
  text-align: right;
  font-family: var(--font-mono);
  font-weight: 850;
  color: var(--ink);
}

/* Archival Evidence Dossier */
.evidence-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 20px;
  margin-top: 18px;
}

.evidence-card {
  border: 1.5px solid var(--card-border-subtle);
  border-top: 4px solid var(--line-strong);
  border-radius: 2px;
  padding: 22px;
  background: #ffffff;
  box-shadow: 0 3px 10px rgba(40, 32, 20, 0.05);
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}

.evidence-source {
  font-weight: 850;
  color: var(--ink);
  font-size: 14.5px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.evidence-source-tag {
  font-size: 10.5px;
  font-weight: 850;
  text-transform: uppercase;
  color: #ffffff;
  background: var(--navy);
  padding: 2px 7px;
  border-radius: 2px;
}

.evidence-locator {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.evidence-excerpt {
  font-family: var(--font-serif);
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ink-secondary);
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-left: 4px solid var(--line-strong);
  padding: 12px 16px;
  margin-bottom: 12px;
  border-radius: 0 2px 2px 0;
}

.page-footer {
  text-align: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 32px 48px;
  color: var(--muted);
  font-size: 12px;
  border-top: 1px solid var(--line);
  letter-spacing: .06em;
  text-transform: uppercase;
}

.cite-pill {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 800;
  color: var(--navy);
  background: var(--navy-soft);
  border: 1px solid var(--navy-border);
  padding: 0 6px;
  margin: 0 2px;
  border-radius: 3px;
  vertical-align: baseline;
}

.kp-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kp-headline-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  line-height: 1.5;
}

.kp-kicker {
  font-size: 11px;
  font-weight: 850;
  color: var(--navy);
  background: var(--navy-soft);
  border: 1px solid var(--navy-border);
  padding: 1px 7px;
  border-radius: 2px;
}

.kp-headline {
  font-size: 14.5px;
  font-weight: 850;
  color: var(--ink);
}

.kp-list {
  margin: 2px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kp-bullet {
  font-size: 13px;
  color: var(--ink-secondary);
  line-height: 1.55;
}

.relation-graph-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rg-legend-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-radius: 3px;
  font-size: 12px;
  font-weight: 700;
}

.rg-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.rg-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.rg-legend-tip {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--muted);
  font-weight: 600;
}

.rg-canvas-box {
  background: var(--bg-page);
  border: 1.5px solid var(--card-border-subtle);
  border-radius: 4px;
  padding: 10px;
  overflow-x: auto;
}

.relation-graph-svg {
  display: block;
  min-width: 720px;
}

.rg-node rect {
  transition: filter .15s ease, stroke-width .15s ease;
}

.rg-node:hover rect, .rg-node.rg-node-active rect {
  stroke-width: 3.2px;
  filter: drop-shadow(0 3px 8px rgba(13, 45, 68, 0.22));
}

.rg-inspector {
  background: var(--card);
  border: 1.5px solid var(--navy-border);
  border-left: 5px solid var(--navy);
  padding: 12px 16px;
  border-radius: 3px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.rg-insp-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rg-insp-badge {
  font-size: 10.5px;
  font-weight: 850;
  text-transform: uppercase;
  background: var(--navy);
  color: #fff;
  padding: 2px 7px;
  border-radius: 2px;
}

.rg-insp-role {
  font-size: 11.5px;
  font-weight: 750;
  color: var(--crimson);
  background: var(--crimson-soft);
  border: 1px solid var(--crimson-border);
  padding: 1px 8px;
  border-radius: 2px;
}

.rg-insp-summary {
  font-size: 13.5px;
  color: var(--ink-secondary);
  line-height: 1.55;
}

.rg-insp-cites {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 750;
  color: var(--navy);
}

.vs-tug-wrap {
  margin-top: 10px;
  padding: 10px 14px;
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-radius: 3px;
}

.vs-tug-labels {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 6px;
  gap: 8px;
  flex-wrap: wrap;
}

.vs-side-left { color: var(--crimson); }
.vs-side-right { color: var(--green); }
.vs-center-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.vs-tug-bar {
  display: flex;
  height: 10px;
  border-radius: 5px;
  overflow: hidden;
  background: var(--line);
  gap: 2px;
}

.vs-tug-fill-left { background: var(--crimson); }
.vs-tug-fill-right { background: var(--green); }

.stance-spectrum-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.stance-spectrum-bar {
  display: flex;
  border-radius: 4px;
  overflow: hidden;
  font-size: 11.5px;
  font-weight: 850;
  color: #fff;
  text-align: center;
}

.ss-seg {
  padding: 6px 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ss-oppose { background: var(--crimson); }
.ss-neutral { background: var(--navy); }
.ss-support { background: var(--green); }

.stance-swimlanes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.stance-lane {
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stance-lane-oppose { border-top: 4px solid var(--crimson); }
.stance-lane-neutral { border-top: 4px solid var(--navy); }
.stance-lane-support { border-top: 4px solid var(--green); }

.stance-lane-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 850;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}

.swimlane-card {
  background: var(--card);
  border: 1px solid var(--card-border-subtle);
  border-radius: 3px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.swimlane-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.swimlane-target {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
}

.swimlane-empty {
  font-size: 12px;
  color: var(--muted);
  text-align: center;
  padding: 16px 0;
}

.tl-flow-track {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding: 14px 16px;
  margin-bottom: 16px;
  background: var(--card-subtle);
  border: 1px solid var(--line);
  border-radius: 4px;
}

.tl-flow-step {
  min-width: 145px;
  background: var(--card);
  border: 1.5px solid var(--navy-border);
  border-top: 3px solid var(--navy);
  border-radius: 3px;
  padding: 8px 10px;
  flex-shrink: 0;
}

.tl-flow-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 850;
  color: var(--crimson);
  margin-bottom: 3px;
}

.tl-flow-title {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--ink);
}

.tl-flow-arrow {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 900;
  color: var(--navy);
  flex-shrink: 0;
}

.cov-pills-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 4px;
}

.cov-pill {
  font-size: 11.5px;
  font-weight: 750;
  padding: 2px 8px;
  border-radius: 3px;
}

.cov-pill-ok {
  color: var(--green);
  background: var(--green-soft);
  border: 1px solid var(--green-border);
}

.cov-pill-gap {
  color: var(--crimson);
  background: var(--crimson-soft);
  border: 1px solid var(--crimson-border);
}

@media print {
  .nav-sticky-wrap, .view-actions, .masthead-controls { display: none !important; }
  .view-panel { display: block !important; margin-bottom: 40px; page-break-after: always; }
  body { background: #fff !important; }
  .card.module { box-shadow: none !important; border: 1px solid #000 !important; }
}

@media (max-width: 768px) {
  .page-header { padding: 24px 16px 14px; }
  .headline-main { font-size: 26px; }
  .nav-inner { padding: 0 16px; }
  main { padding: 0 16px 60px; }
  .cards, .coverage-grid, .evidence-grid, .stance-swimlanes { grid-template-columns: 1fr; }
  .view-tab { padding: 8px 10px; font-size: 13px; }
}
'''
