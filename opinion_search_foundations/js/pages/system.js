// System track: layered overview, component wiring, step data flow,
// state machines, and a searchable code map generated from the source tree.
(function () {
  var DEEP_ARCH = [
    { label: "面试资料 02 架构总览", href: "../docs/interview/02-架构总览.md" },
    { label: "深度课程 · 01 全景", href: "../opinion_search_interview_guide/index.html" },
  ];

  // ---------- 1. Layered overview ----------
  var OVERVIEW_DETAILS = {
    cli: "<h4>CLI（__main__.py）</h4>offline / live / resume 三个子命令。一次跑完，没有交互。" + Site.codeLine("__main__.py"),
    web: "<h4>Web 调查工作台（web/server.py）</h4>主页面 /，另有 /legacy 与 /dev。进度通过 LoopHook 推送给页面（SSE）。" + Site.codeLine("web/server.py"),
    api: "<h4>HTTP API</h4>两套接口：/api/investigations（工作台）与 /api/runs（旧控制台）。入口层只负责接收请求，不做业务判断。",
    appsvc: "<h4>opinion 组合根（app/service.py）</h4>把 OpinionSearch 的 11 个协作者装配成 AgentLoop。CLI 与 /legacy 共用。" + Site.codeLine("app/service.py"),
    invsvc: "<h4>investigation 组合根（investigation/service.py + manager.py）</h4>工作台的装配与调查编排：澄清问题、预算、更新、投影。" + Site.codeLine("investigation/manager.py"),
    domopin: "<h4>领域层：opinion（domain/opinion/）</h4>决策校验、动作解析、状态归约（reducer）、完成策略、溯源。知道“舆情”是什么。" + Site.codeLine("domain/opinion/reducer.py"),
    dominv: "<h4>领域层：investigation（domain/investigation/）</h4>另一套领域规则：6 个动作、引擎与完成闸门。与 opinion 域并列，不互相依赖。" + Site.codeLine("domain/investigation/engine.py"),
    loop: "<h4>AgentLoop（runtime/loop.py）</h4>状态分发器：每轮按 classify_resume 决定做哪个阶段，做完就存档并继续。不知道舆情。" + Site.codeLine("runtime/loop.py"),
    state: "<h4>状态与阶段（runtime/lifecycle.py, transaction.py）</h4>run 的 6 种状态、step 的 7 个阶段、合法转移表，以及 RunState 的不变量。" + Site.codeLine("runtime/transaction.py"),
    store: "<h4>存档与回放（checkpoint.py, journal.py, recording.py, replay.py）</h4>原子存档；回放 journal 记录模型调用与状态指纹，供确定性回放使用。" + Site.codeLine("runtime/recording.py"),
    context: "<h4>Context 编译（context/）</h4>把状态编译成一次模型调用的输入：L0–L3 分层、预算、压缩、信任标签。" + Site.codeLine("context/compiler.py"),
    tools: "<h4>工具层（tools/）</h4>逻辑工具注册、参数校验、缓存、重试、超时、熔断与服务商适配（Brave、Jina、MCP）。" + Site.codeLine("tools/executor.py"),
    models: "<h4>模型客户端（models/）</h4>ModelClient 协议、OpenAI 兼容实现与测试用的脚本化模型。" + Site.codeLine("models/contracts.py"),
    memory: "<h4>Working Memory（memory/）</h4>仅 opinion 域使用的派生视图，从权威状态投影出来，不是第二事实来源。" + Site.codeLine("memory/projector.py"),
    out1: "<h4>明确不做：③ Environment / Sandbox</h4>容器隔离、代码执行沙箱、浏览器集群。原因：不是 Agent 运行语义的核心，做了会分散注意力。",
    out2: "<h4>明确不做：④ Control Plane</h4>任务队列、worker 集群、多租户、分布式调度、lease。单机单进程足够项目规模。",
    out3: "<h4>明确不做：⑤ Trace / Data / Observability 平台</h4>trace 采集、事件仓库、仪表盘。只保留单次 run 内的存档与回放，不做平台。",
    out4: "<h4>明确不做：Eval 平台</h4>没有自动 benchmark。质量数字来自人工标注的检验，并且会标注口径。",
    out5: "<h4>明确不做：Model Serving / Training</h4>不托管模型，不训练模型，只调用外部 OpenAI 兼容接口。",
  };

  function overviewSvg() {
    var parts = [];
    parts.push(Svg.zone({ x: 20, y: 30, w: 720, h: 94, title: "入口层" }));
    parts.push(Svg.zone({ x: 20, y: 150, w: 720, h: 94, title: "组合根（谁把谁装起来）" }));
    parts.push(Svg.zone({ x: 20, y: 270, w: 720, h: 94, title: "领域层（舆情规则）" }));
    parts.push(Svg.zone({ x: 20, y: 390, w: 720, h: 94, title: "Runtime 层（与领域无关）" }));
    parts.push(Svg.zone({ x: 20, y: 510, w: 720, h: 94, title: "支撑层（能力接口）" }));

    parts.push(Svg.box({ x: 50, y: 60, w: 200, h: 50, key: "cli", title: "CLI", sub: "__main__.py" }));
    parts.push(Svg.box({ x: 290, y: 60, w: 200, h: 50, key: "web", title: "Web 工作台", sub: "web/server.py" }));
    parts.push(Svg.box({ x: 530, y: 60, w: 200, h: 50, key: "api", title: "HTTP API", sub: "/api/investigations" }));

    parts.push(Svg.box({ x: 50, y: 180, w: 300, h: 50, key: "appsvc", title: "opinion 组合根", sub: "app/service.py" }));
    parts.push(Svg.box({ x: 390, y: 180, w: 330, h: 50, key: "invsvc", title: "investigation 组合根", sub: "investigation/service.py + manager.py" }));

    parts.push(Svg.box({ x: 50, y: 300, w: 300, h: 50, key: "domopin", title: "domain/opinion", sub: "10 个模块：决策、归约、完成" }));
    parts.push(Svg.box({ x: 390, y: 300, w: 330, h: 50, key: "dominv", title: "domain/investigation", sub: "2 个模块：引擎与模型" }));

    parts.push(Svg.box({ x: 50, y: 420, w: 190, h: 50, key: "loop", title: "AgentLoop", sub: "runtime/loop.py" }));
    parts.push(Svg.box({ x: 260, y: 420, w: 200, h: 50, key: "state", title: "阶段与状态", sub: "lifecycle / transaction" }));
    parts.push(Svg.box({ x: 480, y: 420, w: 240, h: 50, key: "store", title: "存档与回放", sub: "checkpoint / journal / replay" }));

    parts.push(Svg.box({ x: 50, y: 540, w: 150, h: 50, key: "context", title: "Context", sub: "context/" }));
    parts.push(Svg.box({ x: 220, y: 540, w: 150, h: 50, key: "tools", title: "工具层", sub: "tools/" }));
    parts.push(Svg.box({ x: 390, y: 540, w: 150, h: 50, key: "models", title: "模型客户端", sub: "models/" }));
    parts.push(Svg.box({ x: 560, y: 540, w: 160, h: 50, key: "memory", title: "Working Memory", sub: "仅 opinion 域" }));

    // Dependency arrows point downward: entry -> root -> domain -> runtime -> support.
    var xs = [150, 540];
    xs.forEach(function (x) {
      parts.push(Svg.line([[x, 110], [x, 180]], {}));
      parts.push(Svg.line([[x, 230], [x, 300]], {}));
      parts.push(Svg.line([[x, 350], [x, 420]], {}));
      parts.push(Svg.line([[x, 470], [x, 540]], {}));
    });
    parts.push(Svg.text(600, 146, "依赖方向：只向下", "lbl"));

    // Out-of-scope column.
    parts.push(Svg.zone({ x: 780, y: 30, w: 240, h: 574, title: "明确不做" }));
    var outs = [
      ["out1", "③ Sandbox / 环境"],
      ["out2", "④ Control Plane"],
      ["out3", "⑤ Trace / 可观测平台"],
      ["out4", "Eval 平台"],
      ["out5", "Model Serving / 训练"],
    ];
    outs.forEach(function (o, i) {
      parts.push(
        '<g class="out-box">' + Svg.box({ x: 800, y: 70 + i * 90, w: 200, h: 56, key: o[0], title: o[1], cls: "out" }) + "</g>"
      );
    });
    return Svg.wrap(1040, 640, parts.join(""));
  }

  // ---------- 2. Component wiring ----------
  var COMPONENT_DETAILS = {
    opinion: "<h4>opinion 组合根</h4>app/service.py 的 _build_loop 把 OpinionSearch 的实现注入 AgentLoop。CLI、/legacy、/dev 都经过它。",
    investigation: "<h4>investigation 组合根</h4>investigation/service.py 注入另一套实现（6 个动作）。runtime 一行都不用改。",
    model: "<h4>model · ModelClient</h4>协议：decide(context) → 决策。失败时抛 ModelClientError，错误分 8 类。",
    compiler: "<h4>context_compiler · ContextCompiler</h4>协议：compile(state) → 单次模型输入。确定性：同样的状态得到同样的输入。",
    validator: "<h4>decision_validator</h4>协议：校验模型的决策是否合法（领域规则）。不合法就记入失败并重试决策。",
    resolver: "<h4>action_resolver</h4>把决策翻译成可执行动作，并加固（参数、范围）。失败时可以回到决策阶段修复。",
    executor: "<h4>action_executor</h4>执行动作，返回观察结果。内部是 ToolExecutor：校验参数 → 查缓存 → 按服务商顺序调用 → 重试、超时、熔断。",
    processor: "<h4>observation_processor</h4>把观察结果变成 StateDelta（希望对状态做的增量）。纯领域逻辑。",
    completion: "<h4>completion_evaluator</h4>决定 run 是否结束。finish 决策只是提议，必须通过完成检查。",
    reducer: "<h4>reducer（普通函数，不是协议）</h4>reduce(state, delta) → 新 state。纯函数，没有 I/O。全项目唯一能写权威状态的地方。",
    store: "<h4>checkpoint_store · CheckpointStore</h4>每个阶段边界保存完整 state。生产中是 JsonCheckpointStore（原子写）；启用回放时外面再包一层 journal。",
    ids: "<h4>id_factory</h4>确定性生成 step_id、action_id。同样的 run 和步数得到同样的 ID，这是回放能对齐的前提。",
    cancel: "<h4>cancellation_signal</h4>取消信号。取消是与正在进行的调用竞速，而不是直接杀进程。",
    hook: "<h4>hook · LoopHook</h4>每次存档后回调一次，带阶段名。Web 用它推送进度，领域和运行时都不需要改。",
    scalars: "<h4>标量参数</h4>max_steps：最多提交多少步；max_decision_attempts：单步决策最多尝试几次（默认 2）。",
  };

  function componentSvg() {
    var p = [];
    p.push(Svg.box({ x: 260, y: 16, w: 250, h: 50, key: "opinion", title: "opinion 组合根", sub: "app/service.py", fill: "#eef5ff" }));
    p.push(Svg.box({ x: 530, y: 16, w: 250, h: 50, key: "investigation", title: "investigation 组合根", sub: "investigation/service.py", fill: "#eef5ff" }));
    p.push(Svg.box({ x: 400, y: 200, w: 260, h: 84, key: "loopcore", title: "AgentLoop", sub: "12 个注入参数 + 2 个标量", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.line([[385, 66], [430, 200]], {}));
    p.push(Svg.line([[655, 66], [610, 200]], {}));

    var left = [
      ["model", "model", "ModelClient", "models/contracts.py"],
      ["compiler", "context_compiler", "ContextCompiler", "context/compiler.py"],
      ["validator", "decision_validator", "DecisionValidator", "domain 校验"],
      ["resolver", "action_resolver", "ActionResolver", "决策 → 动作"],
      ["executor", "action_executor", "ActionExecutor", "→ ToolExecutor"],
      ["processor", "observation_processor", "ObservationProcessor", "观察 → 增量"],
    ];
    var right = [
      ["completion", "completion_evaluator", "CompletionEvaluator", "finish 只是提议"],
      ["reducer", "reducer", "reduce（普通函数）", "唯一写权威状态"],
      ["store", "checkpoint_store", "CheckpointStore", "原子存档（+回放）"],
      ["ids", "id_factory", "IdFactory", "确定性 ID"],
      ["cancel", "cancellation_signal", "CancellationSignal", "竞速取消"],
      ["hook", "hook", "LoopHook", "存档后回调 → 进度"],
    ];
    var ys = [130, 200, 270, 340, 410, 480];
    left.forEach(function (item, i) {
      var y = ys[i];
      p.push(Svg.box({ x: 30, y: y, w: 300, h: 50, key: item[0], title: item[2], sub: item[1] + " · " + item[3] }));
      p.push(Svg.line([[330, y + 25], [400, 242 + i * 6]], {}));
    });
    right.forEach(function (item, i) {
      var y = ys[i];
      p.push(Svg.box({ x: 710, y: y, w: 300, h: 50, key: item[0], title: item[2], sub: item[1] + " · " + item[3] }));
      p.push(Svg.line([[660, 242 + i * 6], [710, y + 25]], {}));
    });
    p.push(Svg.box({ x: 400, y: 560, w: 260, h: 50, key: "scalars", title: "标量参数", sub: "max_steps · max_decision_attempts", fill: "#f5f7fb" }));
    p.push(Svg.text(30, 648, "注：左列 + 右列 + reducer 共 12 个注入参数；其中 11 个是协议，reducer 是普通函数。", "lbl"));
    return Svg.wrap(1040, 665, p.join(""));
  }

  // ---------- 3. Data flow stepper ----------
  var STAGES = [
    {
      title: "读取存档（classify_resume）",
      code: "runtime/transaction.py · classify_resume",
      input: "RunState（来自上一次存档，不读内存变量）",
      output: "决定下一个阶段：开启新步、请求决策、解析动作、执行动作、归约……",
      saved: "无新存档；只决定做什么。",
      crash: "无副作用。重启后会走同样的判定。",
    },
    {
      title: "编译上下文",
      code: "context/compiler.py · OpinionContextCompiler.compile",
      input: "权威状态 State",
      output: "CompiledContext：L0 指令、L1 任务、L2 工作记忆、L3 最近步骤，每段带信任标签与预算。",
      saved: "不存档。上下文是派生的，可以随时由状态重算。",
      crash: "无副作用。确定性：同一状态得到同一上下文。",
    },
    {
      title: "模型决策",
      code: "models/contracts.py · ModelClient.decide",
      input: "CompiledContext",
      output: "AgentDecision：search / read / reflect / finish 之一（语义意图，不是工具调用）。",
      saved: "DECIDING 已存档；决策尚未存。",
      crash: "重启后重新请求决策（这一次调用可能得到不同答复，所以 attempt 计数在存档中）。",
    },
    {
      title: "校验决策",
      code: "domain/opinion/decisions.py · DecisionValidator.validate",
      input: "AgentDecision",
      output: "DecisionEnvelope 被接受；不合法则记入失败，回到决策阶段（attempt + 1）。",
      saved: "DECISION_ACCEPTED 存档：决策已经被接受，之后不再请求模型。",
      crash: "重启后直接用已接受的决策继续，不会再请求模型。",
    },
    {
      title: "解析为动作",
      code: "domain/opinion/action_resolver.py · ActionResolver.resolve",
      input: "已接受的决策 + 状态",
      output: "ActionRequest（带确定性 action_id）。解析失败可修复，回到决策。",
      saved: "ACTION_RUNNING 存档：这是副作用发生之前的最后一个存档点。",
      crash: "重启后执行这个动作。若此前已发出请求，可能重复（见“核心技术 · 崩溃恢复”）。",
    },
    {
      title: "执行工具",
      code: "app/action_executor.py · tools/executor.py · ToolExecutor",
      input: "ActionRequest",
      output: "ObservationEnvelope：成功结果，或分类后的失败。",
      saved: "成功结果按 action_id 写入结果缓存；OBSERVATION_READY 存档。",
      crash: "若结果已缓存，重启后直接复用，零次外部调用；若未缓存，可能重复调用。",
    },
    {
      title: "构造增量",
      code: "domain/opinion/processor.py · build_delta",
      input: "Observation + 决策",
      output: "StateDelta：希望对状态做的增量。纯领域逻辑，无 I/O。",
      saved: "REDUCING 存档。",
      crash: "重启后重做增量构造，不再调用工具。",
    },
    {
      title: "归约（Reducer）",
      code: "domain/opinion/reducer.py · reduce_opinion_state",
      input: "State + StateDelta",
      output: "新的权威 State。纯函数：同样输入得到同样输出，没有 I/O。",
      saved: "无单独存档；属于下一步的提交。",
      crash: "重启后重做归约，结果相同。",
    },
    {
      title: "提交（commit_step）",
      code: "runtime/transaction.py · commit_step",
      input: "新 State + 已完成的步骤记录",
      output: "一次构造同时完成六件事：新状态、清空活动步、追加历史、推进游标、记录动作 ID、设置 continuation_pending。",
      saved: "STEP_COMMITTED 存档。回放 journal 在这一刻先写入。",
      crash: "已提交的动作再次提交是幂等的：直接返回原状态。",
    },
    {
      title: "完成判定",
      code: "runtime/loop.py · EVALUATE_CONTINUATION → CompletionEvaluator",
      input: "已提交的决策与观察",
      output: "继续（RUNNING）或终止（COMPLETED / PARTIAL）。FAILED / CANCELLED 走另一条路径。",
      saved: "CONTINUATION_APPLIED 存档，然后回到第 0 步开始下一步。",
      crash: "continuation_pending 为真时，恢复会先完成判定，不会打开新的一步或重放上一步。",
    },
  ];

  // Short labels and the checkpoint boundary written at each stage, for the diagram only.
  var FLOW_LABELS = [
    ["读取存档", "无新存档"],
    ["编译上下文", "派生，不存档"],
    ["模型决策", "DECIDING"],
    ["校验决策", "DECISION_ACCEPTED"],
    ["解析为动作", "ACTION_RUNNING"],
    ["执行工具", "OBSERVATION_READY"],
    ["构造增量", "REDUCING"],
    ["归约", "无单独存档"],
    ["提交", "STEP_COMMITTED"],
    ["完成判定", "CONTINUATION_APPLIED"],
  ];
  STAGES.forEach(function (s, i) { s.short = FLOW_LABELS[i][0]; s.boundary = FLOW_LABELS[i][1]; });

  function flowSvg() {
    var w = 170, h = 70, p = [];
    var pos = [];
    for (var i = 0; i < 5; i++) pos.push([30 + i * 205, 40]);
    for (var j = 0; j < 5; j++) pos.push([30 + (4 - j) * 205, 180]);
    STAGES.forEach(function (s, idx) {
      var xy = pos[idx];
      p.push(Svg.box({ x: xy[0], y: xy[1], w: w, h: h, key: String(idx), title: idx + " " + s.short, sub: s.boundary }));
    });
    for (var k = 0; k < 9; k++) {
      var a = pos[k], b = pos[k + 1];
      if (a[1] === b[1]) {
        var forward = b[0] > a[0];
        var y = a[1] + h / 2;
        var x1 = forward ? a[0] + w : a[0];
        var x2 = forward ? b[0] : b[0] + w;
        p.push(Svg.line([[x1, y], [x2, y]], {}));
      } else {
        p.push(Svg.line([[a[0] + w / 2, a[1] + h], [b[0] + w / 2, b[1]]], {}));
      }
    }
    p.push(Svg.text(30, 290, "每个阶段边界都会存档（run 的开始与终止也各有一次）。每个节点的存档名称见下方面板。", "lbl"));
    return Svg.wrap(1040, 306, p.join(""));
  }

  function renderFlow(el) {
    el.innerHTML =
      '<div class="diagram" id="flow-diagram">' + flowSvg() + '<div class="caption">点击任一节点，或使用下方按钮逐步播放</div></div>' +
      '<div class="stepper">' +
      '<button id="flow-prev">← 上一步</button>' +
      '<button id="flow-next" class="primary">下一步 →</button>' +
      '<button id="flow-auto">自动播放</button>' +
      '<span class="mono" id="flow-pos"></span></div>' +
      '<div class="detail" id="flow-detail"></div>' +
      '<h2>为什么要这样切分</h2>' +
      '<div class="callout"><strong>每一步都是“决策 → 执行 → 提交”的一次周期</strong>' +
      "模型只能提议；工具只能返回观察；只有归约（Reducer）能改权威状态。这样的切分让每一段都能单独验证，也让崩溃时只需要问：“我停在哪一段”。</div>";

    var index = 0;
    var timer = null;
    var detail = document.getElementById("flow-detail");
    var nodes = el.querySelectorAll("#flow-diagram [data-key]");

    function show(i) {
      index = Math.max(0, Math.min(STAGES.length - 1, i));
      var s = STAGES[index];
      nodes.forEach(function (n) {
        var k = Number(n.getAttribute("data-key"));
        n.classList.toggle("active", k === index);
        n.classList.toggle("dim", k !== index);
      });
      detail.innerHTML =
        "<h4>阶段 " + index + " · " + Site.esc(s.title) + "</h4>" +
        '<div class="path">' + Site.esc(s.code) + "</div>" +
        "<table><tr><th>输入</th><td>" + Site.esc(s.input) + "</td></tr>" +
        "<tr><th>输出</th><td>" + Site.esc(s.output) + "</td></tr>" +
        "<tr><th>存档</th><td>" + Site.esc(s.saved) + "</td></tr>" +
        "<tr><th>此刻崩溃会怎样</th><td>" + Site.esc(s.crash) + "</td></tr></table>";
      document.getElementById("flow-pos").textContent = "阶段 " + index + " / " + (STAGES.length - 1);
      document.getElementById("flow-prev").disabled = index === 0;
      document.getElementById("flow-next").disabled = index === STAGES.length - 1;
    }

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      document.getElementById("flow-auto").textContent = "自动播放";
    }

    el.querySelector("#flow-prev").addEventListener("click", function () { stop(); show(index - 1); });
    el.querySelector("#flow-next").addEventListener("click", function () { stop(); show(index + 1); });
    el.querySelector("#flow-auto").addEventListener("click", function () {
      if (timer) { stop(); return; }
      document.getElementById("flow-auto").textContent = "暂停";
      if (index === STAGES.length - 1) show(0);
      timer = setInterval(function () {
        if (index >= STAGES.length - 1) { stop(); return; }
        show(index + 1);
      }, 2200);
    });
    el.querySelector("#flow-diagram").addEventListener("click", function (event) {
      var node = event.target.closest("[data-key]");
      if (node) { stop(); show(Number(node.getAttribute("data-key"))); }
    });
    show(0);
  }

  // ---------- 4. State machines ----------
  function runStatusSvg() {
    var p = [];
    p.push(Svg.box({ x: 30, y: 120, w: 150, h: 56, key: "created", title: "CREATED", sub: "刚创建，尚无历史" }));
    p.push(Svg.box({ x: 260, y: 120, w: 150, h: 56, key: "running", title: "RUNNING", sub: "正在执行" }));
    p.push(Svg.line([[180, 148], [260, 148]], { label: "start_run" }));
    var terms = [
      ["completed", "COMPLETED", "完成判定通过"],
      ["partial", "PARTIAL", "诚实停止（步数 / 上下文 / 修复耗尽）"],
      ["failed", "FAILED", "不可恢复的错误"],
      ["cancelled", "CANCELLED", "收到取消信号"],
    ];
    terms.forEach(function (t, i) {
      var y = 20 + i * 84;
      p.push(Svg.box({ x: 540, y: y, w: 220, h: 56, key: t[0], title: t[1], sub: t[2] }));
      p.push(Svg.line([[410, 148], [540, y + 28]], {}));
    });
    p.push(Svg.text(330, 215, "terminate_run / apply_continuation", "lbl"));
    return Svg.wrap(1040, 360, p.join(""));
  }

  var RUN_DETAILS = {
    created: "<h4>CREATED</h4>只能转到 RUNNING。创建状态不能有任何历史（没有步、没有动作）。这是 RunState 的不变量。",
    running: "<h4>RUNNING</h4>唯一的“进行中”状态。只有它可以转到四种终态；每次转移都经过 validate_run_transition 检查。",
    completed: "<h4>COMPLETED</h4>完成判定通过：所有必答问题都有明确处置，且满足完成标准。注意：这只代表“程序认为完成”，不保证结论一定正确。",
    partial: "<h4>PARTIAL：诚实停止</h4>达到 max_steps、必需上下文放不下、决策修复耗尽但已有提交的步骤、或重复动作。结果保留已提交的部分，但不声称完成。",
    failed: "<h4>FAILED</h4>不可恢复：例如归约器的不变量被破坏，或决策修复耗尽且尚无提交的步骤。必须附带 failure 说明。",
    cancelled: "<h4>CANCELLED</h4>收到取消信号后终止。取消不会回滚远端已经发生的事情，只停止本地继续推进。",
  };

  function stepPhaseSvg() {
    var names = ["opened", "deciding", "decision_accepted", "action_running", "observation_ready", "reducing", "committed"];
    var saves = ["STEP_OPENED", "DECIDING", "DECISION_ACCEPTED", "ACTION_RUNNING", "OBSERVATION_READY", "REDUCING", "STEP_COMMITTED"];
    var p = [];
    var xs = names.map(function (_, i) { return 16 + i * 148; });
    names.forEach(function (n, i) {
      p.push(Svg.box({ x: xs[i], y: 130, w: 134, h: 60, key: n, title: n, sub: saves[i] }));
    });
    for (var i = 0; i < names.length - 1; i++) {
      p.push(Svg.line([[xs[i] + 134, 160], [xs[i + 1], 160]], {}));
    }
    // Retry loop: deciding -> deciding (attempt + 1).
    var dx = xs[1];
    p.push('<path class="edge dashed" d="M ' + (dx + 40) + " 130 Q " + (dx + 67) + " 70 " + (dx + 94) + " 130\"/>");
    p.push(Svg.text(dx + 4, 66, "重试：attempt + 1", "lbl"));
    // Repair loop: decision_accepted -> deciding (resolver failed, rewind).
    var ax = xs[2];
    p.push('<path class="edge dashed" d="M ' + (ax + 67) + " 190 Q " + (ax + 67) + " 240 " + (xs[1] + 67) + " 190\"/>");
    p.push(Svg.text(xs[1] + 70, 240, "解析失败：回退到决策（attempt + 1）", "lbl"));
    p.push(Svg.text(16, 40, "七个阶段按顺序前进；虚线是两种回退重试，两者都会让 attempt 加一并记录失败原因。", "lbl"));
    return Svg.wrap(1040, 280, p.join(""));
  }

  var STEP_DETAILS = {
    opened: "<h4>opened</h4>步已开启，尚无决策。存档 STEP_OPENED。恢复动作：进入决策阶段。",
    deciding: "<h4>deciding</h4>正在请求模型。存档 DECIDING。恢复动作：重新请求决策；attempt 已记在存档中。",
    decision_accepted: "<h4>decision_accepted</h4>决策已通过校验并存档。恢复动作：直接解析动作，不再请求模型。解析失败会回到 deciding。",
    action_running: "<h4>action_running</h4>副作用发生前的最后一个存档。恢复动作：执行动作。唯一可能重复外部调用的阶段（见核心技术 · 崩溃恢复）。",
    observation_ready: "<h4>observation_ready</h4>观察结果已存档，不会再调用工具。恢复动作：构造增量并归约。",
    reducing: "<h4>reducing</h4>正在归约。恢复动作：重做归约（纯函数，结果相同），commit_step 的幂等保证不会重复生效。",
    committed: "<h4>committed</h4>步已提交（STEP_COMMITTED）。它不是一个“需要恢复动作”的持久阶段，而是提交后的存档边界：下一次恢复会先做完成判定。",
  };

  // ---------- 5. Code map ----------
  function renderCodeMap(el) {
    var entries = window.CODE_MAP || [];
    var totalLines = entries.reduce(function (sum, e) { return sum + e.lines; }, 0);
    el.innerHTML =
      '<div class="grid grid-3">' +
      '<div class="card"><div class="kpi">' + entries.length + '</div><div class="kpi-label">Python 源文件（src/opinion_search，不含测试）</div></div>' +
      '<div class="card"><div class="kpi">' + totalLines.toLocaleString("en-US") + '</div><div class="kpi-label">总行数（生成时统计）</div></div>' +
      '<div class="card"><div class="kpi">' + entries.filter(function (e) { return e.desc; }).length + '</div><div class="kpi-label">已写说明的核心文件</div></div>' +
      "</div>" +
      '<div class="toolbar"><input type="search" id="code-filter" placeholder="搜索路径或说明，例如 checkpoint、circuit、replay" size="48"></div>' +
      '<div id="code-table"></div>' +
      '<div class="callout warn"><strong>关于数字</strong>这些统计来自 js/data-code-map.js，由 scripts/gen_code_map.py 从仓库生成。' +
      "重新生成前，页面数字不会自动更新。</div>";

    function draw() {
      var q = document.getElementById("code-filter").value.trim().toLowerCase();
      var rows = entries.filter(function (e) {
        return !q || (e.path + " " + e.desc).toLowerCase().indexOf(q) >= 0;
      });
      var html = "<table><tr><th>文件</th><th>行数</th><th>职责</th></tr>" +
        rows.map(function (e) {
          return "<tr><td class=\"mono\">" + Site.esc(e.path) + "</td><td>" + e.lines + "</td><td>" +
            Site.esc(e.desc || "—") + "</td></tr>";
        }).join("") + "</table>";
      document.getElementById("code-table").innerHTML = html;
    }
    document.getElementById("code-filter").addEventListener("input", draw);
    draw();
  }

  // ---------- Page registration ----------
  window.Site.register({
    id: "sys-overview",
    group: "system",
    title: "系统全景：分几层，谁依赖谁",
    lead: "先记住一句话：一个与领域无关的 Runtime，被两套舆情规则分别装配。点击图中的方块看职责与代码落点。",
    deep: DEEP_ARCH,
    render: function (el) {
      el.innerHTML =
        '<div class="callout"><strong>依赖方向严格单向</strong>入口 → 组合根 → 领域 → Runtime → 支撑。Runtime 不 import 领域；领域不 import 任何服务商 SDK。</div>' +
        '<div class="diagram" id="overview">' + overviewSvg() + '<div class="caption">点击方块查看说明</div></div>' +
        '<div class="detail" id="overview-detail"></div>' +
        '<h2>为什么要画出“明确不做”</h2>' +
        '<p>面试官常问“你为什么没做 X”。右侧灰色框是刻意不做的部分。它们说明这个项目的边界是有意识的选择，而不是没想到。</p>';
      Site.bindNodes(document.getElementById("overview"), OVERVIEW_DETAILS, document.getElementById("overview-detail"));
    },
  });

  window.Site.register({
    id: "sys-components",
    group: "system",
    title: "组件接线：AgentLoop 注入了什么",
    lead: "AgentLoop 是中心。它不自己做任何业务，而是通过 12 个注入参数调用外部组件。换一组组件，就是另一条产品线。",
    deep: DEEP_ARCH,
    render: function (el) {
      el.innerHTML =
        '<div class="diagram" id="components">' + componentSvg() + '<div class="caption">点击任一组件查看它的职责</div></div>' +
        '<div class="detail" id="components-detail"></div>' +
        '<h2>这种接线带来的好处</h2>' +
        '<ul>' +
        '<li><b>可替换</b>：测试时用脚本化模型和 fake 执行器，生产时换成真实模型和工具，循环代码不变。</li>' +
        '<li><b>可验证</b>：每个组件都有独立的单元测试；AgentLoop 的集成测试只需要替换边界。</li>' +
        '<li><b>可回放</b>：回放时替换的只是模型和执行器两个边界，其余组件仍是生产代码。</li>' +
        "</ul>" +
        '<div class="callout warn"><strong>注意口径</strong>面试中说“11 个协议接口 + 1 个回调”，不要说“十个协议”。reducer 是普通函数，不是 Protocol。</div>';
      Site.bindNodes(document.getElementById("components"), COMPONENT_DETAILS, document.getElementById("components-detail"));
    },
  });

  window.Site.register({
    id: "sys-dataflow",
    group: "system",
    title: "数据流：一步是怎样走完的",
    lead: "用逐步播放看一次决策如何变成状态变化。每个阶段都标明了输入、输出、存档点，以及此刻崩溃会发生什么。这是本站最重要的一张图。",
    deep: [
      { label: "面试资料 02 · 第 5 节数据流", href: "../docs/interview/02-架构总览.md" },
      { label: "深度课程 · 03 Loop 与事务提交", href: "../opinion_search_interview_guide/index.html" },
    ],
    render: renderFlow,
  });

  window.Site.register({
    id: "sys-states",
    group: "system",
    title: "状态机：run 与 step 各有几种状态",
    lead: "系统里有两本账：run 的整体状态（6 种）和 step 内部的阶段（7 个）。两者不能混在一起。",
    deep: [{ label: "面试资料 03 · 第 1 节三个枚举", href: "../docs/interview/03-逐层机制详解.md" }],
    render: function (el) {
      el.innerHTML =
        "<h2>run 的状态（RunStatus）</h2>" +
        '<div class="diagram" id="run-states">' + runStatusSvg() + '<div class="caption">点击状态查看含义；箭头即合法转移</div></div>' +
        '<div class="detail" id="run-detail"></div>' +
        "<h2>step 的阶段（StepPhase）</h2>" +
        '<div class="diagram" id="step-states">' + stepPhaseSvg() + '<div class="caption">点击阶段查看它的恢复动作；方框下的小字是该阶段边界的存档名</div></div>' +
        '<div class="detail" id="step-detail"></div>' +
        '<div class="callout warn"><strong>严谨口径</strong>有的文档说“七个持久阶段”。严格地说，committed 不需要恢复动作，它是提交后的存档边界。面试中说“七个阶段，其中 committed 是提交后的边界”更准确。</div>';
      Site.bindNodes(document.getElementById("run-states"), RUN_DETAILS, document.getElementById("run-detail"));
      Site.bindNodes(document.getElementById("step-states"), STEP_DETAILS, document.getElementById("step-detail"));
    },
  });

  window.Site.register({
    id: "sys-codemap",
    group: "system",
    title: "代码地图：每个文件是干什么的",
    lead: "这一页的数据直接来自仓库文件（行数由脚本统计）。用它来回答“这个功能在哪个文件里”。",
    deep: [{ label: "面试资料 09 代码导航地图", href: "../docs/interview/09-代码导航地图.md" }],
    render: renderCodeMap,
  });
})();
