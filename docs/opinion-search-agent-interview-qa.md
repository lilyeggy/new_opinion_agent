# OpinionSearch Agent 面试问题与回答

> 文档用途：围绕当前仓库的真实实现准备 Agent Infra / Search Agent 面试。  
> 事实基线：2026-08-27 当前代码、`public-opinion-search-agent-design.md` 与 `opinion-search-agent-implementation-memory.md`。  
> 使用原则：先说结论，再讲机制、失败模式和验证证据；没有实现的能力必须明确说是演进方向。

## 0. 面试前先记住的项目事实

### 当前已经实现

- Python 3.12+、Pydantic 2、自定义 async 单 Agent Runtime；没有依赖 LangChain 或 LangGraph。
- `search -> read -> reflect -> finish` 四类领域决策，模型只提议，Runtime 校验和执行。
- Run/Step 双生命周期、显式 Agent Loop、纯 Reducer、step transaction、checkpoint/resume、取消与 terminal bundle。
- Tool Registry/Executor、typed error、retry、provider fallback、circuit breaker、成功结果缓存，以及 Fake、Brave、Jina、MCP adapter。
- L0-L3 Context Compiler、run-scoped Working Memory、Evidence catalog、ProvenanceIndex、origin/trust 隔离和确定性压缩。
- Candidate/Source/Evidence/Claim/StakeholderPosition/Narrative/FinalSynthesis 领域链，以及四个固定调查维度的 Completion Gate。
- TaskFrame 与冻结时间范围、Reader 正文 artifact、证据定位、结构化 `SearchReportView`、Markdown 投影、CLI 与轻量 Web 控制台。
- 当前验证：非 Web 测试 `561 passed, 2 skipped`；Web E2E `11 passed`；合计 `572 passed, 2 skipped`。两个 skip 是需要真实 provider key 的显式 live smoke。

### 当前没有实现、回答时不能冒充已经实现

- 当前搜索策略仍以四个固定 Gap 驱动，不是完整的动态舆情意图拆解系统。
- `OpinionAnalysisFrame`、`SearchIntent`、`OpinionSignal`、`CoverageMap`、对比搜索、信息增益评分和饱和停止属于下一阶段目标。
- 来源多样性目前是 URL-level `Source` record，不是 publisher/entity 所有权去重，也没有转载链识别。
- 没有社交平台全量采集、传播规模估计、全网正负面比例、跨会话长期记忆、向量数据库、多 Agent、分布式 Control Plane 或 Eval Platform。

---

## 1. 项目定位与开场

### Q1：请用 30 秒介绍这个项目。

**回答：**

这是一个以公开 Web 舆情调查为 workload 的单 Agent Harness。核心不是包装一个搜索 API，而是实现长程 Agent 的可靠执行：模型每一步只能提出 `search/read/reflect/finish` 决策，Runtime 负责校验、工具执行、Observation 归一化、纯 Reducer 提交状态、checkpoint 恢复和完成门禁；同时通过 Tool/MCP Runtime、L0-L3 上下文编译和 run-scoped Working Memory，持续构建带来源、证据、立场、叙事和反叙事的舆情地图。

### Q2：两分钟版本怎么讲？

**回答：**

项目聚焦 Agent Infra 的前两层：Harness/Runtime，以及 Tool/MCP/Context/Memory。Runtime 用显式 async loop 管理 Run 与 Step 两套生命周期，每一个 step 都经历 Decision、Action、Observation、StateDelta 和 commit；稳定 `action_id`、幂等 Reducer、版本化 checkpoint 与成功结果缓存共同保证崩溃恢复后的 effectively-once state effect。工具侧由 Registry 和 Executor 统一拥有参数校验、timeout、retry、fallback、circuit 和错误归一化，MCP 只作为 adapter 接入并加 allowlist、schema pin 和元数据清洗。上下文侧不使用 `messages.append()`，而是从 committed State 投影 Working Memory，再按 L0-L3、预算、相关性、信任来源和确定性降级编译每轮输入。舆情领域用事实基线、利益相关方立场、主导叙事和反叙事四个维度验证这套基础设施；只有证据和语义记录满足 Completion Gate，模型的 finish 才能被接受。

### Q3：项目真正解决的核心问题是什么？

**回答：**

一个长程 Search Agent 如何在单次运行中可靠地完成模型决策、工具执行、状态演进、上下文管理和工作记忆更新。这里“可靠”指的是：模型输出不能直接产生副作用，工具失败有稳定语义，崩溃后能从明确 phase 恢复，重复执行不会重复写入 State，长轨迹不会无限膨胀上下文，最终结论必须能回指 committed Evidence。

### Q4：为什么选择舆情搜索作为 workload？

**回答：**

舆情调查天然包含长程 Agent 最难的因素：多轮查询、候选来源筛选、网页读取、观点冲突、来源差异、上下文持续增长、无唯一正确答案以及停止条件模糊。它能真正逼出 Runtime、Tool、Context 和 Memory 的边界问题，比“查一个事实并回答”的 demo 更能验证 Harness 是否可靠。

### Q5：这个项目是舆情产品还是 Agent Infra 项目？

**回答：**

主身份是 Agent Harness/Capability Runtime，OpinionSearch 是唯一的 reference workload。领域不是装饰：它提供 Evidence、Claim、Narrative 和 Completion Gate 等真实约束；但通用 Runtime 不包含 `counter_narrative` 之类领域判断。这样既能讲基础设施，又能证明基础设施承受过真实业务复杂度。

### Q6：为什么只深做 Agent Infra 前两层？

**回答：**

因为项目需要形成清晰的技术纵深。单次 Agent 的生命周期、事务恢复、工具协议和上下文正确性已经是完整问题域；如果同时扩张到 sandbox、分布式调度、可观测平台、评测平台和训练基础设施，每一层都只能停留在接口拼装。面试中我希望能把一次工具调用前后每个失败窗口讲清，而不是列很多没有做深的平台名词。

### Q7：项目最有差异化的三点是什么？

**回答：**

第一，显式 step transaction 和恢复矩阵，把 Agent Loop 当成可恢复状态机而不是 while-loop demo。第二，Tool/MCP 与 Context/Memory 都有严格所有权和信任边界：provider 无法控制 retry，外部内容无法升级为 instruction。第三，舆情领域把“为什么获取证据”和“证据实际支持什么”分开，并用结构化 Completion Gate 拒绝没有语义覆盖的 finish。

### Q8：为什么使用 Python 而不是 TypeScript？

**回答：**

这个项目的主要复杂度是模型/工具调用、Pydantic 契约、async orchestration 和研究生态接入，Python 在这些方面开发反馈快，且适合把状态模型和测试写得非常直接。选择不是因为 TypeScript 做不了，而是 Python 能让五天原型阶段把精力集中在 Runtime 语义，而不是类型工具链和 SDK 差异上。

---

## 2. 框架选择、Agent 范式与单 Agent 决策

### Q9：为什么没有使用 LangGraph？

**回答：**

不是因为 LangGraph 不好，而是本项目的学习和产出目标正是框架通常替你隐藏的部分：状态何时可见、step 在哪个 phase 落盘、工具返回后崩溃如何恢复、重复 delta 怎样幂等、context 怎样从持久状态重建。使用图框架可以更快搭出流程，但会让 checkpoint 和节点调度成为框架语义；我选择显式 loop，是为了拥有并能证明这些语义。

### Q10：你的实现比 LangGraph 好在哪里？

**回答：**

不能笼统说“更好”，只能说对本项目目标更合适。我们的优势是范围窄但契约更可见：`StepPhase` 与 payload 对齐由 Pydantic 不变量强制；checkpoint 有 schema version 和 execution profile；恢复行为是 `classify_resume` 纯函数；commit 同时推进 state、step cursor、action ledger 和 continuation marker。代价是缺少 LangGraph 成熟的图组合、生态节点、HITL 和分布式扩展。面试里应按场景比较，而不是贬低框架。

### Q11：如果业务只想快速上线，你还会不用 LangGraph 吗？

**回答：**

不一定。如果需求是常规流程编排、团队接受框架持久化语义、恢复要求不特殊，我会优先使用成熟框架。本项目自研的理由是 Runtime 本身就是核心交付物；如果 Runtime 只是实现手段，自研成本通常不划算。

### Q12：这个 Agent 是 ReAct 吗？

**回答：**

它具有 ReAct 的交替决策和观察特征，但不是把自由文本 `Thought/Action/Observation` 直接追加到消息历史。模型输出结构化 Decision，Runtime 将其验证并解析成 Action，工具结果成为 Observation，processor 再生成 StateDelta。`reflect` 是显式内部动作，因此可以称为“typed、stateful、transactional 的 ReAct-like loop”，不应宣称复现了原始 ReAct 协议。

### Q13：为什么不是 Plan-and-Execute？

**回答：**

当前舆情调查的信息结构会随着网页内容改变，过早生成完整计划容易失效，所以采用 gap-guided 的逐步闭环：根据当前缺口选择 search/read/reflect。固定四 Gap 提供最小全局结构，局部行动保持自适应。后续如果实现动态 `SearchIntent`，可以在 Domain Policy 中加入轻量规划，但不需要改变 Runtime transaction。

### Q14：为什么不用多 Agent？

**回答：**

多 Agent 会新增任务分解、消息传递、状态合并、权限、失败传播和并发恢复问题，而当前核心问题是把单条长轨迹的执行语义做扎实。舆情里的多视角不等于必须多 Agent；一个 Agent 也可以通过结构化 Gap、NarrativeKind 和 Completion Gate 主动寻找对立材料。只有当角色隔离或并行吞吐带来的收益能覆盖一致性成本时，我才会引入 subagent。

### Q15：单 Agent 会不会陷入单一视角？兜底是什么？

**回答：**

会有这个风险，所以当前不是只靠 prompt 提醒“客观”，而是把 factual baseline、stakeholder positions、dominant narratives、counter narratives 设为四个显式维度；缺少反叙事时 finish 会被拒绝或只能 partial。来源语义覆盖还要求至少两个 distinct Source records。但这只是结构性兜底，不等同于统计意义上的观点代表性。

### Q16：如果未来引入多 Agent，最适合在哪个边界扩展？

**回答：**

应在 Domain Policy 之上引入任务分派，子 Agent 产生带 provenance 的候选 delta 或 artifact，而不是共享可变 State。主 Runtime 仍通过统一校验和 Reducer 合并，避免多个 Agent 直接写权威状态。需要额外解决 action namespace、并发 checkpoint、冲突合并和取消传播。

---

## 3. Runtime 协议与生命周期

### Q17：为什么 RunStatus 和 StepPhase 必须分开？

**回答：**

RunStatus 回答“整个任务是否仍然存活”，状态是 `created/running/completed/partial/failed/cancelled`；StepPhase 回答“当前事务走到哪里”，状态是 `opened/deciding/decision_accepted/action_running/observation_ready/reducing/committed`。如果混成一个枚举，run 级终态、step 重试和恢复位置会互相污染，也无法表达 running run 内部正处于哪个故障窗口。

### Q18：`InvalidLifecycleTransition` 为什么是空 class？

**回答：**

它不需要额外方法。它的实现价值是提供稳定异常类型，让调用方和测试能区分“非法生命周期转换”与普通 `ValueError`。具体错误信息由 `validate_run_transition` 和 `validate_step_transition` 在抛出时构造；异常类型本身就是契约。

### Q19：Decision、Action、Observation、StateDelta 为什么不能合并？

**回答：**

它们对应四个不同所有者和事实阶段：Decision 是模型提案；ActionRequest 是通过校验、带稳定 action identity 的执行承诺；Observation 是环境实际返回；StateDelta 是 domain processor 对状态变化的受约束提议。合并后模型就可能绕过校验直接执行，工具结果也可能越过领域规则直接写 State。

### Q20：为什么要有 Envelope？

**回答：**

领域 payload 本身不知道它属于哪个 run、step 和 attempt。Envelope 补充 correlation metadata，使 checkpoint、日志、重试和 reducer 能验证同一条因果链。`ActionRequest/ObservationEnvelope/StateDelta` 还共享 `action_id`，防止把一次工具结果提交到另一次动作。

### Q21：为什么 retry 保持同一个 step_id，却增加 attempt？

**回答：**

模型输出 malformed 或 Decision 校验失败时，业务意图仍然是完成当前一步，并没有产生新的已提交状态，因此保留 step identity，增加 attempt 表达同一事务内的修复次数。只有 step committed 后，`next_step_index` 才推进。这样重试不会伪造额外进度。

### Q22：action_id 如何生成，为什么稳定？

**回答：**

当前稳定关系是 `step_id = {run_id}:step:{step_index}`，`action_id = {step_id}:attempt:{attempt}:action`。它把动作身份绑定到 run、逻辑 step 和本次决策 attempt，可用于结果缓存、Observation 关联和 committed ledger；provider retry/fallback 不改变 action_id，因为它们只是同一动作的物理执行尝试。

### Q23：StepRecord 存什么？它是 trace 吗？

**回答：**

StepRecord 保存恢复需要的 phase、Decision、Action、Observation 和失败历史，并强制 payload 与 phase 精确匹配。它不是通用 Observability trace：没有面向分析平台的 span、指标、索引和采样，只服务单次 Runtime 正确恢复。

### Q24：phase-payload 对齐解决什么问题？

**回答：**

例如 `ACTION_RUNNING` 必须同时拥有 Decision 和 Action，但不能提前拥有 Observation；`OBSERVATION_READY` 必须三者都有。checkpoint 加载时若出现“phase 说已观察、payload 却没有 Observation”的半截状态，Pydantic 会直接拒绝，而不是让恢复逻辑猜测。它把恢复前置条件变成可构造性约束。

### Q25：Runtime 的三层校验是什么？

**回答：**

第一层是结构校验：联合类型、必填字段、多余字段；第二层是 state-aware 校验：Gap/Candidate/Evidence ID 是否存在、是否重复、当前状态是否允许；第三层是 completion 校验：调查是否足以 complete，还是继续或 partial。Pydantic validator 不读取完整 State，CompletionPolicy 不修改 State，Reducer 不调用模型或工具。

### Q26：为什么 ActionResolver 失败可以同 step repair，而 processor/reducer 失败要 fail closed？

**回答：**

ActionResolver 失败发生在外部动作开始前，没有副作用，可以清除被拒绝的 Decision 并在同 step 增加 attempt。processor/reducer 失败发生在 Observation 已经存在之后，说明状态变换代码或不变量可能有 bug；盲目让模型重试可能隐藏一致性错误，所以当前直接终止为 failed。

---

## 4. Agent Loop、Reducer 与事务提交

### Q27：一次完整 step 的顺序是什么？

**回答：**

从 checkpoint/初始 state 开始，投影 Working Memory，编译 Context，请求结构化 Decision，做 state-aware validation，ActionResolver 解析，先落 `ACTION_RUNNING` checkpoint，再执行工具或内部动作，落 `OBSERVATION_READY` checkpoint，processor 构造 StateDelta，纯 Reducer 得到新 Domain State，原子 commit step，然后评估 continuation 或 terminal。

### Q28：Loop 为什么不能直接修改 State？

**回答：**

Loop 的职责是时序和失败调度。如果它同时包含 Evidence 构造、Gap 关闭和 Claim 合并，通用 Runtime 会依赖舆情领域，重放也无法独立验证。把写入集中到 pure Reducer 后，可以用相同 old state + delta 重放、比较结果并测试不变量。

### Q29：Reducer 为什么必须是纯函数？

**回答：**

恢复可能重复执行 reduction，所以 reducer 必须确定、无 I/O、不修改输入、不调用模型或工具。这样 `reduce(old_state, accepted_delta)` 可以离线重放，checkpoint 也不依赖进程内隐藏对象。纯函数不是风格偏好，而是恢复和审计的基础。

### Q30：`commit_step` 原子地做了哪些事？

**回答：**

它验证 envelope correlation 和 action identity，调用 reducer 生成新 Domain State，把 active step 转为 committed，清空 active step，把 step 加入 committed history，把 action_id 加入 committed ledger，推进 next_step_index，并设置 `continuation_pending=True`。这些必须作为一个状态转换出现，否则会产生“State 已变但游标没推进”之类撕裂状态。

### Q31：`continuation_pending` 是什么？

**回答：**

它封住 commit 后、完成判断前的崩溃窗口。step 已经提交，但 Runtime 还没决定继续还是终止；恢复看到该标记会先走 `EVALUATE_CONTINUATION`，不会打开新 step，也不会重放 reducer。

### Q32：为什么重复提交同一个 committed delta 返回原 State，而不是报错？

**回答：**

崩溃恢复中可能重放提交请求；只要 action_id 已 committed、correlation 能匹配原 committed step，重复应用应是 no-op。这是状态效果幂等。若 action_id 已存在但没有匹配 step，或当前还有别的 active step，则说明状态损坏，仍会拒绝。

### Q33：effectively-once state effect 和 exactly-once 有什么区别？

**回答：**

系统能保证同一 accepted delta 不会把 Domain State 累加两次，所以状态效果是 effectively-once。但 HTTP 请求可能已经到达 provider，而进程在保存结果前崩溃；没有 provider 参与的事务或幂等协议，客户端无法证明外部副作用 exactly-once。项目明确做诚实承诺，不把本地幂等夸大成分布式 exactly-once。

### Q34：为什么 search/read 是 ToolCall，而 reflect/finish 不是？

**回答：**

search/read 需要访问外部 capability，因此经 Registry/Executor；reflect 是只基于 committed State 提交领域语义对象的内部 action，finish 是交给 Completion Control 的提案。把四者都伪装成外部工具会模糊副作用、timeout 和恢复语义。

### Q35：模型连续输出无效 Decision 时会怎样？

**回答：**

Runtime 将错误归一为 typed failure，并在同 step 增加 attempt，把安全的结构化反馈放入下一轮 Context。达到最大尝试次数后，如果已有 committed step 则返回 partial，保留成果；如果从未有任何有效提交则 failed。这样区分“部分调查后无法继续”和“任务根本没有开始成功”。

---

## 5. Checkpoint、恢复与取消

### Q36：checkpoint 里到底存什么？

**回答：**

外层保存 `schema_version`、不透明 `execution_profile` 和完整 `RunState`。RunState 内含 Domain State、run status、active/committed steps、committed action IDs、游标、continuation marker、stop reason 和 terminal failure。Working Memory 与 Compiled Context 不落盘，因为都能从 State 重建。

### Q37：checkpoint 为什么要有 schema version？

**回答：**

Pydantic 模型形状或恢复语义改变后，旧 JSON 可能仍能部分解析却含义不同。schema version 让加载边界明确拒绝不兼容状态，而不是悄悄迁移或按新逻辑误执行。当前 schema version 为 4。

### Q38：execution profile 解决什么问题？

**回答：**

同一个 checkpoint 不能随意从 offline fake composition 切到 live model/provider，也不能在工具组合变化后继续执行。profile 是由 app composition 计算的不透明 ID，resume 时不匹配就拒绝；它只表达执行兼容性，不保存模型名、base URL、provider 配置或密钥。

### Q39：checkpoint 如何保证原子写？

**回答：**

先在目标目录创建临时文件，写入排序稳定的紧凑 JSON，`flush + fsync` 后用 `os.replace` 原子替换目标。直接覆盖正式文件会在进程崩溃时留下截断 JSON。当前是单机文件语义，不宣称跨机器事务存储。

### Q40：恢复为什么用 `classify_resume` 纯函数？

**回答：**

恢复动作只由持久状态决定：created 启动、terminal 返回、continuation pending 先判断继续、无 active step 则打开 step，其余按 phase 分派请求模型、解析 action、执行 action 或 reduction。纯函数让恢复矩阵可以穷举测试，避免依赖进程内“上次执行到哪”的隐式变量。

### Q41：三个关键崩溃窗口分别怎样恢复？

**回答：**

- `ACTION_RUNNING` 后崩溃：保持原 action_id，先查持久结果缓存；命中则不重调 provider，未命中则可能重新执行只读工具。
- `OBSERVATION_READY` 后崩溃：Observation 已持久化，直接重建 delta 并 commit，不调用工具。
- step committed 后崩溃：`continuation_pending` 驱动完成判断，不重放 reducer。

### Q42：JsonActionResultCache 为什么按 action_id 哈希命名？

**回答：**

任意 action_id 不应直接成为文件路径，避免路径穿越和非法字符；文件名使用 SHA-256。条目同时保存 ToolCall 和 ToolResult identity，命中时会验证 action_id、tool name 和 arguments，一致才复用，同 action_id 不同参数会抛 conflict，而不是返回错误结果。

### Q43：为什么损坏缓存不能当作 cache miss？

**回答：**

miss 意味着可以安全重新执行；损坏意味着系统本来声称持久化过结果，却无法判断外部动作是否已经发生。把它伪装成 miss 可能重复副作用，所以升为 typed `ToolCacheReadError`，让 Runtime fail closed。

### Q44：取消如何处理正在等待的模型或工具？

**回答：**

`CancellationSignal` 与 operation task 通过 `asyncio.wait(FIRST_COMPLETED)` 竞态。取消胜出时取消并 await 本地 task，run 进入 cancelled，保留已 committed State，不提交半个 delta。它只保证本地协程停止，不承诺远端 HTTP 请求一定回滚。

### Q45：如果取消发生在 REDUCING 阶段呢？

**回答：**

取消被延后：已经 checkpoint 的 Observation 先完成 processor/reducer/commit，再终止。否则同一 Observation 可能永远处于“已获得但未形成状态”的悬空状态，恢复语义不稳定。这里追求已观测结果的 state effect 恰好一次。

### Q46：terminal run bundle 包含什么？

**回答：**

新 run 目录包含 `run.json`、`outcome.json`、`report.md`、`artifacts/` 和 `action_results/`。`outcome.json` 是 typed outcome，`report.md` 是确定性展示投影；artifact 保存完整正文，state 只保留引用和精选证据；action_results 支持跨进程恢复。

---

## 6. Tool Runtime 与 provider 可靠性

### Q47：Tool Runtime 的核心链路是什么？

**回答：**

`ToolDefinition -> Registry -> ToolCall 参数校验 -> 成功缓存 -> provider circuit gate -> timeout/retry -> fallback -> adapter -> ToolResult/ToolError`。Registry 负责能力定义和有序 provider 绑定，Executor 拥有所有执行策略，adapter 只做协议翻译。

### Q48：为什么模型不能决定底层 retry？

**回答：**

模型不知道 provider 的限流、幂等和退避策略，让模型“再试一次”会生成新 step、新 action_id 并污染调查轨迹。Executor 的 retry 是同一 action 的物理重试，保持 action_id，按 typed error 和固定 policy 执行；模型只在工具最终失败后决定是否改变调查方向。

### Q49：ToolDefinition 为什么不能携带 adapter？

**回答：**

ToolDefinition 是稳定、模型可见的 capability contract，只包含名称、描述、输入 schema 和 capability metadata。provider ID 与 adapter 是应用装配信息，若进入 model spec，会让模型依赖某个供应商，也可能泄露实现配置。

### Q50：一个 Tool 如何绑定多个 provider？

**回答：**

Registry 为同一完全一致的 ToolDefinition 保存有序 `ProviderBinding`。`register_provider` 只能追加不同 provider_id；定义不一致或 provider 重复会在注册阶段失败且不产生半注册。模型仍只看到一份能力 schema。

### Q51：retry、fallback 和 Agent 再规划有什么区别？

**回答：**

retry 是同 provider、同 action 的瞬时错误恢复；fallback 是同 capability、同 action 切换另一个 provider；Agent 再规划发生在所有执行策略结束并返回 ToolError 之后，模型可以改变 query、candidate 或 gap。三层如果混在一起，step 数、action identity 和失败统计都会失真。

### Q52：哪些错误会重试？

**回答：**

同 provider 有界重试只针对 timeout、rate_limited、server_error。invalid_arguments、unknown_tool、cancelled 立即停止；authentication、permission、not_found、unreadable_content、content_too_large、unknown_provider_error 等可根据 frozen fallback 表尝试下一 provider，但不在同 provider 盲目重试。

### Q53：backoff 如何计算？

**回答：**

指数退避 `min(base * 2^(local_attempt-1), max_backoff_seconds)`；如果 adapter 提供 `retry_after_seconds`，取指数退避与 retry-after 中较大者，再受最大 backoff 截断。`ToolInvocation.attempt` 是跨 provider 累计的物理调用次数。

### Q54：Circuit Breaker 的粒度和状态是什么？

**回答：**

按 `(tool_name, provider_id)` 独立，避免一个 provider 故障拖垮同工具的备份，也避免某工具故障影响同 provider 的所有能力。状态为 closed/open/half-open；冷却后只允许一个 probe，成功复位，毒化失败重新 open。当前 circuit 在内存中，进程重启会重置。

### Q55：哪些失败会 poison circuit？

**回答：**

timeout、rate_limited、server_error、unknown_provider_error 会计入；authentication 和 permission 不计，因为它们通常是配置问题，不应通过 half-open 探测假装能自愈。非毒化失败也必须正确释放 half-open probe，这是项目修过的一个边界问题。

### Q56：为什么只缓存成功 ToolResult？

**回答：**

临时 timeout/rate-limit 如果缓存，会让后续恢复永远看到旧错误并失去重试机会。成功结果才用于跨进程 at-most-once 复用。identity conflict 则是程序不变量错误，直接传播，不能正规化成普通 ToolError。

### Q57：HTTP transport 为什么 `follow_redirects=False`？

**回答：**

搜索 provider 可能用自定义 credential header；跨域 redirect 时不能假设客户端会像处理 `Authorization` 一样自动剥离所有自定义 header。禁用自动跳转后，3xx 在 adapter 边界归一为安全 provider error，避免 key 被带到第二跳域名。

### Q58：URL 安全做了什么？

**回答：**

只接受 HTTP/HTTPS，拒绝 userinfo、空白和控制字符，host 小写和 IDNA，去默认端口与 fragment，拒绝 localhost、非 global IP 以及十进制/十六进制等 legacy IPv4 表示。当前 helper 不做 DNS 解析后的私网重绑定检查，这是明确限制。

### Q59：Brave 和 Jina 各做什么？

**回答：**

Brave Search adapter 把 query 转成稳定 `SearchResults`，只产生 CandidateSource；Jina Reader adapter 读取公开页面并正规化正文、标题、最终 URL 和可用发布时间，完整内容写 artifact，有限正文进入 Observation。供应商私有响应不会穿透内部协议。

### Q60：为什么 search snippet 不能直接成为 Evidence？

**回答：**

snippet 是搜索引擎截断和重写过的导航摘要，缺少完整上下文和稳定 locator。它只能用于发现 Candidate；必须 read 页面后，才能从正规化正文提取带 source_id、block/offset locator 的 Evidence。

---

## 7. MCP 接入与安全边界

### Q61：MCP 在项目里是什么地位？

**回答：**

MCP 只是 Tool adapter，不是 Agent 内核，也不带来第二套执行控制流。远端 `tools/list` 映射为内部 ToolDefinition，内部 ToolCall 映射为 MCP call，结果和错误仍回到 ToolResult/ToolError，并继续受 Registry/Executor 的 timeout、cache、circuit 和 fallback 管理。

### Q62：MCP discovery 为什么需要 allowlist？

**回答：**

不能把 server 临时暴露的所有工具都自动授予 Agent。应用配置必须明确列出允许的 remote tool；发现后还检查每个 allowlisted tool 恰好出现。remote server 不能仅靠更新 discovery 响应扩大 Agent 权限。

### Q63：schema pin 解决什么问题？

**回答：**

即使工具名不变，input/output schema 变化也可能改变副作用或解析语义。项目对 canonical JSON schema 计算 SHA-256，与 app 配置的 expected hash 比较；不匹配则 discovery 失败，Registry 保持字节级不变，避免半注册。

### Q64：为什么本地 description 不能使用 remote description？

**回答：**

description 会直接进入模型上下文，remote prose 等价于外部可控 prompt。项目只使用 app config 中审核过的 local description；remote annotations、description 和 `_meta` 都没有策略权威。

### Q65：MCP content block 如何防 metadata laundering？

**回答：**

不能只删除最外层 `_meta`。当前实现对 BaseModel、Mapping、list/tuple 等逐层递归投影，字段名或 alias 命中 `meta/_meta/annotations` 就在序列化前删除；最后再用 JsonValue 做终检。这样嵌套 resource 里的 metadata 也不能洗白成普通 payload。

### Q66：为什么必须“先过滤、后验证”？

**回答：**

旧思路若先 `model_dump(mode='json')`，攻击者在待删除 metadata 中放不可序列化对象，就能在过滤前触发 Pydantic serialization exception，穿透 adapter 边界。逐字段读取并先过滤，再做 JSON 验证，能把不可 JSON 的公开内容归一成固定安全 ToolAdapterError。

### Q67：循环引用怎么处理？

**回答：**

递归投影维护当前递归路径的 object identity 集合；遇到自引用容器就收口为安全错误。只跟踪当前路径而不是全局 visited，因此共享但无环的子对象不会被误判。

### Q68：output schema 声明了但 structured content 缺失怎么办？

**回答：**

fail closed。既然应用 pin 了 output schema，就不能退回到松散文本并假装契约仍成立；只有结构化内容存在且验证通过才成功。未声明 output schema 时，可以接受协议允许的普通 content，但仍要经过安全投影和 JSON 化。

### Q69：MCP transport 的已知限制是什么？

**回答：**

当前每次 `list_tools/call_tool` 都打开并关闭官方 SDK v2 Client 上下文，不支持状态化 session 复用；stdio 环境变量显式 allowlist，不继承整个进程环境；生产 HTTP 只允许公开 HTTPS，loopback HTTP 需显式 dev opt-in。它适合第一版只读工具，不是通用 MCP gateway。

---

## 8. Context Compiler、Working Memory 与溯源

### Q70：Context Compiler 相比 `messages.append()` 多解决了什么？

**回答：**

它把模型输入当成可编译产物：收集 typed sections、按当前 Gap 选择、按 trust/origin 去重、按预算压缩、稳定渲染、测量并执行 overflow fallback。这样可以明确回答“什么一定保留、什么先删、外部内容有什么权限、resume 后如何重建”，而不是让历史消息无限增长。

### Q71：Full State、Working Memory、Artifact、Recent Interaction 和 Context 有什么区别？

**回答：**

- Full Domain State：权威、完整、checkpoint、唯一事实源。
- Working Memory：从 committed State 纯投影出的紧凑认知视图，可丢弃重建。
- Artifact：完整网页和大型原始内容，State 只保留引用。
- Recent Interaction：有限窗口的近期 Decision/Observation/失败。
- Compiled Context：当前一次模型调用的临时输入，不落盘。

### Q72：L0-L3 分别是什么？

**回答：**

L0 是不可变系统规则和 action 协议；L1 是任务范围、SearchRequest、tool specs 和 decision schema；L2 是 Working Memory，包括 coverage、Evidence/Claim/Position/Narrative、候选与失败方向；L3 是最近交互和 rejection。L0/L1 required 且不能被低优先级网页挤出，L2/L3 按相关性和预算选择。

### Q73：为什么 output headroom 要在输入预算前扣除？

**回答：**

如果把整个窗口都分给输入，模型即使理解了上下文也没有空间输出结构化 Decision，容易得到 length finish 或空 payload。`input_token_limit = max_context_tokens - output_headroom_tokens` 把输出空间变成编译前硬约束。

### Q74：如何选择当前最相关 Evidence？

**回答：**

ProvenanceIndex 区分 semantic relation 与 acquisition relation；当前 Gap 的 semantic evidence 优先，其次 contested、其他 semantic、unlinked、仅为当前 Gap 获取以及其余内容。Evidence excerpt section 的 provenance refs 同时带 source、semantic gap、claim/position/narrative 关系，selector 不只看关键词。

### Q75：Evidence catalog 为什么分 required 和 history chunk？

**回答：**

模型提交 Reflect 时必须逐字引用 opaque Evidence ID，因此当前关键 ID 目录不能被压缩掉；但 640 条 Evidence 全部 required 会让上下文线性膨胀。策略是 required 当前目录最多 64，历史按 64 分 chunk 作为 optional；coverage 每 Gap 最多展示 16 个 sample ID，同时保留总数和 source count。

### Q76：压缩会不会让原内容找不回来？

**回答：**

不会删除权威原内容。Compaction 只决定本轮 Context 放哪些投影视图；完整 State、Evidence locator 和内容寻址 artifact 仍保留。模型下一轮若重新聚焦某 Gap，Compiler 可以从 State/Artifact 重新选择相关内容。当前没有单独的 artifact retrieval action，但审计和报告能沿 Evidence -> Source -> artifact_ref 找回原文。

### Q77：如何保证 Working Memory 不创造事实？

**回答：**

结构化 Working Memory 由纯 projector 从 committed State 生成，不接受任意模型写入，也不单独持久化。丢弃 Memory 后重新投影必须相等。即使未来加入自然语言 summary，也只能压缩已有 State 并保留 provenance reference，不能成为第二事实源。

### Q78：origin 和 trust 为什么是两个维度？

**回答：**

origin 说明内容由 runtime、app_config、user_task、model、tool 或 provider 中谁产生；trust 说明它是否拥有控制语义。高优先级网页证据仍是 untrusted，模型 reflection 即使 committed 也仍是 model-origin/untrusted。持久化赋予 durability，不赋予 authority。

### Q79：如何防 prompt injection？

**回答：**

L0 明确声明网页和工具内容不是指令；ContextSection 强制 model/tool/provider origin 不能 trusted；外部正文只进入 untrusted section；混合错误消息拆为 trusted control fields 和 untrusted prose；renderer 转义伪造的 `[CONTEXT_SECTION ...]` 标记；MCP metadata 也在 adapter 侧剥离。14 条 injection matrix 覆盖 snippet、reader、MCP、query、reflection、错误、rejection 和 resume 等路径。

### Q80：如果 required context 自己就超预算怎么办？

**回答：**

抛 `RequiredContextOverflow`，Runtime 将其转为 partial stop，而不是截断 L0/L1 或最终字符串尾部。系统宁可明确停止，也不在缺失协议和任务约束的情况下继续让模型行动。

### Q81：如何证明长轨迹有界且确定？

**回答：**

压力测试构造 100 个 committed steps、80 Source/Candidate、640 Evidence，并加入 contested claim、counter narrative 和注入内容；固定 80K budget 下 10/50/100 步都不超限，required catalog 不超过 64、coverage sample 不超过 16，两次编译 hash 一致，checkpoint round-trip 后 rendered/plan/hash 一致。

### Q82：token estimator 准确吗？

**回答：**

当前是可替换的启发式估算，不保证与 deepseek tokenizer 逐 token 一致。正确性依赖的是预算策略、确定性降级和可注入 estimator，而不是某个 tokenizer 的魔法数字；生产化时应接模型对应 tokenizer，并保留 provider length error 的最终兜底。

---

## 9. 舆情领域模型与搜索闭环

### Q83：当前四个 Investigation Gap 是什么？

**回答：**

事实基线、利益相关方立场、主导/新兴叙事、反叙事。它们把“找一个正确答案”改成“建立一个最小舆情结构”，并直接驱动 query 目的、Reflect 语义记录和 Completion Gate。

### Q84：CandidateSource、Source 和 Evidence 有什么区别？

**回答：**

CandidateSource 是 search 返回并经过 URL/domain 过滤的导航候选；Source 是已经 read、正规化并可能保存 artifact 的页面；Evidence 是 Source 中带 locator 的可引用 excerpt。这个分层阻止 snippet 冒充证据，也让 read 失败不会产生虚假 Source。

### Q85：为什么 `source_id` 使用 canonical URL？

**回答：**

URL 是跨 provider 可重建的稳定身份，能做候选去重和 checkpoint 恢复，避免把 Brave/Jina 私有 ID 带进 Domain State。当前只能做到 URL-level identity，尚未解决同一媒体多个 URL、转载链和 publisher ownership。

### Q86：Evidence ID 如何保证稳定？

**回答：**

Evidence 来自已正规化正文中的确定性 block/offset 选择，并绑定 Source identity；状态层使用 opaque stable ID，不允许模型自造顺序别名。Context 的可信 ID catalog 只暴露精确 ID 与关系，excerpt 仍保持 untrusted。

### Q87：acquisition provenance 和 semantic provenance 为什么要分开？

**回答：**

`target_gap_id/discovered_for_gap_ids/acquired_for_gap_id` 只回答“Agent 为什么搜索或读取它”；页面实际可能回答另一个问题。只有 Reflect 引用真实 Evidence ID 提交 GapAssessment、Claim、Position 或 Narrative，Reducer 才建立 semantic linkage。否则系统会把“为某 Gap 读过页面”误当成“该 Gap 已获得证据”。

### Q88：Gap 是如何被判定 resolved 的？

**回答：**

模型通过 Reflect 提交 `GapAssessmentProposal`，但 validator 会检查 Evidence ID 存在、时间有效和该维度所需的 semantic record；factual baseline 需要 fact Claim，stakeholder 需要 Position，dominant 需要 dominant/emerging Narrative，counter 需要 counter Narrative。通过后 Reducer 才更新 Gap status 和 evidence_ids。

### Q89：Gap 现在是不是完全依赖模型推理？

**回答：**

语义判断确实主要由模型提出，例如某 excerpt 是否构成立场或反叙事；但模型没有最终写权。结构、引用完整性、维度类型、时间范围、closed-gap 变更和 completion 条件由确定性代码校验。当前缺少更强的动态意图拆解和 signal extraction，这正是下一阶段搜索质量层的方向。

### Q90：Claim status 为什么不让模型直接指定？

**回答：**

`SUPPORTED/CONTESTED/UNRESOLVED` 从 supporting 和 contradicting Evidence 引用确定性派生；模型若直接指定，可能出现“有正反证据却说 supported”的矛盾状态。相同 claim text 还会生成稳定 ID并合并引用，supporting/contradicting 不能重叠。

### Q91：StakeholderPosition 和 Narrative 有什么区别？

**回答：**

Position 表示可归因到具体 stakeholder 的公开立场或表述；Narrative 表示公开来源如何组织和传播一个解释框架，可标为 dominant、emerging 或 counter，也可以关联多个 stakeholder。情感正负不能替代这两类语义结构。

### Q92：为什么舆情分析不能只做正负面 sentiment？

**回答：**

正负面只描述表面极性，不能回答“谁对什么对象、在哪个议题维度、以什么论据表达何种立场”，也无法区分事实争议、利益冲突和叙事框架。当前项目先建事实、主体、立场、叙事和反叙事；未来 `OpinionSignal` 可以加入 stance/sentiment，但必须绑定 holder、target、aspect、time 和 Evidence。

### Q93：Reader 如何从正文提取 Evidence？

**回答：**

完整正规化正文先写 artifact；进入 State 前过滤推广、登录注册、导航链接密集、图片/标记为主和低信息 block，完全重复正文去重，再按 Read focus 做确定性相关性排序，单 Source 默认最多提交三条 Evidence。过滤只生成选择视图，不改写 artifact，locator 仍指向原 block 与字符偏移。

### Q94：时间范围如何保证 resume 后不漂移？

**回答：**

run 创建时把 SearchRequest 编译为 TaskFrame，冻结 anchor date、start/end、原始表达和 provenance；resume 只读 checkpoint 中的 frame，不按恢复当天重新计算“最近 7 天”。只解析明确相对日期和 ISO range，模糊自然语言标为 unspecified，不让模型猜。

### Q95：页面发布时间未知怎么办？

**回答：**

Reader 只在 provider 返回明确可解析时间时标 `reported`，否则 `unavailable`。未知或窗口外 Evidence 可以保留用于审计，但不能把有界时间任务的 Gap 标为 resolved；CompletionPolicy 会再次校验，并将依赖这些证据的结果降级为 partial。

### Q96：当前搜索策略具体是什么？

**回答：**

当前由四个固定 Gap 和 `current_focus` 驱动。模型根据 Working Memory 中的开放维度、候选、失败 query、语义 coverage 和 completion rejection，选择 search/read/reflect；搜索后不是直接结束，而是经过 read、semantic reflect、completion feedback 再迭代。它已经形成执行闭环，但搜索质量层仍偏静态 Gap，没有动态意图树、对比查询模板和信息增益排序。

### Q97：下一阶段如何形成更强的“舆情搜索闭环”？

**回答：**

先把用户任务编译为 `OpinionAnalysisFrame`，明确 subject、事件、时间、stakeholder、aspect 和风险问题；每次查询对应结构化 `SearchIntent`，例如事实确认、主体立场、争议、反证和时间变化；read/reflect 产生 evidence-linked `OpinionSignal`；`CoverageMap` 统计 holder-target-aspect-stance-time-source 覆盖；下一步按覆盖缺口和预期信息增益选择，直到核心 coverage 达标且连续多轮新增信号趋于饱和。这个方向尚未落地，不能作为当前成果描述。

---

## 10. Completion、报告与 Web 输出

### Q98：为什么模型的 finish 不能直接终止？

**回答：**

模型容易因上下文疲劳、单方材料或输出倾向提前结束。finish 只是 proposal，Runtime 调用 Domain CompletionPolicy 得到 accept_complete、reject_and_continue、accept_partial 或 safety_stop。只有 accepted finish 才提交 FinalSynthesis；rejected finish 不改变 Domain State。

### Q99：complete 的核心门禁有哪些？

**回答：**

四个维度都不能 open；有 Source 和 Evidence；事实维度有 evidence-linked fact Claim；stakeholder、dominant/emerging、counter 各有相应语义对象；semantic coverage 至少两个 distinct Source records；contested Claim 的正反材料跨至少两个 Source；有界时间任务的 resolved Evidence 全部发布时间已知且在窗口内。

### Q100：complete、partial、failed 有何区别？

**回答：**

completed 表示领域完成门禁通过；partial 表示已有可交付 committed 成果，但因 blocked gap、证据不足、安全上限、上下文溢出或恢复耗尽而无法完整完成；failed 表示运行没有形成可接受进展或遇到 reducer/checkpoint/config 等不可继续错误。partial 不是失败的美化，而是明确保留局限。

### Q101：FinalSynthesis 为什么要进 Domain State？

**回答：**

如果最终回答只从 trace 临时拼接，resume、Web 重启和报告审计无法得到同一个结论。accepted finish 把 summary、引用 Evidence IDs 和 limitation Gap IDs 作为 FinalSynthesis committed；它随后成为 report 的 conclusion 来源。rejected finish 不写入，避免未通过门禁的文本污染权威状态。

### Q102：为什么报告不能只有 Markdown？

**回答：**

Markdown 是展示格式，Web 若从标题、列表和链接反向解析 Claim/Evidence 关系会脆弱且有损。当前先从 committed State 一次性投影 typed `SearchReportView`，再确定性渲染 Markdown；`outcome.json` 保存 typed outcome，CLI/下载使用 Markdown，Web/SSE/snapshot 使用结构化 view。

### Q103：报告如何保持引用稳定？

**回答：**

`ProvenanceIndex` 将 Evidence 解析到 Source，报告按稳定顺序分配 `S1...Sn` source reference；Claim、Position、Narrative、coverage 和 evidence appendix 都引用同一映射。Markdown link destination 还独立编码，不能因为 URL 通过 HTTP 校验就直接拼接到 Markdown。

### Q104：为什么之前真实结果会显得散乱？

**回答：**

早期输出过度展示 Evidence/Gap 审计明细，缺少先给结论再展开论证的 read model；同时当前静态 Gap 能保证结构完整，却不能保证主题层次和舆情语义足够聚合。已经通过 FinalSynthesis + SearchReportView 解决“结论缺席”和“前端解析 Markdown”问题；更深的主题聚合、动态 intent 和 signal coverage 仍是后续搜索质量层任务。

### Q105：Web 控制台在项目中是什么地位？

**回答：**

它是演示和运行入口，不是项目核心 Infra。它提供启动 offline/live run、SSE 查看进度、snapshot、取消、历史 run 恢复和报告下载；终态事实仍来自 run bundle 与 typed outcome。Web 不拥有另一套 State，也不从 Markdown重建新 run 的领域关系。

---

## 11. 测试、验证与故障故事

### Q106：测试如何分层？

**回答：**

unit 测 lifecycle、transaction、reducer、compiler 和 executor 的局部不变量；contract 测 Fake/Brave/Jina/MCP/model adapter 的同一内部协议；integration 测 loop 与工具、context 增长和 checkpoint resume；security 测注入矩阵；e2e 测 offline CLI、恢复矩阵、真实 stdio MCP、provider fallback 和 Web server。真实 provider smoke 默认 gated。

### Q107：当前最可信的验证数字是什么？

**回答：**

2026-08-27 当前代码：排除需绑定本机端口的 Web 测试为 `561 passed, 2 skipped`；Web E2E 单独在允许 loopback socket 的环境为 `11 passed`；合计 `572 passed, 2 skipped`。两个 skip 是 `RUN_LIVE_TOOL_TESTS` 和 `RUN_LIVE_AGENT_TESTS` gated smoke，不是失败。面试时最好报“570+ 自动化测试”，再按需给精确数字，避免仓库继续演进后数字过时。

### Q108：怎样测试 Reducer 幂等？

**回答：**

对同一 committed action_id 和相同 correlation 的 delta 重放，断言返回状态相等且 revision、Evidence、Claim、Gap coverage 都不增加；再用同 action_id 不同 correlation 或另一个 active step 做负向测试，必须拒绝。领域层还测试 closed Gap 的精确 replay no-op 和修改 replay 失败。

### Q109：怎样测试恢复不是“看起来能跑”？

**回答：**

Recovery Matrix 对每个持久 phase 构造 checkpoint，并断言恢复后 model、resolver、adapter、processor、reducer 的调用次数、step_id、attempt、action_id、revision 和终态。例如 OBSERVATION_READY 恢复时 adapter 调用必须为 0；ACTION_RUNNING cache hit 时 fresh adapter 调用必须为 0。

### Q110：讲一个“空 Decision”故障故事。

**回答：**

真实 run 在已有多个 committed step 后连续得到空 decision。先用小请求验证 endpoint 与 key 连通，再读取只含安全字段的 provider metadata，发现 `finish_reason=length`，推理 token 消耗了原先 2000 completion token 上限，最终结构化输出为空。修复是取消请求体里的硬 `max_tokens/max_completion_tokens`，并用 contract test 断言字段不存在；这说明空响应不一定是 API 断线，也可能是 reasoning budget 与结构化输出争用。

### Q111：讲一个 Evidence ID 故障故事。

**回答：**

模型曾把 opaque Evidence hash 改写为 `evidence-25` 顺序别名，导致 reflect 无法引用真实 State。修复不是放松 validator，而是增加 required Evidence ID catalog、在 L0 明确逐字复制规则，并在 rejection 中返回 known IDs；后续 live run 能按真实 ID 提交语义记录。这个故事体现了“严格契约 + 可修复反馈”优于 silently guess。

### Q112：讲一个安全修复故事。

**回答：**

MCP content block 最初只剥最外层 metadata，嵌套 resource 的 `_meta` 可以进入 payload；改成先整体序列化再删除后，又发现 metadata 中不可序列化对象能在过滤前打穿边界。最终采用逐字段递归投影、先过滤后 JsonValue 验证，并处理循环引用。它展示了安全边界需要考虑数据结构深度和异常路径，而不只是 happy path。

### Q113：测试数量很多，如何证明不是堆重复用例？

**回答：**

关键不是数量，而是每组测试对应一个不变量或故障窗口：生命周期合法图、phase-payload 对齐、三崩溃窗口调用次数、cache identity conflict、circuit half-open 释放、MCP atomic discovery、100-step bounded context、14 路注入、time-bounded completion 和 typed report restore。面试时应说这些证据，不只说“覆盖率高”。

---

## 12. 设计取舍、限制与演进

### Q114：项目当前最大的技术限制是什么？

**回答：**

Harness/Tool/Context 机制已经较完整，但领域搜索策略仍是固定四 Gap 驱动，缺少动态意图拆解、对比搜索、OpinionSignal 标准化、CoverageMap 和信息增益停止。因此它能保证“可靠地执行一条舆情调查”，还不能保证“对所有舆情主题都形成最优搜索路径和高质量综合分析”。

### Q115：为什么不加入向量数据库做 Memory？

**回答：**

当前是单 run、数百 Evidence 规模，核心问题是引用完整性和确定性重建，不是跨百万文档相似检索。Working Memory + bounded catalog 已满足当前消费者；引入向量库会新增 embedding 版本、召回不可确定性和第二事实源风险。未来只有 artifact 规模使结构索引不足时，才把 retrieval 当派生索引加入，并保留 State 为权威源。

### Q116：为什么 checkpoint 不算 Observability？

**回答：**

checkpoint 的 schema 由“恢复需要什么”决定，只保留当前 RunState 和 step transaction；Observability 的 schema 会由查询、聚合、留存、采样、跨 run 分析和告警决定。两者可以共享事件来源，但不能因为落了 JSON 就声称建设了 Trace/Data Platform。

### Q117：为什么轻量 Web server 没用 FastAPI？

**回答：**

当前 Web 只是本地演示控制台，端点少、无复杂中间件和 API 生态需求，标准库 server 降低依赖并避免把工程重心转向 Web 框架。若进入多人使用、认证、OpenAPI、并发和部署阶段，FastAPI 会更合适；这不是“标准库永远更好”。

### Q118：如果 provider 结果非常大怎么办？

**回答：**

HTTP response、Observation inline content 和 artifact 分别有大小限制；完整 Reader 正文内容寻址写 artifact，State 只保留引用和最多三条精选 Evidence；Context 再按 section budget 选择。大小控制分层进行，不能只依赖最后截断 prompt。

### Q119：如果两个进程同时恢复同一个 action 呢？

**回答：**

当前 JsonActionResultCache 只有进程内锁和原子文件替换，不提供跨进程 lease；两个进程可能同时看到 miss 并调用 provider。因此当前承诺是单机单执行者恢复。生产化需要 run ownership/lease、跨进程幂等存储，或依赖 provider 接受 action_id 幂等键。

### Q120：如果 circuit breaker 重启后状态丢失呢？

**回答：**

当前 circuit 是本地瞬时保护，不属于 Domain State，重启会关闭。这是有意的第一版边界；生产多 worker 场景需要共享 provider health 或集中路由，但那属于 Control Plane/Tool Gateway 的扩展，不应伪装成当前能力。

### Q121：如果让你重做一次，会优先改什么？

**回答：**

第一，先设计动态 OpinionAnalysisFrame/SearchIntent/CoverageMap，让搜索策略从固定清单升级为 coverage-driven。第二，为 artifact 增加受控 retrieval/re-read action，让压缩后的 Agent 能按 Evidence locator 主动取回局部原文。第三，把测试证据和运行指标自动生成一份版本化 capability manifest，减少文档数字漂移，但不建设完整 Eval/Observability 平台。

### Q122：如何把项目生产化？

**回答：**

先保持单 run 语义不变，把文件 checkpoint/cache 替换为带 CAS/lease 的持久存储；再增加 task ownership、worker heartbeat、credential isolation 和租户 namespace；ToolExecutor 的 provider health 迁移到共享层；artifact 用对象存储；最后增加独立 trace/eval pipeline。演进原则是保留 Decision/Observation/Delta、stable action ID 和 Reducer 不变量，而不是重写业务闭环。

---

## 13. 概念辨析速答

### Q123：Function Calling 和 Tool Runtime 有什么区别？

**回答：**

Function Calling 只规定模型如何输出结构化调用意图；Tool Runtime 还要负责工具注册、参数校验、权限、timeout、retry、fallback、缓存、错误归一化和结果关联。本项目的 Decision 甚至先于 ToolCall，只有 search/read 经 resolver 后才进入 Tool Runtime。

### Q124：MCP 和 Function Calling 有什么区别？

**回答：**

Function Calling 通常是模型 API 层的输出格式；MCP 是应用与外部工具/资源服务之间的发现和调用协议。MCP 可以为 Function Calling 提供工具 schema，但不能替代本地授权、执行策略和领域状态管理。

### Q125：Prompt Engineering 和 Context Engineering 有什么区别？

**回答：**

Prompt Engineering 主要优化一段指令怎么写；Context Engineering 决定整个窗口放什么、不放什么、顺序、预算、来源和权限。本项目的差异化在后者：L0-L3、selector、dedup、compactor、origin/trust、catalog 和 deterministic render。

### Q126：Memory 和 Context 有什么区别？

**回答：**

Memory 是可跨步骤复用的结构化认知视图，Context 是某一次模型调用实际看到的输入。一个 Memory item 不一定每轮进入 Context；Context 还包含系统规则、任务契约、tool schema 和 recent interaction。当前 Memory 只在 run 内，并由 State 派生。

### Q127：RAG 和这个 Search Agent 有什么区别？

**回答：**

典型 RAG 是一次或少数几次检索后生成；Search Agent 会根据 Observation 改变下一次 query、选择页面、反思语义覆盖并决定继续或停止。RAG 可以成为其某个检索能力，但不包含 step transaction、工具恢复、coverage-driven 决策和 completion control。

### Q128：Harness 和 Control Plane 有什么区别？

**回答：**

Harness 管单次 Agent 如何运行：生命周期、协议、state、checkpoint 和工具/context 调用；Control Plane 管大量 run 在哪里运行：队列、worker、lease、租户、调度、扩缩容。当前项目实现前者，没有把本地 loop 包装成分布式平台。

---

## 14. 面试官连续追问演练

### 追问链 A：崩溃恢复

1. **工具已经执行但进程崩了怎么办？** 先看持久 phase；ACTION_RUNNING 查 action result cache，OBSERVATION_READY 不重调工具。
2. **缓存也没写成功呢？** 可能重新请求，因此不承诺外部 exactly-once；只读 search/read 可接受，生产副作用工具需 provider 幂等键或事务 outbox。
3. **怎么防 State 重复？** committed action ledger + correlation validation + reducer replay no-op。
4. **两个进程一起恢复呢？** 当前不支持跨进程互斥；生产化增加 lease/CAS。

### 追问链 B：上下文与注入

1. **网页里写“忽略系统指令”怎么办？** 它只在 provider/tool-origin untrusted section，没有控制权限。
2. **网页内容 commit 后是不是可信了？** 不是；持久性不改变来源权威。
3. **untrusted 内容还要不要放？** 要，它可能是高价值证据；priority 与 trust 正交。
4. **长轨迹删掉了怎么审计？** Context 选择不删除 State/Artifact，Evidence locator 可回原文。

### 追问链 C：舆情质量

1. **怎样避免只找到单方观点？** 四维 Gap、counter narrative 强制、semantic source diversity completion gate。
2. **两个 URL 就真的独立吗？** 不一定；当前是 URL-level，下阶段需要 publisher/entity/转载链归并。
3. **怎样判断正负面？** 当前不以 sentiment 为中心；后续 OpinionSignal 应绑定 holder-target-aspect-stance-time-evidence。
4. **怎样决定停止搜索？** 当前按固定 Gap + Completion Gate；未来按 CoverageMap + information gain + saturation。

### 追问链 D：框架选择

1. **为什么不用 LangGraph？** Runtime 语义是交付物，需要显式拥有 transaction/recovery/context。
2. **是不是重复造轮子？** 是有意重做窄范围核心，用测试和限制换取机制理解；通用图生态不是目标。
3. **何时会改用框架？** 当业务交付优先、框架语义满足恢复要求、Runtime 不再是核心竞争力时。
4. **能迁移吗？** Domain contracts、Tool protocol 和 pure reducer 可复用；loop/checkpoint 需映射到框架节点和 saver 语义。

---

## 15. 白板图与代码导航

### 一条 step 的白板图

```text
Committed State
    -> Working Memory projector
    -> L0-L3 Context Compiler
    -> ModelClient: structured Decision
    -> structural + state-aware validation
    -> ActionResolver
    -> ACTION_RUNNING checkpoint
    -> ToolExecutor / internal action
    -> OBSERVATION_READY checkpoint
    -> ObservationProcessor -> StateDelta
    -> pure Reducer
    -> atomic commit + continuation_pending
    -> Completion evaluation / next step
```

### 重要代码入口

| 面试主题 | 主要文件 |
|---|---|
| 生命周期与协议 | `opinion_search_agent/src/opinion_search/runtime/lifecycle.py`, `protocols.py` |
| 事务与恢复分类 | `runtime/transaction.py` |
| 主循环、取消、checkpoint boundary | `runtime/loop.py`, `runtime/cancellation.py` |
| 文件 checkpoint | `runtime/checkpoint.py` |
| Tool 契约、Registry、Executor | `tools/contracts.py`, `registry.py`, `executor.py` |
| provider fallback/circuit/cache | `tools/routing.py`, `circuit.py`, `persistent_cache.py` |
| MCP | `tools/adapters/mcp.py`, `mcp_sdk.py` |
| Context/Memory | `context/compiler.py`, `selector.py`, `compactor.py`, `catalog.py`, `memory/projector.py` |
| 舆情 State/Decision/Reducer | `domain/opinion/state.py`, `decisions.py`, `processor.py`, `reducer.py` |
| 语义溯源与完成门禁 | `domain/opinion/provenance.py`, `completion.py` |
| 报告投影 | `domain/opinion/brief.py`, `app/run_bundle.py` |
| 应用装配 | `app/service.py`, `app/config.py` |
| Web 演示 | `web/server.py` |

### 最有代表性的测试入口

| 能力 | 测试文件 |
|---|---|
| 三崩溃窗口 | `tests/e2e/test_recovery_matrix.py`, `test_action_running_recovery.py` |
| checkpoint/resume | `tests/integration/test_checkpoint_resume.py` |
| Tool retry/fallback/circuit | `tests/unit/tools/test_executor.py`, `test_circuit.py`, `tests/e2e/test_tool_fallback.py` |
| MCP discovery/call/security | `tests/contract/test_mcp_adapter.py`, `test_mcp_sdk_transport.py`, `tests/e2e/test_real_mcp_tool.py` |
| 长上下文 | `tests/integration/test_context_long_trajectory.py` |
| Prompt injection | `tests/security/test_context_injection_matrix.py` |
| 舆情门禁 | `tests/unit/domain/opinion/test_completion_policy.py` |
| 结构化报告 | `tests/unit/domain/opinion/test_brief.py`, `tests/unit/app/test_run_bundle.py` |
| Web/SSE/恢复 | `tests/e2e/test_web_server.py` |

---

## 16. 最后自检清单

- 能在 30 秒和 2 分钟两个粒度介绍项目。
- 能画出 Run/Step 双生命周期和一条完整 step。
- 能解释 Decision、Action、Observation、Delta 为什么分开。
- 能逐一回答三个崩溃窗口会不会重调模型、工具、Reducer。
- 能准确区分 effectively-once state effect 与 external exactly-once。
- 能说清 Registry、Executor、Adapter 各自所有权。
- 能解释 MCP allowlist、schema pin、metadata projection 和 fail-closed。
- 能解释 State、Memory、Artifact、Context 和 Recent Interaction。
- 能说明 acquisition provenance 与 semantic provenance 的差异。
- 能背出四个舆情 Gap 和 complete 的关键门禁。
- 能主动承认 URL-level 来源多样性、启发式 token estimator、单机 cache/circuit 等限制。
- 能明确区分当前实现与 OpinionAnalysisFrame/SearchIntent/OpinionSignal/CoverageMap 演进目标。
- 至少准备三个故障故事：空 Decision、Evidence ID 别名、MCP metadata laundering。
- 不只报测试数量，要能指出恢复矩阵、长轨迹和注入矩阵分别证明什么。

