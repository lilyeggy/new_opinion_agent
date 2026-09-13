import { api, TERMINAL, stream } from "./api.js";
import { createEvidencePanel } from "./evidence.js";
import { renderReport } from "./report.js";
import { renderWorkbench, workbenchRouteHash } from "./workbench.js";
import { clear, el, externalLink, LABELS, statusClass, statusLabel } from "./ui.js";

const view = document.getElementById("view");
const evidencePanel = createEvidencePanel();
let activeStream = null;
// Grows on every route change; responses or stream events from an earlier
// route must never overwrite the currently displayed event page.
let routeToken = 0;

function stopStream() {
  if (activeStream) { activeStream.close(); activeStream = null; }
}

function navigate(hash) { window.location.hash = hash; }

async function route() {
  stopStream();
  document.body.classList.remove("wide", "workbench");
  const token = ++routeToken;
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  try {
    if (parts[0] === "i" && parts[1]) {
      if (parts[2] === "compare") return renderCompare(parts[1], new URLSearchParams(query || ""));
      if (parts[2] === "update") return renderUpdateForm(parts[1], new URLSearchParams(query || "").get("issue"));
      return renderDetail(parts[1], token, new URLSearchParams(query || ""));
    }
    return renderHome();
  } catch (error) {
    if (token !== routeToken) return;
    clear(view);
    view.append(el("p", { class: "error", text: error.message }));
  }
}

function renderHome() {
  clear(view);
  view.append(el("div", { class: "home-layout" }, [createForm(), historyCard()]));
  refreshHistory();
}

// Static product copy under the question field. Tone goal: lower the bar to
// starting — one sentence is enough, the planner asks follow-up questions
// instead of requiring a complete query up front.
const GUIDE_EXAMPLES = [
  "某市公交夜班车时间调整，上班族吐槽通勤不便",
  "某市水费上涨与阶梯水价计费争议",
  "某高校食堂被学生反映饭菜有问题",
];

function questionGuide(question) {
  return el("div", { class: "home-guide" }, [
    el("p", { class: "muted home-guide-hint", text: "一句话就能开始：写下你看到的事件就行，不用一次写全，缺什么系统会再问你。" }),
    el("p", { class: "home-guide-title", text: "没有头绪？点一个试试" }),
    el("div", { class: "home-examples" }, GUIDE_EXAMPLES.map((text) => el("button", {
      class: "home-example", type: "button", text,
      onClick: () => { question.value = text; question.focus(); },
    }))),
    el("details", { class: "home-more guide-more" }, [
      el("summary", { text: "想查得更准？可以补充（可选）" }),
      el("ul", { class: "home-guide-list" }, [
        el("li", {}, [el("strong", { text: "谁 / 哪里" }), "：具体机构、学校、公司或城市"]),
        el("li", {}, [el("strong", { text: "发生了什么" }), "：一句话说清事件"]),
        el("li", {}, [el("strong", { text: "关心什么" }), "：官方回应、处理进展、规则或费用变化"]),
      ]),
      el("p", { class: "muted home-guide-note", text: "以上都可以先不写：时间范围留空默认查最近，其余信息系统会通过追问补齐。" }),
    ]),
  ]);
}

function createForm() {
  const question = el("textarea", { placeholder: "例如：某市公交夜班车时间调整引发的争议与机构回应" });
  const focus = el("input", { placeholder: "可选：想重点关注的问题（如工作日替代出行、票价变化）" });
  const timeRange = el("input", { placeholder: "可选：YYYY-MM-DD 至 YYYY-MM-DD 或“过去一周”" });
  const region = el("input", { placeholder: "可选：地区" });
  const references = el("input", { placeholder: "可选：参考链接，多个用逗号分隔" });
  const mode = el("select", {}, [
    el("option", { value: "offline", text: "离线演示（固定虚构材料：公交或水费案例；其他输入默认公交案例）" }),
    el("option", { value: "live", text: "真实联网（Brave / Jina / 模型）" }),
  ]);
  const error = el("p", { class: "error" });
  const submit = el("button", { class: "home-submit", text: "开始调查" });
  submit.addEventListener("click", async () => {
    error.textContent = "";
    if (!question.value.trim()) { error.textContent = "请填写要调查的公开事件。"; return; }
    submit.disabled = true;
    try {
      const snapshot = await api.create({
        question: question.value.trim(),
        focus: focus.value.trim() || undefined,
        time_range: timeRange.value.trim() || undefined,
        region: region.value.trim() || undefined,
        reference_urls: references.value.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean),
        mode: mode.value,
      });
      navigate(`/i/${snapshot.run_id}`);
    } catch (exception) {
      error.textContent = exception.message;
    } finally {
      submit.disabled = false;
    }
  });
  return el("section", { class: "card home-form" }, [
    el("h2", { text: "发起公开事件调查" }),
    el("p", { class: "muted lead", text: "输入公开事件与关注点，系统会查找公开材料、梳理争议与回应，并生成每条判断都可回溯原文的中文报告。" }),
    el("label", { text: "公开事件 *" }),
    question,
    questionGuide(question),
    el("div", { class: "home-mode" }, [el("label", { text: "运行模式" }), mode]),
    el("details", { class: "home-more" }, [
      el("summary", { text: "更多范围设置（可选）" }),
      el("label", { text: "关注点" }), focus,
      el("label", { text: "时间范围" }), timeRange,
      el("label", { text: "地区" }), region,
      el("label", { text: "参考链接" }), references,
    ]),
    el("div", { class: "home-actions" }, [submit]),
    error,
  ]);
}

function historyCard() {
  const list = el("div", { id: "history", class: "home-history-list" }, [el("p", { class: "muted", text: "正在读取历史调查…" })]);
  return el("aside", { class: "card home-history" }, [
    el("h2", { text: "历史调查" }),
    el("p", { class: "muted lead", text: "点击任意一条查看它的工作台与全部版本。" }),
    list,
  ]);
}

async function refreshHistory() {
  const list = document.getElementById("history");
  if (!list) return;
  try {
    const data = await api.list();
    clear(list);
    if (!data.investigations.length) { list.append(el("p", { class: "muted", text: "暂无调查记录。" })); return; }
    for (const item of data.investigations) {
      list.append(el("button", { class: "history-item", onClick: () => navigate(`/i/${item.run_id}`) }, [
        el("div", { class: "history-meta" }, [
          el("span", { class: statusClass(item.status), text: statusLabel(item.status) }),
          el("span", { class: "muted", text: item.mode === "offline" ? "离线演示" : "真实联网" }),
          el("span", { class: "muted", text: (item.created_at || "").slice(5, 16).replace("T", " ") }),
        ]),
        el("div", { class: "history-question", text: item.question || "（无问题）" }),
      ]));
    }
  } catch (error) {
    clear(list);
    list.append(el("p", { class: "error", text: error.message }));
  }
}

async function renderDetail(runId, token = routeToken, params = new URLSearchParams()) {
  const snapshot = await api.snapshot(runId);
  if (token !== routeToken) return;
  if (snapshot.status === "needs_clarification") return renderClarify(runId, snapshot);
  if (!TERMINAL.has(snapshot.status)) return renderProgress(runId, snapshot, token);
  if (!snapshot.report) return renderPending(runId, snapshot);
  return renderWorkbenchView(runId, snapshot, token, params);
}

// Terminal reports are rendered through the workbench projection so the page,
// the report download and the versions all come from the same committed view.
async function renderWorkbenchView(runId, snapshot, token = routeToken, params = new URLSearchParams()) {
  const requestedSnapshot = params.get("snapshot") || snapshot.workbench_revision;
  let workbench;
  try {
    workbench = await api.workbench(runId, requestedSnapshot);
  } catch (error) {
    if (token !== routeToken) return;
    if (snapshot.workbench_revision && !/不匹配|match/.test(error.message || "")) {
      renderReportView(runId, snapshot, token);
      return;
    }
    // A pinned snapshot that no longer matches must not silently become the
    // newest view; the user reloads explicitly.
    clear(view);
    view.append(el("section", { class: "card" }, [
      el("span", { class: "badge warn", text: "工作台快照与当前版本不一致" }),
      el("p", { class: "muted", text: error.message }),
      el("div", { class: "row" }, [el("button", { class: "secondary", text: "查看当前版本", onClick: () => renderDetail(runId) })]),
    ]));
    return;
  }
  if (token !== routeToken) return;
  const reportHandlers = {
    onEvidence: (evidenceId) => evidencePanel.open(runId, evidenceId),
    onUpdate: () => navigate(`/i/${runId}/update`),
    onCompare: () => navigate(`/i/${runId}/compare?base=${snapshot.report.parent_id || ""}`),
    citations: workbench.citations,
  };
  renderWorkbench(view, runId, workbench, snapshot, {
    initialState: {
      snapshot: requestedSnapshot,
      view: params.get("view") || null,
      issue: params.get("issue") || null,
      date: params.get("date") || null,
      role: params.get("role") || null,
      evidence: params.get("evidence") || null,
      material: params.get("material") || null,
      invalidEvidence: params.get("invalidEvidence") === "1",
    },
    onRouteState: (next) => navigate(workbenchRouteHash(runId, workbench, next)),
    onEvidence: reportHandlers.onEvidence,
    onUpdate: (issueId) => navigate(`/i/${runId}/update` + (issueId ? `?issue=${encodeURIComponent(issueId)}` : "")),
    onCompare: reportHandlers.onCompare,
    reportHandlers,
  });
}

function renderPending(runId, snapshot) {
  clear(view);
  const previous = snapshot.latest_completed_run_id;
  view.append(el("section", { class: "card" }, [
    el("span", { class: statusClass(snapshot.status), text: statusLabel(snapshot.status) }),
    el("h2", { text: snapshot.subject || snapshot.request.question }),
    el("p", { class: "muted", text: "调查已结束，但报告仍在写入或未能生成。" }),
    previous ? el("p", {}, [
      el("a", { href: `#/i/${previous}`, text: "查看最近一次完整结果" }),
      el("span", { class: "muted", text: "（本版本的未完成事项不因此被掩盖）" }),
    ]) : null,
    el("div", { class: "row" }, [
      el("button", { class: "secondary", text: "重试恢复", onClick: async () => { await api.resume(runId); route(); } }),
      el("a", { class: "chip", href: "#/", text: "返回首页" }),
    ]),
  ]));
}

function renderClarify(runId, snapshot) {
  clear(view);
  const answer = el("textarea", { placeholder: "补充事件、地区或时间信息" });
  const error = el("p", { class: "error" });
  const submit = el("button", { text: "提交补充信息" });
  submit.addEventListener("click", async () => {
    error.textContent = "";
    submit.disabled = true;
    try {
      await api.clarify(runId, answer.value.trim());
      route();
    } catch (exception) { error.textContent = exception.message; }
    finally { submit.disabled = false; }
  });
  const prior = ((snapshot.request && snapshot.request.clarification) || "").trim();
  view.append(el("section", { class: "card" }, [
    el("span", { class: "badge warn", text: "需要补充信息" }),
    el("h2", { text: snapshot.request.question }),
    el("p", { class: "muted", text: "为了确定调查对象，需要补充以下信息。刷新页面不会丢失。" }),
    el("ul", {}, (snapshot.clarification_questions || []).map((text) => el("li", { text }))),
    prior ? el("p", { class: "muted", text: `已收到的补充：${prior.split(/\n+/).filter(Boolean).join("；").slice(-160)}` }) : null,
    el("label", { text: "补充信息" }), answer,
    // Time clarifications carry their own format hint; for event clarifications
    // the user can always defer and the system proceeds on a stated assumption.
    !/时间/.test(snapshot.phase || "") ? el("p", { class: "muted", style: "margin:6px 0 0; font-size:12.5px",
      text: "不确定的问题可以直接回答“不知道”——系统会按最合理的理解继续调查，并在报告限制中注明这一假设。" }) : null,
    el("div", { class: "row", style: "margin-top:12px" }, [submit]),
    error,
  ]));
}

function renderProgress(runId, initial, token = routeToken) {
  clear(view);
  const connectionBox = el("div", { class: "conn-banner", hidden: true });
  const statusBox = el("div");
  view.append(connectionBox, statusBox);
  const setConnection = (state) => {
    connectionBox.hidden = state === "connected";
    connectionBox.className = state === "disconnected" ? "conn-banner danger" : "conn-banner";
    connectionBox.textContent = state === "reconnecting" ? "连接中断，正在恢复…" : state === "disconnected" ? "连接已断开，请刷新页面重试。" : "";
  };
  const paint = (snapshot) => {
    if (token !== routeToken) return;
    if (TERMINAL.has(snapshot.status)) {
      stopStream();
      if (snapshot.report) renderWorkbenchView(runId, snapshot, token);
      else renderPending(runId, snapshot);
      return;
    }
    paintProgress(statusBox, runId, snapshot);
  };
  paint(initial);
  if (!TERMINAL.has(initial.status)) {
    activeStream = stream(runId, paint, () => {}, setConnection);
  }
}

// Running investigations expose the same workbench contract as a provisional
// stage projection; nothing here becomes part of the published core.
async function renderProvisionalWorkbench(runId, token = routeToken) {
  let workbench;
  try {
    workbench = await api.workbench(runId);
  } catch (error) {
    if (token !== routeToken) return;
    renderDetail(runId, token);
    return;
  }
  if (token !== routeToken) return;
  renderWorkbench(view, runId, workbench, { report: null }, {
    onEvidence: (evidenceId) => evidencePanel.open(runId, evidenceId),
    onBack: () => renderDetail(runId, token),
  });
}

function paintProgress(root, runId, snapshot) {
  clear(root);
  const progress = snapshot.progress || {};
  const issues = progress.questions || [];
  const errorBox = el("p", { class: "error", hidden: true });
  root.append(el("section", { class: "card" }, [
    el("div", { class: "row" }, [
      el("span", { class: statusClass(snapshot.status), text: statusLabel(snapshot.status) }),
      el("span", { class: "muted", text: snapshot.phase || "" }),
    ]),
    el("h2", { text: snapshot.subject || snapshot.request.question }),
    snapshot.mode === "offline" ? el("p", { class: "badge warn", text: "虚构材料演示" }) : null,
    snapshot.plan_hint === "proceed_on_assumption" ? el("div", { class: "notice" }, [
      el("p", { text: `用户未能明确调查对象，系统按“${snapshot.subject || snapshot.request.question}”继续调查；这个理解可能与实际所指不同。` }),
      el("p", { class: "muted", text: "如对象不对，可取消本轮后返回首页重新发起；已提交材料会保留在历史记录中。" }),
      el("button", { class: "secondary", text: "更正调查对象（取消本轮）", onClick: async () => {
        try { await api.cancel(runId); } catch (exception) { errorBox.textContent = exception.message; errorBox.hidden = false; return; }
        navigate("/");
      } }),
    ]) : null,
    el("p", { class: "muted", text: "调查正在进行；这里展示阶段、已提交的问题与材料，不显示精确进度百分比。" }),
    el("ul", {}, issues.map((issue) => el("li", { text: `${LABELS[issue.status] || issue.status}：${issue.question}` }))),
    el("p", { class: "muted", text: `已保存材料 ${progress.source_count || 0} 个｜当前有效判断 ${progress.finding_count || 0} 条｜读取失败 ${progress.read_errors || 0}｜搜索失败 ${progress.search_errors || 0}` }),
    (progress.read_errors || progress.search_errors)
      ? el("p", { class: "notice", text: "本轮存在读取或搜索失败：失败不等于“没有材料”，相关问题的结论会如实标注无法判断或材料不足。" })
      : null,
    errorBox,
    el("div", { class: "row" }, [
      el("button", { class: "secondary", text: "查看阶段工作台（待核查）", onClick: () => renderProvisionalWorkbench(runId) }),
      el("button", { class: "danger", text: "取消调查", onClick: async () => {
        // A failed cancel must not flip local state to cancelled; reload the
        // server truth instead.
        try { await api.cancel(runId); } catch (exception) { errorBox.textContent = exception.message; errorBox.hidden = false; return; }
        route();
      } }),
    ]),
  ]));
}

function renderReportView(runId, snapshot, token = routeToken) {
  if (token !== routeToken) return;
  clear(view);
  renderReport(view, snapshot.report, {
    onEvidence: (evidenceId) => evidencePanel.open(runId, evidenceId),
    onUpdate: () => navigate(`/i/${runId}/update`),
    onCompare: () => navigate(`/i/${runId}/compare?base=${snapshot.report.parent_id || ""}`),
    citations: snapshot.report ? citationMapFromReport(snapshot.report) : null,
  });
}

function citationMapFromReport(report) {
  const citations = {};
  report.evidence.forEach((item, index) => { citations[item.evidence_id] = { label: `引${index + 1}` }; });
  return citations;
}

async function renderUpdateForm(runId, preselect) {
  clear(view);
  let issues = [];
  try {
    const snapshot = await api.snapshot(runId);
    issues = (snapshot.report && snapshot.report.issues) || [];
  } catch { issues = []; }
  const focus = el("textarea", { placeholder: "例如：机构是否有新的补充回应？本周是否已开始执行？" });
  const error = el("p", { class: "error" });
  const submit = el("button", { text: "开始补充调查" });
  const boxes = issues.map((issue) => {
    const box = el("input", { type: "checkbox", value: issue.issue_id });
    box.style.width = "auto";
    if (preselect && preselect === issue.issue_id) box.checked = true;
    return el("div", { class: "row" }, [box, el("span", { text: issue.question })]);
  });
  let intentKey = null;
  let intentSignature = null;
  const newIntentKey = () => crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + "-" + Math.random();
  submit.addEventListener("click", async () => {
    error.textContent = "";
    submit.disabled = true;
    try {
      const selected = boxes.map((row) => row.querySelector("input")).filter((box) => box.checked).map((box) => box.value);
      const focusText = focus.value.trim();
      const signature = JSON.stringify({ focus: focusText, issue_ids: selected });
      // One submission intent, one idempotency key. A retry after a lost
      // response keeps the key; editing the intent starts a new request.
      if (intentKey === null || intentSignature !== signature) {
        intentKey = newIntentKey();
        intentSignature = signature;
      }
      const payload = { client_request_id: intentKey };
      if (focusText) payload.focus = focusText;
      if (selected.length) payload.issue_ids = selected;
      const snapshot = await api.update(runId, payload);
      navigate(`/i/${snapshot.run_id}`);
    } catch (exception) { error.textContent = exception.message; }
    finally { submit.disabled = false; }
  });
  view.append(el("section", { class: "card" }, [
    el("h2", { text: "补充新进展 / 定向补查" }),
    el("p", { class: "muted", text: "本轮保留事件身份、旧材料与旧判断；可附带勾选需要定向核查的问题。原报告仍可只读查看。" }),
    el("label", { text: "本轮关注点" }), focus,
    issues.length ? el("div", {}, [el("label", { text: "定向核查的问题（可选）" }), ...boxes]) : null,
    el("div", { class: "row", style: "margin-top:12px" }, [
      submit,
      el("button", { class: "secondary", text: "取消", onClick: () => navigate(`/i/${runId}`) }),
    ]),
    error,
  ]));
}

async function renderCompare(runId, params) {
  clear(view);
  const versions = (await api.versions(runId)).versions;
  const current = versions.find((item) => item.run_id === runId) || versions[versions.length - 1];
  const select = el("select", {}, versions.filter((item) => TERMINAL.has(item.status)).map((item) =>
    el("option", { value: item.run_id, text: `${statusLabel(item.status)}｜${item.run_id.slice(0, 8)}｜${item.created_at}` })));
  const baseParam = params.get("base") || current.parent_id || "";
  if (baseParam) select.value = baseParam;

  const body = el("div");
  // W17: a comparison shows the verdict and evidence count of each judgment
  // (never raw evidence ids) plus explicit retirement reasons; absence of
  // re-evaluation stays its own kind and is never rendered as a withdrawal.
  const findingLine = (f) => el("li", {}, [
    el("span", { text: f.text }),
    el("span", { class: "muted", text: `（核查：${LABELS[f.support] || f.support} · 依据 ${(f.evidence_ids || []).length} 条）` }),
  ]);
  const load = async () => {
    clear(body);
    try {
      const diff = await api.diff(runId, select.value);
      if (!diff.changes.length) { body.append(el("p", { class: "muted", text: "两版之间没有可比较的问题。" })); return; }
      for (const change of diff.changes) {
        const reasons = Object.values(change.retired_reasons || {}).filter(Boolean);
        body.append(el("div", { class: "issue" }, [
          el("h4", { text: change.question }),
          el("p", {}, [el("span", { class: "badge", text: LABELS[change.kind] || change.kind })]),
          change.before.length ? el("div", {}, [
            el("p", { class: "muted", text: "基准版本：" }),
            el("ul", { class: "tl" }, change.before.map(findingLine)),
          ]) : null,
          change.after.length ? el("div", {}, [
            el("p", { text: "当前版本：" }),
            el("ul", { class: "tl" }, change.after.map(findingLine)),
          ]) : null,
          reasons.length ? el("p", { class: "muted", text: `撤回原因：${reasons.join("；")}` }) : null,
          change.kind === "pending_reevaluation" ? el("p", { class: "muted", text: "尚未重新评估，不代表撤回。" }) : null,
        ]));
      }
    } catch (error) { body.append(el("p", { class: "error", text: error.message })); }
  };
  select.addEventListener("change", load);

  const others = versions.filter((item) => item.run_id !== runId);
  view.append(el("section", { class: "card" }, [
    el("h2", { text: "版本比较" }),
    el("label", { text: "基准版本" }), select,
    el("div", {}, [body]),
    el("div", { class: "row" }, [
      el("a", { class: "chip", href: `#/i/${runId}`, text: "返回当前报告" }),
      el("a", { class: "chip", href: api.reportUrl(runId), text: "下载当前版本 Markdown" }),
    ]),
    others.length ? el("div", {}, [
      el("h4", { text: "同一事件的其他版本" }),
      el("ul", {}, others.map((item) => el("li", {}, [
        el("a", { href: `#/i/${item.run_id}`, text: `${statusLabel(item.status)}｜${item.run_id.slice(0, 8)}` }),
        el("span", { class: "muted", text: `｜${item.created_at}` }),
      ]))),
    ]) : null,
  ]));
  if (select.value) load();
}

let booted = false;
function boot() { if (!booted) { booted = true; route(); } }
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", boot);
if (document.readyState !== "loading") boot();
