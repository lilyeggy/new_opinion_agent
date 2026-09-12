# 舆情 Agent Harness 深入学习大纲与扩写任务书

日期：2026-09-08。

本文用途：交给另一个能够读取仓库的 AI，扩写成系统、具体、可实践的学习文档。本文是学习路线与代码导航，不是已经完成的 benchmark 方案，也不是功能开发清单。

## 1. 学习背景与最终目标

学习者已经较深入学习 Agent Loop、步骤事务、生命周期和恢复流程。后续不再把逐行复述 Loop 作为主体，而是研究：如何围绕舆情调查任务构建 Harness，以及这些设计如何影响模型行为和任务结果。

项目范围是公开 Web 舆情调查：事实基线、主体立场、叙事与反叙事、争议、时间范围及证据出处。不要将其解释成已经具备全网舆情监测、情绪比例统计、传播量估计或代表性抽样能力。

最终目标：在真实外部 benchmark 上运行当前 Agent，识别它覆盖的能力；同时用少量舆情调查案例检查领域质量，形成基线、失败分析与至少一个 Harness 机制的受控对比。

明确不作为主线：通用 Agent 平台、多租户、GPU 调度、分布式执行、完整权限系统、多 Agent 编排、训练或 RL。这些都不是本轮学习的完成条件。

核心问题：固定模型和任务时，任务约束、工具契约、观察表示、上下文选择、证据关系及完成规则，怎样改善调查结果？

## 2. 给扩写 AI 的要求

1. 先读代码，再解释设计。本文的文件路径是导航，实际调用关系、默认配置和测试断言以当前 checkout 为准；不要仅凭文件名推断实现。
2. 每章统一包含：要解决的问题 → 舆情示例 → 输入/输出与数据结构 → 实际调用链 → 设计取舍 → 已有测试证明什么 → 尚未证明什么 → 预测练习 → 观察方法 → 面试追问。
3. 将内容标为“当前实现”“当前测试证据”“历史运行记录”“待验证假设”“未来实验建议”。不要把后两者写成已有功能。
4. 学习单元控制在约 30–60 分钟。按“预测 → 运行 → 观察产物 → 自己解释 → 面试追问”组织；预测题答案放在后面，避免先揭晓。
5. 使用一个贯穿案例，例如某次产品发布后的事实、企业立场与外部质疑。教学用虚构案例必须标注；真实案例必须保留可查来源。
6. 解释如何构建和选择机制，不能只列概念、复述源码或泛讲最佳实践。对每个机制说明一个不采用它的合理场景。
7. 默认只读代码和运行已有离线测试。实验修改应独立、可撤销，不先改动核心项目；真实 API 调用要交代凭据需求与预计预算，不能将批量调用作为隐含步骤。
8. Benchmark 选型必须查阅官方论文、仓库和评测说明，注明查询日期、版本、数据可用性、许可、评分工具及使用限制。当前尚未选定 benchmark，不能编造接入文件或成绩。
9. 既有设计文档只作辅助材料；发生冲突时指出差异，以运行代码为实现依据。
10. 最终文档应能让学习者解释一次调查为什么成功或失败，而不是只会描述模块职责。

## 3. 路径约定与阅读入口

当前仓库根目录：`/Users/mac/Desktop/resume_proj/agent_code`。

下面统一使用相对该根目录的路径，便于复制仓库给另一个 AI；`P` 表示 `opinion_search_agent`，`S` 表示 `opinion_search_agent/src/opinion_search`，`T` 表示 `opinion_search_agent/tests`。展开路径后即可定位实际文件。

建议第一轮只读这些入口，不要一次通读所有文件：

| 顺序 | 文件 | 阅读目的 |
|---|---|---|
| 1 | `P/README.md` | 当前使用方式、能力范围和声明的边界 |
| 2 | `S/app/contracts.py` | 调查请求接受什么约束 |
| 3 | `S/app/service.py` | 查看 `build_live_service`、`build_offline_service`、`_build_loop` 如何组装 Harness |
| 4 | `S/domain/opinion/decisions.py` | 模型允许提出什么决策 |
| 5 | `S/context/compiler.py` | 模型实际获得哪些输入 |
| 6 | `S/domain/opinion/completion.py` | 项目如何判断可以结束 |

辅助资料：`docs/public-opinion-search-agent-design.md`、`docs/opinion-search-agent-implementation-memory.md`、`docs/opinion-search-agent-deep-interview-qa.md`。它们可能包含历史设计，不能替代当前代码核查。

## 4. 学习模块

### 模块 0：从 Loop 走到 Harness 的构建视角

学习内容：

- 区分执行循环、模型策略、任务契约、工具环境、上下文构建和验收规则；理解这些机制共同影响 Agent 行为。
- 以 `_build_loop` 为入口观察依赖注入与应用组装，解释为什么 Offline 与 Live 可以共用核心机制。
- 分清脚本化 Fake 模型证明的是控制流与契约，真实模型实验才提供行为效果证据。

代码：`S/app/service.py`、`S/app/config.py`、`S/models/contracts.py`、`S/models/fake.py`、`S/runtime/loop.py`（只读构造器和依赖边界）。

测试：`T/integration/test_offline_loop.py`、`T/e2e/test_offline_demo.py`。

产出：一张组件关系图，标出哪些逻辑由模型决定、哪些由代码约束、哪些可以作为实验变量。不要重新画成只有步骤状态的生命周期图。

### 模块 1：舆情任务契约与成功定义

学习内容：

- 从自然语言请求到 `SearchRequest`、`TaskFrame`、时间范围和调查 gaps。
- 事实、主体立场、主导/新兴叙事与反叙事如何成为调查维度；固定维度有哪些帮助与偏差。
- 区分“找到了提及某主题的网页”和“有足够材料回答该调查问题”。
- 区分运行状态、任务完成策略和外部评测分数。
- 讨论找不到反方材料时是否应该标为信息不足，而不是为了满足结构强行生成反方。

代码：`S/app/contracts.py`、`S/app/service.py` 的 `default_investigation_gaps`、`S/domain/opinion/framing.py`、`S/domain/opinion/state.py`、`S/domain/opinion/completion.py`。

测试：`T/unit/app/test_search_request.py`、`T/unit/domain/opinion/test_framing.py`、`T/unit/domain/opinion/test_completion_policy.py`。

练习：为一条调查请求写一页验收表，逐项注明“代码能直接检查”“需要语义判断”“需要外部数据”。这张表会成为 benchmark 选型依据。

### 模块 2：动作空间、模型接口与反馈设计

学习内容：

- `search/read/reflect/finish` 为什么是当前动作空间，各动作承担什么职责。
- 结构化输出解析、语法合法、状态合法、任务有用是四个不同层次。
- 阅读候选约束、重复尝试检查、引用约束和修复反馈如何影响下一步选择。
- 追踪 `ReflectDecision` 中主张、立场、叙事和 gap 评估怎样提出并被处理。
- 检查模型请求实际发送的 messages、schema 与上下文；不要把自定义结构化决策误写为原生 function calling。
- 模型可见工具描述与领域动作之间是什么关系；注册 MCP 工具不自动意味着领域决策空间已经支持任意 MCP 动作。

代码：`S/models/openai_compatible.py`、`S/domain/opinion/decisions.py`、`S/domain/opinion/action_resolver.py`、`S/domain/opinion/actions.py`、`S/app/action_executor.py`、`S/context/compiler.py` 的 `_protocol_sections`。

测试：`T/contract/test_model_adapter.py`、`T/unit/domain/opinion/test_decisions.py`、`T/unit/domain/opinion/test_action_resolver.py`、`T/e2e/test_recovery_matrix.py`。

练习：给出“合法但无帮助”“格式错误”“引用不存在证据”的三个决策，预测各自在哪一层被接受、拒绝或无法识别。

### 模块 3：工具契约与执行可靠性

学习内容：

- 区分逻辑工具、物理 provider、一次逻辑 action 和多次物理 invocation。
- 为什么参数验证、超时、重试、fallback 和熔断由 Executor 统一处理。
- 工具 schema 与返回字段如何减少模型歧义；工具错误为什么应该成为控制反馈而不是领域证据。
- 搜索/阅读工具限制、返回数量与响应大小怎样影响质量、成本和失败率。
- MCP 扩展阅读：allowlist、schema 固定、本地描述与内容清理的意义；理解适配器边界，不扩写成通用工具平台课程。

代码：`S/tools/contracts.py`、`S/tools/registry.py`、`S/tools/routing.py`、`S/tools/executor.py`、`S/tools/circuit.py`、`S/tools/capabilities/web.py`、`S/tools/adapters/brave_search.py`、`S/tools/adapters/jina_reader.py`、`S/tools/http.py`。

选读：`S/tools/adapters/mcp.py`、`S/tools/adapters/mcp_sdk.py`。

测试：`T/unit/tools/test_executor.py`、`T/unit/tools/test_circuit.py`、`T/e2e/test_tool_fallback.py`、`T/contract/test_tool_adapters.py`、`T/e2e/test_real_mcp_tool.py`。

练习：预测主 provider 超时、备用 provider 成功时的 action identity、调用次数、最终 observation；再解释“备用 provider 成功”为什么不代表它与主 provider 的内容等价。

### 模块 4：从网页到可追溯证据

学习内容：

- 跟踪搜索结果 → Candidate → 阅读结果 → Source/Evidence → Claim/Position/Narrative 的数据转换。
- 重点分析 `_select_evidence_excerpts` 的启发式选择：可能保留什么、遗漏什么，以及定位信息的作用。
- 区分原始 artifact、被截取的 evidence、模型解释和权威状态记录。
- 理解 `acquired_for_gap_id` 与真正的 semantic gap links；“因某问题获取”不等于“回答了该问题”。
- 区分来源数量、URL 数量与独立信息来源；讨论转载和循环引用的风险，核对当前实际实现到哪里。

代码：`S/domain/opinion/processor.py`、`S/domain/opinion/state.py`、`S/domain/opinion/provenance.py`、`S/domain/opinion/reducer.py`、`S/tools/artifacts.py`、`S/tools/url.py`、`S/tools/capabilities/web.py`。

测试：`T/unit/domain/opinion/test_processor.py`、`T/unit/domain/opinion/test_provenance.py`、`T/unit/domain/opinion/test_reducer.py`、`T/unit/tools/test_artifacts.py`。

练习：手工追踪一条主张到证据片段与原始网页；构造“引用 ID 合法但内容不支持主张”的反例，解释为什么结构校验不够。

### 模块 5：上下文工程与任务内记忆（重点）

学习内容：

- 从领域状态到 Working Memory，再到 selected sections 和最终模型输入的完整路径。
- 为什么持久状态、工作记忆和模型上下文不是同一份数据；哪些信息必须保留，哪些可以裁剪。
- 分层、required、priority、recent window、去重、截断和丢弃如何共同决定模型看见什么。
- Evidence Catalog 的当前窗口与历史分区，如何在预算内保留可引用身份和关键矛盾。
- TokenEstimator 是估计器，不能混同为 provider 实际 token 用量；预算溢出如何处理。
- 讨论“上下文有界但重要证据被裁掉”以及“上下文有界但持久状态持续增长”的不同问题。
- 当前记忆是 run-scoped 投影，不能扩写成已有长期用户记忆或向量检索记忆。

代码：`S/memory/models.py`、`S/memory/projector.py`、`S/context/models.py`、`S/context/compiler.py`、`S/context/selector.py`、`S/context/compactor.py`、`S/context/catalog.py`。

测试：`T/unit/memory/test_projector.py`、`T/unit/context/test_compiler.py`、`T/unit/context/test_selector.py`、`T/unit/context/test_compactor.py`、`T/unit/context/test_catalog.py`、`T/integration/test_context_long_trajectory.py`、`T/integration/test_loop_context_growth.py`。

练习：给出同一状态和两种上下文预算，先预测会删掉哪些信息，再观察实际 rendered context；最后说明哪些任务质量变化尚需真实模型实验才能判断。

### 模块 6：不可信内容与安全边界

学习内容：

- provider、tool、model 和 app-config 内容来源如何区分；为何写入 checkpoint 不应提升信任级别。
- 外部文本通过网页、反思、错误消息、MCP 返回和恢复路径进入上下文的方式。
- 边界标记转义与来源标签能保证什么，不能保证什么。
- 本项目实际模型消息如何承载这些标签；文本中的 trusted/untrusted 不是模型 API 强制权限隔离。
- 舆情页面中的诱导性指令、宣传话术与正常观点需要区分；不能把所有观点表达当成攻击。

代码：`S/context/models.py`、`S/context/compiler.py`、`S/context/selector.py`、`S/models/openai_compatible.py`、`S/tools/adapters/mcp.py`、`S/tools/adapters/mcp_sdk.py`。

测试：`T/security/test_context_injection_matrix.py`、`T/contract/test_mcp_adapter.py`、`T/contract/test_mcp_sdk_transport.py`。

练习：沿一个注入字符串追踪它的来源标签，解释测试为何通过；另写一条真实模型攻击成功判据，说明那属于待运行实验。

### 模块 7：完成策略、质量验收与报告输出（重点）

学习内容：

- FinishDecision、CompletionPolicy、CompletionEvaluator 与报告生成分别负责什么。
- 拒绝结束、接受 partial、接受 complete 的条件；gap、时间范围、主张类型、证据关联如何参与判断。
- 结构覆盖、语义支持、来源独立性、观点代表性是不同维度。
- 报告如何展示事实、立场、争议、缺口与局限；最终摘要怎样关联证据，是否具有逐句验证。
- 如何设计“材料不足时合理结束”，避免追求 completed 比例而诱导编造。

代码：`S/domain/opinion/completion.py`、`S/domain/opinion/processor.py` 的 `OpinionSearchCompletionEvaluator`、`S/runtime/completion.py`、`S/domain/opinion/brief.py`、`S/app/run_bundle.py`。

测试：`T/unit/domain/opinion/test_completion_policy.py`、`T/unit/domain/opinion/test_brief.py`、`T/unit/runtime/test_completion.py`、`T/unit/app/test_run_bundle.py`。

练习：设计“应完整完成”“应部分完成”“结构齐全但结论错误”的三个案例，分别写出当前策略判断和外部质量判断。

### 模块 8：为实验保留可解释、可复查的轨迹

学习内容：

- 只复习与实验有关的运行保障：稳定身份、checkpoint、成功缓存、取消与 committed state。
- 区分恢复执行、事件历史回看、固定观察重放和重新调用真实模型；它们的可复现含义不同。
- 如何从一次失败定位到任务定义、搜索、提取、上下文、推理或完成规则。
- 现有 Run Bundle 保留了什么；模型版本、代码版本、预算、真实 usage、评测版本等还需要核对或补充什么。
- 不将当前 checkpoint 误称为已经包含全部物理调用的 append-only trace。

代码：`S/runtime/checkpoint.py`、`S/runtime/transaction.py`、`S/tools/persistent_cache.py`、`S/app/run_bundle.py`、`S/web/server.py`、`S/__main__.py`。

测试：`T/e2e/test_action_running_recovery.py`、`T/integration/test_checkpoint_resume.py`、`T/e2e/test_resume_demo.py`、`T/e2e/test_web_server.py`。

练习：为一次 run 画出“可从已有产物回答的问题”和“缺少记录无法回答的问题”，形成最小实验记录表。

### 模块 9：真实 benchmark 的选择与任务适配（前期即开始）

当前状态：尚未选定、尚未实现 benchmark runner。本节是调研与实验设计要求。

学习内容：

- 区分检索问答、多跳 Web 研究、带引用生成、观点/事实核查任务，分析它们与舆情调查能力的交集。
- 调研候选时记录：官方地址、版本、任务示例、公开数据/隐藏评测、参考答案、评分规则、允许工具、动态 Web 依赖、成本、许可和污染风险。
- 优先选择当前 search/read 能力可合理参与的任务；不要为了适配 benchmark 先造通用 Agent。
- 如果外部任务是事实短答，当前四维舆情完成策略可能并不适用。明确是运行原有舆情 Agent，还是替换任务契约复用基础 Harness；两种结果必须分别标注。
- 若改变工具、子集或官方评测协议，报告为特定配置下的结果，不宣称与官方 leaderboard 直接可比。

现有接入边界：`S/app/contracts.py`、`S/app/service.py`、`S/models/contracts.py`、`S/domain/opinion/completion.py`、`S/app/run_bundle.py`、`T/e2e/test_real_web_smoke.py`。

拟议接口（不是已有文件）：benchmark sample → request/task policy → agent run → prediction artifact → 官方 scorer/明确的评分器 → 汇总。

产出：一张候选对比表、一个明确选型结论、一条样本的完整接入说明，以及 benchmark 不能覆盖的舆情能力清单。

### 模块 10：基线、消融与失败分析

学习内容：

- 先跑小规模接入验证，确认评分和 artifact 正确，再确定固定评测集；调试集与最终评测集分开。
- 固定模型、任务、工具条件与预算，只改变一个 Harness 机制；同时报告质量与成本，不能只比较 completed 数。
- Web 内容与模型输出可能变化：区分缓存观察的机制实验和真实 Web 的效果实验；重复运行时记录样本量与波动。
- 将恢复/结构测试与任务效果实验分开，不用 pytest 通过率替代 benchmark 分数。

可选假设（每次只选一个，不要求全部实现）：

| 假设 | 代码落点 | 需要同时观察 |
|---|---|---|
| 证据感知的上下文选择能减少遗忘反证 | `S/context/catalog.py`、`S/context/compiler.py` | 反证覆盖、答案质量、token 与调用成本 |
| 完成控制能减少过早结束 | `S/domain/opinion/completion.py` | 外部评分、错误完成、partial、步数 |
| 片段提取策略影响引用支持度 | `S/domain/opinion/processor.py` | 引用支持、关键遗漏、上下文长度 |
| 来源与证据关联信息有助于识别覆盖不足 | `S/domain/opinion/provenance.py`、`S/memory/projector.py` | 语义覆盖、无效关联、下一步动作 |

评分要求：优先使用官方 scorer；舆情补充指标应写清分母、标注规则与无法判定项。可考察引用支持度、调查维度覆盖、错误完成率和来源独立性。使用 LLM judge 时记录 judge 模型、提示词，并对一部分结果进行人工复核。

最终产出：基线结果表、一个受控对比、若干可复查失败案例、结论与限制。负结果同样有效，不能只保留改善样本。

## 5. 推荐学习顺序与完成边界

1. **建立任务与评测坐标**：模块 0、1，并启动模块 9 的候选调研。交付任务验收表和 benchmark 能力匹配表。
2. **理解信息如何进入模型**：模块 2、3、4、5。交付一条从网页到最终上下文的完整数据链。
3. **理解约束与验收边界**：模块 6、7、8。交付一个“结构合法但质量失败”的可解释案例与实验记录表。
4. **运行与验证**：完成模块 9、10。交付真实 benchmark 基线、领域补充检查和一次受控对比。

每个阶段可拆成多个 30–60 分钟单元，不承诺固定几天全部完成。遇到缺口先判断是否阻碍当前实验，其余进入 Backlog。

学习完成标准：能够独立解释一次调查的任务契约、工具观察、上下文选择、证据判断和结束原因；能够运行选定 benchmark，读懂评分与失败，说明一个 Harness 设计是否带来可观察收益。

## 6. 已有证据与表述限制

- 本次代码审查的全量测试为 562 passed、2 skipped，另有 1 failed 和 9 errors 均涉及沙箱禁止本地端口绑定；允许本地服务后，Web 测试文件单独复跑为 11 passed。不要写成在同一次全量运行中全部通过。
- 两项外部 provider/live Agent 测试默认跳过，本次没有重新调用真实模型或搜索服务。
- `T/integration/test_context_long_trajectory.py` 使用构造状态验证长上下文性质，不能称为真实模型自主完成 100 步的证据。
- `T/security/test_context_injection_matrix.py` 主要证明内容来源与信任标签保持、边界转义等结构性质，不能等同于真实模型抗注入成功率。
- `P/reports/gpt-5.4-opinion-search-live-report.md` 是历史运行报告；其中 `/tmp` 原始 checkpoint 在本次检查时已不存在，不能据此宣称当前可以重放完整历史 live 运行。
- 成功缓存对已持久化成功提供复用，不是通用外部副作用 exactly-once。
- 来源 ID、证据关联与 completed 状态不能单独证明事实真实、语义支持或观点代表性。

## 7. 请扩写 AI 最终交付什么

请基于以上路线与实际仓库，交付：

1. 一份按模块组织的完整学习文档，重点放在模块 1–7 与 9–10，Loop/生命周期只作背景。
2. 每章的准确代码导航、核心符号、数据流和代表性测试，而不是整文件粘贴。
3. 每章至少一个舆情案例、一个反例、一项先预测后验证的练习，以及参考答案和面试追问。
4. 一份经官方资料核实的 benchmark 选型建议，明确原有 Agent 与必要任务适配的边界。
5. 一份从单样本接入到小规模基线再到受控对比的实验计划；清楚区分已有能力与待实现部分。

请始终围绕“针对舆情任务如何构建、理解和验证 Harness”展开，避免扩写成生产平台建设清单或再次完整讲解 Agent Loop。
