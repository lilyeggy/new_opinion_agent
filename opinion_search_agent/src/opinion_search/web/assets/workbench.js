import { api } from "./api.js";
import { renderReport } from "./report.js";
import { clear, el, externalLink, LABELS, statusClass, statusLabel } from "./ui.js";

const ROLE_LABELS = { original: "机构原文", reporting: "新闻报道", commentary: "评论文章", unknown: "来源类型未知" };
const RELATION_LABELS = { duplicate: "与已有版本正文重复", unverified: "来源关系未核实" };
const MODULE_STATE_LABELS = { ready: "可查看", provisional: "待核查", insufficient: "材料不足", unavailable: "无法查看", not_applicable: "不适用" };
const REVIEW_HINT = { supported: "引用支持", partial: "证据部分支持", contradicted: "与引用矛盾", insufficient: "证据不足", unreviewed: "尚未完成核查" };
const PROVISIONAL_STATES = new Set(["planning", "running", "finalizing", "needs_clarification"]);

// Mirrors docs/design/professional-event-workbench.reference.html: left
// investigation nav, heading + scope, judgement summary with inline citation
// marks, day-bar material distribution, filterable report list, issue blocks
// and a persistent evidence inspector. Every value comes from the committed
// workbench projection; the page never renders model-authored markup.
export function renderWorkbench(root, runId, workbench, snapshot, handlers = {}) {
  const report = snapshot && snapshot.report;
  const views = workbench.views;
  const provisional = PROVISIONAL_STATES.has(workbench.publication_state);
  const citations = Object.entries(workbench.citations || {})
    .map(([id, item]) => ({ id, ...item }))
    .sort((a, b) => a.index - b.index);
  const state = { view: "overview", date: null, issue: "all", role: "all", expanded: false, selected: firstCitation(workbench) };

  clear(root);
  // The workbench needs the full page width; other routes reset this in app.js.
  document.body.classList.add("wide");
  const connectionBox = el("span", { class: "badge", hidden: true });
  if (handlers.onConnectionState) {
    handlers.onConnectionState((status) => {
      connectionBox.hidden = status === "connected";
      connectionBox.textContent = status === "reconnecting" ? "连接中断，正在恢复…" : status === "disconnected" ? "连接已断开。" : "";
      connectionBox.className = status === "disconnected" ? "badge danger" : "badge warn";
    });
  }
  const navBox = el("nav", { class: "os-nav", "aria-label": "调查视图" });
  const contentBox = el("div", { class: "os-content" });
  const inspectorBox = el("aside", { class: "os-inspector", "aria-label": "证据与核查详情", "aria-live": "polite" });
  root.append(el("div", { class: "os-page" }, [
    el("header", { class: "os-top" }, [
      el("div", { class: "os-brand" }, [el("span", { text: "Opinion" }), "Search", el("small", { text: " / 事件工作台" })]),
      el("span", { class: "os-demo", text: provisional ? "阶段投影 · 内容未经最终审查" : "已发布快照 · 与下载文件同源" }),
      connectionBox,
      report ? el("div", { class: "os-tools" }, [
        el("a", { class: "os-text-button", href: api.pageUrl(workbench.run_id, workbench.snapshot_id), target: "_blank", rel: "noopener noreferrer", text: "打开静态页" }),
        el("a", { class: "os-text-button", href: api.pageDownloadUrl(workbench.run_id, workbench.snapshot_id), text: "下载 HTML" }),
        el("a", { class: "os-text-button", href: api.reportUrl(workbench.run_id), text: "下载 Markdown" }),
        el("a", { class: "os-text-button", href: `#/i/${workbench.run_id}/compare` + (report.parent_id ? `?base=${report.parent_id}` : ""), text: "版本比较" }),
      ]) : null,
    ]),
    previousCompleteNote(),
    el("div", { class: "os-frame" }, [navBox, el("main", {}, [
      heading(),
      summary(),
      el("div", { class: "os-main-grid" }, [contentBox, inspectorBox]),
      footer(),
    ])]),
  ]));

  paintNav();
  paintContent();
  paintInspector();

  function go(next) { state.view = next; state.expanded = false; paintNav(); paintContent(); }

  // A partial must never hide the last complete result: the pointer comes from
  // the server snapshot, and the older version stays read-only (W18).
  function previousCompleteNote() {
    const previous = snapshot && snapshot.latest_completed_run_id;
    if (!previous || previous === workbench.run_id) return null;
    return el("div", { class: "os-version-note" }, [
      el("span", { text: `本版本${statusLabel(workbench.publication_state)}；最近一次完整结果仍可查看：` }),
      el("a", { href: `#/i/${previous}`, text: "查看上一完整版本" }),
      el("span", { class: "os-note", text: "未复评的判断以当前页面为准，不视为已被上一版撤回。" }),
    ]);
  }
  function select(evidenceId, options = {}) {
    state.selected = evidenceId;
    if (options.view) state.view = options.view;
    paintNav(); paintContent(); paintInspector();
  }

  function citationButtons(ids, options = {}) {
    const found = (ids || []).map((id) => citations.find((item) => item.id === id)).filter(Boolean);
    if (!found.length) return null;
    return el("span", {}, found.map((item) => el("button", {
      class: "os-inline",
      text: `[${item.label.replace("引", "")}]`,
      "aria-pressed": String(state.selected === item.id),
      title: item.source_title,
      onClick: () => select(item.id, options),
    })));
  }

  function citationsLine(ids, prefix = "依据：") {
    const chips = citationButtons(ids);
    return chips ? el("div", {}, [el("span", { class: "os-note", text: prefix }), chips]) : null;
  }

  function heading() {
    const profile = workbench.profile || {};
    const materials = views.coverage.materials || [];
    const days = materials.filter((item) => item.published_at).map((item) => String(item.published_at).slice(0, 10)).sort();
    const meta = (label, value) => el("span", { class: "os-meta-item" }, [el("span", { text: label }), el("b", { text: value })]);
    const window = days.length ? (days[0] === days[days.length - 1] ? days[0] : `${days[0]} — ${days[days.length - 1]}`) : "";
    return el("div", { class: "os-heading" }, [
      el("div", { class: "os-eyebrow" }, [
        el("span", { text: "事件侧重点" }),
        el("b", { text: (profile.facets || ["general"]).join("、") }),
        el("span", { class: "os-sep", text: "·" }),
        el("span", { text: `快照 ${String(workbench.snapshot_id).slice(-8)}` }),
        el("span", { class: "os-sep", text: "·" }),
        el("span", { text: `生成于 ${String(workbench.generated_at || "").slice(0, 16).replace("T", " ")}` }),
        el("span", { class: statusClass(workbench.publication_state), text: statusLabel(workbench.publication_state) }),
        views.overview.mode === "offline" ? el("span", { class: "os-tag warn", text: "虚构材料演示" }) : null,
      ]),
      el("div", { class: "os-title-row" }, [
        el("h2", { text: views.overview.subject }),
        report ? el("button", { class: "os-primary", text: "补查新进展", onClick: () => handlers.onUpdate && handlers.onUpdate() })
               : el("button", { class: "os-secondary", text: "返回调查进度", onClick: () => handlers.onBack && handlers.onBack() }),
      ]),
      el("div", { class: "os-scope-row" }, [
        meta("排查问题", views.overview.question),
        meta("收录材料", `${materials.length} 篇`),
        window ? meta("材料发布窗口", window) : null,
        meta("发布时未知", `${materials.filter((item) => !item.published_at).length} 篇`),
      ]),
      (views.coverage.search_coverage || []).length ? el("details", { class: "os-scope-panel" }, [
        el("summary", { text: "查看检索范围（本次已查范围，非全网召回率）" }),
        ...views.coverage.search_coverage.map((entry) => el("div", {
          text: `${entry.question}：尝试 ${entry.attempts} 次` + (entry.targeted ? `（定向 ${entry.targeted} 次）` : "") + (entry.errors ? `，失败 ${entry.errors} 次（失败不等于无材料）` : ""),
        })),
      ]) : null,
    ]);
  }

  function summary() {
    const judgments = views.overview.judgments || [];
    if (!judgments.length) {
      return el("section", { class: "os-summary" }, [
        el("div", { class: "os-summary-title" }, [el("span", { class: "os-tag warn", text: "当前研判" }), el("span", { class: "os-note", text: "尚无可对外核查的核心判断" })]),
        el("p", { class: "os-note", text: "本轮材料不足以形成已核查的核心判断，未完成问题保持未知。" }),
      ]);
    }
    const lead = judgments[0];
    return el("section", { class: "os-summary" }, [
      el("div", { class: "os-summary-title" }, [
        el("span", { class: "os-tag", text: "当前研判" }),
        el("span", { class: "os-note", text: "每条判断都可下钻到保存的原文与核查状态" }),
      ]),
      el("h3", { text: lead.text }),
      citationsLine(lead.citation_ids) || el("div", { class: "os-note", text: `核查：${REVIEW_HINT[lead.review] || lead.review}` }),
      ...judgments.slice(1).map((item) => el("div", {}, [
        el("p", { text: item.text }),
        citationsLine(item.citation_ids) || el("div", { class: "os-note", text: `核查：${REVIEW_HINT[item.review] || item.review}` }),
      ])),
    ]);
  }

  function paintNav() {
    clear(navBox);
    const items = [["overview", "事件总览"], ["coverage", "报道对照"], ["issues", "议题与核查"], ["citations", "引用与原文"]];
    if (report) items.push(["report", "完整报告"]);
    navBox.append(el("p", { text: "当前调查" }));
    for (const [key, label] of items) {
      navBox.append(el("button", {
        text: key === "overview" && provisional ? `${label}（阶段投影）` : label,
        "aria-pressed": String(state.view === key),
        onClick: () => go(key),
      }));
    }
  }

  function paintContent() {
    clear(contentBox);
    if (state.view === "overview") contentBox.append(overviewView());
    else if (state.view === "coverage") contentBox.append(coverageView());
    else if (state.view === "issues") contentBox.append(issuesView());
    else if (state.view === "citations") contentBox.append(citationsView());
    else if (state.view === "report" && report) {
      renderReport(contentBox, report, handlers.reportHandlers || { onEvidence: (evidenceId) => select(evidenceId, { view: "citations" }) });
    }
  }

  function overviewView() {
    const overview = views.overview;
    const modules = (workbench.modules || []).filter((module) => module.facet);
    const timeline = overview.timeline || { events: [], unparsed: [] };
    const nodes = [...(timeline.events || []), ...(timeline.unparsed || [])];
    const limitations = workbench.limitations || {};
    return el("div", {}, [
      modules.length ? el("section", {}, [
        el("div", { class: "os-section-head" }, [
          el("h3", { text: "本事件重点模块" }),
          el("span", { class: "os-note", text: "由事件侧重点与已有证据决定；材料不足时显示缺口" }),
        ]),
        ...modules.map((module) => moduleCard(module)),
      ]) : null,
      el("section", {}, [
        el("div", { class: "os-section-head" }, [el("h3", { text: "事件进程与材料分布" }), el("span", { class: "os-note", text: "按发布日期 · 篇" })]),
        dayBars(overview.publication_distribution),
        nodes.length ? el("div", {}, [
          el("div", { class: "os-note", text: "已找到依据的事件节点：" }),
          ...nodes.map((node) => el("div", {}, [
            el("strong", { text: `${node.event_time} ` }),
            el("span", { text: node.text }),
            el("span", { text: " " }),
            citationButtons(node.citation_ids) || el("span", { class: "os-note", text: "（无对应引用）" }),
          ])),
        ]) : el("p", { class: "os-note", text: "本轮材料中没有可定位的事件时间。" }),
        (limitations.search_failures || limitations.read_failures)
          ? el("p", { class: "os-open-question", text: `本轮存在供应商搜索/读取失败（搜索失败 ${limitations.search_failures || 0}，读取失败 ${limitations.read_failures || 0}）：缺失材料不代表没有新进展。` })
          : null,
        el("p", { class: "os-note", text: limitations.scope_limitation || "" }),
      ]),
    ]);
  }

  function moduleCard(module) {
    return el("div", { class: "os-module-card" }, [
      el("div", { class: "os-module-head" }, [
        el("h4", { text: module.title }),
        el("span", { class: module.state === "ready" ? "os-tag ok" : "os-tag warn", text: MODULE_STATE_LABELS[module.state] || module.state }),
      ]),
      module.selection_rationale ? el("p", { class: "os-note", text: module.selection_rationale }) : null,
      module.gap ? el("p", { class: "os-open-question", text: module.gap }) : null,
      ...(module.items || []).map((item) => el("div", { class: "os-module-item" }, [
        el("div", { text: item.question }),
        ...item.findings.map((finding) => el("p", { class: "os-finding" }, [
          el("span", { text: finding.text }),
          el("span", { text: " " }),
          citationButtons(finding.citation_ids) || el("span", { class: "os-note", text: "（无对应引用）" }),
          el("span", { class: "os-note", text: `（核查：${REVIEW_HINT[finding.review] || finding.review}）` }),
        ])),
      ])),
    ]);
  }

  function dayBars(distribution) {
    if (!distribution) return el("p", { class: "os-note", text: "缺少可靠发布日期，不绘制材料发布时间分布。" });
    const peak = Math.max(...distribution.buckets.map((bucket) => bucket.count), 1);
    return el("div", {}, [
      el("div", { class: "os-day-list" }, distribution.buckets.map((bucket) => el("button", {
        class: "os-day",
        "aria-pressed": String(state.date === bucket.date),
        title: `${bucket.date}：${bucket.count} 篇`,
        onClick: () => {
          state.date = state.date === bucket.date ? null : bucket.date;
          state.expanded = false;
          go("coverage");
        },
      }, [
        el("span", { text: String(bucket.count) }),
        el("span", { class: "os-day-bars" }, [el("span", { class: "os-day-bar", style: `height:${Math.max(6, Math.round(bucket.count / peak * 56))}px` })]),
        el("span", { class: "os-day-date", text: bucket.date.slice(5) }),
        el("span", { class: "os-day-note", text: `${(bucket.members || []).length} 个页面` }),
      ]))),
      distribution.unknown_count
        ? el("p", { class: "os-note", text: `发布时间未知：${distribution.unknown_count} 篇（涉及 ${distribution.unknown_documents || 0} 个页面），不计入上图。` })
        : null,
      el("p", { class: "os-note", text: "柱高表示本次收录材料数（同一 URL 的多个正文版本按一个页面计）；点击日期筛选材料，不代表全网声量或舆情热度。" }),
    ]);
  }

  function issueById(issueId) {
    return (views.issues.issues || []).find((issue) => issue.issue_id === issueId);
  }

  function filteredMaterials() {
    const materials = views.coverage.materials || [];
    const issue = state.issue === "all" ? null : issueById(state.issue);
    const issueEvidence = issue ? new Set(issue.findings.flatMap((finding) => [...finding.citations.support, ...finding.citations.contradict])) : null;
    return materials.filter((material) => {
      if (state.date && String(material.published_at || "").slice(0, 10) !== state.date) return false;
      if (state.role !== "all" && material.role !== state.role) return false;
      if (issueEvidence && !material.citation_ids.some((id) => issueEvidence.has(id))) return false;
      return true;
    });
  }

  function coverageView() {
    const coverage = views.coverage;
    const issues = views.issues.issues || [];
    const roles = [...new Set((coverage.materials || []).map((material) => material.role))];
    const materials = filteredMaterials();
    const shown = state.expanded ? materials : materials.slice(0, 4);
    return el("div", {}, [
      el("section", {}, [
        el("div", { class: "os-section-head" }, [
          el("h3", { text: "同一事件，不同报道角度" }),
          el("span", { class: "os-note", text: `${materials.length} 篇匹配材料` }),
        ]),
        el("div", { class: "os-filter-line" }, [
          el("label", {}, [el("span", { class: "os-note", text: "议题 " }), filterSelect(
            [["all", "全部议题"], ...issues.map((issue) => [issue.issue_id, issue.question.slice(0, 16)])],
            state.issue, (value) => { state.issue = value; state.expanded = false; paintContent(); })]),
          el("label", {}, [el("span", { class: "os-note", text: "材料 " }), filterSelect(
            [["all", "全部类型"], ...roles.map((role) => [role, ROLE_LABELS[role] || role])],
            state.role, (value) => { state.role = value; state.expanded = false; paintContent(); })]),
          state.date ? el("button", { class: "os-text-button", text: `清除 ${state.date} 筛选`, onClick: () => { state.date = null; paintContent(); } }) : null,
        ]),
        el("p", { class: "os-note", text: "比较同一问题下的报道；被采访者观点保留主体，转载与重复内容不作为独立证据。" }),
        ...shown.map((material) => story(material)),
        materials.length > 4 ? el("button", {
          class: "os-text-button",
          text: state.expanded ? "收起材料列表" : `展开全部 ${materials.length} 篇`,
          onClick: () => { state.expanded = !state.expanded; paintContent(); },
        }) : null,
        materials.length ? null : el("p", { class: "os-note", text: "当前浏览条件下没有材料。可调整筛选，不代表本次调查没有发现。" }),
      ]),
    ]);
  }

  function filterSelect(options, value, onChange) {
    const node = el("select", { "aria-label": "筛选" }, options.map(([key, label]) => el("option", { value: key, text: label })));
    node.value = value;
    node.addEventListener("change", (event) => onChange(event.target.value));
    return node;
  }

  function story(material) {
    return el("article", {
      class: "os-story",
      "aria-pressed": String(material.citation_ids.includes(state.selected)),
      onClick: () => material.citation_ids.length ? select(material.citation_ids[0]) : select(null),
    }, [
      el("small", {}, [
        el("span", { text: ROLE_LABELS[material.role] || material.role }),
        el("span", { text: `发布 ${String(material.published_at || "未知").slice(0, 10)}` }),
        el("span", { text: `获取 ${String(material.fetched_at || "").slice(0, 10)}` }),
        el("span", { class: "os-origin", text: RELATION_LABELS[material.relation] || material.relation }),
      ]),
      el("strong", {}, [externalLink(material.title, material.final_url)]),
      citationButtons(material.citation_ids) ? el("p", {}, [citationButtons(material.citation_ids)]) : null,
    ]);
  }

  function issuesView() {
    const issues = views.issues.issues || [];
    return el("div", {}, [
      el("div", { class: "os-section-head" }, [el("h3", { text: "议题与回应对应" }), el("span", { class: "os-note", text: "按具体问题核查；渠道开通不等于问题解决" })]),
      ...issues.map((issue) => el("article", { class: "os-issue" }, [
        el("span", { class: "os-tag", text: LABELS[issue.status] || issue.status }),
        el("h3", { text: issue.question }),
        issue.note ? el("p", { class: "os-note", text: issue.note }) : null,
        ...issue.findings.map((finding) => {
          const tags = [el("span", { class: "os-tag", text: REVIEW_HINT[finding.review] || finding.review })];
          if (finding.response) tags.push(el("span", { class: "os-tag", text: LABELS[finding.response] || finding.response }));
          const lines = [el("div", {}, tags)];
          lines.push(finding.stakeholder
            ? el("p", {}, [el("strong", { text: finding.stakeholder }), el("span", { text: ` · ${finding.text}` })])
            : el("p", { text: finding.text }));
          if (["direct", "partial", "non_substantive"].includes(finding.response)) {
            const parts = [`覆盖：${(finding.covered || []).join("、") || "未标注"}`];
            if ((finding.uncovered || []).length) parts.push(`未覆盖：${finding.uncovered.join("、")}`);
            if (finding.coverage_reason) parts.push(finding.coverage_reason);
            lines.push(el("p", { class: "os-note", text: parts.join("；") }));
          }
          const refs = el("p", { class: "os-note" }, [el("span", { text: "依据：" })]);
          const support = citationButtons(finding.citations.support);
          refs.append(support || document.createTextNode("—"));
          if (finding.citations.contradict.length) {
            refs.append(el("span", { text: "；反驳：" }));
            refs.append(citationButtons(finding.citations.contradict));
          }
          lines.push(refs);
          return el("div", {}, lines);
        }),
        el("div", { class: "os-issue-controls" }, [
          el("button", { class: "os-text-button", text: `对照相关材料（${issue.involved_materials ? issue.involved_materials.count : 0} 篇）`,
            onClick: () => { state.issue = issue.issue_id; state.date = null; state.expanded = false; go("coverage"); } }),
          el("button", { class: "os-text-button", text: "补查缺失依据", onClick: () => handlers.onUpdate && handlers.onUpdate(issue.issue_id) }),
        ]),
      ])),
      issues.length ? null : el("p", { class: "os-note", text: "尚未形成可展示的调查问题。" }),
    ]);
  }

  function citationsView() {
    const evidence = (report && report.evidence) || [];
    return el("div", {}, [
      el("div", { class: "os-section-head" }, [el("h3", { text: "引用与原文" }), el("span", { class: "os-note", text: "字符区间基于保存的不可变正文，不是实时网页" })]),
      citations.length ? el("ol", { class: "os-citations" }, citations.map((citation) => {
        const item = evidence.find((entry) => entry.evidence_id === citation.id);
        return el("li", { class: "os-cite-target", id: `cite-${citation.index}` }, [
          el("button", {
            class: "os-inline",
            text: citation.label,
            "aria-pressed": String(state.selected === citation.id),
            onClick: () => select(citation.id),
          }),
          el("strong", { text: `｜${citation.source_title}` }),
          item ? el("blockquote", { text: item.excerpt })
               : el("div", { class: "os-open-question", text: "该引用缺少可核对的保存正文，保持未知。" }),
          item ? el("div", { class: "os-note", text: item.locator }) : null,
        ]);
      })) : el("p", { class: "os-note", text: "本轮没有可展示的引用。" }),
    ]);
  }

  async function paintInspector() {
    clear(inspectorBox);
    const pending = (workbench.modules || []).filter((module) => module.facet && module.state === "insufficient" && module.gap).slice(0, 2);
    const citation = citations.find((item) => item.id === state.selected) || citations[0];
    if (!citation) {
      inspectorBox.append(el("h4", { text: "证据核查" }), el("p", { class: "os-note", text: "本轮没有可定位的引用。" }));
      return;
    }
    const detail = el("div", {}, [el("p", { class: "os-note", text: "正在定位证据…" })]);
    inspectorBox.append(
      el("div", { class: "os-section-head" }, [el("h4", { text: "证据核查 / 当前选中材料" })]),
      el("h3", { text: citation.source_title }),
      el("div", { class: "os-note", text: `正文引用角标 [${citation.label.replace("引", "")}]` }),
      detail,
      ...pending.map((module) => el("div", { class: "os-open-question", text: `仍缺：${module.gap}` })),
      el("button", { class: "os-text-button", text: "补查这个问题", onClick: () => handlers.onUpdate && handlers.onUpdate() }),
      el("p", { class: "os-note", text: report ? "" : "阶段投影：证据原文在调查结束后随快照一并固化。" }),
    );
    if (!report) {
      detail.replaceWith(el("p", { class: "os-note", text: "调查进行中，原文定位以已提交材料为准。" }));
      return;
    }
    try {
      const item = await api.evidence(workbench.run_id, citation.id);
      detail.replaceWith(el("div", {}, [
        el("div", { class: "os-note", text: `${ROLE_LABELS[item.source.role] || item.source.role} · 发布 ${String(item.source.published_at || "未知").slice(0, 10)} · 更新 ${String(item.source.updated_at || "未知").slice(0, 10)} · 获取 ${String(item.source.fetched_at || "").slice(0, 10)}` }),
        el("h4", { text: "原文片段" }),
        el("blockquote", {}, [el("span", { text: item.before || "" }), el("mark", { text: item.excerpt }), el("span", { text: item.after || "" })]),
        el("div", { class: "os-note", text: item.locator }),
        el("h4", { text: "这份材料与判断的关系" }),
        item.relations && item.relations.length
          ? el("ul", { class: "os-note" }, item.relations.map((relation) => el("li", {
              text: relation.relation === "contradict" ? "反驳/冲突一条已提交判断" : "支持一条已提交判断",
            })))
          : el("p", { class: "os-note", text: "该材料当前未被任一判断引用。" }),
        el("p", { class: "os-note" }, [externalLink(item.source.final_url, item.source.final_url)]),
      ]));
    } catch (error) {
      detail.replaceWith(el("p", { class: "error", text: `证据读取失败：${error.message}` }));
    }
  }

  function footer() {
    const counts = (report && report.source_relation_counts) || {};
    const materials = (report && report.sources) || [];
    return el("footer", { class: "os-bottom" }, [
      el("span", { text: report
        ? `当前材料集：${counts.document_count || 0} 个页面 / ${counts.version_count || materials.length} 个正文版本（已识别重复 ${counts.identified_duplicate_count || 0} 个，来源关系未核实 ${counts.unverified_relation_count || 0} 个）· 不是全网讨论样本`
        : "阶段投影：材料统计以已提交部分为准。" }),
      el("span", { text: `快照 ${workbench.snapshot_id} · 状态 ${statusLabel(workbench.publication_state)}` }),
    ]);
  }
}

function firstCitation(workbench) {
  const judgments = (workbench.views && workbench.views.overview && workbench.views.overview.judgments) || [];
  for (const judgment of judgments) {
    for (const id of judgment.citation_ids || []) if (workbench.citations[id]) return id;
  }
  const first = Object.entries(workbench.citations || {}).sort((a, b) => a[1].index - b[1].index)[0];
  return first ? first[0] : null;
}
