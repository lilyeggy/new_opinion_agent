import { api } from "./api.js";
import { clear, el, externalLink, LABELS, statusClass, statusLabel } from "./ui.js";

const STATUS_HELP = {
  answered: "材料已能回答该问题",
  disputed: "不同材料存在分歧",
  not_found: "在声明的查找范围内未发现",
  unavailable: "因读取失败或材料不足，无法判断",
  open: "尚未得出处置结论",
};

function evidenceChips(report, ids, onEvidence, labels) {
  const known = new Set(report.evidence.map((item) => item.evidence_id));
  return el("span", { class: "chips" }, ids.filter((id) => known.has(id)).map((id) =>
    el("button", { class: "chip", text: (labels && labels[id]) || id, onClick: () => onEvidence(id) })));
}

// Citation chips show a local, human-readable marker; internal evidence IDs
// stay in the program/developer surface instead of the main page.
function citationLabels(report, citations) {
  const labels = {};
  report.evidence.forEach((item, index) => {
    labels[item.evidence_id] = (citations && citations[item.evidence_id] && citations[item.evidence_id].label) || `引${index + 1}`;
  });
  return labels;
}

function findingLine(report, finding, onEvidence, labels) {
  const tags = [LABELS[finding.kind] || finding.kind, `核查：${LABELS[finding.support] || finding.support}`];
  if (finding.stakeholder) tags.push(`主体：${finding.stakeholder}`);
  if (finding.stance && finding.stance !== "unclear") tags.push(`态度：${finding.stance}→${finding.stance_target}`);
  if (finding.response) tags.push(`回应：${LABELS[finding.response] || finding.response}`);
  const lines = [
    el("div", { text: finding.text }),
    el("div", { class: "muted", text: tags.join("｜") }),
  ];
  if (["direct", "partial", "non_substantive"].includes(finding.response)) {
    const coverage = [`覆盖：${(finding.covered || []).join("、") || "未标注"}`];
    if ((finding.uncovered || []).length) coverage.push(`未覆盖：${finding.uncovered.join("、")}`);
    if (finding.coverage_reason) coverage.push(finding.coverage_reason);
    lines.push(el("div", { class: "muted", text: coverage.join("；") }));
  }
  lines.push(evidenceChips(report, [...finding.evidence_ids, ...finding.contradicting_ids], onEvidence, labels));
  return el("div", { class: "finding" }, lines);
}

function section(title, children) {
  return el("section", { class: "card" }, [el("h3", { class: "section-title", text: title }), ...[].concat(children)]);
}

export function renderReport(root, report, handlers) {
  clear(root);
  const onEvidence = handlers.onEvidence;
  const labels = citationLabels(report, handlers.citations);
  root.append(header(report, handlers));

  const risky = report.status !== "completed";
  root.append(section("核心回答与限制", [
    risky ? el("p", { class: "notice", text: `调查状态：${statusLabel(report.status)}。以下结论只覆盖已获得并核查的材料。` }) : null,
    el("p", { class: "muted", text: `停止原因：${report.stop_reason || "—"}` }),
    report.conclusions.length
      ? el("ul", {}, report.conclusions.map((finding) => el("li", {}, [
          el("span", { text: finding.text }),
          el("span", { text: " " }),
          evidenceChips(report, finding.evidence_ids, onEvidence, labels),
        ])))
      : el("p", { class: "muted", text: "尚无可对外核查的核心结论。" }),
    el("p", { class: "muted", text: report.scope_limitation }),
  ]));

  const timeline = report.findings
    .filter((finding) => finding.event_time)
    .slice()
    .sort((a, b) => String(a.event_time).localeCompare(String(b.event_time)));
  root.append(section("事件时间线", timeline.length
    ? el("ol", { class: "tl" }, timeline.map((finding) => el("li", { class: "timeline-row" }, [
        el("strong", { text: `${finding.event_time} ` }),
        el("span", { text: finding.text }),
        el("span", { class: "muted", text: `（核查：${LABELS[finding.support] || finding.support}）` }),
        el("span", { text: " " }),
        evidenceChips(report, finding.evidence_ids, onEvidence, labels),
      ])))
    : el("p", { class: "muted", text: "本轮材料中没有可定位的事件时间。" })));

  root.append(section("按问题组织的争议与各方主张",
    report.issues.map((issue) => issueBlock(report, issue, onEvidence, labels))));

  root.append(section("回应覆盖",
    report.issues.map((issue) => {
      const responses = report.findings.filter((finding) => finding.issue_id === issue.issue_id && finding.response);
      const note = issue.status === "not_found"
        ? `声明“范围内未发现回应”以截止时间 ${report.cutoff} 与第 7 节的查找范围为限。`
        : STATUS_HELP[issue.status];
      return el("div", { class: "issue" }, [
        el("h4", { text: issue.question }),
        el("p", { class: "muted", text: `${LABELS[issue.status] || issue.status}：${issue.note || note || ""}` }),
      ].concat(responses.map((finding) => findingLine(report, finding, onEvidence, labels))));
    })));

  root.append(section("已确认 / 分歧 / 未知", ["answered", "disputed", "not_found", "unavailable", "open"].map((status) => {
    const group = report.issues.filter((issue) => issue.status === status);
    if (!group.length) return null;
    return el("div", {}, [
      el("h4", { text: LABELS[status] || status }),
      el("ul", {}, group.map((issue) => el("li", { text: issue.question }))),
    ]);
  }).filter(Boolean)));

  if (report.required_questions && report.required_questions.length) {
    root.append(section("用户明确提出的问题", [
      el("p", { class: "muted", text: "以下问题由系统保存，并映射到调查问题，不会因模型计划而丢弃。" }),
      el("ul", {}, report.required_questions.map((text) => {
        const owners = report.issues.filter((issue) => (issue.origin_questions || []).includes(text));
        return el("li", { text: `${text} → ${owners.map((issue) => issue.question).join("；") || "未映射"}` });
      })),
    ]));
  }

  if (report.changes && report.changes.length) {
    root.append(section("版本变化", report.changes.map((change) => el("div", { class: "issue" }, [
      el("h4", { text: change.question }),
      el("p", {}, [el("span", { class: "badge", text: LABELS[change.kind] || change.kind })]),
      change.kind === "pending_reevaluation"
        ? el("p", { class: "muted", text: "本轮尚未重新取证或核查该问题，不代表旧判断被撤回。" })
        : null,
      change.before && change.before.length ? el("p", { class: "muted", text: `上一版：${change.before.map((f) => f.text).join("；")}` }) : null,
      change.after && change.after.length ? el("p", { class: "muted", text: `本版：${change.after.map((f) => f.text).join("；")}` }) : null,
    ]))));
  }

  root.append(appendix(report, onEvidence, labels));
}

function header(report, handlers) {
  return el("section", { class: "card" }, [
    el("div", { class: "row" }, [
      el("span", { class: statusClass(report.status), text: statusLabel(report.status) }),
      report.mode === "offline" ? el("span", { class: "badge warn", text: "虚构材料演示，不代表真实搜索结果" }) : null,
    ]),
    el("h2", { text: report.subject }),
    el("p", { class: "muted", text: `用户请求：${report.question}` }),
    el("p", { class: "muted", text: `报告生成：${report.generated_at || report.cutoff}｜查找截止：${report.lookup_cutoff || report.cutoff}｜开始：${report.started_at || "未知"}` }),
    (report.search_failures || report.read_failures)
      ? el("p", { class: "notice", text: `本轮存在供应商搜索/读取失败（搜索失败 ${report.search_failures}，读取失败 ${report.read_failures}）：缺失材料不代表没有新进展。` })
      : null,
    el("div", { class: "row" }, [
      el("a", { class: "chip", href: api.reportUrl(report.run_id), text: "下载 Markdown" }),
      el("button", { class: "secondary", text: "补充新进展", onClick: () => handlers.onUpdate(report) }),
      el("button", { class: "secondary", text: "版本比较", onClick: () => handlers.onCompare(report) }),
    ]),
  ]);
}

function issueBlock(report, issue, onEvidence, labels) {
  const findings = report.findings.filter((finding) => finding.issue_id === issue.issue_id);
  return el("div", { class: "issue" }, [
    el("h4", { text: issue.question }),
    el("p", { class: "muted", text: `${LABELS[issue.status] || issue.status}：${issue.note || STATUS_HELP[issue.status] || ""}` }),
  ].concat(findings.length ? findings.map((finding) => findingLine(report, finding, onEvidence, labels))
    : [el("p", { class: "muted", text: "本轮没有形成可核查的判断。" })]));
}

function appendix(report, onEvidence, labels) {
  const counts = report.source_relation_counts;
  const relationsLine = counts
    ? `收录页面 ${counts.document_count} 个｜正文版本 ${counts.version_count} 个｜已识别重复 ${counts.identified_duplicate_count} 个｜来源关系未核实 ${counts.unverified_relation_count} 个（未识别重复不等于已验证独立）`
    : `来源 ${report.sources.length} 个（其中与已有版本正文重复 ${report.sources.filter((s) => s.independent === false).length} 个）`;
  const details = el("details", { class: "card" }, [
    el("summary", { text: `范围与来源证据附录（${report.sources.length} 个来源版本，${report.evidence.length} 条定位）` }),
    el("h4", { text: `来源：${relationsLine}` }),
    el("ul", {}, report.sources.map((source) => el("li", {}, [
      externalLink(source.title, source.final_url),
      el("span", { class: "muted", text: `｜${LABELS[source.discovery] || source.discovery || ""}｜获取 ${source.fetched_at}｜发布 ${source.published_at || "未知"}` }),
      source.independent === false ? el("span", { class: "badge warn", text: "与已有版本正文重复，不作为独立证据" }) : null,
    ]))),
    el("h4", { text: "证据定位（字符区间基于保存的 Unicode 原文）" }),
    el("ul", {}, report.evidence.map((item, index) => el("li", {}, [
      el("button", { class: "chip", text: (labels && labels[item.evidence_id]) || `引${index + 1}`, onClick: () => onEvidence(item.evidence_id) }),
      el("span", { text: ` ${item.excerpt.slice(0, 80)}${item.excerpt.length > 80 ? "…" : ""}` }),
      el("span", { class: "muted", text: `（${item.locator}）` }),
    ]))),
    el("h4", { text: "本轮搜索尝试" }),
    el("ul", { class: "muted" }, report.searches.map((attempt) => el("li", {
      text: `[${attempt.purpose}/${attempt.outcome}] ${attempt.query}（新增 ${attempt.count}）`,
    }))),
    (report.checks && report.checks.length) ? el("h4", { text: "本轮来源复查记录" }) : null,
    (report.checks && report.checks.length) ? el("ul", { class: "muted" }, report.checks.map((check) => el("li", {
      text: `${check.checked_at} 复查 ${check.url} → 版本 ${check.version_id}${check.changed ? "（正文已变化，新增版本）" : "（正文未变）"}`,
    }))) : null,
  ]);
  return details;
}
