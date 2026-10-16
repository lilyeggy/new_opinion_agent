// Entry page: what the project is in one paragraph, the study path, and a
// self-check list that links to the page covering each answer.
(function () {
  var SITE_DEEP = [
    { label: "现有深度课程（14 模块）", href: "../opinion_search_interview_guide/index.html" },
    { label: "面试资料 00 索引", href: "../docs/interview/00-INDEX.md" },
  ];

  var PATH = [
    { time: "约 40 分钟", page: "agent-loop", title: "AgentLoop 主循环", note: "Agent 运行的主线：每一轮从存档判定、决策、执行、归约、完成判定。" },
    { time: "约 30 分钟", page: "agent-failure", title: "失败与修复分支", note: "决策失败如何修复、重试、耗尽；为什么耗尽时终态不同。" },
    { time: "约 40 分钟", page: "sys-dataflow", title: "一步的数据流", note: "决策、动作、观察、增量、状态之间的流转，以及每一步的存档点。" },
    { time: "约 45 分钟", page: "core-context", title: "上下文编译", note: "模型每一轮看到什么：分层、预算、信任边界。" },
    { time: "约 40 分钟", page: "core-domain", title: "舆情领域：决策与完成", note: "四个动作，finish 为什么只是提议，完成判定怎样约束它。" },
    { time: "约 60 分钟", page: "core-recovery", title: "崩溃恢复与边界", note: "基础设施如何保证 Agent 运行在中断后仍然正确。" },
    { time: "约 40 分钟", page: "core-tools", title: "工具容错", note: "搜索与读取失败时，如何分类、熔断、回退。" },
    { time: "约 40 分钟", page: "core-replay", title: "确定性回放", note: "用录制的模型输出与工具结果重放整个 run，定位第一处偏离。" },
    { time: "约 90 分钟", page: "iv-pitch", title: "面试表述与问答", note: "以 Agent 运行为主线讲项目，再按问答库自测。" },
  ];

  var CHECKS = [
    { q: "一句话说清这个项目是做什么的？", page: "iv-pitch" },
    { q: "为什么要把一步拆成多个阶段，并在每个阶段存档？", page: "basics-crash" },
    { q: "“边界恢复语义”指什么？", page: "basics-boundary" },
    { q: "模型输出的 Decision 和执行的 Action 有什么区别？", page: "core-domain" },
    { q: "崩溃后重启，哪一步可能重复调用外部工具？为什么？", page: "core-recovery" },
    { q: "为什么不能说“我们保证 exactly-once”？", page: "iv-redlines" },
    { q: "确定性回放能证明什么，不能证明什么？", page: "core-replay" },
    { q: "为什么不用 LangGraph，为什么不做多 Agent？", page: "iv-decisions" },
  ];

  window.Site.register({
    id: "home",
    group: "start",
    title: "总览与学习路径",
    lead:
      "这个站以舆情 Agent 的运行为主线。基础设施（存档、工具容错、回放）只是为了让这次运行可靠，" +
      "所以每一页都从 Agent 运行的问题出发，再回到它对应的代码分支。概念速查放在附录。",
    deep: SITE_DEEP,
    render: function (el) {
      var checks = CHECKS.map(function (c) {
        return '<li>' + Site.esc(c.q) + ' <a href="#/' + c.page + '">→ 去看</a></li>';
      }).join("");
      var steps = PATH.map(function (s, i) {
        return '<div class="card"><div class="tag">第 ' + (i + 1) + " 步 · " + Site.esc(s.time) + "</div>" +
          '<h4><a href="#/' + s.page + '">' + Site.esc(s.title) + "</a></h4>" +
          '<div class="analogy">' + Site.esc(s.note) + "</div></div>";
      }).join("");
      el.innerHTML =
        '<div class="callout"><strong>一句话项目</strong>' +
        "这是一个面向公开网页的舆情调查 Agent。模型每一轮只提出一个决策（搜索、读取、反思或结束）；" +
        "程序负责把决策变成可执行的动作、记录结果、按规则修改权威状态，并在每个阶段存档，" +
        "使进程在任何一点崩溃后都能从存档继续。项目的重点不是“搜索做得多好”，而是" +
        "<b>长时间运行的 Agent 如何可靠地走完</b>。</div>" +
        "<h2>学习路径（合计约 7 小时，可分三次完成）</h2>" +
        '<div class="grid grid-2">' + steps + "</div>" +
        "<h2>自测：能回答这些问题再进入面试</h2>" +
        '<p>每题都能在一两分钟内用自己的话讲清楚，且能说出一个具体的例子，才算过关。</p>' +
        "<ol>" + checks + "</ol>" +
        '<div class="callout warn"><strong>使用提醒</strong>' +
        "站内的数字和代码事实来自仓库当前代码与面试资料，并标注了口径。" +
        "如果你在仓库里改了代码，以代码为准，并同步修改本站。</div>";
    },
  });
})();
