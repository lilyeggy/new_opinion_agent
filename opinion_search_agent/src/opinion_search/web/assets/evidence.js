import { api } from "./api.js";
import { el, externalLink, LABELS, clear } from "./ui.js";

const RELATION_LABEL = { support: "支持该判断", contradict: "反驳/冲突该判断" };

// Evidence drawer: locates a reviewed excerpt inside its immutable source version.
export function createEvidencePanel() {
  const body = el("div");
  const closeBtn = el("button", { class: "secondary", text: "关闭", onClick: close });
  const drawer = el("aside", { class: "drawer", "aria-hidden": "true", "aria-label": "证据原文" }, [
    el("div", { class: "row" }, [
      el("strong", { text: "证据原文" }),
      closeBtn,
    ]),
    body,
  ]);
  document.body.append(drawer);
  // Escape closes the drawer wherever focus is while it is open.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawer.classList.contains("open")) close();
  });
  let triggerCounter = 0;
  return { open, close };

  function close() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    // Focus returns to the element that opened the panel.
    if (drawer.dataset.opener) {
      const opener = document.getElementById(drawer.dataset.opener);
      if (opener) opener.focus();
    }
  }

  async function open(runId, evidenceId) {
    const trigger = document.activeElement;
    if (trigger && trigger !== drawer) {
      if (!trigger.id) trigger.id = "ev-trigger-" + (++triggerCounter);
      drawer.dataset.opener = trigger.id;
    }
    clear(body);
    body.append(el("p", { class: "muted", text: "正在定位证据…" }));
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    // Keyboard users land on the close button; focus returns to the trigger on close.
    closeBtn.focus();
    let item;
    try {
      item = await api.evidence(runId, evidenceId);
    } catch (error) {
      clear(body);
      body.append(el("p", { class: "error", text: error.message }));
      return;
    }
    clear(body);
    body.append(
      el("h3", { text: item.source.title }),
      el("p", { class: "muted" }, [
        externalLink(item.source.final_url, item.source.final_url),
      ]),
      el("p", { class: "muted", text: `请求地址与最终地址不同时以最终地址为准；发布时间：${item.source.published_at || "未知"}｜更新：${item.source.updated_at || "未知"}｜获取时间：${item.source.fetched_at}` }),
      el("p", { class: "muted", text: `${item.locator}｜来源角色：${LABELS[item.source.role] || item.source.role}` }),
      item.relations && item.relations.length
        ? el("ul", { class: "muted" }, item.relations.map((relation) =>
            el("li", { text: `该材料与一条已提交判断的关系：${RELATION_LABEL[relation.relation] || relation.relation}` })))
        : null,
      el("div", { class: "excerpt" }, [
        el("span", { text: item.before || "" }),
        el("mark", { text: item.excerpt }),
        el("span", { text: item.after || "" }),
      ]),
      el("p", { class: "muted", text: "展示的是该版本保存的不可变原文及上下文，不是实时网页。" }),
    );
  }
}
