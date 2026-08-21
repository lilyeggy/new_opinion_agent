# OpinionSearch Agent Infra 深化总纲

> 文档性质：面向后续实现者的方向约束与执行索引  
> Canonical Design：[`public-opinion-search-agent-design.md`](./public-opinion-search-agent-design.md)  
> 当前实现事实：[`opinion-search-agent-implementation-memory.md`](./opinion-search-agent-implementation-memory.md)  
> 适用读者：主实现者、代码审查者、上下文较小的执行模型  
> 最后更新：2026-08-21

## 1. 深化目标

OpinionSearch 继续只深做两层：

```text
① Agent Harness / Runtime
② Tool / MCP / Context / Run-scoped Memory
```

舆情搜索是验证这些机制的真实 workload，不是把项目扩成采集平台、舆情 SaaS 或多 Agent 产品。本轮深化的目标是让项目能够在 Agent Infra 校招面试中用代码、故障实验和恢复证据回答以下问题：

1. Agent 的一次决策如何被校验、执行、提交和恢复？
2. 进程在不同生命周期边界崩溃时，哪些工作可以重放，哪些结果必须复用？
3. Tool capability、provider adapter、MCP transport 和 Agent Decision 如何解耦？
4. timeout、retry、fallback、cache、identity conflict 和 provider error 分别由谁负责？
5. Full State、Working Memory 与单轮 Context 为什么必须分离？
6. 长轨迹下如何保证 Context 有界、可解释、可恢复且不发生 trust laundering？
7. 舆情 Claim、Position、Narrative 和 Gap 如何保持 Evidence provenance？

本轮完成后的项目主张应当是：

> 一个面向公开 Web 舆情调查的可恢复单 Agent Harness；它能在不可信工具输出、有限模型上下文和外部服务失败下，保持决策、执行、状态提交与恢复语义的一致性。

## 2. 严格非目标

执行模型不得把本计划解释成以下建设任务：

- 不引入 LangGraph、CrewAI 或新的 Agent 编排框架；
- 不增加 planner/researcher/writer/verifier 多 Agent；
- 不建设 Sandbox、容器或浏览器集群；
- 不建设任务队列、分布式 worker 或 Control Plane；
- 不建设 trace ingestion、dashboard 或 Observability 平台；
- 不建设 Eval/benchmark 平台；
- 不建设向量数据库、跨 run 用户记忆或 memory service；
- 不接入微博、抖音、小红书等登录平台；
- 不为了展示而增加 Web UI；
- 不把 provider 名称、SDK 类型或 MCP 对象放进 Runtime/Domain State；
- 不把模型自报的来源类型、reflection 或 summary 提升为 trusted Runtime fact；
- 不读取、复制或导入 `archive/` 中的任何实现。

测试数据、故障注入和 Context 统计只服务当前两层的正确性，不得包装成第五层或第六层基础设施。

## 3. 三条深化主线及执行顺序

### 3.1 主线 A：Harness / Runtime 恢复一致性

执行计划：[`2026-08-21-runtime-recovery-hardening.md`](./superpowers/plans/2026-08-21-runtime-recovery-hardening.md)

核心结果：

- accepted Decision 在 ActionResolver 阶段失败时可以同 step repair，而不是直接终止；
- Tool 成功结果可以跨进程按 action identity 复用；
- `ACTION_RUNNING` crash window 的恢复语义有明确测试证据；
- cancellation 可以中断正在等待的 model/tool await，而不产生半提交 State；
- terminal run 自动形成 `run.json + report.md + artifacts/` Run Bundle；
- recovery matrix 覆盖每个 checkpoint boundary。

必须先完成本主线，因为 Tool fallback 和 MCP transport 都依赖稳定的 action identity、failure ownership 和恢复边界。

### 3.2 主线 B：Tool / MCP 可靠执行

执行计划：[`2026-08-21-tool-mcp-reliability.md`](./superpowers/plans/2026-08-21-tool-mcp-reliability.md)

核心结果：

- 使用官方 MCP Python SDK v2 实现真实 transport；
- 至少完成一个真实、本地、无需密钥的 MCP Server discovery/call smoke；
- MCP tool 仍经过本地 ToolDefinition、Registry 和 Executor；
- 一个稳定 tool capability 可以拥有有序 provider bindings；
- retry、provider fallback 和 circuit breaker 的责任不重叠；
- provider-specific 错误不泄漏 credential、响应正文或底层异常；
- Brave/Jina 的现有 live 路径保持不变。

MCP 官方 SDK v2 在 2026-08-21 是当前 stable release line；实现时使用 `mcp>=2,<3`，不得照抄 v1 的 `ClientSession` 示例。官方依据：

- [MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK Client](https://py.sdk.modelcontextprotocol.io/client/)
- [MCP transport specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

### 3.3 主线 C：Memory / Context 长轨迹正确性

执行计划：[`2026-08-21-context-memory-hardening.md`](./superpowers/plans/2026-08-21-context-memory-hardening.md)

核心结果：

- ContextSection 显式记录内容 origin，trust 由 origin 约束；
- control metadata 与可能包含模型/provider 文本的 message 分段；
- 建立确定性 ProvenanceIndex，统一 Gap/Claim/Position/Narrative 到 Evidence/Source 的关系；
- Evidence catalog 分为当前调查所需的有界 required window 与可降级 history；
- selection 使用 semantic gap relevance，而不是只使用 acquisition intent；
- CompiledContext 带确定性 hash 和按 layer/trust 的分配摘要；
- 100-step/大 Evidence 离线压力测试证明 Context 有界、resume 一致、关键 Evidence 不丢；
- prompt injection matrix 覆盖 Tool、MCP、query、reflection、failure message 和 resume。

本主线不引入 embedding、LLM summary 或向量检索。所有 Memory 与 Context 关系必须能够由 committed State 纯函数重建。

## 4. 全局不可破坏的不变量

任何子任务实现前后都必须满足：

### 4.1 Runtime 不变量

1. Model 只产生 Domain Decision，不直接创建 ToolCall。
2. ActionResolver 只把 accepted Decision 转成内部 Action。
3. ActionExecutor 不修改 Domain State。
4. ObservationProcessor 只产生 Delta。
5. Reducer 是 Domain State 唯一写入口。
6. 同一次 decision repair 保持 `step_id`，增加 `attempt`。
7. 同一次 accepted Action 的工具 retry 保持 `action_id`。
8. `OBSERVATION_READY` 或 `REDUCING` 恢复不得再次调用 Tool。
9. committed action 不得重复应用 Delta。
10. terminal State 不得继续执行。

### 4.2 Tool 不变量

1. 模型只看到稳定 ToolDefinition，不看到 API key 或 provider transport。
2. Registry 负责名称解析；Executor 负责参数校验、timeout、retry、fallback 和 success cache。
3. Adapter 只负责 provider protocol normalization。
4. Adapter 不建立自己的 Agent retry loop。
5. Provider 原始 exception、响应正文和 credential 不进入 ToolError。
6. 相同 `action_id` 只能对应一个完全相同的 ToolCall。
7. MCP annotations、description、content 和 `_meta` 都是不可信输入。
8. MCP discovery 必须先完整验证，再原子注册；半成功 registration 不允许存在。

### 4.3 Memory / Context 不变量

1. Full Domain State 是唯一权威事实。
2. Working Memory 是可删除、可重建的确定性投影。
3. Compiled Context 只服务一次 Model Decision。
4. commit/checkpoint/resume 不改变内容 trust。
5. 网页、MCP、模型 query、focus、reflection、rationale 和 provider message 始终 untrusted。
6. trusted section 只能包含 Runtime/config/user-task 确定的结构或受控文本。
7. Evidence acquisition intent 不等于 semantic coverage。
8. Context compaction 不修改 Domain State。
9. required context 放不下时 typed partial stop，不截断最终 rendered prompt。
10. 相同 committed State、Compiler 配置与 active step 必须生成字节一致的 Context 和 hash。

## 5. 小模型执行协议

每次只执行一个计划 Task，不得一次实现多个 Task。每个 Task 的固定流程：

```text
1. 完整阅读本总纲
2. 完整阅读对应子计划
3. 只读取 Task 列出的现有文件和直接依赖
4. 先写或修改测试
5. 运行定向测试，确认预期失败
6. 实现最小改动
7. 运行定向测试
8. 运行现有相关测试组
9. 输出 git diff 与测试结果供 review
10. review 通过后才进入下一 Task
```

执行模型不得：

- 自动修改 canonical 范围；
- 自动增加依赖；依赖变更必须是计划中明确列出的 Task；
- 自动重命名公共协议；
- 自动重构无关文件；
- 自动修改 `archive/`；
- 自动执行 git add、commit、push、建分支或 PR；
- 在测试失败时继续实现下一 Task；
- 把计划中的内容写成 implementation memory 已完成事实。

每个 Task 完成后提交给 reviewer 的内容必须包括：

- 修改文件清单；
- 核心契约变化；
- 新增失败模式及恢复行为；
- 定向测试命令与结果；
- 全量回归结果（只在子计划指定节点执行）；
- 未完成和未覆盖范围；
- 是否修改 checkpoint schema 或 execution profile。

### 5.1 可直接交给小模型的实现提示词

每次只替换下面的 `<PLAN_PATH>` 和 `<TASK_NUMBER>`；不要把整条主线一次性交给执行模型：

```text
你正在实现 OpinionSearch Agent 的一个受限 Agent Infra Task。

工作目录：/Users/mac/Documents/codex_project/public_opinion_agent/agent_code
总纲：docs/agent-infra-interview-deepening.md
Canonical Design：docs/public-opinion-search-agent-design.md
执行计划：<PLAN_PATH>
本次唯一任务：Task <TASK_NUMBER>

执行要求：
1. 完整阅读总纲、canonical design、执行计划，以及该 Task 列出的文件。
2. 只实现 Task <TASK_NUMBER>；不得顺手实现下一 Task。
3. 不读取、复制、导入或修改 archive/。
4. 不修改无关公共契约，不新增计划外依赖，不做架构重写。
5. 先补该 Task 明确要求的失败测试，运行并记录预期失败；再做最小实现。
6. 保持总纲中的 Runtime、Tool、Memory/Context 不变量。
7. 如发现计划与当前代码冲突，停止编码，逐项报告：文件、符号、冲突、影响、建议；不得自行改变方向。
8. 如定向测试失败，先修复本 Task；不得进入后续 Task。
9. 不执行 git add、commit、push、建分支或 PR。
10. 不把本计划写入 implementation memory，除非该 Task 已全部验证通过且计划明确要求更新事实。

完成后只输出：
- 修改文件；
- 契约和行为变化；
- 首次失败测试及失败原因；
- 最终测试命令和完整结果；
- crash/retry/trust/identity 边界中与本 Task 有关的结论；
- 未覆盖项；
- git diff。
```

### 5.2 小模型的强制停止条件

遇到以下任一情况，执行模型必须停止并等待 review：

- 计划要求的类、函数、字段或阶段在当前代码中不存在，且没有计划内等价物；
- 需要改变 `RunStatus`、`StepPhase`、Domain action space 或 checkpoint schema version；
- 需要把 provider SDK 类型放入 Runtime/Domain；
- 需要把 model/tool/provider 文本标记为 trusted；
- 需要新增真实付费 provider、数据库、队列、向量库或 Web UI；
- 同一 action identity 在 retry/fallback/resume 中无法保持；
- 测试只能通过访问公网、使用真实 API key 或降低既有断言；
- 全量回归出现与本 Task 相关的新失败；
- 实现需要修改 Task 文件清单之外超过三个生产文件，且计划没有明确说明。

### 5.3 Reviewer 的固定检查顺序

Reviewer 不先看代码风格，按下面顺序验收：

1. 范围是否只覆盖当前 Task；
2. 不变量是否仍成立；
3. 错误所有权是否放在正确层；
4. identity、retry、resume 或 trust 是否在边界处改变；
5. 负向测试是否真的经过目标生产路径；
6. 测试是否可能只验证 fixture 而没有验证 processor/reducer/compiler/transport 的真实组合；
7. checkpoint roundtrip 和重新建进程是否覆盖；
8. 是否泄漏 credential、provider body、原始异常或 untrusted prose；
9. 现有行为是否有未声明变化；
10. 证据齐全后才允许进入下一 Task。

## 6. 统一验收层级

### 6.1 Contract acceptance

- Pydantic/Protocol 契约可序列化或明确标注只存在于 app composition；
- `extra="forbid"`、frozen 和 identity 规则保持一致；
- 未知字段、错误类型、identity conflict 有负向测试；
- Domain/Runtime 不导入 provider SDK。

### 6.2 Component acceptance

- 每个新增组件至少有成功、边界、失败和幂等测试；
- clock、sleep、filesystem path、transport 使用可注入依赖；
- 测试不访问公网；
- 测试不依赖真实 API key。

### 6.3 Recovery acceptance

- 对每个新增持久化点说明 crash-before 与 crash-after；
- 对每个可重试操作说明 identity 是否保持；
- 对每个不可恢复错误说明 terminal 状态；
- resume 后不得重复已持久化成功结果。

### 6.4 Final acceptance

每份子计划结束时执行：

```bash
cd opinion_search_agent
/Users/mac/miniconda3/bin/python -m ruff check src tests
/Users/mac/miniconda3/bin/python -m pytest -q -W error
/Users/mac/miniconda3/bin/python -m compileall -q src tests
```

并执行对应的离线 CLI、resume 或 MCP smoke。验证通过后，才把事实追加到 `docs/opinion-search-agent-implementation-memory.md`。

## 7. 面试验收问题

三个子计划全部完成后，主实现者必须能够脱离代码回答：

### Harness / Runtime

- 为什么 Decision retry 和 Tool retry 不是同一种 retry？
- 为什么 ActionResolver failure 可以回到 deciding，而 Reducer invariant 必须 fail closed？
- `ACTION_RUNNING` checkpoint 为什么存在重复外部调用窗口？本项目如何缩小该窗口？
- exactly-once 为什么通常无法由 Agent Runtime 单方面保证？本项目实际保证到什么程度？
- crash 在七个 StepPhase 各自如何恢复？

### Tool / MCP

- 为什么 provider fallback 属于 Executor，而不是模型或 Adapter？
- 同 provider retry 与跨 provider fallback 的计数和 identity 如何定义？
- MCP discovery 为什么必须原子注册？
- MCP stdio 与 Streamable HTTP 的生命周期和安全边界有什么不同？
- MCP annotations、structured content、content 和 `_meta` 分别应该如何处理？

### Memory / Context

- Full State、Working Memory、Context 的一致性来源分别是什么？
- 为什么 semantic Gap relevance 不能只从 `acquired_for_gap_id` 推导？
- required Evidence catalog 为什么必须有界？超过窗口后如何降级？
- trust 与 priority 为什么正交？
- checkpoint 为什么不能把模型文本升级为 trusted？
- 如何证明 100-step run 的 Context 不随历史线性增长？

## 8. 完成定义

“深化完成”不以新增文件数量判断，而以以下证据判断：

1. 一个 crash-recovery demo 能证明 action result 跨进程复用；
2. 一个真实 MCP demo 能证明 discovery、schema、registration、execution 全链路；
3. 一个 provider-chain 测试能证明 retry/fallback/circuit responsibility；
4. 一个 100-step Context stress test 能证明有界和确定性；
5. 一个 injection matrix 能证明 commit/resume 不洗白外部或模型文本；
6. 一个 live OpinionSearch run 自动生成完整 Run Bundle；
7. 所有现有测试继续通过；
8. 最终 reviewer 无残余 Critical/Important。
