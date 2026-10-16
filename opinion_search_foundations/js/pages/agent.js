// Agent run track: the AgentLoop control flow drawn from runtime/loop.py,
// and the decision-failure branch drawn from _recover_decision_failure.
// Node labels name the real methods; every checkpoint name is a CheckpointBoundary.
(function () {
  var CX = 330;          // spine centre
  var SPINE_W = 320;
  var EXIT_X = 640;
  var EXIT_W = 380;

  function diamond(cx, y, w, h, key, lines) {
    var pts = [[cx, y], [cx + w / 2, y + h / 2], [cx, y + h], [cx - w / 2, y + h / 2]]
      .map(function (p) { return p[0] + "," + p[1]; }).join(" ");
    var mid = y + h / 2;
    var text = lines.map(function (line, i) {
      return '<text class="node-title" x="' + cx + '" y="' + (mid - 4 + i * 15 - (lines.length - 1) * 7) +
        '" text-anchor="middle">' + Svg.esc(line) + "</text>";
    }).join("");
    return '<g class="node" data-key="' + key + '"><polygon points="' + pts +
      '" fill="#ffffff" stroke="#b9c2d0" stroke-width="1.4"/>' + text + "</g>";
  }

  function vline(x, y1, y2, label, dashed) {
    return Svg.line([[x, y1], [x, y2]], { label: label, dashed: dashed, dx: 8, dy: 0 });
  }

  // Spine item: kind is "rect" or "diamond". Returns markup and the bottom y.
  function buildSpine(items, startY) {
    var out = [];
    var y = startY;
    var positions = [];
    items.forEach(function (it) {
      var h = it.kind === "diamond" ? 64 : 58;
      positions.push({ top: y, bottom: y + h, item: it });
      y += h + 26;
    });
    positions.forEach(function (pos, i) {
      var it = pos.item;
      if (it.kind === "diamond") {
        out.push(diamond(CX, pos.top, SPINE_W, 64, it.key, it.lines));
      } else {
        out.push(Svg.box({ x: CX - SPINE_W / 2, y: pos.top, w: SPINE_W, h: 58, key: it.key, title: it.title, sub: it.sub, fill: it.fill, stroke: it.stroke }));
      }
      if (i < positions.length - 1) {
        out.push(Svg.line([[CX, pos.bottom], [CX, positions[i + 1].top]], it.kind === "diamond" ? { label: "否", dx: 6, dy: 0 } : { dashed: true }));
      }
    });
    return { svg: out.join(""), positions: positions, bottom: y };
  }

  function exit(y, key, title, sub, fill, stroke) {
    return Svg.box({ x: EXIT_X, y: y, w: EXIT_W, h: 58, key: key, title: title, sub: sub, fill: fill || "#fff6f5", stroke: stroke || "#e0a39a" });
  }

  var LOOP_ITEMS = [
    { kind: "rect", key: "top", title: "run() 循环顶部", sub: "classify_resume 只读 RunState 判定", fill: "#eef5ff", stroke: "#2f6fdb" },
    { kind: "diamond", key: "q_result", lines: ["RETURN_RESULT ?"] },
    { kind: "diamond", key: "q_cancel", lines: ["RUNNING 且已取消 ?", "（REDUCE 阶段除外）"] },
    { kind: "rect", key: "start", title: "START_RUN", sub: "start_run → 存档 RUN_STARTED" },
    { kind: "diamond", key: "q_limit", lines: ["OPEN_STEP：", "next_step > max_steps ?"] },
    { kind: "rect", key: "open", title: "OPEN_STEP", sub: "open_step → 存档 STEP_OPENED" },
    { kind: "rect", key: "decide", title: "REQUEST_DECISION", sub: "存档 DECIDING → 编译上下文 → 请求模型 → 校验" },
    { kind: "rect", key: "accept", title: "决策通过校验", sub: "accept_decision → 存档 DECISION_ACCEPTED" },
    { kind: "rect", key: "resolve", title: "RESOLVE_ACTION", sub: "resolve → start_action → 存档 ACTION_RUNNING" },
    { kind: "rect", key: "execute", title: "EXECUTE_ACTION", sub: "execute（外部副作用）→ 存档 OBSERVATION_READY" },
    { kind: "rect", key: "reduce", title: "REDUCE_OBSERVATION", sub: "增量 → 存档 REDUCING → 提交 → STEP_COMMITTED" },
    { kind: "diamond", key: "q_verdict", lines: ["完成判定", "verdict 为空 ?"] },
    { kind: "rect", key: "continue", title: "apply_continuation(RUNNING)", sub: "存档 CONTINUATION_APPLIED → 回到循环顶部" },
  ];

  function loopSvg() {
    var spine = buildSpine(LOOP_ITEMS, 40);
    var pos = {};
    spine.positions.forEach(function (p) { pos[p.item.key] = p; });
    var p = [spine.svg];

    // Left rail: every step ends by going back to the top and re-reading the saved state.
    var topMid = pos.top.top + 29;
    var lastMid = pos.continue.top + 29;
    var railX = CX - SPINE_W / 2 - 34;
    p.push('<path class="edge" d="M ' + (CX - SPINE_W / 2) + " " + lastMid + " L " + railX + " " + lastMid +
      " L " + railX + " " + topMid + " L " + (CX - SPINE_W / 2) + " " + topMid + '"/>');
    p.push(Svg.text(railX - 6, (topMid + lastMid) / 2, "下一轮：重新 classify", "lbl").replace('<text', '<text transform="rotate(-90 ' + (railX - 6) + ' ' + ((topMid + lastMid) / 2) + ')" text-anchor="middle"'));

    // Right-side exits, aligned with the spine items that cause them.
    var exits = [
      ["e_result", pos.q_result, "返回 RunResult", "终态直接返回，不再执行", "#f3f7fb", "#b9c2d0"],
      ["e_cancel", pos.q_cancel, "CANCELLED", "terminate_run → 存档 RUN_TERMINATED", null, null],
      ["e_limit", pos.q_limit, "PARTIAL（步数上限）", "terminate_run → 存档 RUN_TERMINATED", null, null],
      ["e_resolve", pos.resolve, "解析失败 → 决策失败处置", "INVALID_ACTION：见“失败与修复分支”", "#fff8e6", "#d9a441"],
      ["e_exec", pos.execute, "CANCELLED（执行中取消）", "取消与调用竞速，取消胜出则终止", null, null],
      ["e_invariant", pos.reduce, "FAILED：REDUCER_INVARIANT", "build_delta / commit_step 抛 ValueError → fail closed", null, null],
      ["e_verdict", pos.q_verdict, "COMPLETED 或 PARTIAL", "verdict 存在则 terminate；由 completion 策略给出", null, null],
    ];
    exits.forEach(function (e) {
      var target = e[1];
      var y = target.top + 29;
      var exitY = y - 29;
      p.push(exit(exitY, e[0], e[2], e[3], e[4], e[5]));
      p.push(Svg.line([[CX + SPINE_W / 2, y], [EXIT_X, y]], { label: "是", dy: -4, dx: 6 }));
    });

    // The request row has two distinct exits: context overflow and model/validator failures.
    var dTop = pos.decide.top;
    var dMid = dTop + 29;
    p.push(Svg.box({ x: EXIT_X, y: dTop - 6, w: EXIT_W, h: 40, key: "e_ctx", title: "PARTIAL（上下文放不下）", sub: "ContextOverflowError → terminate_run" }));
    p.push(Svg.line([[CX + SPINE_W / 2, dMid - 6], [EXIT_X, dTop + 14]], { label: "溢出", dy: -4, dx: 6 }));
    p.push(Svg.box({ x: EXIT_X, y: dTop + 38, w: EXIT_W, h: 40, key: "e_recover", title: "决策失败处置", sub: "模型错误 / 校验失败：见“失败与修复分支”", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.line([[CX + SPINE_W / 2, dMid + 6], [EXIT_X, dTop + 58]], { label: "失败", dy: 10, dx: 6 }));

    // Title strip for orientation.
    p.push(Svg.text(EXIT_X, 22, "右侧红框：异常与终止出口（每个都先存档再结束）", "lbl"));
    p.push(Svg.text(16, 22, "虚线：常见顺序；实际下一步由存档决定", "lbl"));
    return { svg: Svg.wrap(1040, spine.bottom + 20, p.join("")), spine: spine };
  }

  var LOOP_DETAILS = {
    top: "<h4>循环顶部：classify_resume</h4>只读 RunState，不读内存变量。这就是为什么首次执行与崩溃恢复走同一条路径：崩溃后重启，直接回到这里，按存档所在的阶段继续。<div class=\"path\">runtime/transaction.py · classify_resume ｜ runtime/loop.py · AgentLoop.run</div>",
    q_result: "<h4>RETURN_RESULT ?</h4>如果 run 已经是终态（COMPLETED / PARTIAL / FAILED / CANCELLED），直接返回结果，不再执行任何阶段。",
    q_cancel: "<h4>取消检查</h4>只在 RUNNING 状态下检查取消信号。REDUCE_OBSERVATION 阶段例外：如果观察结果已经存档，必须先把它提交一次，否则同一个观察的命运取决于取消时机。",
    start: "<h4>START_RUN</h4>把 CREATED 转为 RUNNING，存档 RUN_STARTED。",
    q_limit: "<h4>步数上限</h4>下一步编号超过 max_steps 时，以 PARTIAL 终止，保留已提交的步骤。这是“跑不完”，不是“跑不动”。",
    open: "<h4>OPEN_STEP</h4>分配 step_id（确定性），进入 OPENED 阶段，存档 STEP_OPENED。",
    decide: "<h4>REQUEST_DECISION（决策段）</h4>1. mark_deciding，存档 DECIDING。2. 编译上下文（溢出则 PARTIAL）。3. 调用 model.decide。4. 校验决策。失败的分支见右侧与下一页。<div class=\"path\">runtime/loop.py · REQUEST_DECISION 分支</div>",
    accept: "<h4>accept_decision</h4>决策通过校验，包装成 DecisionEnvelope，存档 DECISION_ACCEPTED。之后恢复时不再请求模型。",
    resolve: "<h4>RESOLVE_ACTION（解析段）</h4>ActionResolver 把决策翻译为内部动作，生成确定性的 action_id，存档 ACTION_RUNNING。这是副作用发生前的最后一个存档点。解析失败会回到决策段（修复）。",
    execute: "<h4>EXECUTE_ACTION（执行段）</h4>调用 ActionExecutor（底层是工具层：校验参数、缓存、重试、熔断）。这里有外部副作用，也是唯一可能重复调用外部服务的窗口。取消与调用竞速。成功后存档 OBSERVATION_READY。",
    reduce: "<h4>REDUCE_OBSERVATION（归约段）</h4>ObservationProcessor 生成增量 StateDelta；mark_reducing 存档 REDUCING；commit_step 调用纯函数 Reducer，一次构造完成六项状态更新，存档 STEP_COMMITTED。不变量被破坏则 FAILED。",
    q_verdict: "<h4>EVALUATE_CONTINUATION（完成判定）</h4>CompletionEvaluator 对本步决策与观察给出 verdict。无 verdict → 继续；有 verdict → 以 COMPLETED 或 PARTIAL 结束。finish 决策只是提议，必须通过这里。",
    continue: "<h4>apply_continuation(RUNNING)</h4>清除 continuation_pending，存档 CONTINUATION_APPLIED，回到循环顶部。下一轮从存档重新判定要做什么。",
    e_recover: "<h4>出口：决策失败处置</h4>模型调用抛出 ModelClientError，或决策未通过校验，都进入这里（修复、重试或耗尽，见下一页）。<br>注意：上下文溢出是另一个出口，发生在模型调用之前，直接以 PARTIAL 结束。",
    e_resolve: "<h4>出口：解析失败</h4>决策已被接受，但 ActionResolver 无法把它翻译为动作（ValueError，映射为 INVALID_ACTION）。处置与决策失败相同：通常回到决策段修复。",
    e_result: "<h4>出口：返回结果</h4>run 已是终态时由 result_from_state 生成 RunResult。不做任何新的执行。",
    e_cancel: "<h4>出口：CANCELLED</h4>terminate_run 设置 CANCELLED 与原因，存档 RUN_TERMINATED。已提交的步骤保留。",
    e_limit: "<h4>出口：PARTIAL（步数上限）</h4>达到 max_steps 且下一步尚未开始，PARTIAL 结束。已提交的成果保留，不声称完成。",
    e_ctx: "<h4>出口：PARTIAL（上下文放不下）</h4>必需的上下文（指令、任务）在预算内放不下时，抛 ContextOverflowError，以 PARTIAL 诚实停止，而不是截断指令。",
    e_exec: "<h4>出口：执行中取消</h4>外部调用与取消信号竞速，取消胜出时 CANCELLED。远端是否已执行无法回滚。",
    e_invariant: "<h4>出口：FAILED（归约不变量）</h4>build_delta 或 commit_step 抛出 ValueError，说明状态或增量不符合不变量。系统不尝试修补，直接 FAILED 并附 RuntimeFailure（fail closed）。",
    e_verdict: "<h4>出口：COMPLETED 或 PARTIAL</h4>完成策略给出 verdict：满足完成标准为 COMPLETED，否则 PARTIAL。注意：COMPLETED 只代表程序认为完成，不保证结论正确。",
  };

  // ---------- Decision failure branch ----------
  function failureSvg() {
    var p = [];
    // Row 1: classify the failure, repeated action ends the run.
    p.push(Svg.box({ x: 20, y: 30, w: 240, h: 62, key: "f_src", title: "决策段出现失败", sub: "模型错误 / 校验失败 / 解析失败", fill: "#eef5ff", stroke: "#2f6fdb" }));
    p.push(Svg.line([[260, 61], [300, 61]], {}));
    p.push(diamond(430, 22, 260, 78, "f_repeat", ["REPEATED_ACTION ?"]));
    p.push(Svg.line([[560, 61], [620, 61]], { label: "是", dy: -6 }));
    p.push(Svg.box({ x: 620, y: 30, w: 390, h: 62, key: "f_partial_repeat", title: "PARTIAL：重复动作", sub: "terminate_run → 存档 RUN_TERMINATED", fill: "#fff6f5", stroke: "#e0a39a" }));

    // Row 2: retry budget and whether anything was committed.
    p.push(Svg.line([[430, 100], [430, 130]], { label: "否", dx: 6, dy: 0 }));
    p.push(diamond(430, 130, 300, 84, "f_exhaust", ["不可重试（鉴权/配置）", "或 attempt ≥ max_decision_attempts ?"]));
    p.push(Svg.line([[580, 172], [660, 169]], { label: "是", dy: -6 }));
    p.push(diamond(780, 130, 240, 78, "f_committed", ["已有提交的步骤 ?"]));
    p.push(Svg.line([[780, 208], [735, 250]], { label: "是", dx: 8, dy: 0 }));
    p.push(Svg.line([[900, 169], [935, 250]], { label: "否", dx: 6, dy: -6 }));
    p.push(Svg.box({ x: 660, y: 250, w: 150, h: 58, key: "f_partial", title: "PARTIAL", sub: "决策修复耗尽", fill: "#fff6f5", stroke: "#e0a39a" }));
    p.push(Svg.box({ x: 860, y: 250, w: 150, h: 58, key: "f_failed", title: "FAILED", sub: "带 RuntimeFailure", fill: "#fff6f5", stroke: "#e0a39a" }));

    // Row 3: repair or retry depends on the phase where the failure happened.
    p.push(Svg.line([[430, 214], [430, 262]], { label: "否", dx: 6, dy: 0 }));
    p.push(diamond(430, 262, 260, 78, "f_stage", ["当前阶段是 ?"]));
    p.push(Svg.box({ x: 40, y: 372, w: 280, h: 66, key: "f_retry", title: "DECIDING：retry_decision", sub: "attempt + 1，追加 failure，仍在 DECIDING", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.box({ x: 520, y: 372, w: 300, h: 66, key: "f_repair", title: "DECISION_ACCEPTED：repair_accepted_decision", sub: "丢弃被拒绝的决策，attempt + 1，回到 DECIDING", fill: "#fff8e6", stroke: "#d9a441" }));
    p.push(Svg.line([[300, 301], [180, 372]], { label: "DECIDING", dx: -90, dy: -4 }));
    p.push(Svg.line([[560, 301], [670, 372]], { label: "DECISION_ACCEPTED", dx: 4, dy: -4 }));

    // Row 4: both repairs end in a saved DECIDING state, then the loop re-reads it.
    p.push(Svg.box({ x: 300, y: 480, w: 320, h: 58, key: "f_save", title: "存档 DECIDING → 回到循环顶部", sub: "下一次重新请求模型（attempt 已在存档中）", fill: "#eef5ff", stroke: "#2f6fdb" }));
    p.push(Svg.line([[180, 438], [380, 480]], {}));
    p.push(Svg.line([[670, 438], [480, 480]], {}));
    p.push(Svg.text(20, 556, "默认 max_decision_attempts = 2：一次失败后还可以再试一次；第二次仍失败则进入耗尽分支。", "lbl"));
    return Svg.wrap(1040, 575, p.join(""));
  }

  var FAIL_DETAILS = {
    f_src: "<h4>失败来源</h4>三类：ModelClientError（超时、限流、空响应、拒绝等 8 种模型错误）；校验失败（DecisionValidationError 或 ValueError）；解析失败（ActionResolver 的 ValueError，映射为 INVALID_ACTION）。<div class=\"path\">runtime/loop.py · REQUEST_DECISION / RESOLVE_ACTION</div>",
    f_repeat: "<h4>重复动作</h4>同一动作被判定为重复，直接 PARTIAL。不再重试，因为重试只会得到同样的结果。",
    f_exhaust: "<h4>是否还能重试</h4>鉴权与配置类错误不可重试（重试没有意义）。其他错误只要 attempt 还没到上限，就可以再试。",
    f_committed: "<h4>已有提交的步骤</h4>如果本 run 已经有提交过的步骤，耗尽时保留这些成果，以 PARTIAL 结束；如果一步都没有，以 FAILED 结束并附 RuntimeFailure。这是“跑不完”与“跑不动”的区分。",
    f_stage: "<h4>修复还是重试</h4>被拒绝的决策若还停在 DECIDING（模型调用本身失败），用 retry_decision。若已经是 DECISION_ACCEPTED（解析失败），用 repair_accepted_decision：丢弃被拒绝的决策，回到 DECIDING。两者都会让 attempt 加一、保留失败原因。",
    f_retry: "<h4>retry_decision</h4>StepRecord 以 attempt + 1 重建，failures 追加本次失败，phase 为 DECIDING。已经存档，所以崩溃后可以续跑。",
    f_repair: "<h4>repair_accepted_decision</h4>从 DECISION_ACCEPTED 回退到 DECIDING。被拒绝的决策与部分载荷被丢弃，之前的失败原因按顺序保留。",
    f_partial_repeat: "<h4>PARTIAL：重复动作</h4>同一动作重复出现，说明模型陷入循环。以 PARTIAL 结束，保留已提交的成果。",
    f_partial: "<h4>PARTIAL：决策修复耗尽</h4>决策失败已经用尽重试次数，但 run 已有提交的步骤。保留成果，状态 PARTIAL。",
    f_failed: "<h4>FAILED：决策修复耗尽且一步都没提交</h4>没有任何成果可保留，run 以 FAILED 结束，并附带最后一次失败的 RuntimeFailure。",
    f_save: "<h4>回到循环顶部</h4>修复或重试后的状态被存档，循环回到顶部，由 classify_resume 判定：仍在 DECIDING，于是重新请求模型。",
  };

  var CANCEL_DETAILS = {
    race: "<h4>取消是竞速，不是直接杀死</h4>_await_operation 同时等待“调用完成”和“取消信号”。哪个先完成就用哪个。取消胜出时，取消在途任务，并以 CANCELLED 结束。",
  };

  window.Site.register({
    id: "agent-loop",
    group: "agent",
    title: "AgentLoop 主循环流程图",
    lead: "这是 Agent 运行的主线。每一轮都从存档重新判定该做什么，做完一个阶段就存档、回到顶部。图中每个方框都对应 runtime/loop.py 里的一个真实分支。",
    deep: [
      { label: "代码 · runtime/loop.py", href: "../opinion_search_agent/src/opinion_search/runtime/loop.py" },
      { label: "深度课程 · 03 Loop 与事务提交", href: "../opinion_search_interview_guide/index.html" },
    ],
    render: function (el) {
      var loop = loopSvg();
      el.innerHTML =
        '<div class="callout"><strong>读图方法</strong>中间一列是正常路径，从上往下；每个方框底部写明了它存档的 checkpoint 名称。右侧的出口是异常或终止路径。点击任一节点看它的职责和代码位置。</div>' +
        '<div class="diagram" id="loop-diagram">' + loop.svg + '<div class="caption">AgentLoop.run 的控制流（点击节点查看说明）</div></div>' +
        '<div class="detail" id="loop-detail"></div>' +
        '<h2>三条必须记住的规则</h2>' +
        '<ol>' +
        '<li><b>先存档，再进入下一阶段。</b>每个阶段结束都调用一次 _save，然后 continue 回到顶部。没有嵌套流程，只有状态分发。</li>' +
        '<li><b>下一步由存档决定，不由代码顺序决定。</b>图中的虚线只是常见顺序；崩溃恢复时，classify_resume 直接跳到存档所在的阶段。</li>' +
        '<li><b>副作用只发生在 EXECUTE_ACTION。</b>ACTION_RUNNING 存档之后、OBSERVATION_READY 存档之前，是唯一可能重复调用外部服务的窗口。</li>' +
        "</ol>";
      Site.bindNodes(document.getElementById("loop-diagram"), LOOP_DETAILS, document.getElementById("loop-detail"));
    },
  });

  window.Site.register({
    id: "agent-failure",
    group: "agent",
    title: "失败与修复分支",
    lead: "Agent 最常见的问题不是崩溃，而是模型给出了不合法的决策。这一页看决策失败如何被修复、何时放弃、以及为什么放弃时的终态不同。",
    deep: [
      { label: "代码 · runtime/loop.py · _recover_decision_failure", href: "../opinion_search_agent/src/opinion_search/runtime/loop.py" },
      { label: "深度课程 · 03 重试、修复与耗尽", href: "../opinion_search_interview_guide/index.html" },
    ],
    render: function (el) {
      el.innerHTML =
        '<div class="diagram" id="fail-diagram">' + failureSvg() + '<div class="caption">决策失败后的处置（点击节点查看说明）</div></div>' +
        '<div class="detail" id="fail-detail"></div>' +
        '<h2>为什么要区分“修复”和“重试”</h2>' +
        '<table><tr><th>失败发生在</th><th>处置</th><th>原因</th></tr>' +
        '<tr><td>DECIDING（模型调用失败或决策不合法）</td><td>retry_decision</td><td>还没有任何决策被接受，直接再问一次模型。</td></tr>' +
        '<tr><td>DECISION_ACCEPTED（解析失败）</td><td>repair_accepted_decision</td><td>决策已被接受，但无法翻译为动作。丢弃它，回到决策段。</td></tr></table>' +
        '<h2>取消如何打断一个阶段</h2>' +
        '<div class="diagram">' +
        Svg.wrap(1040, 150,
          Svg.box({ x: 20, y: 40, w: 220, h: 60, key: "race", title: "在途调用", sub: "model.decide / execute" }) +
          Svg.line([[240, 70], [300, 70]], {}) +
          Svg.box({ x: 300, y: 40, w: 220, h: 60, key: "race", title: "asyncio.wait", sub: "操作 与 取消信号 竞速", cls: "node" }) +
          Svg.line([[520, 70], [580, 52]], { label: "操作先完成" }) +
          Svg.line([[520, 70], [580, 110]], { label: "取消先到达" }) +
          Svg.box({ x: 580, y: 22, w: 200, h: 58, key: "race", title: "使用操作结果", sub: "继续正常路径" }) +
          Svg.box({ x: 580, y: 84, w: 200, h: 58, key: "race", title: "取消在途任务", sub: "→ CANCELLED", fill: "#fff6f5", stroke: "#e0a39a" })
        ) + '<div class="caption">取消不会等待模型或工具返回；取消胜出时在途任务被取消</div></div>' +
        '<div class="detail" id="race-detail"></div>' +
        '<div class="callout warn"><strong>诚实的口径</strong>取消只中止本地协程，不承诺远端回滚。如果工具已经发出请求，远端可能仍然执行完成。</div>';
      Site.bindNodes(document.getElementById("fail-diagram"), FAIL_DETAILS, document.getElementById("fail-detail"));
      Site.bindNodes(el.querySelectorAll(".diagram")[1], CANCEL_DETAILS, document.getElementById("race-detail"));
    },
  });
})();
