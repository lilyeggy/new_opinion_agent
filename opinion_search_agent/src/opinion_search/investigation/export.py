"""Self-contained HTML export of a published workbench snapshot.

The export is a rendering outlet, not a second authority: it consumes the same
``opinion-workbench/1`` projection the interactive page uses, so page, export,
Markdown and version comparison always describe one committed version. No model
output is ever treated as markup — every value is escaped, and the only
generated structure is the fixed template below.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

STYLESHEET = Path(__file__).resolve().parent.parent / "web" / "assets" / "workbench.css"
TOKENSHEET = Path(__file__).resolve().parent.parent / "web" / "assets" / "style.css"

# Base reset for the standalone document: the online page gets this from
# style.css, the export must carry its own copy so tokens resolve offline.
EXPORT_BASE = """
* { box-sizing: border-box; }
body { margin: 0; padding: 22px; background: var(--bg); color: var(--ink);
  font: 15px/1.65 -apple-system, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; }
a { color: var(--accent); }
mark { background: #ffe08a; color: #1d2129; }
@media (max-width: 1040px) { body { padding: 0; } }
"""

STATUS_LABELS = {"completed": "调查完成", "partial": "部分完成", "failed": "调查失败",
                 "cancelled": "已取消", "running": "调查进行中"}
ROLE_LABELS = {"original": "机构原文", "reporting": "新闻报道", "commentary": "评论文章", "unknown": "来源类型未知"}
RELATION_LABELS = {"duplicate": "与已有版本正文重复", "same_text": "与已有版本正文一致",
                   "repost": "转载/转述关系", "excerpt": "摘录/引用关系",
                   "followup": "后续跟进材料", "unverified": "来源关系未核实"}
REVIEW_LABELS = {"supported": "引用支持", "partial": "证据部分支持", "contradicted": "与引用矛盾",
                 "insufficient": "证据不足", "unreviewed": "尚未完成核查"}
KIND_LABELS = {"fact": "事实", "attributed": "归因转述", "interpretation": "解释", "request": "诉求"}
RESPONSE_LABELS = {"direct": "直接回答", "partial": "部分回答", "non_substantive": "涉及但未实质回答",
                   "not_found": "范围内未发现回应", "unknown": "无法判断"}
MODULE_STATE_LABELS = {"ready": "可查看", "provisional": "待核查", "insufficient": "材料不足",
                       "unavailable": "无法查看", "not_applicable": "不适用"}


def render_page(workbench: dict, report: dict | None = None, evidence_context: dict | None = None,
                generated_at: datetime | None = None) -> str:
    """Render one committed snapshot into a single self-contained HTML document."""

    report = report or {}
    contexts = evidence_context or {}
    overview = workbench["views"]["overview"]
    coverage = workbench["views"]["coverage"]
    issues = workbench["views"]["issues"]["issues"]
    citations = workbench.get("citations", {})
    evidence_index = {item["evidence_id"]: item for item in report.get("evidence", [])}
    sources = {item["version_id"]: item for item in report.get("sources", [])}
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    offline = overview.get("mode") == "offline"
    state = workbench.get("publication_state", "")
    limitations = workbench.get("limitations", {})

    body = [
        _header(offline),
        '<div class="os-frame">',
        _nav(state),
        "<main>",
        _heading(workbench, overview, coverage),
        _summary(overview, citations),
        '<div class="os-main-grid"><div class="os-content">',
        _overview_section(workbench, overview, citations),
        _coverage_section(coverage, citations),
        _issues_section(issues, citations),
        _citations_section(citations, evidence_index, sources, contexts),
        "</div>",
        _inspector(workbench, overview, citations, evidence_index, sources, contexts),
        "</div>",
        _footer(workbench, report, stamp, limitations),
        "</main></div>",
    ]
    return ("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{_esc(overview.get('subject', '事件工作台'))}｜OpinionSearch 事件工作台</title>\n"
            f"<style>\n{_stylesheet()}\n</style>\n</head>\n<body>\n"
            '<div id="os-professional-workbench" class="os-page">\n'
            + "\n".join(part for part in body if part)
            + "\n</div>\n</body>\n</html>\n")


def _stylesheet() -> str:
    parts = [EXPORT_BASE]
    for path in (TOKENSHEET, STYLESHEET):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(parts)


def _esc(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _safe_url(value) -> str:
    text = str(value or "")
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    return text if parts.scheme in {"http", "https"} and parts.hostname else ""


def _citation(citations: dict, evidence_id: str) -> str:
    entry = citations.get(evidence_id)
    if not entry:
        return ""
    return entry["label"]


def _cite_links(citations: dict, ids, *, prefix="") -> str:
    links = []
    for evidence_id in ids or ():
        entry = citations.get(evidence_id)
        if not entry:
            continue
        links.append(f'<a class="os-inline" href="#cite-{entry["index"]}" '
                     f'title="{_esc(entry.get("source_title", ""))}">{_esc(entry["label"])}</a>')
    return (prefix + " ".join(links)) if links else ""


def _header(offline: bool) -> str:
    badge = "静态导出 · 事件与材料以快照为准" if not offline else "静态导出 · 虚构材料演示"
    return ('<header class="os-top"><div class="os-brand">Opinion<span>Search</span>'
            f'<small> / 事件工作台</small></div><span class="os-demo">{badge}</span></header>')


def _nav(state: str) -> str:
    provisional = state not in {"completed", "partial", "failed", "cancelled"}
    note = "（阶段投影，待核查）" if provisional else ""
    return (
        '<nav class="os-nav" aria-label="调查视图"><p>当前调查</p>'
        f'<a href="#sec-overview" aria-current="true">事件总览{note}</a>'
        '<a href="#sec-coverage">报道对照</a>'
        '<a href="#sec-issues">议题与核查</a>'
        '<a href="#sec-citations">引用与原文</a>'
        "</nav>")


def _heading(workbench, overview, coverage) -> str:
    profile = workbench.get("profile", {})
    facets = "、".join(profile.get("facets", [])) or "general"
    state = STATUS_LABELS.get(workbench.get("publication_state", ""), workbench.get("publication_state", ""))
    materials = coverage.get("materials", [])
    known = [m for m in materials if m.get("published_at")]
    window_value = ""
    if known:
        days = sorted(str(m["published_at"])[:10] for m in known)
        window_value = f"{days[0]} — {days[-1]}"
    coverage_lines = [
        f'{_esc(entry["question"])}：尝试 {entry["attempts"]} 次'
        + (f'（定向 {entry["targeted"]} 次）' if entry.get("targeted") else "")
        + (f'，失败 {entry["errors"]} 次（失败不等于无材料）' if entry.get("errors") else "")
        for entry in coverage.get("search_coverage", [])
    ]
    scope = ""
    if coverage_lines:
        scope = ('<details class="os-scope-panel"><summary>查看检索范围（本次已查范围，非全网召回率）</summary>'
                 + "".join(f"<div>{line}</div>" for line in coverage_lines) + "</details>")

    def meta(label, value):
        return f'<span class="os-meta-item"><span>{_esc(label)}</span><b>{_esc(value)}</b></span>'

    return (
        '<div class="os-heading">'
        '<div class="os-eyebrow"><span>事件侧重点</span>'
        f'<b>{_esc(facets)}</b><span class="os-sep">·</span>'
        f'<span>快照 {_esc(str(workbench.get("snapshot_id", ""))[-8:])}</span>'
        '<span class="os-sep">·</span><span>静态导出</span>'
        f'<span class="os-tag">{_esc(state)}</span>'
        + ('<span class="os-tag warn">虚构材料演示</span>' if overview.get("mode") == "offline" else "")
        + '</div>'
        f'<div class="os-title-row"><h2>{_esc(overview.get("subject", ""))}</h2></div>'
        '<div class="os-scope-row">'
        + meta("排查问题", overview.get("question", ""))
        + meta("收录材料", f"{len(materials)} 篇")
        + (meta("材料发布窗口", window_value) if window_value else "")
        + meta("发布时未知", f"{sum(1 for m in materials if not m.get('published_at'))} 篇")
        + "</div>"
        f"{scope}</div>")


def _summary(overview, citations) -> str:
    judgments = overview.get("judgments", [])
    if not judgments:
        return ('<section class="os-summary"><div class="os-summary-title">'
                '<span class="os-tag warn">当前研判</span><span class="os-meta">尚无可对外核查的核心判断</span>'
                '</div><p class="os-note">本轮材料不足以形成已核查的核心判断，未完成问题保持未知。</p></section>')
    lead = judgments[0]
    rest = judgments[1:]
    rest_html = "".join(
        f'<div><p>{_esc(item["text"])} {_cite_links(citations, item.get("citation_ids"))}</p>'
        f'<div class="os-note">核查：{_esc(REVIEW_LABELS.get(item.get("review", ""), item.get("review", "")))}</div></div>'
        for item in rest)
    return (
        '<section class="os-summary">'
        '<div class="os-summary-title"><span class="os-tag">当前研判</span>'
        '<span class="os-meta">每条判断都可下钻到保存的原文与核查状态</span></div>'
        f'<h3>{_esc(lead["text"])}</h3>'
        f'<p>{_cite_links(citations, lead.get("citation_ids"), prefix="依据：")}</p>'
        f'<div class="os-note">核查：{_esc(REVIEW_LABELS.get(lead.get("review", ""), lead.get("review", "")))}</div>'
        f"{rest_html}</section>")


def _bars(distribution) -> str:
    if not distribution:
        return '<p class="os-note">缺少可靠发布日期，不绘制材料发布时间分布。</p>'
    buckets = distribution.get("buckets", [])
    peak = max([bucket["count"] for bucket in buckets] or [1])
    cells = []
    for bucket in buckets:
        height = max(6, round(bucket["count"] / peak * 56))
        cells.append(
            '<div class="os-day"><span>' + str(bucket["count"]) + "</span>"
            f'<span class="os-day-bars"><span class="os-day-bar" style="height:{height}px"></span></span>'
            f'<span class="os-day-date">{_esc(str(bucket["date"])[5:])}</span>'
            f'<span class="os-day-note">{_esc(len(bucket.get("members", [])))} 个页面</span></div>')
    unknown = ""
    if distribution.get("unknown_count"):
        unknown = (f'<p class="os-note">发布时间未知：{distribution["unknown_count"]} 篇'
                   f'（涉及 {distribution.get("unknown_documents", 0)} 个页面），不计入上图。</p>')
    return f'<div class="os-day-list">{"".join(cells)}</div>{unknown}'


def _overview_section(workbench, overview, citations) -> str:
    highlighted = [m for m in overview.get("highlights", []) if m.get("facet")]
    all_facets = [m for m in workbench.get("modules", []) if m.get("facet")]
    modules = highlighted or all_facets
    cards = "".join(_module_card(module, citations) for module in modules)
    timeline = overview.get("timeline", {})
    events = timeline.get("events", []) + timeline.get("unparsed", [])
    nodes = "".join(f'<div>{_esc(node.get("event_time", ""))} {_esc(node["text"])} '
                    f'{_cite_links(citations, node.get("citation_ids"))}</div>' for node in events)
    limitations = workbench.get("limitations", {})
    failure_note = ""
    if limitations.get("search_failures") or limitations.get("read_failures"):
        failure_note = (f'<p class="os-open-question">本轮存在供应商搜索/读取失败'
                        f'（搜索失败 {limitations.get("search_failures", 0)}，读取失败 {limitations.get("read_failures", 0)}）：'
                        "缺失材料不代表没有新进展。</p>")
    return (
        '<section class="os-section" id="sec-overview">'
        + (f'<div class="os-section-head"><h3>本事件重点模块</h3>'
           f'<span class="os-note">由事件侧重点与已有证据决定，最多显示三个重点；材料不足时显示缺口</span></div>{cards}'
           if cards else "")
        + '<div class="os-section-head"><h3>事件进程与材料分布</h3><span class="os-note">按发布日期 · 篇</span></div>'
        + _bars(overview.get("publication_distribution"))
        + (f'<div class="os-note">已找到依据的事件节点：</div>{nodes}' if nodes else
           '<p class="os-note">本轮材料中没有可定位的事件时间。</p>')
        + failure_note
        + f'<p class="os-note">{_esc(limitations.get("scope_limitation", ""))}</p>'
        + "</section>")


def _module_field_html(field, citations) -> str:
    label = _esc(field.get("label", ""))
    state = field.get("state", "")
    if state == "known":
        value = f'{_esc(field.get("value", ""))} {_cite_links(citations, field.get("citations"))}'
        return f'<div class="os-facet-field"><span class="os-facet-label">{label}</span><span class="os-facet-value">{value}</span></div>'
    if state == "conflict":
        values = " / ".join(_esc(value) for value in field.get("values", []))
        return (f'<div class="os-facet-field"><span class="os-facet-label">{label}</span>'
                f'<span class="os-open-question">字段冲突：{values}；待核查。</span></div>')
    return f'<div class="os-facet-field"><span class="os-facet-label">{label}</span><span class="os-note">未知</span></div>'


def _module_card(module, citations) -> str:
    state = MODULE_STATE_LABELS.get(module.get("state", ""), module.get("state", ""))
    items = ""
    for item in module.get("items", []):
        findings = "".join(
            f'<p>{_esc(finding["text"])} {_cite_links(citations, finding.get("citation_ids"))}'
            f'<span class="os-note">（核查：{_esc(REVIEW_LABELS.get(finding.get("review", ""), finding.get("review", "")))}）</span></p>'
            for finding in item.get("findings", []))
        items += f'<div class="os-note">{_esc(item["question"])}</div>{findings}'
    fields = module.get("fields", [])
    fields_html = ('<div class="os-facet-fields">'
                   + "".join(_module_field_html(field, citations) for field in fields) + "</div>") if fields else ""
    if fields:
        items_html = f'<details class="os-module-provenance"><summary>查看支撑判断</summary>{items}</details>' if items else ""
    else:
        items_html = items
    gap = f'<p class="os-open-question">{_esc(module["gap"])}</p>' if module.get("gap") else ""
    return ('<div class="os-module-card"><div class="os-module-head">'
            f'<h4>{_esc(module.get("title", ""))}</h4><span class="os-tag">{_esc(state)}</span></div>'
            f'<p class="os-note">{_esc(module.get("selection_rationale", ""))}</p>{gap}{fields_html}{items_html}</div>')


def _coverage_section(coverage, citations) -> str:
    materials = coverage.get("materials", [])
    stories = []
    for material in materials:
        url = _safe_url(material.get("final_url") or material.get("url"))
        title = (f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(material["title"])}</a>'
                 if url else _esc(material["title"]))
        relation = RELATION_LABELS.get(material.get("relation", ""), RELATION_LABELS["unverified"])
        relation_tag = f'<span class="os-origin">{_esc(relation)}</span>'
        if material.get("relation_status") == "model_proposed":
            relation_tag += '<span class="os-note">（模型基于原文提出，待人工复核）</span>'
        summary = material.get("summary", "")
        summary_html = f'<p class="os-story-summary">{_esc(summary)}</p>' if summary else ""
        relation_basis = ""
        if material.get("relation_status") == "model_proposed" and material.get("relation_explanation"):
            relation_basis = (f'<p class="os-note">关系依据（模型提出，待人工复核）：'
                              f'{_esc(material["relation_explanation"])} '
                              f'{_cite_links(citations, material.get("relation_evidence_ids"))}</p>')
        context_parts = []
        if material.get("subjects"):
            context_parts.append("表达主体：" + "、".join(material["subjects"]))
        if material.get("issue_questions"):
            context_parts.append("相关议题：" + "；".join(material["issue_questions"]))
        context_html = f'<p class="os-note">{_esc("；".join(context_parts))}</p>' if context_parts else ""
        judgment_links = "".join(
            f'<div class="os-note">{_esc(KIND_LABELS.get(judgment.get("kind", ""), judgment.get("kind", "材料")))}'
            f'｜{_esc("反驳" if judgment.get("relation") == "contradict" else "支持")}：{_esc(judgment.get("text", ""))} '
            f'{_cite_links(citations, judgment.get("citation_ids"))}</div>'
            for judgment in material.get("judgments", []) or [])
        stories.append(
            '<article class="os-story">'
            f'<small><span>{_esc(material.get("role_label") or ROLE_LABELS.get(material.get("role", ""), ""))}</span>'
            f'<span>发布 {_esc(str(material.get("published_at") or "未知")[:10])}</span>'
            f'<span>获取 {_esc(str(material.get("fetched_at") or "")[:10])}</span>{relation_tag}</small>'
            f'<strong>{title}</strong>{relation_basis}{summary_html}{context_html}{judgment_links}'
            f'<p>{_cite_links(citations, material.get("citation_ids"))}</p></article>')
    counts = coverage.get("search_coverage", [])
    coverage_note = ""
    if counts:
        coverage_note = ('<div class="os-section-head"><h3>搜索覆盖</h3>'
                         '<span class="os-note">本次已查范围，非全网召回率</span></div><ul class="os-note">'
                         + "".join(f'<li>{_esc(entry["question"])}：尝试 {entry["attempts"]} 次'
                                   + (f'，失败 {entry["errors"]} 次' if entry.get("errors") else "")
                                   + (f'；已查方向：{_esc("、".join(entry.get("purposes", {})))}' if entry.get("purposes") else "；已查方向：无")
                                   + (f'；未尝试：{_esc("、".join(entry.get("unattempted_directions", [])))}' if entry.get("unattempted_directions") else "")
                                   + (f'；失败未出候选：{_esc("、".join(entry.get("failed_directions", [])))}' if entry.get("failed_directions") else "")
                                   + (f'；本轮补查缺口：{_esc("；".join(entry.get("target_gaps", [])))}' if entry.get("target_gaps") else "")
                                   + "</li>" for entry in counts) + "</ul>")
    return (
        '<section class="os-section" id="sec-coverage">'
        '<div class="os-section-head"><h3>同一事件，不同报道角度</h3>'
        f'<span class="os-note">{len(materials)} 篇收录材料（未知发布日期 '
        f'{coverage.get("unknown_date_count", 0)} 篇，排最后）</span></div>'
        '<p class="os-note">比较同一问题下的报道；被采访者观点保留主体，转载与重复内容不作为独立证据。</p>'
        + "".join(stories) + coverage_note + "</section>")


def _issues_section(issues, citations) -> str:
    blocks = []
    for issue in issues:
        involved = issue.get("involved_materials") or {}
        involved_note = (f'<p class="os-note">涉及材料：{_esc(involved["count"])} 篇（同一快照内的筛选口径，'
                         "非公众讨论总量）</p>" if involved.get("count") else "")
        findings = []
        for finding in issue.get("findings", []):
            tags = [f'<span class="os-tag">{_esc(REVIEW_LABELS.get(finding.get("review", ""), ""))}</span>']
            if finding.get("response"):
                tags.append(f'<span class="os-tag">{_esc(RESPONSE_LABELS.get(finding["response"], ""))}</span>')
            voices = ""
            if finding.get("stakeholder"):
                voices = f'<p><strong>{_esc(finding["stakeholder"])}</strong> · {_esc(finding["text"])}</p>'
            else:
                voices = f'<p>{_esc(finding["text"])}</p>'
            coverage = ""
            if finding.get("response") in {"direct", "partial", "non_substantive"}:
                parts = [f'覆盖：{_esc("、".join(finding.get("covered") or []) or "未标注")}']
                if finding.get("uncovered"):
                    parts.append(f'未覆盖：{_esc("、".join(finding["uncovered"]))}')
                if finding.get("coverage_reason"):
                    parts.append(_esc(finding["coverage_reason"]))
                coverage = f'<p class="os-note">{"；".join(parts)}</p>'
            findings.append('<div>' + "".join(tags) + voices + coverage
                            + f'<p class="os-note">依据：{_cite_links(citations, finding.get("citations", {}).get("support")) or "—"}'
                            + ("；反驳：" + _cite_links(citations, finding.get("citations", {}).get("contradict"))
                               if finding.get("citations", {}).get("contradict") else "")
                            + "</p></div>")
        components_html = ""
        if issue.get("components"):
            rows = []
            for component in issue["components"]:
                rows.append(
                    '<div class="os-component">'
                    f'<span class="os-tag">{_esc(RESPONSE_LABELS.get(component.get("status", ""), component.get("status", "")))}</span>'
                    f'<span>{_esc(component.get("text", ""))}</span>'
                    f'{_cite_links(citations, component.get("evidence_ids"))}'
                    + (f'<span class="os-note">{_esc(component.get("note", ""))}</span>' if component.get("note") else "")
                    + "</div>")
            components_html = '<div class="os-components">' + "".join(rows) + "</div>"
        blocks.append(
            '<article class="os-issue">'
            f'<span class="os-tag">{_esc(issue.get("status", ""))}</span>'
            f'<h3>{_esc(issue["question"])}</h3>'
            + involved_note
            + (f'<p class="os-note">{_esc(issue.get("note", ""))}</p>' if issue.get("note") else "")
            + components_html
            + "".join(findings) + "</article>")
    return ('<section class="os-section" id="sec-issues">'
            '<div class="os-section-head"><h3>议题与回应对应</h3>'
            '<span class="os-note">按具体问题核查；渠道开通不等于问题解决</span></div>'
            + ("".join(blocks) or '<p class="os-note">尚未形成可展示的调查问题。</p>') + "</section>")


def _excerpt_block(evidence: dict, context: dict | None) -> str:
    """Render a saved excerpt together with its archive-verification status.

    Only a verified context gets the ``mark`` highlight. Missing or mismatched
    archive text keeps the report excerpt visible as provenance, but says so at
    the citation position instead of implying it was checked against the source text.
    """

    excerpt = _esc(evidence.get("excerpt", ""))
    locator = _esc(evidence.get("locator", ""))
    if context is not None and context.get("status", "verified") == "verified":
        before = _esc(context.get("before", ""))
        after = _esc(context.get("after", ""))
        return (f'<blockquote>{before}<mark>{excerpt}</mark>{after}</blockquote>'
                f'<div class="os-note">{locator}；请求地址与最终地址不同时以最终地址为准</div>')
    reason = (context or {}).get("reason") or "当前无法核对保存的归档正文。"
    return (f'<div class="os-open-question">{_esc(reason)}'
            "以下为报告保存的摘录，未与归档正文比对，不作为已定位原文。</div>"
            f'<blockquote>{excerpt}</blockquote><div class="os-note">{locator}</div>')


def _citations_section(citations, evidence_index, sources, contexts) -> str:
    entries = []
    for evidence_id, citation in sorted(citations.items(), key=lambda item: item[1]["index"]):
        evidence = evidence_index.get(evidence_id)
        source = sources.get(citation.get("version_id", ""), {})
        url = _safe_url(source.get("final_url") or source.get("url"))
        link = (f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(url)}</a>'
                if url else "来源地址不可用")
        context = contexts.get(evidence_id)
        excerpt = (_excerpt_block(evidence, context) if evidence
                   else '<div class="os-open-question">该引用缺少可核对的保存正文，保持未知。</div>')
        entries.append(
            f'<li class="os-cite-target" id="cite-{citation["index"]}">'
            f'<strong>{_esc(citation["label"])}｜{_esc(citation.get("source_title", ""))}</strong>'
            f'<div class="os-note">发布 {_esc(str(source.get("published_at") or "未知")[:10])}｜'
            f'更新 {_esc(str(source.get("updated_at") or "未知")[:10])}｜'
            f'获取 {_esc(str(source.get("fetched_at") or "")[:10])}｜{_esc(ROLE_LABELS.get(source.get("role", ""), ""))}</div>'
            f"{excerpt}<div class='os-note'>{link}</div></li>")
    return ('<section class="os-section" id="sec-citations">'
            '<div class="os-section-head"><h3>引用与原文</h3>'
            '<span class="os-note">字符区间基于保存的不可变正文，不是实时网页</span></div>'
            f'<ol class="os-citations">{"".join(entries) or "<li>本轮没有可展示的引用。</li>"}</ol></section>')


def _inspector(workbench, overview, citations, evidence_index, sources, contexts) -> str:
    first = None
    for judgment in overview.get("judgments", []):
        for evidence_id in judgment.get("citation_ids", []):
            if evidence_id in citations:
                first = evidence_id
                break
        if first:
            break
    if first is None:
        return ('<aside class="os-inspector" aria-label="证据与核查详情">'
                '<h4>证据核查</h4><p class="os-note">本轮没有可定位的引用。</p></aside>')
    citation = citations[first]
    evidence = evidence_index.get(first)
    source = sources.get(citation.get("version_id", ""), {})
    context = contexts.get(first)
    url = _safe_url(source.get("final_url") or source.get("url"))
    link = f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(url)}</a>' if url else "来源地址不可用"
    excerpt = _excerpt_block(evidence, context) if evidence else ""
    gaps = [module["gap"] for module in workbench.get("modules", [])
            if module.get("facet") and module.get("state") == "insufficient" and module.get("gap")]
    gap_html = "".join(f'<div class="os-open-question">仍缺：{_esc(gap)}</div>' for gap in gaps[:2])
    return ('<aside class="os-inspector" aria-label="证据与核查详情" aria-live="polite">'
            '<div class="os-section-head"><h4>证据核查 / 当前选中材料</h4></div>'
            f'<h3>{_esc(citation.get("source_title", ""))}</h3>'
            f'<div class="os-note">{_esc(ROLE_LABELS.get(source.get("role", ""), ""))} · '
            f'发布 {_esc(str(source.get("published_at") or "未知")[:10])}</div>'
            f'<h4>原文片段</h4>{excerpt}'
            f'<h4>对应引用</h4><p class="os-note">{_esc(citation["label"])}（正文中的引用角标可跳转到本页引用与原文一节）</p>'
            f"{gap_html}"
            '<p class="os-note">静态导出只呈现已提交快照；交互页面可点选任意材料与引用。</p></aside>')


def _footer(workbench, report, stamp, limitations) -> str:
    counts = report.get("source_relation_counts", {})
    total = counts.get("version_count", 0)
    material_note = (f'当前材料集：{counts.get("document_count", total)} 个页面 / {total} 个正文版本'
                     f'（已识别重复 {counts.get("identified_duplicate_count", 0)} 个，'
                     f'来源关系未核实 {counts.get("unverified_relation_count", 0)} 个）· 不是全网讨论样本')
    state = STATUS_LABELS.get(workbench.get("publication_state", ""), workbench.get("publication_state", ""))
    return ('<footer class="os-bottom">'
            f'<span>{_esc(material_note)}</span>'
            f'<span>快照 {_esc(workbench.get("snapshot_id", ""))} · 状态 {_esc(state)} · 导出时间 {_esc(stamp)}</span>'
            "</footer>")
