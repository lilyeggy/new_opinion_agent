export const LABELS = {
  open: "待调查", answered: "已有材料回答", disputed: "证据存在分歧",
  not_found: "范围内未发现", unavailable: "无法判断",
  direct: "直接回答", partial: "部分回答", non_substantive: "涉及但未实质回答", unknown: "无法判断",
  supported: "引用支持", contradicted: "与引用矛盾", insufficient: "证据不足", unreviewed: "尚未完成核查",
  completed: "调查完成", partial_run: "部分完成", failed: "调查失败", cancelled: "已取消",
  finalizing: "正在写入报告", running: "调查中", planning: "正在明确事件", needs_clarification: "需要补充信息",
  added: "新增判断", revised: "修订判断", withdrawn: "撤回判断", strengthened: "支持加强",
  weakened: "支持减弱", unchanged: "判断未变", evidence_added: "补充依据", pending_reevaluation: "尚未重新评估",
  fact: "事实", attributed: "归因转述", interpretation: "解释", request: "诉求",
  original: "原始材料", reporting: "报道", commentary: "评论", initial: "首版来源",
  existing: "沿用来源", changed_page: "页面内容有变化", new_publication: "新发布材料",
  newly_found_old_material: "新发现的旧材料", publication_unknown: "发布时间未知",
};

export function statusLabel(status) {
  if (status === "partial") return "部分完成";
  return LABELS[status] || status;
}

export function statusClass(status) {
  if (status === "completed") return "badge ok";
  if (status === "partial" || status === "finalizing") return "badge warn";
  if (status === "failed" || status === "cancelled") return "badge danger";
  return "badge";
}

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "href") { if (safeUrl(value) || safeHashLink(value) || safeSameOriginPath(value)) node.setAttribute("href", value); }
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// In-page hash routes are safe; same-origin API paths are safe too. Anything
// else must be an absolute http(s) URL, so javascript:, data: and
// protocol-relative links still cannot become href attributes.
export function safeHashLink(value) {
  const text = String(value);
  return text.startsWith("#") && text.startsWith("#" + "/" + "/") === false;
}

export function safeSameOriginPath(value) {
  const text = String(value);
  if (text.startsWith("/") === false || text.startsWith("/" + "/")) return false;
  if (/[\u0000-\u001f\u007f]/.test(text)) return false;
  try {
    const base = globalThis.location && globalThis.location.origin;
    if (base === undefined || base === null) return false;
    const url = new URL(text, base);
    return url.origin === base && (url.protocol === "http:" || url.protocol === "https:");
  } catch { return false; }
}

export function safeUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "http:" || url.protocol === "https:";
  } catch { return false; }
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function externalLink(label, href) {
  if (safeUrl(href) === false) return el("span", { text: label });
  return el("a", { href, target: "_blank", rel: "noopener noreferrer", text: label });
}
