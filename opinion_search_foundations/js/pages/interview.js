// Interview track: pitch scripts, question bank, decisions and trade-offs,
// red-line phrasing, number provenance, incident stories, and self-check.
(function () {
  var DEEP_IV = [
    { label: "面试资料 00 索引", href: "../docs/interview/00-INDEX.md" },
    { label: "面试资料 01 项目速览与自我介绍", href: "../docs/interview/01-项目速览与自我介绍.md" },
  ];

  // ---------- Pitch ----------
  var PITCH = [
    {
      time: "30 秒",
      text:
        "我做的是一个面向公开网页舆情调查的 Agent Harness。核心不是搜索，而是一次长时间运行的 Agent 怎样可靠地走完。" +
        "模型每轮只提一个决策：搜索、读取、反思或结束。运行时把它校验、解析成动作、执行、拿到观察结果，再经过一个纯函数归约器提交成新的权威状态。" +
        "每个阶段都存档，所以崩溃后的恢复和首次执行走同一条代码路径。",
    },
    {
      time: "1 分钟",
      text:
        "在 30 秒的基础上补两件事：一是边界，我刻意只深做运行时和工具上下文两层，多 Agent、LangGraph、评测平台都没做，其中多 Agent 实现过后砍掉了；" +
        "二是证据，一次真实运行跑满 60 步，产出 14 条发现、92 处引用，并有崩溃窗口的恢复测试，断言每个组件的调用次数。",
    },
    {
      time: "3 分钟",
      text:
        "问题：长程 Agent 最难的不是模型聪明不聪明，而是执行语义——模型说的和做的是否一致，崩溃后该重放还是复用，上下文怎样不被注入，模型怎样不靠一个假的完整答案收工。" +
        "做法：一步拆成七个阶段，每个阶段边界存档，阶段与载荷由校验器绑定；模型只有提案权，只有归约器能写状态；上下文从状态确定性编译，分四层，信任标签写进类型。" +
        "取舍：自研显式循环而不是图框架，因为要交付的正是执行语义本身；不做多 Agent，因为它绕过了运行时的可靠性机制。" +
        "证据与边界：崩溃恢复的承诺是已落盘的成功结果不重复请求、状态效果幂等，不是外部 exactly-once；这些都有测试和文档口径。最近加入的确定性回放，可以把恢复后的行为和原始运行逐步比对。",
    },
  ];

  // ---------- Question bank ----------
  var QA = [
    {
      level: "基础",
      q: "一句话介绍这个项目。",
      a: "面向公开网页舆情调查的可恢复单 Agent Harness：模型提决策，运行时负责校验、执行、归约、存档和恢复。",
      follow: "为什么强调“可恢复”？——长任务会崩溃，恢复要能说清每个阶段的副作用。",
    },
    {
      level: "基础",
      q: "一次 run 怎么走？",
      a: "循环：读存档判断阶段 → 编译上下文 → 模型决策 → 校验 → 解析为动作 → 执行工具 → 观察 → 构造增量 → 归约提交 → 完成判定。每个阶段边界存档。",
      follow: "为什么每一步都要“先存档再继续”？——存档点决定了崩溃后哪些事必须重做。",
    },
    {
      level: "基础",
      q: "模型怎么调用工具？",
      a: "模型不调用工具。它输出语义决策（如“搜索某个缺口”），运行时把决策解析成内部动作，执行器才去调用具体服务商。模型看不见服务商。",
      follow: "那 Decision 和 Action 的区别是什么？——Decision 是提议，Action 是可执行的内部单元。",
    },
    {
      level: "基础",
      q: "状态存在哪里？长什么样？",
      a: "存在一个 JSON 检查点文件里，是完整的状态快照（不是事件日志），带 schema 版本和配置指纹，写入使用临时文件加 fsync 再原子替换。",
      follow: "为什么用快照不用事件溯源？——单机单写者场景下快照的恢复语义更直接；代价是存储和序列化开销。",
    },
    {
      level: "基础",
      q: "崩溃了怎么恢复？",
      a: "恢复只读存档，不读内存。按阶段决定动作：决策阶段可能重问模型；观察已存的阶段绝不重调工具；已提交的步骤先做完成判定，不重放执行。唯一有重复风险的是动作执行中途崩溃，用成功结果缓存把它缩到最小。",
      follow: "能保证 exactly-once 吗？——不能，见下一题。",
    },
    {
      level: "进阶",
      q: "为什么不用 LangGraph？",
      a: "判断标准：框架是实现手段，还是要交付的能力。这个项目要交付的正是执行语义（状态何时更新、工具如何恢复、步骤如何提交），用图执行会把它们藏起来。所以自研了显式的异步循环。",
      follow: "那你的循环是不是在重复造轮子？——是为了可见性和可验证性，不是为了通用性。",
    },
    {
      level: "进阶",
      q: "多 Agent 你试过吗？",
      a: "试过，实现了一版规划者、研究者、分析者、审阅者的流水线，评估后归档。理由：它重复了已有的页面计划与定向搜索；绕过了运行时的可靠性机制；而且没有解决真正的问题，单 Agent 不知道覆盖哪些维度时，复制成多个只会产生更多散乱材料。",
      follow: "什么情况下你会重新考虑多 Agent？——当单 Agent 的上下文和职责确实无法划分，而且运行时能给每个角色同样的可靠性保证。",
    },
    {
      level: "进阶",
      q: "exactly-once 能保证吗？",
      a: "不能。准确承诺是：已落盘的成功结果不会被再次请求（at-most-once 复用），加上状态效果幂等，即 effectively-once 的状态效果。“工具已收到请求、结果还没存”这个窗口无法消除。",
      follow: "生产化需要什么？——服务商支持幂等键、运行所有权与租约、动作记录的比较并交换、有副作用工具的补偿或人工确认。",
    },
    {
      level: "进阶",
      q: "为什么 Reducer 必须是纯函数？",
      a: "因为恢复时可能要重做归约。纯函数同样的输入得到同样的输出，重做是安全的；有 I/O 的归约会在恢复时再次产生副作用。",
      follow: "归约器不变量被破坏怎么办？——fail closed：run 直接 FAILED，而不是试图修补状态。",
    },
    {
      level: "进阶",
      q: "为什么 finish 不由模型决定？",
      a: "finish 只是一个提议。完成策略会检查每个必答缺口是否有处置、结论是否有足够来源、引用的 ID 是否真实存在。不满足时，理由作为可执行的反馈返回，继续下一步。模型既没有写权，也没有收工权。",
      follow: "提示词不够吗？——实测中仅靠提示词，模型会用完全部预算却不产生发现。所以需要程序强制。",
    },
    {
      level: "进阶",
      q: "熔断为什么按 (工具, 服务商) 隔离？",
      a: "只按服务商：某个工具的故障会拖垮该服务商的其他能力。只按工具：一个坏服务商会遮蔽另一个健康的服务商。组合键两个问题都避免了。只有中毒类错误（超时、限流、5xx、未知服务商错误）计入；鉴权错误是配置问题，必须每次可见。",
      follow: "半开状态为什么只放一个探测？——避免恢复瞬间的请求洪峰再次压垮服务。",
    },
    {
      level: "深挖",
      q: "如果让你重做，你会改什么？",
      a: "（请结合自己的判断回答。）参考方向：把恢复所需的副作用记录做成显式的动作记录表，而不是靠缓存推断；给工具结果增加可验证的内容哈希；把上下文的“重读原文”动作补上。",
      follow: "为什么现在没做？——每一项都需要新的边界与测试，超出了这个项目的五天范围。",
    },
    {
      level: "深挖",
      q: "怎么扩展到分布式？",
      a: "需要的不是更多机器，而是更多保证：运行所有权与租约（同一个 run 只有一个执行者）；动作记录的比较并交换；服务商支持幂等键；共享的事务存储或 outbox。这些在当前项目中都没有，也都不在范围内。",
      follow: "你的回放能帮助分布式吗？——回放只证明单机上的行为一致，不证明多执行者之间的协调正确。",
    },
    {
      level: "深挖",
      q: "你的回放证明了什么？",
      a: "给定录制的模型输出和工具结果，当前代码会得到同样的步骤序列和状态指纹；第一处分歧会精确到步骤和字段。它不证明模型在真实环境里会给出同样答案，也不证明答案的语义正确。",
      follow: "为什么 journal 不放进 checkpoint？——保持 checkpoint 版本不变，回放材料可以独立归档或删除，不影响恢复。",
    },
    {
      level: "深挖",
      q: "为什么不做向量检索？",
      a: "单次运行的证据规模是几百条，首先需要的是确定性引用和可恢复。向量检索的召回不确定性会破坏“相同状态生成相同上下文”这条性质。规模超过结构索引能力后，可以作为派生索引加入，但不能取代状态。",
      follow: "那长期记忆怎么办？——当前只有单次运行内的投影，没有跨运行记忆，不要说有。",
    },
  ];

  function renderPitch(el) {
    el.innerHTML =
      '<div class="callout"><strong>背诵顺序</strong>先背 30 秒版，再背 1 分钟版，最后用 3 分钟版的“问题 → 做法 → 取舍 → 证据”结构展开。被打断时，直接从当前段落结束的地方接着讲。</div>' +
      PITCH.map(function (p) {
        return '<h2>' + Site.esc(p.time) + "版</h2><p>" + Site.esc(p.text) + "</p>";
      }).join("") +
      "<h2>四个承重词（每个都能被追问）</h2>" +
      '<div class="grid grid-2">' +
      '<div class="card"><h4>可恢复</h4><p>崩溃在任一阶段边界都能定位并继续。</p><div class="analogy">追问：哪些事会重做？→ 见“崩溃恢复”。</div></div>' +
      '<div class="card"><h4>单 Agent</h4><p>显式自研循环，不是图框架；多 Agent 试过后砍掉。</p><div class="analogy">追问：为什么不做多 Agent？→ 见问答库。</div></div>' +
      '<div class="card"><h4>Harness</h4><p>项目本体是执行骨架，不是“调用模型 + 搜索 API”的薄封装。</p><div class="analogy">追问：Harness 和 Agent 有什么区别？</div></div>' +
      '<div class="card"><h4>一致性</h4><p>决策、动作、观察、状态四层分离，只有归约器能写状态。</p><div class="analogy">追问：Reducer 为什么是纯函数？</div></div>' +
      "</div>";
  }

  function renderQa(el) {
    el.innerHTML =
      '<div class="toolbar"><label>级别：<select id="qa-level"><option value="">全部</option><option>基础</option><option>进阶</option><option>深挖</option></select></label>' +
      '<label>搜索：<input type="search" id="qa-search" placeholder="例如 exactly-once、熔断、回放" size="30"></label></div>' +
      '<div id="qa-list"></div>' +
      '<div class="callout warn"><strong>答题纪律</strong>先给结论，再给一个具体例子，最后等追问。不要把“追问”的内容一次全说完。</div>';

    function draw() {
      var level = document.getElementById("qa-level").value;
      var q = document.getElementById("qa-search").value.trim().toLowerCase();
      var items = QA.filter(function (x) {
        if (level && x.level !== level) return false;
        if (!q) return true;
        return (x.q + x.a + x.follow).toLowerCase().indexOf(q) >= 0;
      });
      document.getElementById("qa-list").innerHTML = items.length
        ? items.map(function (x) {
            return '<details class="qa"><summary>' + Site.esc(x.q) + '<span class="level">' + x.level + "</span></summary>" +
              '<div class="body"><p><b>标准答法：</b>' + Site.esc(x.a) + "</p>" +
              '<p><b>追问链：</b>' + Site.esc(x.follow) + "</p></div></details>";
          }).join("")
        : '<p>没有匹配的问题。</p>';
    }
    document.getElementById("qa-level").addEventListener("change", draw);
    document.getElementById("qa-search").addEventListener("input", draw);
    draw();
  }

  var DECISIONS = [
    ["自研显式异步循环，不用 LangGraph", "框架会隐藏状态演进，项目要交付的正是这些语义", "上手快，但状态与恢复语义被框架决定", "需要自己写与测试循环本身"],
    ["不做多 Agent（试过并砍掉）", "单 Agent 加定向搜索已能覆盖；多角色绕过运行时可靠性", "拆分职责更直观，演示效果可能更好", "无法复用同一套恢复保证，协作语义更难验证"],
    ["一个 Runtime + 两个组合根", "运行时不知道舆情；两套领域各自装配", "只写一套领域更简单", "两套领域的 Context Compiler 不共享，有重复"],
    ["只深做两层，明确五个非目标", "边界清楚，能讲深", "什么都做一点看起来更完整", "没有 Sandbox、控制面、可观测平台，遇到相关问题只能讲取舍"],
    ["checkpoint 存全量快照，不存事件日志", "单机单写者，恢复语义直接", "事件溯源可以审计历史", "存储与序列化开销；没有天然的完整历史"],
    ["阶段与载荷由校验器绑定", "非法的中间状态在构造时就不存在", "靠约定和代码审查", "每个阶段要明确定义载荷，改动成本更高"],
    ["成功结果按 action_id 落盘，承诺 at-most-once 复用", "崩溃后不重复请求已成功的结果", "不做缓存，恢复时重新执行", "只能说 effectively-once；窗口仍然存在"],
    ["熔断键为 (工具, 服务商)，只统计中毒类错误", "故障隔离，配置错误可见", "全局熔断更简单", "状态只在内存中，重启后清零"],
    ["Reducer 是纯函数，且是唯一写入口", "恢复时可以安全重做归约", "允许任意代码写状态", "归约器的逻辑必须写得很克制"],
    ["finish 只是提议，由程序检查", "模型既不能写权，也不能擅自收工", "信任模型的完成判断", "完成检查可能误杀合理结论，需要反馈机制"],
    ["回放用独立 journal，不扩展 checkpoint 版本", "checkpoint 格式不变，回放材料可独立归档", "把步骤记录放进 checkpoint 更统一", "需要处理 journal 与 checkpoint 的一致性（已实现对齐规则）"],
    ["回放只替换模型与执行器，其余用生产代码", "回放检查的是真实逻辑，不是另一套模拟", "全部模拟更快更稳", "需要覆盖提交顺序与 ID 生成的确定性"],
  ];

  function renderDecisions(el) {
    el.innerHTML =
      '<p>面试官问“为什么”时，按这张表的四列回答：选了什么、为什么、放弃了什么、付出了什么代价。</p>' +
      "<table><tr><th>决策</th><th>理由</th><th>替代方案</th><th>代价</th></tr>" +
      DECISIONS.map(function (d) {
        return "<tr><td>" + Site.esc(d[0]) + "</td><td>" + Site.esc(d[1]) + "</td><td>" + Site.esc(d[2]) + "</td><td>" + Site.esc(d[3]) + "</td></tr>";
      }).join("") +
      "</table>" +
      '<div class="callout"><strong>诚实的一句话</strong>每一个决策都有代价。讲代价比讲优点更能证明你理解它。</div>';
  }

  var REDLINES = [
    ["我们做了多 Agent 编排", "实现过一版多角色流水线，评估后归档，生产路径是单循环。", "这是最容易被追穿的说法，代码里有归档记录。"],
    ["基于 LangGraph 二次开发", "自研显式的异步循环，依赖里没有 LangGraph。", "与依赖文件直接冲突。"],
    ["两套 domain 共用同一个 Context Compiler", "共享的只有 section 模型与压缩算法；两个 compiler 各自实现。", "Working Memory 只在一侧存在。"],
    ["我们保证 exactly-once", "at-most-once 复用已落盘的成功结果，加上状态效果幂等。", "外部 exactly-once 需要服务商和存储的配合。"],
    ["每个检查点崩溃都能零重复调用", "动作执行中途崩溃是唯一的重复调用窗口。", "这是有测试支撑的精确表述，不要夸大。"],
    ["checkpoint 存的是事件日志", "存的是全量状态快照，schema 版本为 4。", "事件溯源与快照的恢复语义不同。"],
    ["trusted 标签是模型的权限隔离", "它是上下文里的来源标签，保证外部内容不获得指令地位。", "不是运行时的权限控制。"],
    ["注入测试证明抗注入成功", "注入矩阵证明的是结构性质，不保证模型不被说服。", "测的是“没有指令权限”，不是“模型不会上当”。"],
    ["我们有长期记忆和向量检索", "当前只有单次运行内的投影。", "没有跨运行记忆，也没有向量库。"],
    ["完成了 benchmark 评测", "有的是人工标注的领域质量检验，有明确口径。", "项目明确不做评测平台。"],
    ["系统能保证结论正确、不会幻觉", "程序保证的是引用完整、状态转换合法、完成标准满足；语义正确仍依赖模型与审查。", "完成判定的理由里明确写着“不是真相保证”。"],
    ["测试全部通过", "写明命令、口径和日期，例如“本次实测 822 passed、2 skipped”。", "不同环境结果不同，需要说清环境。"],
    ["修复后提升了 N 倍", "没有对照实验的幅度都不能说；可以说“修复把不可执行的拒绝变成了可执行的拒绝，并有回归测试”。", "被追问“怎么测的”就会穿帮。"],
    ["模型通过工具调用获取信息", "模型输出语义决策；运行时把它翻译成动作，再执行工具。", "这是理解边界的关键，说错会显得没看过代码。"],
  ];

  function renderRedlines(el) {
    el.innerHTML =
      '<div class="callout danger"><strong>面试前 10 分钟必读</strong>下表每一行都是“与代码事实不符、但很容易脱口而出”的说法。宁可少说一句，不要说错一句。</div>' +
      "<table><tr><th>不要说</th><th>应该说</th><th>为什么</th></tr>" +
      REDLINES.map(function (r) {
        return "<tr><td>" + Site.esc(r[0]) + "</td><td>" + Site.esc(r[1]) + "</td><td>" + Site.esc(r[2]) + "</td></tr>";
      }).join("") +
      "</table>" +
      '<h2>“能证明什么就说什么”</h2><p>面试官追问“怎么测的”时，最有说服力的回答是说出机制和口径，而不是报一个漂亮的数字。</p>';
  }

  var NUMBERS = [
    ["全量测试", "822 passed，2 skipped（本次会话实测；命令 .venv/bin/python -m pytest；2 个 skip 是需要真实密钥的 live 测试）", "随测试增减会变，必须带命令与日期。"],
    ["历史记录的测试数", "779 passed / 2 skipped（正常环境，早前记录）；受限沙箱 788 passed / 3 failed（3 个是轮询终态的时限断言）", "这些是早前记录，与今天的 822 不矛盾，但不要混用。"],
    ["源码规模", "生成清单：95 个 Python 文件，约 24.4k 行（不含测试；由 scripts/gen_code_map.py 统计）", "01 稿写的是 91 个文件、约 20.6k 行，是更早的口径。以生成为准。"],
    ["一次真实 live 运行", "60 步；17 次搜索、17 次读取；14 条发现；92 处证据引用（三九胃泰事件）", "步数 ≠ 搜索次数。讲清楚各自的数量。"],
    ["检索召回", "60%（6/10 人工标注的必中清单，逐项独立搜索验证）", "不是全部来源的召回率；口径是人工标注的 10 项。"],
    ["忠实性", "10/14 完全有来源支持；零虚构 100%（人工检验）", "人工标注，不是自动评测。"],
    ["注入矩阵", "14 路（结构性质测试）", "证明的是“没有指令权限”，不是“抗注入成功”。"],
    ["长轨迹压力测试", "100 步、640 条证据（构造状态，非真实模型运行）", "不要说成真实模型跑出来的。"],
    ["运行时常量", "RunStatus 6 态；StepPhase 7 阶段；CheckpointBoundary 10 个；ToolErrorKind 12 种；RuntimeFailureKind 20 种；ModelErrorKind 8 种", "来自代码枚举，可以直接说。"],
    ["熔断参数", "连续 3 次中毒类失败开路；冷却 30 秒；半开只放一个探测", "默认值，可由配置覆盖（以代码为准）。"],
    ["确定性回放（本轮新增）", "journal 单元测试 13 项；回放集成测试 6 项；跨 PYTHONHASHSEED 的 journal 字节级一致（本次实测）", "只覆盖离线 fake 装配，没有在真实模型录制上验证。"],
  ];

  function renderNumbers(el) {
    el.innerHTML =
      "<p>每个数字都要能说出三件事：它是怎么测的、什么时候测的、适用于什么范围。下表是本站使用的全部数字。</p>" +
      "<table><tr><th>数字</th><th>完整口径</th><th>使用注意</th></tr>" +
      NUMBERS.map(function (n) {
        return "<tr><td>" + Site.esc(n[0]) + "</td><td>" + Site.esc(n[1]) + "</td><td>" + Site.esc(n[2]) + "</td></tr>";
      }).join("") +
      "</table>" +
      '<div class="callout warn"><strong>为什么数字会对不上</strong>仓库里的文档在不同时间校准，测试数随代码增加而变化。面试中看到不一致的数字，不要猜，直接说“以本次实测为准”并给出命令。</div>';
  }

  var STORIES = [
    ["空拒绝让模型空转 18 次", "拒绝只是“不行”，没有给下一步。finish 被拒后，模型不知道该做什么，于是重复 18 次。", "拒绝必须附带可执行的下一步；程序强制而不是提示词建议。"],
    ["空 Decision：推理 token 吃掉输出上限", "模型把输出预算用在推理上，结构化决策为空，看起来像成功但没有内容。", "“成功”和“有结果”是两件事；空响应要有专门的失败类型。"],
    ["Evidence ID 被改写成顺序别名", "模型在 reflect 里不复制真实的不透明 ID，自己编 ev-1、ev-2 之类的别名，验证器因此拒绝决策。ID 是哈希派生的、人眼无结构，数量多或被压缩丢弃时，模型就倾向于编一个好记的。", "严格的契约必须配合可恢复的上下文：信息完整、有界、确定地放在模型面前。"],
    ["MCP metadata 洗白：两轮失败", "第一版只剥顶层；第二版先序列化再删，更糟；第三版先过滤再验证才正确。", "过滤与验证的顺序有语义；修复本身也可能引入新攻击面。"],
    ["20 步与 60 步：配置问题被当成逻辑问题", "同一题跑两次，一次停在 20 步 partial，一次跑满 60 步。诊断数据显示 committed_steps 恰好等于 max_steps=20，而预算只用了 16%–45%：不是跑不动，是被上限截断。根因是步数默认值不够。", "用诊断数据区分“跑不动”和“被上限截断”，不要第一反应归咎于模型不稳定。"],
    ["“过去 30 天”带空格不解析", "用户输入的空白位置不受控，strip 和去掉所有空白是两回事。", "修解析 bug 时，把等价的输入变体一起补进回归测试。"],
  ];

  function renderStories(el) {
    el.innerHTML =
      "<p>每个故事都按同一结构讲：现象 → 定位 → 根因 → 修复 → 一般化。一般化那一句才是面试官想听的。</p>" +
      STORIES.map(function (s, i) {
        return '<details class="qa"><summary>故事 ' + (i + 1) + "：" + Site.esc(s[0]) + '</summary><div class="body">' +
          "<p><b>现象与根因：</b>" + Site.esc(s[1]) + "</p>" +
          '<p><b>一般化：</b>' + Site.esc(s[2]) + "</p></div></details>";
      }).join("") +
      '<div class="callout"><strong>讲故事的四个必答句</strong>我看到了什么；我怀疑是什么；我如何证明它不是别的原因；我改了什么，以及以后怎么防止。</div>';
  }

  var CHECKS = [
    ["画出五层分层图，标注依赖方向。", "入口 → 组合根 → 领域 → Runtime → 支撑；Runtime 不 import 领域。"],
    ["画一步的七个阶段，标出存档点。", "opened → deciding → decision_accepted → action_running → observation_ready → reducing → committed；每个阶段边界存档。"],
    ["在任一箭头上写出：此刻崩溃会怎样？", "用“核心技术 · 崩溃恢复”的表格核对。"],
    ["说出“边界”和“语义”各是什么。", "边界：要么全成功要么全失败的区间；语义：失败后重来，外部效果发生几次的承诺。"],
    ["说出三种语义，并说明本项目选了哪一种。", "至多一次、至少一次、效果上只一次；本项目是“已落盘结果复用 + 状态幂等”，即 effectively-once 的状态效果。"],
    ["解释为什么恢复时 ACTION_RUNNING 有重复风险。", "工具可能已收到请求，结果还没存；缓存只能缩小窗口。"],
    ["解释 Decision、Action、Observation、Delta 的区别。", "提议、可执行单元、外部返回、希望对状态做的改动。"],
    ["解释确定性回放证明了什么、没证明什么。", "证明给定录制输入下行为不变；不证明模型答案正确。"],
    ["说出三类工具错误的处置策略。", "可重试（超时、限流、5xx）；立即停止（参数错、未知工具、取消）；跨服务商回退（鉴权、权限等）。"],
    ["说出你最想改进的一处，并说为什么现在没做。", "例如：副作用记录表、工具结果哈希、重读原文动作；受范围和测试边界限制。"],
  ];

  function renderSelfcheck(el) {
    el.innerHTML =
      "<h2>白板练习</h2>" +
      '<p>不看资料，在纸上完成下面的任务。画完再对照答案。</p>' +
      "<ol>" + CHECKS.map(function (c, i) {
        return '<li class="quiz-item"><div>' + Site.esc(c[0]) + '</div><button data-ans="' + i + '">显示参考答案</button>' +
          '<div class="answer" id="ans-' + i + '">' + Site.esc(c[1]) + "</div></li>";
      }).join("") + "</ol>" +
      "<h2>三天复习计划</h2>" +
      "<table><tr><th>天</th><th>任务</th></tr>" +
      "<tr><td>第 1 天</td><td>基础篇全部（词汇、崩溃、边界与语义）；系统全景与数据流；画两遍分层图。</td></tr>" +
      "<tr><td>第 2 天</td><td>核心技术：Runtime、存档、恢复、工具容错；用白板完成上面的 10 项练习。</td></tr>" +
      "<tr><td>第 3 天</td><td>面试篇：30 秒与 1 分钟版本；问答库全部（口头回答，不看答案）；表述红线；数字口径。</td></tr></table>" +
      '<div class="callout ok"><strong>面试前 10 分钟</strong>只看“表述红线”和“数字口径”两页，然后默念 30 秒版本。</div>';

    el.querySelectorAll("button[data-ans]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var box = document.getElementById("ans-" + btn.getAttribute("data-ans"));
        box.classList.toggle("show");
        btn.textContent = box.classList.contains("show") ? "隐藏答案" : "显示参考答案";
      });
    });
  }

  window.Site.register({
    id: "iv-pitch",
    group: "interview",
    title: "开场表述：30 秒、1 分钟、3 分钟",
    lead: "面试的第一个问题几乎总是“介绍一下你的项目”。这一页给出三个长度的版本，并说明每个版本的结构。",
    deep: DEEP_IV,
    render: renderPitch,
  });

  window.Site.register({
    id: "iv-qa",
    group: "interview",
    title: "问答库：标准答法与追问链",
    lead: "按基础、进阶、深挖三级组织。每题先给标准答法，再给常见追问。先自己口头回答，再展开看。",
    deep: [{ label: "面试资料 07 面试问答库（完整版）", href: "../docs/interview/07-面试问答库.md" }],
    render: renderQa,
  });

  window.Site.register({
    id: "iv-decisions",
    group: "interview",
    title: "设计决策与取舍",
    lead: "面试官最爱问“为什么”。下表是本项目关键决策的四列：选择、理由、替代方案、代价。",
    deep: [{ label: "面试资料 04 关键设计决策与取舍（完整版）", href: "../docs/interview/04-关键设计决策与取舍.md" }],
    render: renderDecisions,
  });

  window.Site.register({
    id: "iv-redlines",
    group: "interview",
    title: "表述红线：不能说的话",
    lead: "这些说法与代码事实不符，却很容易脱口而出。每一条都给出正确说法和原因。",
    deep: [{ label: "面试资料 08 表述红线与陷阱（完整版）", href: "../docs/interview/08-表述红线与陷阱.md" }],
    render: renderRedlines,
  });

  window.Site.register({
    id: "iv-numbers",
    group: "interview",
    title: "数字口径：每个数字怎么说",
    lead: "数字是最容易被追穿的地方。每个数字都标注了测量方式、时间和适用范围。",
    deep: [{ label: "面试资料 05 实测数据与验证证据", href: "../docs/interview/05-实测数据与验证证据.md" }],
    render: renderNumbers,
  });

  window.Site.register({
    id: "iv-stories",
    group: "interview",
    title: "故障复盘故事",
    lead: "“讲一个你踩过的坑”是高频题。下面六个故事都是真实发生过的，每个都有一条可以推广的教训。",
    deep: [{ label: "面试资料 06 故障复盘故事（完整版）", href: "../docs/interview/06-故障复盘故事.md" }],
    render: renderStories,
  });

  window.Site.register({
    id: "iv-selfcheck",
    group: "interview",
    title: "自测与三天复习计划",
    lead: "最后一关：能不能在白板上讲清楚，并能在三分钟内把项目说完整。",
    deep: [{ label: "面试资料 02 白板自测", href: "../docs/interview/02-架构总览.md" }],
    render: renderSelfcheck,
  });
})();
