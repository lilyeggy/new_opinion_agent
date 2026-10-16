// Basics track: vocabulary, crash-recovery intuition, and the meaning of
// "boundary" and "semantics". Written for a reader without distributed-systems background.
(function () {
  var WORDS = [
    {
      term: "Agent（智能体）",
      plain: "一个会循环做事的程序：看当前状态 → 决定下一步 → 执行 → 看结果 → 再决定。",
      analogy: "像一个按步骤办事的助理，每做完一件事就在工作日志上记一笔。",
      here: "本项目只有一个 Agent，循环做 search / read / reflect / finish 四类决策。",
    },
    {
      term: "模型（LLM）与决策（Decision）",
      plain: "模型只负责“提议下一步做什么”，它不直接修改任何数据。提议的内容叫决策。",
      analogy: "像顾问给建议。建议能不能生效，要看制度怎么审核。",
      here: "模型返回 AgentDecision；它只是 proposal，程序校验后才会执行。",
    },
    {
      term: "工具（Tool）与服务商（Provider）",
      plain: "程序可以调用的外部能力，例如搜索网页、读取网页正文。同一种能力可以有多个服务商。",
      analogy: "同一种外卖需求可以找不同商家，一家不行就换一家。",
      here: "逻辑工具是 search.web / read.web；物理服务商是 Brave、Jina 等适配器。模型只看见逻辑工具。",
    },
    {
      term: "状态（State）",
      plain: "程序“记得什么”的全部数据：问题拆成了哪些子问题、找到了哪些来源、哪些已经解决。",
      analogy: "像银行账户的余额和流水。所有业务判断都以它为准。",
      here: "OpinionSearchState 是唯一的权威状态。其他视图（如 Working Memory）都是从它派生的。",
    },
    {
      term: "运行时（Runtime）",
      plain: "负责“怎么一步一步执行”的那层程序。它管调度、存档、恢复，不关心业务内容是什么。",
      analogy: "工厂里的流水线与质检线。它不关心产品是手机还是冰箱。",
      here: "runtime/ 目录不 import 任何舆情相关代码；它只认识通用的信封和阶段枚举。",
    },
    {
      term: "步（Step）与阶段（Phase）",
      plain: "一步是“决策 → 执行 → 提交状态”的一次完整周期。阶段是这一步内部的进度标记。",
      analogy: "一笔快递：揽收、运输、派送、签收。每个节点都可以被查到。",
      here: "一步有七个阶段：opened、deciding、decision_accepted、action_running、observation_ready、reducing、committed。",
    },
    {
      term: "检查点（Checkpoint）",
      plain: "在某个时刻把全部状态完整写入磁盘。以后进程崩溃，就从最近的检查点继续。",
      analogy: "游戏的存档点。读档后不会丢失存档之前的进度。",
      here: "JsonCheckpointStore 在每个阶段边界都存一次，文件里有 schema 版本和执行配置指纹。",
    },
    {
      term: "持久化与 fsync",
      plain: "持久化是“写到磁盘上，重启后还在”。fsync 是要求操作系统真正把数据刷到磁盘，而不是还留在内存缓冲里。",
      analogy: "在草稿纸上写账目，和写进账本并盖章，是两回事。",
      here: "存档先写临时文件，fsync，再用 os.replace 原子替换正式文件。",
    },
    {
      term: "原子性（Atomicity）",
      plain: "一组修改要么全部发生，要么全部没发生。中间的“做了一半”状态不能被外界看见。",
      analogy: "转账：A 扣款和 B 收款必须同时成功，不能只扣了一边。",
      here: "提交一步时，新状态的六个字段在一次构造中同时变化；构造不出“做了一半”的状态。",
    },
    {
      term: "崩溃与恢复（Crash & Resume）",
      plain: "进程在任何时刻都可能被杀掉（断电、超时、被关闭）。恢复就是从最近的存档重新开始。",
      analogy: "停电后重启电脑，Word 自动恢复到上次保存的版本。",
      here: "恢复入口 AgentLoop.resume 只读存档，不读内存；首次执行与恢复走同一条代码路径。",
    },
    {
      term: "幂等（Idempotent）",
      plain: "同一个操作做一次和做多次，效果相同。",
      analogy: "电梯按钮按一下和按十下，电梯只会来一次。",
      here: "同一个 action_id 的增量只会生效一次；已提交过的 step 再次提交时直接返回原状态。",
    },
    {
      term: "边界（Boundary）",
      plain: "一段“要么全成功、要么全失败”的操作区间，两端是存档点。边界之间的东西，崩溃时要么整段重做，要么整段不做。",
      analogy: "一笔整笔入账的电汇：从发起到到账是一个边界。",
      here: "本项目的 CheckpointBoundary 有 10 个；每个都是一个可以恢复的位置。详见下一页。",
    },
    {
      term: "语义（Semantics）",
      plain: "系统对“失败后重试，外部效果会发生几次”做出的承诺。常见三种：至多一次、至少一次、效果上只一次。",
      analogy: "快递承诺：“最多送一次”“至少送一次”“送一次且只收一次钱”，三种承诺的执行成本不同。",
      here: "本项目承诺：已落盘的成功结果不会再次请求，状态效果幂等；不承诺外部 exactly-once。详见下一页。",
    },
    {
      term: "确定性（Deterministic）",
      plain: "同样的输入一定得到同样的输出。没有隐藏的随机数、当前时间或外部差异。",
      analogy: "数学公式 2+3 永远等于 5；掷骰子不是。",
      here: "上下文编译、Reducer、ID 生成都是确定的；这是能做回放的前提。",
    },
    {
      term: "回放（Replay）",
      plain: "把录下来的输入（模型输出、工具结果）重新喂给程序，看它是否得到同样的结果。",
      analogy: "复盘一场比赛的录像，逐回合核对比分。",
      here: "runtime/replay.py：只替换模型和工具为录制内容，其余逻辑都用生产代码。",
    },
    {
      term: "熔断（Circuit breaker）",
      plain: "某个服务连续失败达到阈值后，暂时不再调用它；冷却一段时间后再试探。",
      analogy: "电路跳闸：连续过载就断开，过一会儿再合上看看。",
      here: "阈值 3 次连续失败，冷却 30 秒；key 是 (工具名, 服务商)。状态只存在内存中。",
    },
    {
      term: "上下文窗口（Context window）",
      plain: "模型一次能读入的最大文字量，超过就必须裁剪或压缩。",
      analogy: "一张便签纸的大小：写满了就要挑哪些内容留下。",
      here: "Context Compiler 在每次模型调用前，按预算分层挑选内容，不是把历史对话原样拼接。",
    },
  ];

  function card(w) {
    return '<div class="card"><h4>' + Site.esc(w.term) + "</h4>" +
      "<p>" + Site.esc(w.plain) + "</p>" +
      '<div class="analogy">类比：' + Site.esc(w.analogy) + "</div>" +
      '<p><span class="tag">本项目</span>' + Site.esc(w.here) + "</p></div>";
  }

  // Crash scenario: a three-stage operation with a checkpoint written only at stage boundaries.
  var CRASH_POINTS = [
    {
      key: "a",
      label: "决定做什么之后、执行之前",
      nosave: "重启后不知道是否已经决定过；可能重新决定（如果决定有副作用，会重复），也可能直接跳过。",
      save: "存档里记录的是“已决定”，重启后直接进入执行，不会重新决定。",
      calls: "外部调用：0 次（还没执行）",
    },
    {
      key: "b",
      label: "工具已经发出请求，但结果还没保存",
      nosave: "不知道工具是否真的执行过。如果重做，外部可能被调用两次。",
      save: "存档记录的是“准备执行”，重启后会再次执行一次。若结果已落到成功缓存，则直接复用，不再调用。",
      calls: "外部调用：可能重复（这是唯一无法完全消除的窗口）",
    },
    {
      key: "c",
      label: "结果已保存，但还没把它写进权威状态",
      nosave: "结果在内存里丢了，只能再调用一次工具；或者状态已经改了一半。",
      save: "存档里已经有完整结果。重启后只重做“写入状态”这一步，绝不再调用工具。",
      calls: "外部调用：0 次（结果已存档）",
    },
    {
      key: "d",
      label: "状态已写入，但还没存档",
      nosave: "状态可能已经生效，重启后又算一遍，结果被累加两次。",
      save: "存档还停在上一个阶段。重启后重做这一步；提交操作是幂等的，不会重复生效。",
      calls: "外部调用：0 次",
    },
  ];

  function renderCrash(el) {
    var options = CRASH_POINTS.map(function (p) {
      return '<option value="' + p.key + '">' + Site.esc(p.label) + "</option>";
    }).join("");
    el.innerHTML =
      '<p>假设一步操作分三段：<b>决定</b> → <b>调用外部工具</b> → <b>写入状态</b>。' +
      "你可以选择进程在哪一刻崩溃，看两种做法（无存档 / 有存档）重启后会发生什么。</p>" +
      '<div class="toolbar"><label>崩溃时刻：<select id="crash-select">' + options + "</select></label></div>" +
      '<div class="grid grid-2" id="crash-out"></div>' +
      '<div class="callout"><strong>要记住的一句话</strong>' +
      "存档点决定了“重启后哪些事必须重做”。存档越靠近外部副作用，重复的风险越小；" +
      "但存档本身也有成本，所以只在阶段边界存，而不是每一行代码后存。</div>";

    function show() {
      var key = document.getElementById("crash-select").value;
      var p = CRASH_POINTS.filter(function (x) { return x.key === key; })[0];
      document.getElementById("crash-out").innerHTML =
        '<div class="card"><h4><span class="tag danger">无存档</span></h4><p>' + Site.esc(p.nosave) + "</p></div>" +
        '<div class="card"><h4><span class="tag ok">有存档（本项目）</span></h4><p>' + Site.esc(p.save) + "</p>" +
        '<div class="analogy">' + Site.esc(p.calls) + "</div></div>";
    }
    document.getElementById("crash-select").addEventListener("change", show);
    show();
  }

  // Boundary and semantics: three promises applied to the same crash window.
  var SEMANTICS = [
    {
      key: "amo",
      name: "至多一次（at-most-once）",
      promise: "宁可不做，也不重复做。",
      calls: "最多 1 次；可能是 0 次",
      effect: "可能丢失效果",
      note: "适合“重复就会出问题”的动作；代价是用户可能看到结果缺失。",
    },
    {
      key: "alo",
      name: "至少一次（at-least-once）",
      promise: "宁可重复做，也不漏做。",
      calls: "至少 1 次；可能多次",
      effect: "效果可能重复",
      note: "需要接收方能识别重复（幂等键），否则会重复产生副作用。",
    },
    {
      key: "eo",
      name: "状态效果上只一次（effectively-once）",
      promise: "外部可能被调用多次，但对系统状态的影响只发生一次。",
      calls: "外部可能多次（取决于窗口）",
      effect: "状态只生效一次",
      note: "通过幂等提交和成功结果复用实现。不等于外部 exactly-once。",
    },
  ];

  function renderBoundary(el) {
    var options = SEMANTICS.map(function (s) {
      return '<option value="' + s.key + '">' + Site.esc(s.name) + "</option>";
    }).join("");
    el.innerHTML =
      '<h2>先理解两个词</h2>' +
      '<div class="grid grid-2">' +
      '<div class="card"><h4>边界（Boundary）</h4>' +
      "<p>边界是“整段要么全成功、要么全失败”的区间。在本项目里，每个 checkpoint 都是一条边界：它说明“到这里为止，系统的状态是一致的”。</p>" +
      '<div class="analogy">问自己：崩溃后，这段东西能不能被整段重做而不产生错误？</div></div>' +
      '<div class="card"><h4>语义（Semantics）</h4>' +
      "<p>语义是系统对“失败后重来，会发生什么”的承诺。同一个操作，承诺不同，实现成本和风险完全不同。</p>" +
      '<div class="analogy">面试官问“能保证 exactly-once 吗”，问的就是语义。</div></div>' +
      "</div>" +
      "<h2>同一个窗口，三种承诺</h2>" +
      '<p>场景：工具已经返回结果，但进程在保存结果之前崩溃了。</p>' +
      '<div class="toolbar"><label>选择承诺：<select id="sem-select">' + options + "</select></label></div>" +
      '<div id="sem-out"></div>' +
      '<h2>本项目选了哪一种</h2>' +
      '<div class="callout ok"><strong>承诺：已落盘的成功结果复用 + 状态效果幂等</strong>' +
      "重启后，如果成功结果已经存在缓存，就直接复用，不再请求工具；状态的提交也只会生效一次。" +
      "<br><b>不承诺</b>：在“工具已收到请求、但结果还没写入缓存”的那一刻崩溃，外部服务可能被再次调用。" +
      "所以项目说的是 <b>effectively-once 状态效果</b>，不是外部 exactly-once。</div>" +
      '<div class="callout warn"><strong>面试里的正确说法</strong>' +
      "“我们做到了状态效果只生效一次，外部调用在一个窗口内可能重复，这个窗口我们知道、测过、并在文档里写明了。”</div>";

    function show() {
      var key = document.getElementById("sem-select").value;
      var s = SEMANTICS.filter(function (x) { return x.key === key; })[0];
      document.getElementById("sem-out").innerHTML =
        '<table><tr><th>承诺</th><td>' + Site.esc(s.promise) + "</td></tr>" +
        "<tr><th>外部调用次数</th><td>" + Site.esc(s.calls) + "</td></tr>" +
        "<tr><th>对状态的影响</th><td>" + Site.esc(s.effect) + "</td></tr>" +
        "<tr><th>说明</th><td>" + Site.esc(s.note) + "</td></tr></table>";
    }
    document.getElementById("sem-select").addEventListener("change", show);
    show();
  }

  window.Site.register({
    id: "basics-words",
    group: "appendix",
    title: "先认识这些词",
    lead: "这一页的词会在后面的每一页出现。每个词都给出三件事：大白话、一个生活类比、它在本项目里对应什么。",
    deep: [{ label: "深度课程 · 02 Runtime 协议", href: "../opinion_search_interview_guide/index.html" }],
    render: function (el) {
      el.innerHTML = '<div class="grid grid-2">' + WORDS.map(card).join("") + "</div>";
    },
  });

  window.Site.register({
    id: "basics-crash",
    group: "appendix",
    title: "为什么要存档：崩溃之后怎么办",
    lead: "程序随时可能被杀掉。不存档，就不知道做到哪了；存档太频繁又很慢。关键是：在哪里存档。",
    deep: [{ label: "深度课程 · 04 Checkpoint 与崩溃恢复", href: "../opinion_search_interview_guide/index.html" }],
    render: renderCrash,
  });

  window.Site.register({
    id: "basics-boundary",
    group: "appendix",
    title: "“边界”与“语义”到底是什么",
    lead: "这是最容易听不懂的两个词。下面用一个操作在三种承诺下的结果来讲清楚。",
    deep: [
      { label: "深度课程 · 03 Loop 与事务提交", href: "../opinion_search_interview_guide/index.html" },
      { label: "面试资料 · 03 逐层机制（B4 exactly-once）", href: "../docs/interview/07-面试问答库.md" },
    ],
    render: renderBoundary,
  });
})();
