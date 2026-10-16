# Agent Harness 面试分层学习地图

> 目的：把 OpinionSearch 的 Harness 拆成可独立掌握、可独立被面试考察的层，给出每层的代码落点、必须能讲清的机制、面试追问和验证证据。
> 读者：主实现者（面试主讲人）。
> 边界：只覆盖 Harness / Runtime 与 Tool / Context / Memory；不扩成平台建设清单。
>
> 与其他文档的关系：
>
> | 文档 | 定位 | 本文与它的关系 |
> |---|---|---|
> | **`interview/`（面试资料集）** | **面试导向的完整材料：开场稿 / 架构 / 逐层机制 / 取舍 / 数据 / 故障复盘 / 问答库 / 红线 / 代码地图** | **本文是它的"层定义"部分；`interview/03` 是本文的展开版**（层不变，补齐机制细节、答法与追问链）。面试准备请以 `interview/` 为主 |
> | `public-opinion-search-agent-design.md` | 唯一 canonical 设计 | 本文是它的**学习切片**，不产生新设计 |
> | `agent-infra-interview-deepening.md` | 三层不变量与面试验收问题总纲 | 本文把它的 §4 不变量、§7 问题**分配到层** |
> | `opinion-agent-harness-learning-outline.md` | benchmark / 消融导向的学习单元任务书 | 本文是**面试导向**的分层地图，映射见 §5 |
> | `opinion-search-agent-implementation-memory.md` | 实现事实与验证证据 | 本文每层的「验证证据」从它和测试中取 |
> | `agent-infra-learning-map.md` | OS / 运行时基础实验（`agent_infra_lab/`） | 独立线，服务于"下一个执行边界"，不属于本文七层 |

## 1. 分层依据

按两条标准切，不按文件目录切：

1. **依赖顺序**：下层不依赖上层；讲不清下层就无法讲清上层。
2. **可独立考察**：一层对应面试官能单独追问、且答错会立刻暴露的一组机制。

因此层与文件不是一一对应：`runtime/` 一个目录横跨 L1、L2、L3 三层，因为它们回答的是三个不同问题。

## 2. 分层总览

| 层 | 回答什么问题 | 核心模块 | 优先级 |
|---|---|---|---|
| **L0 坐标层** | 这个项目是什么、边界在哪、为什么不那样做 | README、CLAUDE.md、canonical design §1–§4 | 先建立，之后反复回扣 |
| **L1 Loop 与生命周期** | 一次 run 怎么走完？崩在任一阶段从哪继续？ | `runtime/loop.py`、`lifecycle.py`、`cancellation.py` | 最高 |
| **L2 Step 事务与恢复** | 谁有权写状态？崩溃后什么复用、什么重放？ | `runtime/transaction.py`、`checkpoint.py`、`tools/persistent_cache.py`、`app/run_bundle.py` | 最高 |
| **L3 状态与 Reducer** | 权威状态如何演进且不被污染？ | `runtime/protocols.py`、`domain/opinion/{state,reducer}.py`、`domain/investigation/{models.py,engine.reduce_state}` | 最高 |
| **L4 决策协议与校验** | 模型的意图如何变成可执行动作？在哪一层被拦？ | `runtime/errors.py`、`domain/opinion/{decisions,actions,action_resolver}.py`、`domain/investigation/{models.py,engine.Validator/Resolver}` | 高 |
| **L5 上下文与记忆** | 模型每一步看见什么？为什么这些内容可信？ | 共享：`context/{models,compactor}.py`；opinion 专用：`context/{compiler,selector,catalog}.py`、`memory/*`、`domain/opinion/provenance.py`；investigation 专用：`investigation/context.py` | 高 |
| **L6 工具执行** | 外部调用失败时，重试与责任归谁？ | `tools/registry.py`、`executor.py`、`circuit.py`、`cache.py`、`persistent_cache.py` | 高 |
| **L7 完成控制与失败恢复** | 什么时候允许结束？出错如何降级？ | `runtime/completion.py`、`errors.py`、`domain/opinion/completion.py`、`domain/investigation/engine.completion`、`investigation/service.ConsolidationValidator` | 中高 |
| **应用层 · 领域包** | 舆情规则怎么长在 Runtime 上而不侵入它？ | `domain/opinion/*`、`domain/investigation/*`、`investigation/*` | 中（Harness 的验证载体） |

三个板块：

- **板块 A · Runtime 骨架** = L1 + L2 + L3。这是"Runtime 本体"，与领域无关。
- **板块 B · 能力接口** = L4 + L5 + L6。这是 Runtime 对接模型、上下文、外部世界的三个接口。
- **板块 C · 策略收束** = L7 + 应用层。决定"何时停、停得对不对、规则长在哪"。

### 2.1 必须先知道的一个代码事实：两个域不对称

这是核对代码后最重要的一条，**讲错会立刻被追问穿**：

| | `domain/opinion`（CLI + 离线演示） | `domain/investigation`（Web 生产路径） |
|---|---|---|
| 文件数 | 10 个独立模块 | **只有 2 个**：`engine.py` + `models.py` |
| 状态 / Reducer | `state.py` + `reducer.py` | `models.py` 的 `State` + `engine.reduce_state` |
| 决策 / 动作 / 解析 | `decisions.py` / `actions.py` / `action_resolver.py` | 全在 `models.py`（Decision 联合类型）+ `engine.Resolver` |
| 校验 / 处理 / 完成 | `decisions.OpinionSearchDecisionValidator`、`processor.py`、`completion.py` | `engine.Validator`、`engine.Processor`、`engine.completion` |
| 上下文编译 | `context/compiler.py` 的 `OpinionContextCompiler`（**硬类型检查 `OpinionSearchState`**） | `investigation/context.py` 的 `Compiler`（自己内联组装 section） |
| Working Memory | 有：`memory/projector.py` → `WorkingMemory` | **没有这个对象** |
| Provenance | `domain/opinion/provenance.py` | 无（用 `evidence → version_id → source` 直接映射） |

由此推出的三条结论：

1. **`context/` 与 `memory/` 不是同一个栈。** 两个域真正共享的只有 `context/models.py`（`ContextSection` / `ContextBudget` / `CompiledContext` / `TrustBoundary` / `render_sections` / `HeuristicTokenEstimator`）和 `context/compactor.py`。`context/compiler.py`、`selector.py`、`catalog.py` 与整个 `memory/` 都只被 `app/service.py`（opinion 路径）使用。
2. **"Context Compiler 是第二层通用能力"只在契约层成立。** 实际上有两个 compiler：一个在 `context/`，一个在 `investigation/`。共享的是 section 模型与压缩算法，不是编译逻辑。
3. **`WorkingMemory` 是 opinion 域的实现细节，不是 Runtime 概念。** 面试时不要说"我们的 Working Memory 层服务于两条路径"。

**面试追问**：为什么 investigation 域不复用 `OpinionContextCompiler`？——答：它硬类型检查 `OpinionSearchState`；而 investigation 的上下文要携带 issues / findings / page_plan / next_action_constraint / consolidate 指令，形状不同。复用 `ContextSection` 模型与 compactor 已经拿到共享收益，强行统一 compiler 会让两边都变复杂。

## 3. 逐层详解

### L0 · 坐标层

**必须能讲清**

- 一句话定义：面向公开 Web 舆情调查的**可恢复单 Agent Harness**。
- 只深做两层：① Agent Harness / Runtime；② Tool / MCP / Context / Run-scoped Memory。
- 五个明确非目标：Environment/Sandbox、Control Plane、Trace/Observability、Eval/Feedback、Model Serving。
- 三条取舍叙事：为什么不用 LangGraph、为什么不做多 Agent、为什么不做 Eval 平台。

**代码落点**：`README.md`、`CLAUDE.md`、`docs/public-opinion-search-agent-design.md` §1–§4。

**面试追问**

- 你说"只做两层"，那第 5、6 层你为什么不建？——答：不是没能力，是**边界纪律**；Eval 平台和 Control Plane 会让项目从"讲得清取舍"变成"什么都做了一点"。
- 为什么不用 LangGraph？——答：学习与工程价值就在"状态何时更新、工具调用如何恢复、step 如何提交、context 如何重建、finish 如何验收"；图执行会把这些藏起来。
- 多 Agent 你试过吗？——**这题必须答"试过并砍掉"**，见下。

**验证证据**：`opinion_search_agent/archive/harness-pipeline/README.md`（多角色流水线归档决策记录，含三条否决理由）；`docs/opinionsearch-current-vs-multi-agent-architecture.md`（提案与最终结论）。

> 这一层是**面试开场 3 分钟**的内容。讲完要能让面试官知道：你知道自己没做什么，以及为什么。

---

### L1 · Loop 与生命周期

**必须能讲清**

- `RunStatus` 六态：`created → running → completed | partial | failed | cancelled`；终态集合 `_TERMINAL_RUN_STATUSES`。
- `StepPhase` 七阶段：`opened → deciding → decision_accepted → action_running → observation_ready → reducing → committed`。
- `classify_resume(state)` 是 `run()` 唯一的分发依据：**首次执行与崩溃恢复走同一条代码路径**，resume 不是补丁而是主路径。
- 每阶段边界 `checkpoint.save()` 后触发 `LoopHook.after_checkpoint(boundary, state)`——Web 端靠这个 hook 推 SSE，Runtime 与 Domain 零改动。
- 取消语义：`_await_operation` 用 `asyncio.wait(FIRST_COMPLETED)` 让"操作"与"取消信号"竞速；取消若在 Observation 落盘**之后**到达，该步仍会被 reduce 并提交一次，不丢弃已观察结果。

**代码落点**：`runtime/loop.py`（`AgentLoop.run`、`CheckpointBoundary`、`_await_operation`）、`runtime/lifecycle.py`、`runtime/cancellation.py`。

**面试追问**

- crash 在七个 StepPhase 各自如何恢复？——逐阶段答，重点讲 `ACTION_RUNNING` 与 `OBSERVATION_READY`。
- 为什么 `run()` 是 `while True` 而不是顺序流程？——答：把"恢复到哪"变成数据问题而不是控制流问题。
- 取消为什么不能简单 `task.cancel()`？——答：要区分"取消赢得竞速"与"取消到达时该步已观察完毕"。

**验证证据**：`tests/unit/runtime/test_lifecycle.py`、`test_cancellation.py`、`tests/e2e/test_recovery_matrix.py`。

---

### L2 · Step 事务与恢复

**必须能讲清**

- 单写者提交链：`Decision → Validator → ActionResolver → Executor → Observation → Processor(Delta) → Reducer → Checkpoint`。
- `StepRecord` 用 pydantic validator 强制"**阶段 ↔ 载荷**"一致：某阶段必须恰好携带 decision/action/observation 中的哪几个，且 `run_id / step_id / attempt` 必须与 step 对齐。反序列化被篡改或半写的 checkpoint 会直接失败。
- checkpoint 原子写：临时文件 + `fsync` + `os.replace`；`schema_version`（当前 4）与 `execution_profile` 不匹配直接拒载。
- **成功结果复用**：工具成功结果按 action identity 落盘（`action_results/`）。进程在"缓存已写、observation 未落盘"之间死掉时，resume 复用而不重复调用 provider。
- Run Bundle：终态 run 自动落 `run.json + report.md + action_results/ + artifacts/`。

**面试追问**

- `exactly-once` 为什么通常无法由 Agent Runtime 单方面保证？本项目实际保证到什么程度？——答：这是**at-most-once 复用已持久化成功**，不是通用 exactly-once；舆情工具只读，可安全重试。
- `ACTION_RUNNING` 为什么存在重复外部调用窗口？如何缩小？——答：窗口在"调用返回"与"observation 落盘"之间；靠 action identity + 成功缓存把窗口压到"仅当崩溃发生在缓存写入之前"。
- 为什么 `execution_profile` 要进 checkpoint？——答：换模型或换工具组合后重放同一 action 语义已变，必须在动作重放前拒绝。

**代码落点**：`runtime/transaction.py`、`runtime/checkpoint.py`、`tools/persistent_cache.py`、`app/run_bundle.py`。

**验证证据**：`tests/unit/runtime/test_checkpoint.py`、`tests/unit/runtime/test_transaction.py`、`tests/integration/test_checkpoint_resume.py`、`tests/e2e/test_action_running_recovery.py`。

---

### L3 · 状态与 Reducer

**必须能讲清**

- 四段信封：`DecisionEnvelope` / `ActionRequest` / `ObservationEnvelope` / `StateDelta`，各自携带关联信息，不把领域 action 泛化成任意 JSON。
- **Reducer 是权威状态的唯一写入口**，是纯函数：`new_state = reduce(old_state, accepted_delta)`，要么返回新 State（`revision + 1`），要么抛不变量错误 fail closed。
- 不变量举例：证据必须引用已知 source；claim 不能同时支持又反驳；candidate 必须引用已知 gap；`next_step_index == len(committed_steps) + 1`；终态 run 不得有 active_step。
- 权威状态最小化：`PagePlan / CoverageMatrix / Metric / ContentDocument` 等是**派生视图**，可持久化用于诊断，但不得成为第二事实源。

**面试追问**

- 为什么 Reducer 必须是纯函数？——答：可重放、可测试、resume 后结果一致；副作用会让恢复语义不可判定。
- 派生视图为什么不能写回权威状态？——答：一旦能写回就有两个事实源，渲染层失效会污染领域事实。
- 为什么把 Position/Demand 表达成 Finding 字段而不是权威实体？——答：先按最小权威状态实现，等真实需要稳定主体 ID 再升级。**注意**：这条只对 `domain/investigation` 成立；`domain/opinion` 按 canonical design §8.2 保留 `Claim / StakeholderPosition / Narrative` 为权威对象。

**代码落点**：`runtime/protocols.py`（`StepRecord` validator）；opinion 域 `domain/opinion/state.py` + `reducer.py`；investigation 域 `domain/investigation/models.py`（`State`）+ `engine.reduce_state`。**`runtime/` 下没有 `reducer.py`**——Reducer 属于领域层。

**验证证据**：`tests/unit/runtime/test_protocols.py`、`tests/unit/domain/opinion/test_state.py`、`test_reducer.py`、`tests/investigation/test_evidence_integrity.py`。

---

### L4 · 决策协议与校验

**必须能讲清**

- **决策 ≠ 动作**：`Decision` 是模型的语义意图（`search / read / reflect / finish`，investigation 域另有 `retrieve / review`）；`Action` 是 Runtime 的可执行单元（`ToolAction` 带 `tool_name` + `arguments`，或 `ReflectAction` / `FinishAction` 这类无副作用动作）。
- `ActionResolver` 负责翻译与加固：拼 offset、注入 `-site:` 排除、按 include_domains 追加 `site:`、校验 query 长度、给 review 决策打包 `review_context`。
- **三层校验**：结构校验（pydantic `extra="forbid"`）→ state-aware 校验（ID 是否存在、是否重复行动、状态是否允许）→ completion 校验。
- **决策失败可修复**：`retry_decision`（同 `step_id`，`attempt + 1`）用于模型错误；`repair_accepted_decision` 用于"已 accept 但 ActionResolver 拒绝"——**回退到 DECIDING 而不终止 run**，因为此时尚无外部副作用。`REPEATED_ACTION` 直接 partial stop。

**面试追问**

- 为什么 Decision retry 与 Tool retry 不是同一种 retry？——答：Decision retry 换的是**语义**（attempt 变），Tool retry 保的是**同一 action 身份**（action_id 不变）；前者是模型再想一次，后者是物理重试。
- 为什么 ActionResolver failure 可以回到 deciding，而 Reducer invariant 必须 fail closed？——答：前者未产生外部副作用、可安全重试；后者意味着已提交状态内部矛盾，继续跑会污染更多事实。
- 给出"合法但无帮助""格式错误""引用不存在证据"三个决策，各自在哪一层被处理？——结构层 / state-aware 层 / reducer 层。

**代码落点**：`runtime/errors.py`（`RuntimeFailureKind` + `RecoveryDirective`）；opinion 域 `domain/opinion/{decisions,actions,action_resolver}.py`；investigation 域 `domain/investigation/models.py`（`Decision` 联合类型）+ `engine.Validator` / `engine.Resolver`。**注意后者没有独立的 decisions/actions/resolver 文件**，见 §2.1。

**验证证据**：`tests/unit/domain/opinion/test_decisions.py`、`test_action_resolver.py`、`tests/unit/runtime/test_errors.py`、`tests/e2e/test_recovery_matrix.py`。

---

### L5 · 上下文与记忆

**必须能讲清**

- **共享部分**：`ContextSection` / `ContextBudget` / `CompiledContext` / `TrustBoundary` / `ContextLayer` / `CompactionMode` / `render_sections` / `HeuristicTokenEstimator` 与 `compact_context_sections`——**只有这些是两个域共用的**。
- **opinion 域的权威梯度**：`State`（唯一权威，落盘）→ `WorkingMemory`（`project_working_memory` 派生投影，可重建、不落盘）→ `CompiledContext`（单次模型输入，带 `content_sha256`，不落盘）。**investigation 域没有 WorkingMemory 这一层**，见 §2.1。
- 编译四段流水线：`collect → select → compact → render`。共享的是 compact 这一段与 section 模型；collect/select 两个域各自实现。
- **信任分层**：每个 `ContextSection` 带 `origin` + `trust`；`origin ∈ {model, tool, provider}` **永远**只能是 untrusted，pydantic validator 直接拒绝非法组合。commit / checkpoint / resume 只赋予持久性，不洗白信任。
- **有界与降级**：`required ∪ NEVER` 锁定段超预算 → `RequiredContextOverflow` → partial 收尾（不静默截断）；可选段按"untrusted 优先、L3 优先、低 priority 优先"先 TRUNCATE 再 DROP。
- Evidence ID catalog 分为必需当前窗口 + 可降级历史块；trusted coverage cell 只采样真实语义 Gap 链接，`acquired_for_gap_id` 不等于 semantic coverage。**catalog 是 opinion 域专用**（`context/catalog.py` 依赖 `memory/models.py`）。

**面试追问**

- Full State / Working Memory / Context 的一致性来源分别是什么？——分别：Reducer 提交 / State 纯函数投影 / 编译配置 + active step 决定。**补一句**：Working Memory 只在 opinion 路径存在。
- trust 与 priority 为什么正交？——答：priority 决定"预算紧张时先丢谁"，trust 决定"能不能当指令"；一个 untrusted 高优先级证据仍然不能被当成指令。
- 如何证明 100 步 run 的 Context 不随历史线性增长？——答：压力测试 + 必需窗口有界 + 每段 token 测量。
- required context 放不下时为什么不是截断？——答：截断会让"必需"名不副实，宁可 typed partial stop。
- 两个域为什么不共用同一个 Compiler？——见 §2.1 的面试追问。

**代码落点**：共享 `context/models.py`、`context/compactor.py`；opinion 专用 `context/compiler.py`（`OpinionContextCompiler`）、`selector.py`、`catalog.py`、`memory/models.py`、`memory/projector.py`、`domain/opinion/provenance.py`；investigation 专用 `investigation/context.py`（`Compiler` + `structured_context`）。

**验证证据**：`tests/unit/context/*`、`tests/unit/memory/test_projector.py`、`tests/integration/test_context_long_trajectory.py`、`test_loop_context_growth.py`、`tests/security/test_context_injection_matrix.py`、`tests/investigation/test_context_integrity.py`。

---

### L6 · 工具执行

**必须能讲清**

- **逻辑工具 vs 物理 provider**：模型只看到稳定 `ToolDefinition`（name / description / input_schema），看不到 API key、provider id 或 transport。
- `ToolRegistry` 负责名称解析与 provider 绑定；`ToolExecutor` 独占**参数校验、成功缓存、同 provider 重试、跨 provider 回退、超时、熔断、安全错误构造**。
- **identity 规则**：`ToolInvocation.attempt` 是全局物理计数；`action_id` 跨 retry 与 fallback 保持恒定；`asyncio.CancelledError` 永远向上传播。
- 错误三分类：可重试（timeout / rate_limited / server_error）→ 立即停止（invalid_arguments / unknown_tool / cancelled）→ 跨 provider 回退（auth / permission / not_found / unreadable 等）。
- 熔断：per tool/provider 内存态，只有"中毒类"错误计入；auth/permission 不算，因为那是配置问题不是供应商健康度。
- MCP：显式 allowlist + 本地描述与 schema SHA-256 固定远端契约；discovery 必须**全部匹配后原子注册**。

**面试追问**

- 为什么 provider fallback 属于 Executor 而不是模型或 Adapter？——答：模型不该知道 provider 存在；Adapter 只做协议归一化，不该有自己的 Agent 重试循环。
- 同 provider retry 与跨 provider fallback 的计数与 identity 如何定义？——全局 attempt 递增，action_id 不变。
- 为什么 auth 失败不触发熔断？——答：配置错误必须下一次仍然可见，不能被熔断器永久掩盖。
- MCP discovery 为什么必须原子注册？——答：半成功注册会让 Registry 处于"部分工具可信"的中间态。

**代码落点**：`tools/contracts.py`、`registry.py`、`routing.py`、`executor.py`、`circuit.py`、`cache.py`、`persistent_cache.py`、`capabilities/web.py`、`adapters/*`。

**验证证据**：`tests/unit/tools/*`、`tests/e2e/test_tool_fallback.py`、`tests/contract/test_mcp_adapter.py`、`test_mcp_sdk_transport.py`、`tests/e2e/test_real_mcp_tool.py`。

---

### L7 · 完成控制与失败恢复

**必须能讲清**

- **finish 只是一个 proposal**。`CompletionPolicy` 独立评估，返回四种 disposition：`accept_complete` → `completed`；`reject_and_continue` → `running`（继续循环）；`accept_partial` → `partial`；`safety_stop` → `partial`。
- `RecoveryDirective` 五类：`retry_attempt` / `feedback_and_continue` / `partial_stop` / `fail_run` / `cancel_run`，由 `RuntimeFailureKind` 映射。
- 真实闸门（investigation 域）：必答问题仍 open → 拒绝 finish，且拒绝理由必须**点名**每个问题下未处置的证据、未读候选与三条合法出路；`response = not_found` 需要 scoped 回应搜索已完成且无读取错误（**provider_failure 不能解释成 not_found**）。
- **发布保留段**：`ConsolidationValidator` 在模型调用用掉 2/3 后锁定动作空间——先 review 全部 active finding，再 finish。

**面试追问**

- 为什么 finish 不由模型决定？——答：模型有"想收工"的激励；完成判定必须是程序对**已提交状态**的独立判断。
- 为什么拒绝理由要写这么长？——答：实测教训，见下。
- 为什么在 2/3 处设保留段？——答：保证"有限预算内一定有经过审查的产出"，而不是耗尽后留下大量 unreviewed。

**代码落点**：`runtime/completion.py`、`runtime/errors.py`、`domain/opinion/completion.py`、`domain/investigation/engine.completion`、`investigation/service.ConsolidationValidator`。

**验证证据**：`tests/unit/runtime/test_completion.py`、`tests/unit/domain/opinion/test_completion_policy.py`、`tests/investigation/test_finish_guidance.py`。

> **这条最好用的失败故事**：原始拒绝理由只有一句 "Required investigation questions remain open."，模型没有任何可执行的下一步，于是反复重试 finish——一次真实 live run 里 completion gate 拒绝了 `finish` **18 次**直到步数耗尽。修复是让闸门对每个 open 问题输出"未处置证据数（含 ID 与摘录预览）+ 未读候选数 + 三条合法出路"。回归测试见 `tests/investigation/test_finish_guidance.py`。
>
> **口径提醒**：修复后"同题 live 能达到什么效果"没有可引用的对照数字，不要编造改进幅度。

---

### 应用层 · 领域包

**必须能讲清**

- 两套 domain 共用同一个 `AgentLoop`，靠构造函数注入。精确计数：`loop.py` 内声明 **7 个 `Protocol`**（`ContextCompiler` / `DecisionValidator` / `ActionResolver` / `ActionExecutor` / `ObservationProcessor` / `IdFactory` / `LoopHook`），另加 **4 个外部契约**（`ModelClient` / `CheckpointStore` / `CompletionEvaluator` / `CancellationSignal`）；`reducer` 是普通 `Callable`，**不是 Protocol**。说"十个协议接口"会被追问口径。
- `domain/opinion`（CLI + 离线演示）：4 动作，gap / claim / narrative / stakeholder position。
- `domain/investigation`（Web 生产路径）：6 动作（+ `retrieve` / `review`），issue / finding / review / PagePlan。
- **哪些规则必须在 domain**：时间窗口校验、`not_found` 的 scoped 搜索前置条件、语义维度覆盖（resolve 事实维度必须有一条 FACT claim）、finding 与 review hash 绑定。这些一旦写进 Runtime 就会让 Runtime 变成"舆情专用"。

**面试追问**

- 为什么有两套 domain？——答：这是"Runtime 领域无关"的**可验证证据**；但作为长期维护项目迟早要收敛，这一点要主动说。
- 固定四 Gap 的偏差是什么？——答：提供最小全局结构但可能固化调查视角；反叙事缺失时宁可标不足也不强行生成。
- 一次调查为什么是 partial？——用实测数字回答（见 §4 阶段 3）。

**验证证据**：`tests/investigation/*`（含 `test_quality_baseline.py`、`test_evidence_integrity.py`、`test_replay_harness.py`）、`tests/unit/domain/opinion/*`。

## 4. 三阶段推进与完成标准

### 阶段 1 · 骨架（L0 + L1 + L2 + L3）

**交付标准**：能白板画出 `RunStatus` 六态与 `StepPhase` 七阶段；说出每个 checkpoint boundary 崩溃后的恢复动作，以及哪些已持久化结果会被复用而不是重放。

**做法**：只读代码 + 跑现有离线测试。先预测、再运行、再解释。**不要先读实现再倒推设计**。

**自检**：能否在 5 分钟内画出从 `POST /api/runs` 到终态的完整路径，并在任一箭头处标出"此刻崩溃会怎样"。

### 阶段 2 · 接口（L4 + L5 + L6）

**交付标准**：说清"合法但无用""引用不存在证据""provider 超时"三类输入分别在哪一层被拦、被修复或被降级；并解释 Decision retry 与 Tool retry 为什么不是同一种重试。

**做法**：对每层做一次"改变一个变量"的预测实验（改预算、改 provider 顺序、改 focus），观察 rendered context / observation / delta 的变化。

**自检**：能否给出一条从网页文本到最终模型输入的完整数据链，并在每一跳说明 trust 是否变化。

### 阶段 3 · 策略（L7 + 应用层）

**交付标准**：用实测数字解释一次 partial 的成因、指出决定性规则，并给出至少一条可验证的改进方向。

**可引用的实测数字**（来源：`docs/舆情agent-质量三数字-D4-2026-09-21.html`、`docs/舆情agent-实测检验报告-2026-09-23.html`、README）：

| 维度 | 数字 |
|---|---|
| 检索召回 | 60%（6/10 人工标注必中清单，逐项独立搜索验证） |
| 忠实性 | 71% 完全支持（10/14）、100% 零虚构 |
| 对抗回放 | 7 篇真实 + 3 篇埋点文档，2/3 达到预期（更正被采纳 ✓、反方稿已读已摘但零 finding 引用 ✗、错误数字未传播 ✓） |
| 一次真实 run | 60 步、17 搜、17 读、14 findings、92 处引用；review 6 supported / 8 partial |
| finish 闸门 | 被拒 18 次后诚实 partial |

**已知限制必须主动说**：单一搜索引擎（Brave）；旧 opinion 路径固定 5 条结果，时间窗口与语言已透传为 `freshness`/`search_lang`，域名约束在候选入库时后过滤，工作台路径另以 `site:` 前置域名，`country` 未使用；证据摘录选择是召回瓶颈、模型不会把证据不足的问题收成 `not_found`、数字类主张只做 provenance 检查未做冲突交叉核对。

## 5. 与既有文档的映射

`opinion-agent-harness-learning-outline.md` 的模块 ↔ 本文层：

| 该文档模块 | 本文层 | 说明 |
|---|---|---|
| 模块 0 构建视角 | L0 + L1 | 本文更强调"边界与取舍叙事" |
| 模块 1 任务契约与成功定义 | 应用层 + L7 | |
| 模块 2 动作空间与模型接口 | L4 | |
| 模块 3 工具契约与执行可靠性 | L6 | |
| 模块 4 从网页到可追溯证据 | L3 + L5 | |
| 模块 5 上下文工程与任务内记忆 | L5 | 本文的 L5 与之等价 |
| 模块 6 不可信内容与安全边界 | L5 | 本文归入 L5 的信任分层 |
| 模块 7 完成策略与报告输出 | L7 | |
| 模块 8 可解释轨迹 | L2 | |
| 模块 9–10 benchmark 与消融 | 无对应 | 该线未执行（项目封存），本文不含 |

`agent-infra-interview-deepening.md` §7 的 16 个面试验收问题，已按层重新分配到本文 §3 各层的「面试追问」中。

## 6. 表述红线

以下说法**不能说**，因为与代码事实不符：

- "我们做了多 Agent 编排"——多角色流水线已归档；正确说法是"实现过、评估后砍掉，理由是违反单 Runtime 原则"。
- "保证 exactly-once"——实际是 at-most-once 复用已持久化成功，且依赖"舆情工具只读"这一前提。
- "trusted/untrusted 是模型 API 层面的权限隔离"——实际只是上下文里的来源标签与结构约束。
- "有长期记忆 / 向量检索"——当前只有 run-scoped 投影。
- "完成了 benchmark 评测"——benchmark 未执行；有的是人工标注的领域质量检验。
- "100 步是真实模型自主跑出来的"——长轨迹是构造状态的压力测试。
- "报告质量分 X 分"——只有召回率、忠实性、对抗回放三组人工检验数字，不是综合质量分。
- "注入矩阵证明抗注入成功"——它证明的是来源与信任标签保持、边界转义等**结构性质**。
- "两套 domain 共用同一套 Context Compiler / Working Memory"——错。共享的只有 `context/models.py` 与 `compactor.py`；两个域各有一个 compiler，Working Memory 只存在于 opinion 域。见 §2.1。
- "Reducer 在 runtime/ 里"——错。`runtime/` 没有 `reducer.py`；Reducer 是领域职责，因为状态不变量属于领域语义。
- "Context 编译流水线只有一条"——错。`collect → select → compact → render` 是共享的**描述**，但 collect/select 两个域各自实现；共享的只有 compact 与 section 模型。
- "Web 主页面是那个单问题 demo 控制台"——错。`/` 是调查工作台（investigation 域），旧 console 在 `/legacy`。
