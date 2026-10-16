from pathlib import Path

p = Path("src/opinion_search/report_contract/renderer.py")
s = p.read_text()

s = s.replace(
    '  <div>\n'
    '    <h3>{escape(module.title)}</h3>\n'
    '    <div class="module-type">{escape(module.semantic_type)}</div>\n'
    '  </div>\n',
    '  <div>\n'
    '    <h3>{escape(module.title)}</h3>\n'
    '  </div>\n',
)
s = s.replace(
    '<div class="visual-note">visual={escape(module.selected_visual.value)} · {escape(module.selection_reason)}</div>\n',
    '',
)
s = s.replace(
    '  <div class="meta">状态：{escape(plan.status)} · 内容版本：{plan.source_content_revision} · 生成时间：{escape(plan.generated_at)}</div>\n',
    '  <div class="meta">状态：{_status_label(plan.status)} · 内容版本：{plan.source_content_revision} · 生成时间：{escape(plan.generated_at)}</div>\n',
)
s = s.replace(
    '<footer class="page-footer">Content Contract → PresentationPlan → Deterministic Renderer</footer>',
    '<footer class="page-footer">内容契约 → 呈现方案 → 确定性渲染</footer>',
)
s = s.replace(
    'def _render_views(plan: PresentationPlan) -> tuple[str, str]:\n',
    'def _status_label(status: str) -> str:\n'
    '    labels = {\n'
    '        "completed": "已完成",\n'
    '        "partial": "部分完成",\n'
    '        "failed": "失败",\n'
    '        "cancelled": "已取消",\n'
    '        "finalizing": "正在收束",\n'
    '        "running": "调查中",\n'
    '    }\n'
    '    return labels.get(status, status)\n\n\n'
    'def _render_views(plan: PresentationPlan) -> tuple[str, str]:\n',
)
old_evidence = '''def _render_evidence(module: PlannedModule) -> str:
    if not module.citations and not module.items:
        return _render_text(module)
    rows = []
    for citation in module.citations:
        rows.append(
            f'<div class="evidence-row"><div class="evidence-id">{escape(citation.evidence_id)}</div>'
            f'<div class="evidence-excerpt">{escape(citation.excerpt)}</div>'
            f'<div class="evidence-locator">{escape(citation.locator)}</div></div>'
        )
    for item in module.items:
        rows.append(f'<div class="evidence-row">{escape(str(item))}</div>')
    return f'<div class="evidence-list">{"".join(rows)}</div>'
'''
new_evidence = '''IMAGE_PATTERN = chr(33) + r"\\[[^\\]]*\\]\\([^\\)]*\\)"


def _clean_evidence_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(IMAGE_PATTERN, "", cleaned)
    cleaned = re.sub(r"\\[([^\\]]+)\\]\\([^\\)]*\\)", r"\\1", cleaned)
    cleaned = re.sub(r"[#*_>`~]+", "", cleaned)
    cleaned = re.sub(r"\\s+", " ", cleaned)
    return cleaned.strip()


def _render_evidence(module: PlannedModule) -> str:
    if not module.citations:
        return _render_text(module)
    cards = []
    for citation in module.citations:
        cleaned = _clean_evidence_text(citation.excerpt)
        if not cleaned:
            continue
        summary = cleaned[:220].rstrip()
        if len(cleaned) > 220:
            summary += "…"
        source_label = citation.label or "未命名来源"
        cards.append(
            '<article class="evidence-card">'
            f'<div class="evidence-source">{escape(source_label)}</div>'
            f'<div class="evidence-excerpt">{escape(summary)}</div>'
            f'<details class="item-details"><summary>展开原文</summary><p>{escape(cleaned)}</p></details>'
            '</article>'
        )
    return f'<div class="evidence-grid">{"".join(cards)}</div>'
'''
if old_evidence not in s:
    raise SystemExit("evidence renderer block not found")
s = s.replace(old_evidence, new_evidence)
s = s.replace(
    '.evidence-list{margin-top:14px}.evidence-row{border-bottom:1px solid var(--line);padding:10px 0;font-size:13px}.evidence-id{color:var(--blue);font-weight:750}.evidence-excerpt{margin-top:4px}.evidence-locator{color:var(--muted);font-size:12px;margin-top:4px}\n',
    '.evidence-grid{display:grid;gap:12px;margin-top:14px}\n'
    '.evidence-card{border:1px solid #e4ebf5;border-radius:14px;padding:14px;background:linear-gradient(180deg,#fff,#fbfdff)}\n'
    '.evidence-source{font-weight:800;color:var(--blue);font-size:14px;margin-bottom:8px}\n'
    '.evidence-excerpt{color:#334155;font-size:13px;line-height:1.7}\n',
)
p.write_text(s)
print("renderer patched")
