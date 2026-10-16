// Browser smoke test for the foundations site. It drives an already running
// headless Chrome over the DevTools protocol and checks each interactive widget.
//
// Usage (from opinion_search_foundations/):
//   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
//     --no-sandbox --allow-file-access-from-files --remote-debugging-port=9333 \
//     --user-data-dir=/tmp/cdp-prof about:blank &
//   node scripts/browser_smoke.mjs
// Drives the local Chrome over DevTools Protocol and exercises the interactive widgets.
const base = "http://127.0.0.1:9333";
const target = await (await fetch(`${base}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
});
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => {
  const res = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (res.result.exceptionDetails) throw new Error(JSON.stringify(res.result.exceptionDetails).slice(0, 300));
  return res.result.result.value;
};
const url = (hash) => `file://${process.cwd()}/index.html${hash}`;
async function open(hash) {
  await send("Page.enable");
  await send("Page.navigate", { url: url(hash) });
  await new Promise((r) => setTimeout(r, 900));
}
const results = [];
const check = (name, cond, detail = "") => { results.push(`${cond ? "PASS" : "FAIL"} ${name} ${detail}`); };

// 1. Circuit breaker simulator: three poisoning failures open the circuit; waiting 30s half-opens it.
await open("#/core-tools");
const cbText = () => evaluate(`document.getElementById("cb-state").innerText`);
const click = (sel) => evaluate(`document.getElementById("${sel}").click(), true`);
await click("cb-poison"); await click("cb-poison");
check("circuit: 2 failures stay closed", (await cbText()).includes("2 / 3") && (await cbText()).includes("闭合"));
await click("cb-poison");
check("circuit: 3rd failure opens", (await cbText()).includes("开路"));
await click("cb-ok");
check("circuit: request rejected while open", (await evaluate(`document.getElementById("cb-log").innerText`)).includes("熔断中"));
await click("cb-w30");
check("circuit: 30s cooldown half-opens", (await cbText()).includes("半开"));
await click("cb-other");
check("circuit: non-poisoning probe closes", (await cbText()).includes("闭合"));

// 2. Data flow stepper: next/prev and node click update the detail.
await open("#/sys-dataflow");
await evaluate(`document.getElementById("flow-next").click(), true`);
await evaluate(`document.getElementById("flow-next").click(), true`);
check("flow: next moves to stage 2", (await evaluate(`document.getElementById("flow-detail").innerText`)).includes("阶段 2"));
await evaluate(`document.querySelector('#flow-diagram [data-key="6"]').dispatchEvent(new MouseEvent("click",{bubbles:true})), true`);
check("flow: clicking node 6 jumps", (await evaluate(`document.getElementById("flow-detail").innerText`)).includes("阶段 6"));
check("flow: prev disabled at start", (await evaluate(`(async()=>{document.querySelector('#flow-diagram [data-key="0"]').dispatchEvent(new MouseEvent("click",{bubbles:true}));return document.getElementById("flow-prev").disabled})()`)) === true);

// 3. Context budget: overflow trims L3 then L2; L0/L1 overflow is a typed partial stop.
await open("#/core-context");
const setSlider = (id, v) => evaluate(`(()=>{const e=document.getElementById("${id}");e.value=${v};e.dispatchEvent(new Event("input"));return true})()`);
await setSlider("ctx-budget", 40); await setSlider("ctx-l2", 60); await setSlider("ctx-l3", 40);
const ctxText = () => evaluate(`document.getElementById("ctx-text").innerText`);
check("context: overflow reports trimming", (await ctxText()).includes("先截断 L3"), (await ctxText()).slice(0, 120));
await setSlider("ctx-budget", 100); await setSlider("ctx-l2", 10); await setSlider("ctx-l3", 5);
check("context: fits without compaction", (await ctxText()).includes("无需压缩"), (await ctxText()).slice(0, 80));

// 4. Replay demo: tamper options report the first divergence.
await open("#/core-replay");
await evaluate(`(()=>{const s=document.getElementById("rp-select");s.value="ctx";s.dispatchEvent(new Event("change"));return true})()`);
const rp = await evaluate(`document.getElementById("rp-out").innerText`);
check("replay: context tamper reports step 2", rp.includes("第 2 步") && rp.includes("context_hash"), rp.replace(/\s+/g, " ").slice(0, 100));

// 5. Recovery selector shows the action for a chosen phase.
await open("#/core-recovery");
await evaluate(`(()=>{const s=document.getElementById("rec-select");s.value="3";s.dispatchEvent(new Event("change"));return true})()`);
check("recovery: action_running shows EXECUTE_ACTION", (await evaluate(`document.getElementById("rec-out").innerText`)).includes("EXECUTE_ACTION"));

// 6. Checkpoint crash lab and boundary semantics selector.
await open("#/core-checkpoint");
await evaluate(`(()=>{const s=document.getElementById("cp-select");s.value="s4";s.dispatchEvent(new Event("change"));return true})()`);
check("checkpoint: atomic replace outcome", (await evaluate(`document.getElementById("cp-out").innerText`)).includes("原子"));
await open("#/basics-boundary");
await evaluate(`(()=>{const s=document.getElementById("sem-select");s.value="amo";s.dispatchEvent(new Event("change"));return true})()`);
check("semantics: at-most-once table", (await evaluate(`document.getElementById("sem-out").innerText`)).includes("宁可不做"));

// 7. Interview Q&A filter and code map search.
await open("#/iv-qa");
await evaluate(`(()=>{const s=document.getElementById("qa-search");s.value="exactly";s.dispatchEvent(new Event("input"));return true})()`);
const qaCount = await evaluate(`document.querySelectorAll("#qa-list details").length`);
check("qa: search narrows to exactly-once items", qaCount >= 1 && qaCount < 16, `count=${qaCount}`);
await open("#/sys-codemap");
await evaluate(`(()=>{const s=document.getElementById("code-filter");s.value="circuit";s.dispatchEvent(new Event("input"));return true})()`);
const rows = await evaluate(`document.querySelectorAll("#code-table tr").length`);
check("codemap: filter finds circuit.py", rows >= 2 && (await evaluate(`document.getElementById("code-table").innerText`)).includes("circuit.py"), `rows=${rows}`);

// 8. Self-check reveal toggles.
await open("#/iv-selfcheck");
await evaluate(`document.querySelector('button[data-ans="0"]').click(), true`);
check("selfcheck: answer reveals", (await evaluate(`document.getElementById("ans-0").classList.contains("show")`)) === true);

console.log(results.join("\n"));
console.log(results.every((r) => r.startsWith("PASS")) ? "ALL PASS" : "SOME FAILED");
ws.close();
