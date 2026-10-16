// Core technology track. Each page follows the same shape: the problem, the
// naive approach and why it fails, what this project does, the code landing
// points, and the failure modes. Interactive pieces replicate the actual rules.
(function () {
  var DEEP_CORE = [
    { label: "深度课程 · 02–07 逐层机制", href: "../opinion_search_interview_guide/index.html" },
    { label: "面试资料 03 逐层机制详解", href: "../docs/interview/03-逐层机制详解.md" },
  ];

  function flowRow(items, opts) {
    opts = opts || {};
    var w = opts.w || 150, h = opts.h || 58, gap = opts.gap || 34, y = opts.y || 30;
    var parts = [];
    items.forEach(function (it, i) {
      var x = 20 + i * (w + gap);
      parts.push(Svg.box({ x: x, y: y, w: w, h: h, key: it.key || "", title: it.title, sub: it.sub || "", cls: it.cls || "", fill: it.fill || "#ffffff", stroke: it.stroke }));
      if (i < items.length - 1) parts.push(Svg.line([[x + w, y + h / 2], [x + w + gap, y + h / 2]], {}));
    });
    var width = 40 + items.length * (w + gap);
    return { svg: parts.join(""), width: width };
  }

  // ---------- Runtime ----------
  function singleWriterSvg() {
    var items = [
      { title: "模型决策", sub: "AgentDecision（提议）" },
      { title: "校验", sub: "DecisionValidator" },
      { title: "解析", sub: "ActionResolver" },
      { title: "执行", sub: "ActionExecutor" },
      { title: "观察", sub: "ObservationEnvelope" },
      { title: "增量", sub: "ObservationProcessor" },
      { title: "归约", sub: "Reducer（唯一写者）", fill: "#fff8e6", stroke: "#d9a441" },
      { title: "提交", sub: "commit_step + 存档" },
    ];
    var row = flowRow(items, { w: 118, gap: 22, y: 24, h: 60 });
    return Svg.wrap(row.width, 110, row.svg);
  }

  var PHASE_TABLE = [
    ["opened", "无", "步已开启"],
    ["deciding", "无", "正在请求模型"],
    ["decision_accepted", "decision", "决策已接受；不得有 action"],
    ["action_running", "decision + action", "副作用前的最后存档；不得有 observation"],
    ["observation_ready", "decision + action + observation", "观察已存档，不会再调用工具"],
    ["reducing", "同上", "正在归约"],
    ["committed", "同上", "已提交（STEP_COMMITTED）"],
  ];

  var DIRECTIVES = [
    ["retry_attempt（重试决策）", "模型超时、限流、空响应、服务器错误等。在同一步内再请求一次决策，attempt 加一。"],
    ["feedback_and_continue（反馈后继续）", "决策不合法、动作解析失败、工具返回错误等。把失败作为下一次决策的反馈。"],
    ["partial_stop（诚实停止）", "上下文放不下、重复动作、达到安全上限。保留已提交的部分，状态为 PARTIAL。"],
    ["fail_run（直接失败）", "鉴权或配置错误、归约器不变量被破坏、存档读写失败。状态为 FAILED。"],
    ["cancel_run（取消）", "收到取消信号。状态为 CANCELLED。"],
  ];

  function renderRuntime(el) {
    el.innerHTML =
      '<h2>1. 问题：一步里有很多东西，哪一个说了算？</h2>' +
      "<p>Agent 每一步都会做很多事：模型给出决策、工具返回结果、状态被修改。如果任何一个环节直接修改状态，就无法说清“哪个版本的状态是对的”，崩溃之后也无从判断做到哪了。</p>" +
      "<h2>2. 朴素做法为什么不够</h2>" +
      "<p>常见做法是“模型一边想一边调工具一边改状态”。这样一旦崩溃，状态可能已经半改，工具可能已经调用，重启后无法区分哪些已经发生。</p>" +
      "<h2>3. 本项目的做法：单写者提交链</h2>" +
      '<div class="diagram">' + singleWriterSvg() + '<div class="caption">模型只能提议，工具只能返回观察，只有 Reducer 能写权威状态</div></div>' +
      "<p>把一步拆成七个阶段，每个阶段边界都存档。每个阶段允许携带的数据是<b>硬约束</b>，由 StepRecord 的校验器强制（不是靠约定）：</p>" +
      "<table><tr><th>阶段</th><th>允许携带的载荷</th><th>含义</th></tr>" +
      PHASE_TABLE.map(function (r) { return "<tr><td class=\"mono\">" + r[0] + "</td><td>" + Site.esc(r[1]) + "</td><td>" + Site.esc(r[2]) + "</td></tr>"; }).join("") +
      "</table>" +
      '<div class="callout"><strong>为什么这很重要</strong>如果 action_running 阶段的存档里出现了 observation，就说明写入顺序出错了。校验器会在构造时拒绝这种非法组合，所以“存档里是半截事务”在数据层面不可能出现。</div>' +
      "<h2>4. 提交为什么要“一次构造”</h2>" +
      "<p>提交一步时，新状态要同时改六个字段（新的领域状态、清空活动步、追加历史、推进游标、记录动作 ID、设置 continuation_pending）。这六件事在一次构造中完成；分两次改，中间状态会被不变量拒绝。这是用<b>不变量</b>保证原子性，而不是靠锁。</p>" +
      "<h2>5. 失败怎么分类</h2>" +
      "<p>失败不是一种：有的可以重试，有的应当反馈给模型，有的必须停止。分类表定义在 <code>runtime/errors.py</code>，共 20 种失败类型，映射到 5 种处置指令。</p>" +
      "<table><tr><th>处置指令</th><th>典型情形</th></tr>" +
      DIRECTIVES.map(function (d) { return "<tr><td>" + Site.esc(d[0]) + "</td><td>" + Site.esc(d[1]) + "</td></tr>"; }).join("") +
      "</table>" +
      '<div class="callout warn"><strong>口径提醒</strong>上表是 errors.py 中的映射。具体的恢复行为以 loop.py 为准：例如决策失败在次数用尽后，已有提交的 run 会变成 PARTIAL，没有提交的会变成 FAILED。</div>' +
      "<h2>6. 代码落点</h2>" +
      "<ul>" +
      "<li><code>runtime/loop.py</code> · AgentLoop.run：状态分发器，每轮按 classify_resume 决定动作。</li>" +
      "<li><code>runtime/transaction.py</code> · RunState、commit_step、classify_resume。</li>" +
      "<li><code>runtime/protocols.py</code> · StepRecord 的阶段与载荷约束。</li>" +
      "<li><code>runtime/lifecycle.py</code> · 合法转移表。</li>" +
      "</ul>" +
      '<h2>7. 面试一句话</h2>' +
      '<div class="callout ok">“模型只提议，工具只观察，只有归约器能写状态。每个阶段边界存档，阶段和载荷由校验器绑定，所以崩溃后只需要问‘我停在哪一段’。”</div>';
  }

  // ---------- Checkpoint ----------
  var WRITE_STEPS = [
    { key: "s1", title: "1. 序列化", text: "把状态转成 JSON，键排序、分隔符紧凑。同样的状态永远得到同样的字节，便于比对和调试。" },
    { key: "s2", title: "2. 写临时文件", text: "写到和目标文件同一目录的临时文件里（同一文件系统，才能保证 os.replace 是原子的）。" },
    { key: "s3", title: "3. fsync", text: "强制操作系统把临时文件的内容真正写到磁盘，而不是还留在内存缓冲里。" },
    { key: "s4", title: "4. os.replace", text: "把临时文件原子地换成正式文件。读者要么看到旧版本，要么看到新版本，不会看到半个文件。" },
  ];

  var CRASH_WRITE = {
    before: { file: "正式文件：旧版本，完整可用。临时文件：可能残缺，但不会被读取。", outcome: "重启后加载旧版本，最多丢失这一次存档，run 从上一个存档继续。" },
    s2: { file: "正式文件：旧版本，完整。临时文件：写了一部分。", outcome: "同上：加载旧版本。残留的临时文件不会被当作存档。" },
    s3: { file: "正式文件：旧版本，完整。临时文件：内容可能没落盘。", outcome: "同上：加载旧版本。这就是 fsync 的意义：没有它，断电后临时文件可能是空的，换过去就是坏存档。" },
    s4: { file: "替换是一条原子操作：它要么完成，要么没发生。", outcome: "要么加载旧版本，要么加载新版本。两者都是完整的、可用的。" },
    after: { file: "正式文件：新版本，完整。", outcome: "加载新版本，继续执行。" },
  };

  var LOAD_CHECKS = [
    ["JSON 能否解析", "CheckpointReadError"],
    ["根必须是 object", "CheckpointReadError"],
    ["schema_version 必须等于当前版本（现为 4）", "CheckpointVersionError"],
    ["execution_profile 必须与当前装配一致", "CheckpointProfileError"],
    ["state 字段存在且能通过模型校验", "CheckpointReadError"],
  ];

  function renderCheckpoint(el) {
    var stepsHtml = WRITE_STEPS.map(function (s) {
      return '<div class="card"><h4>' + Site.esc(s.title) + '</h4><p>' + Site.esc(s.text) + "</p></div>";
    }).join("");
    var options = [
      ["before", "写临时文件之前断电"],
      ["s2", "写临时文件的过程中断电"],
      ["s3", "fsync 之后、替换之前断电"],
      ["s4", "替换过程中（原子操作）"],
      ["after", "替换完成之后断电"],
    ];
    el.innerHTML =
      '<h2>1. 问题：存档文件写到一半断电怎么办？</h2>' +
      "<p>如果直接覆盖正式文件，写到一半断电，文件里就是半个 JSON。重启后既读不出旧状态，也读不出新状态。存档本身变成了故障源。</p>" +
      "<h2>2. 本项目的做法：临时文件 + fsync + 原子替换</h2>" +
      '<div class="grid grid-2">' + stepsHtml + "</div>" +
      "<h2>3. 断电实验</h2>" +
      '<p>选择断电的时刻，看正式文件和重启后的结果。</p>' +
      '<div class="toolbar"><label>断电时刻：<select id="cp-select">' +
      options.map(function (o) { return '<option value="' + o[0] + '">' + Site.esc(o[1]) + "</option>"; }).join("") +
      "</select></label></div>" +
      '<div class="detail" id="cp-out"></div>' +
      "<h2>4. 加载时还要校验什么</h2>" +
      "<p>原子写入保证“文件不会半截”，但文件可能来自旧版本程序，或另一套配置。所以加载时有五道校验：</p>" +
      "<table><tr><th>校验</th><th>失败时抛出</th></tr>" +
      LOAD_CHECKS.map(function (c) { return "<tr><td>" + Site.esc(c[0]) + "</td><td class=\"mono\">" + c[1] + "</td></tr>"; }).join("") +
      "</table>" +
      "<h2>5. execution_profile 是什么</h2>" +
      "<p>它是一个由配置生成的不透明摘要（模型名、服务地址、步数上限、超时等）。它的作用是：换了模型或工具组合之后，旧存档不能被新配置继续执行。否则新模型会去解释旧模型的决策，语义已经变了。摘要不包含密钥本身。</p>" +
      '<div class="callout warn"><strong>已知限制（面试主动说）</strong>当前实现对临时文件做了 fsync，但没有对所在目录做 fsync。在某些文件系统上，断电后 rename 本身可能还没持久化。这意味着“替换完成”的瞬间断电，极少数情况下可能加载到旧版本。它不会损坏存档，但会让最近一步需要重做。</div>' +
      "<h2>6. 代码落点与面试一句话</h2>" +
      "<ul><li><code>runtime/checkpoint.py</code> · JsonCheckpointStore._save_sync / _load_sync</li>" +
      "<li><code>app/run_bundle.py</code> · 终态产物也用同样的原子写</li></ul>" +
      '<div class="callout ok">“存档用临时文件加 fsync 再原子替换，所以读者只会看到完整的旧版或新版。加载时校验版本和配置指纹，防止旧存档被新配置误用。”</div>';

    function show() {
      var key = document.getElementById("cp-select").value;
      var r = CRASH_WRITE[key];
      document.getElementById("cp-out").innerHTML =
        "<table><tr><th>磁盘上的文件</th><td>" + Site.esc(r.file) + "</td></tr>" +
        "<tr><th>重启后</th><td>" + Site.esc(r.outcome) + "</td></tr></table>";
    }
    document.getElementById("cp-select").addEventListener("change", show);
    show();
  }

  // ---------- Recovery ----------
  var RECOVERY = [
    { phase: "opened", resume: "REQUEST_DECISION", action: "进入决策阶段，请求模型", calls: "模型：0 次（尚未请求）", risk: "低：尚未请求模型，没有外部副作用。", tone: "ok" },
    { phase: "deciding", resume: "REQUEST_DECISION", action: "重新请求决策；attempt 计数已在存档中", calls: "模型：可能再请求 1 次", risk: "低：模型输出可能不同，但决策只在被接受后才生效。", tone: "ok" },
    { phase: "decision_accepted", resume: "RESOLVE_ACTION", action: "重新解析动作，不再请求模型", calls: "模型：0 次；外部工具：0 次", risk: "无外部副作用。", tone: "ok" },
    { phase: "action_running", resume: "EXECUTE_ACTION", action: "执行动作；先查成功结果缓存，命中则复用", calls: "工具：命中缓存 0 次；未命中可能再调用 1 次", risk: "唯一存在重复外部调用窗口的阶段。", tone: "warn" },
    { phase: "observation_ready", resume: "REDUCE_OBSERVATION", action: "构造增量并归约，绝不再调用工具", calls: "工具：0 次", risk: "无外部副作用。归约必须是纯函数。", tone: "ok" },
    { phase: "reducing", resume: "REDUCE_OBSERVATION", action: "同上；commit_step 幂等，防止重复生效", calls: "工具：0 次", risk: "无外部副作用；重复提交不会生效两次。", tone: "ok" },
    { phase: "committed", resume: "EVALUATE_CONTINUATION", action: "先做完成判定（continuation_pending 为真）", calls: "工具：0 次", risk: "不会打开新的一步，也不会重放上一步。", tone: "ok" },
  ];

  function renderRecovery(el) {
    var timeline = (function () {
      var names = RECOVERY.map(function (r) { return r.phase; });
      var parts = [];
      names.forEach(function (n, i) {
        var x = 16 + i * 146;
        parts.push(Svg.box({ x: x, y: 40, w: 128, h: 56, key: n, title: n, sub: "阶段 " + i }));
        if (i < names.length - 1) parts.push(Svg.line([[x + 128, 68], [x + 146, 68]], {}));
      });
      // Window bars: A spans action_running..observation_ready, B spans observation_ready..reducing, C sits on committed.
      function barX(i) { return 16 + i * 146; }
      function bar(from, to, color, label) {
        var x1 = barX(from), x2 = barX(to) + 128;
        return '<rect x="' + x1 + '" y="106" width="' + (x2 - x1) + '" height="8" rx="4" fill="' + color + '"/>' +
          '<text class="node-title" x="' + (x1 + (x2 - x1) / 2) + '" y="128" text-anchor="middle" fill="' + color + '">' + label + "</text>";
      }
      parts.push(bar(3, 4, "#b7791f", "窗口 A"));
      parts.push(bar(4, 5, "#2f6fdb", "窗口 B"));
      parts.push(bar(6, 6, "#1f8a5b", "窗口 C"));
      parts.push(Svg.text(16, 160, "窗口 A：ACTION_RUNNING 已存，OBSERVATION 未存 → 可能重复调用工具", "lbl"));
      parts.push(Svg.text(16, 178, "窗口 B：OBSERVATION 已存，State 未提交 → 只重做归约，绝不调用工具", "lbl"));
      parts.push(Svg.text(16, 196, "窗口 C：State 已提交，调用方未拿到结果 → 先做完成判定，不重做执行", "lbl"));
      return Svg.wrap(1040, 210, parts.join(""));
    })();

    el.innerHTML =
      '<h2>1. 问题：崩溃以后，哪些事不能再做一遍？</h2>' +
      "<p>重启后最怕两件事：一是漏做（状态不完整），二是重做（副作用发生两次，例如重复搜索、重复扣款）。恢复的核心就是在两者之间找到边界。</p>" +
      "<h2>2. 本项目的答案：恢复只看存档</h2>" +
      "<p><code>classify_resume</code> 只读存档里的 RunState，不读任何内存变量。首次执行和崩溃恢复走的是同一条代码路径。</p>" +
      '<div class="diagram">' + timeline + '<div class="caption">三个崩溃窗口在阶段序列中的位置</div></div>' +
      "<h2>3. 七个阶段各自怎么恢复</h2>" +
      '<p>点击一行，看它的恢复动作与外部调用次数。</p>' +
      '<div class="toolbar"><label>崩溃时停在：<select id="rec-select">' +
      RECOVERY.map(function (r, i) { return '<option value="' + i + '">' + Site.esc(r.phase) + "</option>"; }).join("") +
      "</select></label></div>" +
      '<div class="detail" id="rec-out"></div>' +
      "<h2>4. 三个窗口：为什么只有一个会重复调用</h2>" +
      "<ul>" +
      "<li><b>窗口 A（action_running → observation_ready）</b>：工具可能已经收到请求，结果还没存。缓存能把重复缩小到“结果写入缓存之前崩溃”这一小段，但不能消除。</li>" +
      "<li><b>窗口 B（observation_ready → reducing）</b>：观察结果已存档。恢复时只重做归约，绝不再调用工具。归约器必须是纯函数，重做才安全。</li>" +
      "<li><b>窗口 C（committed → 调用方收到结果之间）</b>：状态已提交，continuation_pending 标志保证先做完成判定，不会重复执行上一步。</li>" +
      "</ul>" +
      '<div class="callout danger"><strong>不要说“exactly-once”</strong>外部 exactly-once 需要服务商接受幂等键、共享事务存储、或 outbox 机制。本项目的准确承诺是：<b>已落盘的成功结果不会被再次请求</b>，加上<b>状态效果幂等</b>，即 effectively-once 的状态效果。这依赖于一个前提：舆情工具是只读的，重发安全。</div>' +
      "<h2>5. 怎么验证的</h2>" +
      "<p>恢复矩阵不只断言“最终完成了”，还断言各组件的<b>调用次数</b>。例如：观察结果已存档时，工具适配器的调用次数必须为 0。注入矩阵覆盖了 14 条注入路径；每个崩溃窗口都有对应的测试。</p>" +
      '<div class="callout ok"><strong>面试一句话</strong>“恢复只依赖存档。每个阶段恢复时要做的事各不相同：决策阶段可能重问模型，观察已存的阶段绝不重调工具。唯一有重复风险的是动作执行中途崩溃，我们用成功结果缓存把它缩到最小，并且明确不承诺外部 exactly-once。”</div>';

    function show() {
      var r = RECOVERY[Number(document.getElementById("rec-select").value)];
      document.getElementById("rec-out").innerHTML =
        "<h4>停在 <span class=\"mono\">" + Site.esc(r.phase) + "</span></h4>" +
        "<table><tr><th>resume 判定</th><td class=\"mono\">" + r.resume + "</td></tr>" +
        "<tr><th>恢复动作</th><td>" + Site.esc(r.action) + "</td></tr>" +
        "<tr><th>外部调用</th><td>" + Site.esc(r.calls) + "</td></tr>" +
        '<tr><th>风险</th><td><span class="tag ' + r.tone + '">' + Site.esc(r.risk) + "</span></td></tr></table>";
    }
    document.getElementById("rec-select").addEventListener("change", show);
    show();
  }

  // ---------- Tools ----------
  var ERROR_GROUPS = [
    ["可重试", "同一服务商内重试（有退避）", "timeout · rate_limited · server_error"],
    ["立即停止", "不再尝试，直接把错误交给上层", "invalid_arguments · unknown_tool · cancelled"],
    ["跨服务商回退", "同一请求换下一个服务商", "authentication · permission · not_found · unreadable_content · content_too_large · unknown_provider_error"],
  ];

  function executorSvg() {
    var p = [];
    var chain = [
      ["逻辑工具", "search.web / read.web"],
      ["参数校验", "失败 → invalid_arguments"],
      ["结果缓存", "命中则直接返回"],
      ["服务商循环", "按绑定顺序尝试"],
      ["Observation", "成功写入缓存"],
    ];
    chain.forEach(function (c, i) {
      var x = 16 + i * 206;
      p.push(Svg.box({ x: x, y: 30, w: 170, h: 56, title: c[0], sub: c[1], key: "chain" + i }));
      if (i < chain.length - 1) p.push(Svg.line([[x + 170, 58], [x + 206, 58]], {}));
    });
    // Inner loop for the provider chain, drawn under the fourth box.
    var lx = 16 + 3 * 206;
    p.push(Svg.box({ x: lx - 10, y: 130, w: 190, h: 46, title: "熔断门控", sub: "熔断中则跳过该服务商", key: "gate", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.box({ x: lx - 10, y: 200, w: 190, h: 46, title: "调用（带超时）", sub: "失败 → 分类", key: "call", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.box({ x: lx - 10, y: 270, w: 190, h: 46, title: "分类后决定", sub: "重试 / 停止 / 换服务商", key: "decide", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.line([[lx + 85, 176], [lx + 85, 200]], {}));
    p.push(Svg.line([[lx + 85, 246], [lx + 85, 270]], {}));
    p.push(Svg.line([[lx + 85, 130], [lx + 85, 86]], { dashed: true }));
    p.push(Svg.text(16, 300, "服务商循环：熔断门控 → 调用 → 分类；可重试则带退避再试，否则换下一个服务商。", "lbl"));
    return Svg.wrap(1040, 320, p.join(""));
  }

  // Circuit breaker simulator mirrors tools/circuit.py: threshold 3, cooldown 30 s, one probe in half-open.
  function circuitState() {
    return { status: "closed", failures: 0, probe: false, openedAt: 0, now: 0, log: [] };
  }

  function circuitAct(s, action) {
    function log(msg) { s.log.unshift("t=" + s.now + "s  " + msg); }
    if (action === "wait10") { s.now += 10; log("等待 10 秒"); }
    if (action === "wait30") { s.now += 30; log("等待 30 秒"); }
    if (s.status === "open" && s.now - s.openedAt >= 30) { s.status = "half"; s.probe = false; log("冷却结束 → 半开"); }
    if (action !== "request_ok" && action !== "request_poison" && action !== "request_other") return s;

    if (s.status === "open") { log("请求被拒绝：熔断中，不调用服务商"); return s; }
    if (s.status === "half") {
      if (s.probe) { log("请求被拒绝：半开状态只允许一个探测请求"); return s; }
      s.probe = true;
      var outcome = action === "request_ok" ? "ok" : action === "request_poison" ? "poison" : "other";
      if (outcome === "ok") { s.status = "closed"; s.failures = 0; s.probe = false; log("探测成功 → 闭合"); }
      else if (outcome === "poison") { s.status = "open"; s.openedAt = s.now; s.probe = false; log("探测遇中毒类失败 → 重新开路"); }
      else { s.status = "closed"; s.failures = 0; s.probe = false; log("探测得到非中毒结果（如鉴权失败）→ 闭合，因为这不是服务商健康问题"); }
      return s;
    }
    // closed
    if (action === "request_ok") { s.failures = 0; log("成功 → 计数清零"); }
    else if (action === "request_poison") {
      s.failures += 1;
      if (s.failures >= 3) { s.status = "open"; s.openedAt = s.now; log("第 3 次连续中毒类失败 → 开路"); }
      else log("中毒类失败，计数 " + s.failures + "/3");
    } else { log("非中毒失败（如鉴权）→ 不计入熔断"); }
    return s;
  }

  function renderCircuit(el) {
    el.innerHTML =
      '<div class="toolbar">' +
      '<button id="cb-ok">请求成功</button>' +
      '<button id="cb-poison">中毒类失败（超时/限流/5xx）</button>' +
      '<button id="cb-other">非中毒失败（鉴权/权限）</button>' +
      '<button id="cb-w10">等待 10 秒</button>' +
      '<button id="cb-w30">等待 30 秒</button>' +
      '<button id="cb-reset">重置</button></div>' +
      '<div class="detail" id="cb-state"></div>' +
      '<div class="card"><h4>事件日志</h4><div id="cb-log" class="mono" style="font-size:13px"></div></div>' +
      '<div class="callout warn"><strong>模拟器说明</strong>规则与 tools/circuit.py 一致：键是 (工具, 服务商)；阈值 3；冷却 30 秒；半开只放一个探测。这是算法模拟，不是真实的网络调用。</div>';

    var s = circuitState();
    function draw() {
      var label = { closed: "闭合（正常调用）", open: "开路（暂停调用）", half: "半开（只放一个探测）" }[s.status];
      document.getElementById("cb-state").innerHTML =
        "<h4>当前状态：" + label + "</h4>" +
        "<table><tr><th>连续中毒类失败</th><td>" + s.failures + " / 3</td></tr>" +
        "<tr><th>时间</th><td>" + s.now + " 秒</td></tr>" +
        "<tr><th>探测进行中</th><td>" + (s.probe ? "是" : "否") + "</td></tr></table>";
      document.getElementById("cb-log").innerHTML = s.log.slice(0, 8).map(Site.esc).join("<br>") || "（暂无事件）";
    }
    function act(a) { circuitAct(s, a); draw(); }
    document.getElementById("cb-ok").addEventListener("click", function () { act("request_ok"); });
    document.getElementById("cb-poison").addEventListener("click", function () { act("request_poison"); });
    document.getElementById("cb-other").addEventListener("click", function () { act("request_other"); });
    document.getElementById("cb-w10").addEventListener("click", function () { act("wait10"); });
    document.getElementById("cb-w30").addEventListener("click", function () { act("wait30"); });
    document.getElementById("cb-reset").addEventListener("click", function () { s = circuitState(); draw(); });
    draw();
  }

  function renderTools(el) {
    el.innerHTML =
      '<h2>1. 问题：外部服务随时会失败，失败还有不同性质</h2>' +
      "<p>搜索服务可能超时、限流、返回 500，也可能是鉴权失败或者网页打不开。它们的处理方式完全不同：超时值得重试，鉴权失败重试没有意义，一个服务挂了还要避免拖慢整个系统。</p>" +
      "<h2>2. 朴素做法为什么不够</h2>" +
      "<p>“失败就重试 N 次”的问题是：对鉴权失败重试是浪费；对一个已经挂掉的服务持续重试会放大故障；而且重试是在单个服务商内，还是跨服务商，没有说清。</p>" +
      "<h2>3. 本项目的做法：分类、门控、回退</h2>" +
      '<div class="diagram">' + executorSvg() + '<div class="caption">ToolExecutor 的执行流水线</div></div>' +
      "<h3>错误的三种命运</h3>" +
      "<table><tr><th>策略</th><th>含义</th><th>错误类型</th></tr>" +
      ERROR_GROUPS.map(function (g) { return "<tr><td>" + Site.esc(g[0]) + "</td><td>" + Site.esc(g[1]) + "</td><td class=\"mono\">" + Site.esc(g[2]) + "</td></tr>"; }).join("") +
      "</table>" +
      "<p>共 12 种错误类型（ToolErrorKind）。注意：<code>max_attempts_per_provider</code> 是<b>单服务商内</b>的次数；跨服务商的回退是另一层。ToolInvocation.attempt 是跨服务商的物理计数，而 action_id 在整个过程中保持不变。</p>" +
      "<h3>熔断器：一个服务挂了，别拖垮其他</h3>" +
      "<p>熔断的键是 <b>(工具名, 服务商)</b>。只按服务商会让某个工具的故障拖垮该服务商的其他能力；只按工具会让一个坏服务商遮蔽另一个健康的服务商。只有“中毒类”错误（超时、限流、5xx、未知服务商错误）计入熔断；鉴权和权限错误是配置问题，必须每次都可见。</p>" +
      '<div id="circuit-sim"></div>' +
      "<h3>两级缓存与 MCP 边界</h3>" +
      "<ul>" +
      "<li><b>进程内缓存</b>与<b>按 action 落盘的成功结果缓存</b>是两层。落盘缓存让崩溃后的恢复可以复用成功结果（见“崩溃恢复”）。损坏的缓存会抛出明确错误，不会被当作“没有缓存”而悄悄重试。</li>" +
      "<li><b>MCP</b>：外部 MCP server 的工具必须先过应用自己的 allowlist，并且 schema 指纹必须与审核时一致，然后才原子地注册。发现（discovery）不等于授权。</li>" +
      "<li><b>HTTP 边界</b>：不自动跟随重定向；URL 要做公开地址校验。</li>" +
      "</ul>" +
      '<div class="callout ok"><strong>面试一句话</strong>“错误按性质分三类：可重试的在单服务商内带退避重试，不可重试的直接停，配置类的换服务商。熔断按工具和服务商组合隔离，只统计中毒类错误，所以鉴权问题不会被熔断吞掉。”</div>' +
      "<h3>代码落点</h3><ul><li><code>tools/executor.py</code> · ToolExecutor.execute</li><li><code>tools/circuit.py</code> · CircuitBreaker</li><li><code>tools/contracts.py</code> · ToolErrorKind 与重试策略</li><li><code>tools/persistent_cache.py</code> · JsonActionResultCache</li><li><code>tools/adapters/mcp.py</code> · MCP 边界</li></ul>";

    renderCircuit(document.getElementById("circuit-sim"));
  }

  // ---------- Context ----------
  var LAYERS = [
    { key: "L0", name: "不可变指令", what: "运行时核心指令、领域规则", rule: "必须 required、必须 trusted、来源必须是应用配置、永不压缩", color: "#2f6fdb" },
    { key: "L1", name: "稳定任务", what: "任务请求、决策 schema、工具说明", rule: "必须 required、必须 trusted、永不压缩", color: "#4f87e3" },
    { key: "L2", name: "工作记忆", what: "缺口覆盖、证据、主张、候选来源、失败方向", rule: "按需选择；预算紧张时可截断或丢弃", color: "#8fb3f0" },
    { key: "L3", name: "近期交互", what: "最近几步的决策、观察、错误与拒绝理由", rule: "按需选择；预算紧张时最先被截断", color: "#c4d8f7" },
  ];

  function renderContext(el) {
    var layerHtml = LAYERS.map(function (l) {
      return '<div class="card" style="border-left:6px solid ' + l.color + '"><h4>' + l.key + " · " + Site.esc(l.name) + "</h4>" +
        "<p>" + Site.esc(l.what) + '</p><div class="analogy">' + Site.esc(l.rule) + "</div></div>";
    }).join("");
    el.innerHTML =
      '<h2>1. 问题：模型每次只能看到一小段文字</h2>' +
      "<p>上下文窗口有限。如果把所有历史原样拼进去，长任务很快放不下；如果随便截断，关键证据可能被丢掉；而网页内容、工具返回的文字可能夹带“请忽略之前的指令”这类注入。</p>" +
      "<h2>2. 本项目的做法：每次调用前从状态重新编译</h2>" +
      '<p>上下文不是聊天历史，而是从权威状态<b>确定性地编译</b>出来的：<code>collect → select → compact → render</code>。同样的状态，永远得到同样的上下文。</p>' +
      "<h2>3. 四层结构</h2>" +
      '<div class="grid grid-2">' + layerHtml + "</div>" +
      "<h2>4. 预算示意（教学模拟，非真实 token 计算）</h2>" +
      '<p>拖动滑块，看预算紧张时哪些层先被牺牲。规则：L0 和 L1 永远不压缩；超出预算时先截断 L3，再丢弃 L2 中未被引用的部分；如果 L0 + L1 本身就放不下，就<b>诚实停止</b>（PARTIAL），而不是截断指令。</p>' +
      '<div class="card"><label>预算（相对单位）<input type="range" id="ctx-budget" min="40" max="100" value="80"></label>' +
      '<label>L2 工作记忆大小<input type="range" id="ctx-l2" min="10" max="60" value="35"></label>' +
      '<label>L3 近期交互大小<input type="range" id="ctx-l3" min="5" max="40" value="20"></label>' +
      '<div class="bar" id="ctx-bar" style="margin-top:10px"></div><div id="ctx-text" style="margin-top:8px"></div></div>' +
      "<h2>5. 信任边界：写进类型里，而不是靠约定</h2>" +
      "<table><tr><th>来源</th><th>能否标为 trusted</th><th>说明</th></tr>" +
      "<tr><td>应用配置</td><td>可以</td><td>L0 指令的唯一来源</td></tr>" +
      "<tr><td>用户任务</td><td>可以（仅 L1 任务段）</td><td>用户的问题本身</td></tr>" +
      "<tr><td>模型（model）</td><td>不可以</td><td>模型上一轮说的话，永远是 untrusted</td></tr>" +
      "<tr><td>工具（tool）</td><td>不可以</td><td>网页正文、搜索结果都在这里</td></tr>" +
      "<tr><td>服务商（provider）</td><td>不可以</td><td>服务商返回的任何文字</td></tr></table>" +
      '<div class="callout warn"><strong>注意口径</strong>这是上下文里的来源与信任标签，由 pydantic 校验器强制。它保证的是“外部内容不获得指令地位”这一结构性质，<b>不是</b>运行时的权限隔离，也不保证模型不会被说服。</div>' +
      "<h2>6. 压缩不删除事实</h2>" +
      "<p>压缩只影响“这一轮模型看到什么”。完整状态和产物仍然保留，溯源链是：结论 → 证据 ID → 来源 ID → 产物引用 → 原文位置。目前还缺一个让模型主动重读某段原文的动作，这是下一步可补的能力。</p>" +
      "<h2>7. 面试一句话</h2>" +
      '<div class="callout ok">“上下文是从状态确定性编译出来的，分四层：指令和任务永远完整，工作记忆和近期交互按预算裁剪。信任标签写在类型里，模型和工具的输出永远不能获得指令地位。”</div>';

    function draw() {
      var budget = Number(document.getElementById("ctx-budget").value);
      var l2 = Number(document.getElementById("ctx-l2").value);
      var l3 = Number(document.getElementById("ctx-l3").value);
      var fixed = 25; // L0 + L1, never compacted
      var total = fixed + l2 + l3;
      var keepL3 = l3, keepL2 = l2;
      var text = "";
      if (total > budget) {
        var over = total - budget;
        var cutL3 = Math.min(keepL3, over);
        keepL3 -= cutL3; over -= cutL3;
        var cutL2 = Math.min(keepL2, over);
        keepL2 -= cutL2; over -= cutL2;
        if (over > 0) {
          text = '<span class="tag danger">L0 + L1 超出预算，诚实停止（PARTIAL），不截断指令</span>';
        } else {
          text = '<span class="tag warn">超出预算：先截断 L3（' + (l3 - keepL3) + "），再丢弃 L2（" + (l2 - keepL2) + "）</span>";
        }
      } else {
        text = '<span class="tag ok">全部放得下，无需压缩</span>';
      }
      var scale = 100 / Math.max(total, budget);
      var bar = document.getElementById("ctx-bar");
      bar.innerHTML =
        '<div style="width:' + fixed * scale + '%;background:#2f6fdb" title="L0+L1"></div>' +
        '<div style="width:' + keepL2 * scale + '%;background:#8fb3f0" title="L2 保留"></div>' +
        '<div style="width:' + keepL3 * scale + '%;background:#c4d8f7" title="L3 保留"></div>' +
        '<div style="width:' + Math.max(0, (budget - (fixed + keepL2 + keepL3))) * scale + '%;background:#eef1f6" title="空余"></div>';
      document.getElementById("ctx-text").innerHTML = "预算 " + budget + "；需求 " + total + "；" + text;
    }
    ["ctx-budget", "ctx-l2", "ctx-l3"].forEach(function (id) { document.getElementById(id).addEventListener("input", draw); });
    draw();
  }

  // ---------- Replay ----------
  var TAMPERS = {
    none: { label: "不篡改（原样回放）", result: "matched", text: "回放的 5 个步骤与录制完全一致。" },
    ctx: { label: "篡改第 2 步的上下文哈希", result: "diverged", step: 2, field: "model_calls[0].context_hash", text: "回放到第 2 步时，模型拿到的上下文与录制不同。回放停止，并指出第一处分歧。" },
    fp: { label: "篡改第 3 步的状态指纹", result: "diverged", step: 3, field: "state_fingerprint", text: "前两步一致；第 3 步提交后的状态指纹与录制不同。" },
    miss: { label: "删除最后一条录制", result: "missing", text: "回放请求了一个不存在的模型调用。系统报错，而不是悄悄调用真实模型（这是 I4 不变量）。" },
  };

  function renderReplay(el) {
    el.innerHTML =
      '<h2>1. 问题：怎么证明“恢复之后的行为”和原来一致？</h2>' +
      "<p>崩溃恢复、代码重构、改了一个函数，都可能悄悄改变 Agent 的行为。光看“最后跑通了”不够，需要能逐步对比。</p>" +
      "<h2>2. 做法：录下外部输入，原样重放，逐步比对</h2>" +
      '<div class="diagram">' +
      Svg.wrap(1040, 250,
        Svg.box({ x: 20, y: 30, w: 200, h: 56, title: "真实运行", sub: "模型 + 工具（外部）" }) +
        Svg.line([[220, 58], [270, 58]], {}) +
        Svg.box({ x: 270, y: 30, w: 220, h: 56, title: "录制器", sub: "每次模型调用 + 步骤指纹" }) +
        Svg.line([[490, 58], [540, 58]], {}) +
        Svg.box({ x: 540, y: 30, w: 200, h: 56, title: "journal 文件", sub: "每个提交的步骤一条", fill: "#fff8e6", stroke: "#d9a441" }) +
        Svg.line([[740, 58], [790, 58]], { dashed: true }) +
        Svg.box({ x: 790, y: 30, w: 230, h: 56, title: "回放", sub: "替换模型与工具为录制内容" }) +
        Svg.line([[905, 86], [905, 150]], {}) +
        Svg.box({ x: 790, y: 150, w: 230, h: 56, title: "逐步比对", sub: "第一处分歧 → 步骤与字段" }) +
        Svg.box({ x: 270, y: 150, w: 220, h: 56, title: "生产代码", sub: "上下文编译、校验、归约都不替换", fill: "#eef5ff" }) +
        Svg.line([[380, 150], [380, 86]], { dashed: true }) +
        Svg.text(20, 230, "虚线：回放时只替换模型和工具；其余组件仍然是生产代码，所以回放检查的是真实逻辑。", "lbl")
      ) + '<div class="caption">录制与回放的数据流</div></div>' +
      "<h2>3. 每一步记录什么</h2>" +
      "<table><tr><th>内容</th><th>用途</th></tr>" +
      "<tr><td>每次模型调用的上下文哈希</td><td>检查回放时模型看到的输入是否一样（上下文编译是否确定）</td></tr>" +
      "<tr><td>模型输出（决策或错误）</td><td>回放时原样返回，不再调用真实模型</td></tr>" +
      "<tr><td>动作与观察</td><td>回放时工具返回录制值；动作必须一致</td></tr>" +
      "<tr><td>提交后状态的指纹</td><td>检查状态是否按同样的方式演变</td></tr></table>" +
      "<h2>4. 在线试一试：篡改一个字段</h2>" +
      '<div class="toolbar"><label>选择：<select id="rp-select">' +
      Object.keys(TAMPERS).map(function (k) { return '<option value="' + k + '">' + Site.esc(TAMPERS[k].label) + "</option>"; }).join("") +
      "</select></label></div>" +
      '<div class="detail" id="rp-out"></div>' +
      '<div class="callout warn"><strong>这是教学模拟</strong>结果展示的是比对逻辑的行为，不是在运行真实回放。真实的回放测试在 tests/integration/test_decision_replay.py。</div>' +
      "<h2>5. 比较的顺序很重要</h2>" +
      "<p>比较按执行顺序进行：先步骤编号与 ID，再模型调用（哈希、结果），再动作与观察，最后状态指纹。所以第一处分歧就指向<b>最早出问题的地方</b>，后面的连锁差异不会干扰判断。</p>" +
      "<h2>6. 能证明什么，不能证明什么</h2>" +
      "<table><tr><th>能证明</th><th>不能证明</th></tr>" +
      "<tr><td>给定录制的输入，当前代码会得到同样的步骤序列和状态</td><td>模型在真实环境里一定会给出同样的回答</td></tr>" +
      "<tr><td>崩溃恢复之后，状态与不崩溃时一致（在测试覆盖的窗口内）</td><td>所有崩溃窗口都被覆盖（当前只覆盖了其中的代表性窗口）</td></tr>" +
      "<tr><td>代码改动是否改变了既有行为</td><td>答案的语义正确（这仍需要人工审查）</td></tr>" +
      "<tr><td>相同 journal 多次回放结果相同</td><td>跨机器、跨语言环境的完全一致（依赖 Python 的确定性序列化）</td></tr></table>" +
      "<h2>7. 面试一句话</h2>" +
      '<div class="callout ok">“我们把模型输出和工具结果录下来，用生产代码原样重放，逐步比对状态指纹。第一处分歧会精确到步骤和字段。它证明的是‘给定相同的外部输入，行为不变’，而不是‘模型的答案正确’。”</div>';

    function show() {
      var k = document.getElementById("rp-select").value;
      var t = TAMPERS[k];
      var statusTag = t.result === "matched" ? '<span class="tag ok">MATCHED</span>' :
        t.result === "diverged" ? '<span class="tag warn">DIVERGED</span>' : '<span class="tag danger">报错：缺少录制</span>';
      var div = t.result === "diverged"
        ? "<tr><th>第一处分歧</th><td>第 " + t.step + " 步 · <span class=\"mono\">" + t.field + "</span></td></tr>" : "";
      document.getElementById("rp-out").innerHTML =
        "<h4>" + statusTag + "</h4><table><tr><th>说明</th><td>" + Site.esc(t.text) + "</td></tr>" + div + "</table>";
    }
    document.getElementById("rp-select").addEventListener("change", show);
    show();
  }

  // ---------- Domain ----------
  function renderDomain(el) {
    el.innerHTML =
      '<h2>1. 问题：模型说的“做什么”和真正做的“做什么”不是一回事</h2>' +
      "<p>模型可能提议搜索一个不存在的 ID，或者引用一条从未读过的来源。系统要做的是：把模型的<b>提议</b>和系统的<b>动作</b>分开，中间用校验和解析隔开。</p>" +
      "<h2>2. 四个对象，各管一段</h2>" +
      "<table><tr><th>对象</th><th>由谁产生</th><th>含义</th><th>例子</th></tr>" +
      "<tr><td>Decision（决策）</td><td>模型</td><td>语义意图，只是提议</td><td>“我想搜索 gap-primary 的官方声明”</td></tr>" +
      "<tr><td>Action（动作）</td><td>ActionResolver</td><td>可执行的内部单元，带 action_id</td><td>一次 search.web 调用的请求</td></tr>" +
      "<tr><td>Observation（观察）</td><td>执行器</td><td>外部世界返回了什么</td><td>搜索返回的候选列表</td></tr>" +
      "<tr><td>Delta（增量）</td><td>ObservationProcessor</td><td>希望对状态做的改动</td><td>新增两个候选来源</td></tr></table>" +
      "<h2>3. 四个动作（domain decision，不等于 Runtime 的工具调用）</h2>" +
      "<table><tr><th>动作</th><th>含义</th></tr>" +
      "<tr><td>search</td><td>为某个缺口搜索候选来源</td></tr>" +
      "<tr><td>read</td><td>读取一个候选来源的正文，形成证据</td></tr>" +
      "<tr><td>reflect</td><td>对当前已有信息写下一条反思（领域记录，不是通用的“自我反思”能力）</td></tr>" +
      "<tr><td>finish</td><td>提议结束。只是一个提议，必须通过完成检查</td></tr></table>" +
      '<div class="callout warn"><strong>常见误解</strong>模型并不直接调用“搜索 API”。它只输出 SearchDecision 这样的语义决策，ActionResolver 把它翻译成内部动作，执行器才去调用 Brave 或 Jina。模型从来不知道背后是哪家服务商。</div>' +
      "<h2>4. finish 不由模型说了算</h2>" +
      "<p>模型提出 finish 时，完成策略会逐项检查：每个必答缺口是否有明确处置，每条结论是否有足够的证据来源，引用的 ID 是否真实存在。不满足时，理由会作为可执行的反馈返回给模型，并继续下一步。</p>" +
      '<div class="callout"><strong>一个容易说错的点</strong>完成通过只代表“程序认为满足了完成标准”，不代表“结论一定正确”。系统限制的是模型能改变的范围，不保证语义正确。</div>' +
      "<h2>5. 为什么领域和运行时要分开</h2>" +
      "<p>运行时只知道“决策、动作、观察、增量、状态”这些通用信封，不知道“舆情”是什么。这样同一个运行时可以装配另一套领域（investigation 域就是例子），而运行时代码不需要改。</p>" +
      "<h2>6. 面试一句话</h2>" +
      '<div class="callout ok">“模型输出的是决策，不是工具调用。决策经过校验和解析变成动作，执行后得到观察，领域规则把观察变成增量，只有归约器能写状态。finish 只是提议，要过完成检查，所以模型没有写权，也没有收工权。”</div>';
  }

  // ---------- Registration ----------
  window.Site.register({
    id: "core-runtime",
    group: "core",
    title: "Runtime：状态机与一步的事务",
    lead: "这是项目最核心的部分。它回答：一步里的很多事情，怎样保证有且只有一个版本的状态是对的。",
    deep: DEEP_CORE,
    render: renderRuntime,
  });

  window.Site.register({
    id: "core-checkpoint",
    group: "core",
    title: "Checkpoint：存档为什么不会坏",
    lead: "存档本身也可能出错。这一页讲怎样让“写存档”这件事在断电时依然安全，以及加载时要防什么。",
    deep: [{ label: "深度课程 · 04 Checkpoint 与崩溃恢复", href: "../opinion_search_interview_guide/index.html" }],
    render: renderCheckpoint,
  });

  window.Site.register({
    id: "core-recovery",
    group: "core",
    title: "崩溃恢复：七个阶段与三个窗口",
    lead: "这是你最需要真正理解的一页。它回答：重启之后，每个阶段要做什么；哪些事绝对不能重做；哪里无法完全避免重复。",
    deep: [
      { label: "深度课程 · 03 三个崩溃窗口", href: "../opinion_search_interview_guide/index.html" },
      { label: "面试资料 07 · B3 / B4 追问链", href: "../docs/interview/07-面试问答库.md" },
    ],
    render: renderRecovery,
  });

  window.Site.register({
    id: "core-tools",
    group: "core",
    title: "工具容错：分类、熔断与回退",
    lead: "外部服务一定会失败。这一页讲失败如何分类、如何隔离、以及为什么“重试”不是一个答案。",
    deep: [{ label: "深度课程 · 05 Tool Runtime 可靠执行", href: "../opinion_search_interview_guide/index.html" }],
    render: renderTools,
  });

  window.Site.register({
    id: "core-context",
    group: "core",
    title: "Context：每次调用前怎样编译上下文",
    lead: "模型一次只能看一小段。这一页讲上下文怎样确定性地编译、怎样分层裁剪，以及为什么信任标签很重要。",
    deep: [{ label: "深度课程 · 07 Context 与 Working Memory", href: "../opinion_search_interview_guide/index.html" }],
    render: renderContext,
  });

  window.Site.register({
    id: "core-replay",
    group: "core",
    title: "确定性回放：怎样证明行为没有变",
    lead: "本项目最新加入的能力。它把“恢复之后是否一致”变成可以机械检查的问题。",
    deep: [{ label: "方案文档 · 确定性回放", href: "../docs/opinion-search-deterministic-replay-plan.md" }],
    render: renderReplay,
  });

  window.Site.register({
    id: "core-domain",
    group: "core",
    title: "领域层：OpinionSearch 的决策与完成",
    lead: "运行时是通用的，舆情规则在这里。这一页讲模型提议什么、系统做什么、以及完成判定为什么不由模型说了算。",
    deep: [{ label: "深度课程 · 08 领域层", href: "../opinion_search_interview_guide/index.html" }],
    render: renderDomain,
  });
})();
