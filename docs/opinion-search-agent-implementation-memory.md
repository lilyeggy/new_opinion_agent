# OpinionSearch Agent 实施记忆

> 文档性质：持续追加的工程事实记录  
> Canonical Design：[`public-opinion-search-agent-design.md`](./public-opinion-search-agent-design.md)  
> 执行计划：[`opinion-search-agent-5-day-plan.md`](./opinion-search-agent-5-day-plan.md)  
> 当前记录截至：2026-10-15（M1–M6 全链路深度化改造完成：展示层视觉拓扑重构 + 收束死锁解除 + 页面内证据清洗加权 + 反方与数值冲突检测）
> 当前已完成节点：Day 1–4、Web 演示控制台、工作台与研判流程（§18/§19 各批次）、秋招收尾（D1–D5）、深度化改造 M1–M6（视觉拓扑与自主编排 Presentation Agent + 收束控制修复 + 页面内检索清洗与冲突检测）

## 0. 最新节点：M1–M6 全链路深度化改造（2026-10-15）

### 解决的问题

针对真实运行产物（三九胃泰 `9b1bf7d631804cffbfc85a00086aef52` 与罗永浩吐槽野人先生 `cb39508854dd491a8d9752fae46e2ec6`）及 D4 对抗评测暴露出的核心痛点：
1. **呈现层文字过重、缺乏图形化关系表达且与上游强耦合**：非必答模块因未填 `module_fields` 或存在多源表述差异被隐藏为 `insufficient`；通用事件退化为长段落卡片列表；缺乏主体、议题、立场与信源之间的可视化拓扑网络。
2. **收束控制阶段存在双门控死锁**：`response_search_complete` 使用全局 `state.read_errors` 导致单网页反爬失败锁死所有问题的 `not_found` 收口；`ConsolidationValidator` 在模型调用过 `2/3` 且已有判断全部审查后只允许 `FinishDecision`，而 `completion()` 又因必答问题仍 `open` 拒绝 `FinishDecision`，导致三九胃泰连续 18 次 `finish` 被拒直至步数耗尽。
3. **页面内摘录混入图片/链接噪声且漏摘关键引语**：`chunks()` 未过滤纯 Markdown 图片标签（`![Image ...]`）且硬切边界劈断引语；`terms()` 未过滤高频虚词双字；缺少同源通稿识别、未处置反方证据提示与跨源数值冲突（316.03 亿 vs 3160.3 亿）检测。

### 实现范围与相关文件

- **M1–M3 视觉拓扑呈现引擎与自主编排 Presentation Agent（`investigation/presentation.py`, `investigation/workbench.py`, `report_contract/*`, `presentation_skill/llm_planner.py`, `investigation/manager.py`）**：
  - 放宽 `facet_modules` 状态判定并扩展 `_timeline` 支持中文日期与斜杠日期前缀。
  - 在 `projector.py` 与 `renderer.py` 中实现交互式三层 SVG 节点关系拓扑图（`RELATION_GRAPH`：参与主体/信源 ──▶ 核心争议子议题 ──▶ 事件总枢纽，支持点击/悬停高亮路径与穿透面板）、正反阵营证据拔河条与对抗卡（`DEBATE_VERSUS`）、三栏立场光谱泳道看板（`POSITION_MATRIX`）、横向里程碑流向链（`TIMELINE`）以及长文本自动提炼标题+要点胶囊（`_extract_structured_summary`）。
  - 升级 `LlmPresentationPlanner` 支持 `DynamicModuleProposal`，强制校验 `source_finding_ids` 与 `unbacked_specifics` 数字防幻觉护栏。
- **M4 收束死锁修复（`domain/investigation/engine.py`, `investigation/service.py`, `investigation/context.py`）**：
  - 新增 `_issue_has_read_errors(state, issue_id)`，将读取失败判定局部化到当前议题候选 URL，解除无关议题对 `not_found` 的阻塞，并在 `_open_questions_guidance` 中明确提示合法收口状态。
  - 在 `ConsolidationValidator.validate` 中解除 `FinishDecision` 与 `open_required` / `partial` 审查结果的死锁：当保留段内仍有 `open` 必答议题或 `partial` 判断且剩余模型调用充足时，允许执行 `ReflectDecision` 收口或零网络开销的本地 `RetrieveDecision` 补证。
- **M5 页面内证据清洗、句子边界切块与引语/日期加权（`investigation/storage.py`）**：
  - 新增 `_is_noise_chunk` 过滤纯 Markdown 图片标签（`![Image ...]`）、裸跟踪链接与 Base64 噪声块，同时严格保持 `[start, end)` 与原文切片一致（100% 通过 `verify_evidence`）。
  - `chunks(text)` 优先对齐句末标点与引号边界并保留滑动重叠；`terms(text)` 过滤高频无意义双字并补充 3-gram 特征；`Corpus` 按 `version_id` 增量写入 FTS5，并在 BM25 召回池上对包含直接引语（`“...”`、`「...」`）和明确日期/数值量纲的片段进行重排加权。
- **M6 聚合站饱和预警、近似通稿检测与反方/数值冲突提醒（`domain/investigation/engine.py`, `investigation/context.py`）**：
  - 新增 `evidence_quality_signals(state)` 并注入 `memory.coverage`：自动检测单一域名饱和（`>= 50%` 候选或多次读取失败）、跨源双字集合 Jaccard `>= 0.75` 的近似通稿转载、未处置反方/质疑证据，以及同单位相差 `>= 2x` 的跨源数值冲突（如 `316.03亿元` vs `3160.3亿元`）。

### 验证证据

- `tests/unit/report_contract`、`tests/unit/presentation_skill` 及 `tests/investigation/` 下的专项、页面计划、工作台投影、页面导出、回应覆盖、决策校验、回放套件等 **86 项核心测试全部通过**。
- 两个真实运行产物（三九胃泰 `9b1bf7d631804cffbfc85a00086aef52` 与罗永浩事件 `cb39508854dd491a8d9752fae46e2ec6`）生成包含双 SVG 关系拓扑图、正反拔河条与三栏泳道看板的 `dossier.html` 验证通过。

## 0.1 历史节点：项目封存（2026-09-22）

### 解决的问题

秋招面试导向的快速收尾。项目功能早已足够，缺的是四件收口事实：单一可讲述的系统、一次真实闭环、可引用的质量数字、成形的面试叙事。

### 实现范围与相关文件

- **D1 单一 harness（09-21）**：实验性多角色流水线（planner→research→analyst→reviewer）评估后归档至 `opinion_search_agent/archive/harness-pipeline/`（含完整决策记录 README）；该代码从未提交进 git，主线始终单 harness。生产路径保留 `runtime/loop.py` 一套循环，「骨架→渲染」思路由 PagePlan + search_targets 在生产路径实现。归档后全量 779 passed, 2 skipped（沙箱环境需 `--basetemp` 指向项目内目录）。
- **阻塞项核查（09-21）**：「过去 30 天」空格不解析在 09-12 提交中已修（`strip()`→`re.sub(r"\s+","")`），09-09 分析文档记的是旧行为；补回归测试覆盖 4 种空格变体（`tests/unit/domain/opinion/test_framing.py`）。`live_model()` 的 max_output_tokens/timeout 注入经实证验证无需修。
- **D2–D3 真实闭环（09-21）**：新增 `scripts/run_live_investigation.py`（生产路径 runner，`model_copy` 调步数不动源码）。三九胃泰中秋广告争议事件两跑：s5-a 默认 20 步 partial（诊断显示 `committed_steps=20` 恰等于默认上限、预算仅用 16%–45%——配置问题非逻辑问题）；s5-b 60 步全流程走完——17 搜/17 读/14 findings/92 处证据引用，review 执行（6 supported/8 partial），completion gate 拒绝 finish 18 次直到步数耗尽（必答问题仍 open），诚实 partial。产物在 `artifacts/live-runs/investigations/runs/{f045d7ee…,9b1bf7d6…}/`。
- **D4 质量基线（09-21）**：检索召回 60%（6/10 人工标注必中清单，逐项独立搜索验证）；忠实性 71% 完全支持（10/14）且 100% 零虚构；对抗埋点 2/3（更正完全采纳✓、反方稿已读已摘 5 条证据但零 finding 引用✗、错误数字未传播✓但靠的是未轮到综合而非矛盾检测）。对抗案例与 replay 产物在 `artifacts/adversarial-cases/sanjiu-2026-09/`。方法见 `docs/舆情agent-质量三数字-D4-2026-09-21.html`。
- **D5 面试资产（09-22）**：`docs/舆情agent-面试收口手册-D5-2026-09-22.html`——3 分钟电梯陈述、白板架构图、§16 十四问要点答案、三个数字、失败修复故事链、已知限制与下一步。README 增加 Project status 段（定位/实测结果/已知限制）。

### 关键取舍

- 合流做「决策级」不做代码级：完整重构（流水线作为 Runtime 之上的调度策略）故事更美但秋招前做不扎实；砍 fork 本身是 scope discipline 的面试资产。
- 质量工作定位为「验收工程」而非产品优化：数字的短板定位比数字本身更有面试价值，修复方向全部写入「下一步」清单但不动手。
- 即使终态是 partial 也计为闭环完成：诊断链完整记录系统如何发现自己的不足，这是可靠性机制的卖点。

### 测试命令与结果

归档后全量：779 passed, 2 skipped（live-gated smoke，设计内）；framing 回归测试新增后通过。D5 仅改动 Markdown/HTML 文档与 README，未触碰运行时代码。

### 已知限制（面试主动讲）

候选 66% 来自 news.qq.com 聚合站、原发媒体站零覆盖；qq/sohu 反爬 6/17 读取失败；证据摘录召回是单点（4 条 partial 全是引语在原文但摘录未摘到；反方稿已读已摘未引用）；模型不会把长期无证据问题显式从 open 转 not_found（gate 拒 finish 18 次的直接原因）；数字护栏只验出处不验可信度（真实 316.03 亿与埋点 3160.3 亿静默并存；2026-10-17 起读取时会建数值台账、报告里多一节「数据口径存疑」，但只在跨文档整十次幂时触发，且只列分歧、不裁决谁对）。

### 对下一节点的约束

秋招前封存，不改运行时代码。秋招后若重启，优先级：① TaskFrame 约束传导到 Brave 参数（freshness/search_lang/域名）；② 结构化 QueryPlan + 第二引擎破聚合站偏向；③ 事件内 FTS5/BM25 二次检索命中「摘录未摘到」「已读未引用」两个失败模式；④ 数字矛盾检测（已完成：机制层 + 运行时台账 + 报告显性化）；⑤ open→not_found 显式收口动作；⑥ 必中清单+对抗埋点回归套件化。

## 归档节点：最终结论的可恢复提交（2026-08-23）

### 解决的问题

真实调查中，模型已经在 `FinishDecision.answer_candidate` 里给出总结，但旧实现把 accepted finish 转成空 `OpinionSearchDelta`。因此 summary 没有进入 `OpinionSearchState` 或 checkpoint，`SearchOutcome` 只能把 Claim、Narrative 和全部 Evidence 摊平输出；用户看到的是审计账本，而非调查结论。

### 已实现的语义

- 新增 frozen `FinalSynthesis(summary, evidence_ids, limitation_gap_ids)`；它属于领域 State，不是 trace 或临时 UI 文本。
- `OpinionSearchObservationProcessor` 只在 finish verdict 为 `accept_complete`、`accept_partial` 或 `safety_stop` 时，从 answer candidate 和已 resolved Gap 的 Evidence 构造 `set_final_synthesis` delta；`reject_and_continue` 保持空 delta。
- Reducer 对 synthesis 验证 Evidence/Gap 引用、保持 immutable/idempotent replay，并拒绝一个已提交结论被不同内容覆盖。
- `build_search_outcome` 在报告顶部渲染 `Core conclusion`，带来源引用和 limitation Gap；原始网页摘录改名为 `Evidence appendix`，明确其审计定位。
- Web 的 Markdown section 映射新增“核心结论”和“证据审计附录”。

### 关键取舍

本节点没有让模型直接生成一套新的自由格式报告，也没有把 synthesis 当作未经验证的最终真相。它仍是模型文本，但只有 Completion Policy 接受后才提交；其引用只能来自已经 committed 的 resolved-gap Evidence。当前 evidence 粒度是“结论所依据的已解决 Gap 证据集合”，不是逐句 claim-to-evidence 对齐；后者需要后续质量层的 structured finding contract。

### 验证证据

- 22 个相关 unit/integration tests 通过：accepted finish 提交、rejected finish 不提交、Reducer replay/overwrite 规则、报告首屏顺序、工具闭环。
- 离线 CLI 冒烟成功：报告包含 `Core conclusion`、结论来源 `[S1]...[S3]` 与 `Evidence appendix`。
- 全量测试在受限 sandbox 中运行到 Web server fixture 时因本机端口 bind 被拒绝；这是环境权限限制，而非断言失败。Web e2e 应在可绑定 `127.0.0.1` 的本机终端复跑。

### 下一节点

仍需实现 TaskFrame/time scope、来源发布日期与证据质量门、文档正文去噪和 typed web outcome；它们会修复“过去一周却引用六月材料”和网页导航/广告被当作 Evidence 的问题，不能靠本节点掩盖。

### 补充：TaskFrame 与冻结时间窗口（2026-08-23）

- 新增 `domain/opinion/framing.py`：`TaskFrame` 和 `TemporalScope` 是 typed、frozen 的领域对象；相对时间不会留在模型 prompt 中等待解释。
- `OpinionSearchService.investigate` 在 run 创建时调用 `build_task_frame(..., anchor_date=date.today())`，把 frame 写入初始 `OpinionSearchState`；Reducer、WorkingMemory、Context 及 resume 都保留同一个 frame。
- 支持的确定性解析：`过去一周`/`最近一周`/`最近7天`/`过去7天`，以及 30 天窗口和 `YYYY-MM-DD 至 YYYY-MM-DD`；未支持表达明确变成 `unspecified`，不做猜测。
- `SearchRequest.time_range` 是用户显式约束，优先于 question 中的相对语句。离线冒烟中，“过去一周”在 2026-08-23 的 run 被持久化、并在报告显示为 `2026-08-17 to 2026-08-23 (inferred_from_question)`。
- 49 个 framing/context/memory/reducer/brief/tool-loop 相关测试通过。

这只是范围的“声明与冻结”，尚未把来源发布日期接入 acquisition/completion；因此它不能单独阻止旧网页完成调查。下一节点必须把该 frame 变成 Source/Evidence 可验证的时间门。

### 补充：来源发布时间与时间范围强制校验（2026-08-26）

Reader capability 新增 `published_at` 与派生的 reported/unavailable 状态；Jina adapter 仅接受可解析的供应商时间字段，Fake Reader 支持确定性日期 fixture。Observation processor 将发布时间写入 Source，Working Memory 和最终 Sources 列表继续暴露它，完整正文 artifact 不受影响。

当 TaskFrame 具有有界窗口时，Decision Validator 在 Reflect 提交前检查 resolved assessment 引用的每个 Evidence：其 Source 日期未知或不在窗口内时拒绝该 Decision。Completion Policy 对 committed State 再做同一语义的终态兜底，使旧状态或其他组合路径最多得到 partial，不能错误标记 completed。该规则只存在于 OpinionSearch domain/capability 边界，AgentLoop、transaction 和 checkpoint primitive 未增加舆情专属逻辑。

验证覆盖 Jina 时间正规化、Reader→Source 传播、过期 Evidence 的 Reflect 拒绝、unknown/stale/current 三种 Completion 结果、Memory/Context、报告、恢复、工具和 Web。分组全量结果为 571 passed、2 skipped；跳过项是需要显式开启真实 provider 的 live smoke tests。Web E2E 在允许绑定本机随机端口的环境中单独运行，11 passed。

### 补充：Reader 正文去噪与 Evidence 有界选择（2026-08-26）

`OpinionSearchObservationProcessor` 在 Evidence 构造前新增确定性 block 质量门：推广/赞助、登录注册、导航链接密集、信息量过低的内容不进入 State；重复 block 按正规化正文去重，中英文 focus 词用于相关性排序，每个 Source 最多保留三条。若页面只有一个通过质量门的正文 block，则允许无词面重合的保守回退，避免同义改写导致整页无 Evidence；多 block 页面没有任何相关命中时不制造 Evidence。

这次改变的是 Reader artifact 的派生选择视图，不修改、不覆盖全文 artifact；已有 locator 继续保存原 block index 和字符区间。新增测试以推广、四个导航链接、四段相关正文组成页面，证明推广和导航均被排除、Evidence 有界为三条且 artifact reference 不变；工具闭环、恢复和长 Context 注入场景回归通过。

## 1. 这份文档解决什么问题

本文件保存 OpinionSearch Agent 已经落入仓库并得到验证的重要工程事实，使后续开发者或 Agent 在丢失聊天上下文后，仍然能够回答：

1. 当前系统实际实现到了哪里；
2. 每个重要模块解决了什么问题；
3. 核心对象之间如何协作；
4. 哪些契约和不变量已经冻结；
5. 遇到崩溃、重启、取消和提前结束时系统如何处理；
6. 哪些行为已经由测试证明；
7. 下一节点应建立在什么基础上。

它不是新的设计来源。目标、范围和最终架构仍以 canonical design 为准；未来任务仍以五天计划为准。本文件只记录实际实现和验证结果。

## 2. 后续维护规则

每完成一个重要节点，都必须在最终宣布完成前更新本文件。重要节点包括但不限于：

- 新增或冻结核心协议；
- 完成一个 Runtime、Tool、Context 或 Memory 模块；
- 改变 State ownership、事务边界或恢复语义；
- 新增外部 adapter 或改变 provider 正规化行为；
- 修复会改变系统语义的重要缺陷；
- 完成一个 Milestone、Day 或纵向闭环；
- 新增能够证明关键工程性质的测试。

每次记录至少包含：

- 日期和节点名称；
- 实现范围与相关文件；
- 要解决的问题；
- 运行流程；
- 输入输出契约；
- 关键不变量；
- 重要设计取舍及原因；
- 失败、重试和恢复语义；
- 测试命令与结果；
- 已知限制；
- 对下一节点的约束和衔接。

记录必须区分三种状态：

- **已实现并验证**：代码已经存在，并有对应验证证据；
- **已实现但未完全验证**：必须明确缺失的验证和风险；
- **计划中**：不得写进完成事实，只能在“下一节点”中引用计划。

## 3. 当前系统快照

截至当前记录，项目已经具备一个完全离线、确定性、可 checkpoint 和 resume 的单 Agent Harness，以及已经接入 Harness 的 provider-neutral Tool Runtime、真实 Web provider adapters、MCP adapter boundary、确定性 Working Memory、有界 Context Compiler，和一个可在浏览器中启动/观察/取消调查的零新依赖 Web 演示控制台（`python -m opinion_search.web`）。

当前纵向链路为：

```text
RunState created
  -> start run
  -> open stable step
  -> project Working Memory from committed Domain State
  -> compile bounded L0/L1/L2/L3 context
  -> Fake Model produces domain Decision
  -> state-aware validation
  -> resolve accepted Decision into typed planned action
  -> persist ACTION_RUNNING checkpoint
  -> search/read: ActionRequest -> ToolCall -> Registry/Executor -> configured adapter
  -> reflect/finish: execute typed internal action
  -> persist OBSERVATION_READY checkpoint
  -> Observation processor builds domain delta
  -> pure Reducer produces new Domain State
  -> atomically commit step and action identity
  -> persist STEP_COMMITTED checkpoint
  -> evaluate completion or continue
  -> terminal RunResult
```

当前默认离线脚本具有五个 committed steps：

1. `search`：为开放 Gap 发现一个候选来源；
2. `finish`：模型过早请求结束，Completion Policy 拒绝并反馈原因；
3. `read`：读取已经存在于 State 中的候选来源；
4. `reflect`：提交调查判断并解决 Gap；
5. `finish`：满足最小完成条件，run 进入 `completed`。

Day 3 已经完整实现 contracts、Registry、Executor、Fake Search/Reader、Serper Search、Jina Reader、公共 HTTP/URL/cache primitives 和 MCP discovery/call adapter，并通过正式 `OpinionSearchActionResolver`、`OpinionActionExecutor` 和 `OpinionSearchObservationProcessor` 接入 AgentLoop。Day 4 又在 Loop 已有 `ContextCompiler.compile(state)` 边界上接入 Working Memory projection、section selection、deterministic compaction、trust rendering 和 output headroom；Runtime Loop 核心不需要修改。

当前全量验证结果：

```text
cd opinion_search_agent
pytest -q -W error
332 passed, 1 skipped in 0.64s
```

同时通过：

- `python -m compileall -q src tests`；
- `git diff --check`；
- 新项目源码与测试中不存在 `archive` 或 LangGraph 依赖；真实 provider 只存在于 adapter boundary。
- 默认 test run 跳过两个显式 gated live smoke；2026-08-20 已使用真实 Brave、无 Key Jina 和 `deepseek-v4-flash` 分别执行并通过。
- Day 4 的 7-step 长轨迹、固定 context budget 和 checkpoint resume 重建已经进入集成测试。

## 4. Day 1：Runtime 控制语言与协议

### 4.1 节点目标

Day 1 没有先写工具或复杂舆情对象，而是先定义 Agent Harness 各组件交换信息时使用的控制语言。这样做使模型提案、Runtime 执行、环境结果和领域状态变化拥有不同的类型和责任，后续 Loop 不需要依赖任意字典猜测语义。

### 4.2 Run 与 Step 生命周期

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/lifecycle.py`

Run lifecycle：

```text
created -> running -> completed | partial | failed | cancelled
```

Run lifecycle 表达整个任务是否仍然存活。四个终态不可重新进入 `running`。

Step lifecycle：

```text
opened
  -> deciding
  -> decision_accepted
  -> action_running
  -> observation_ready
  -> reducing
  -> committed
```

Step phase 表达一个独立事务内部走到了哪里。RunStatus 和 StepPhase 被拆成两套枚举，因为 run 可以在多个 step 之间持续处于 `running`，而 step phase 是一个 action 的局部事务状态。如果混在一起，恢复逻辑无法判断“整个 run 是否结束”和“当前 step 从哪里继续”。

`InvalidLifecycleTransition` 不需要保存额外状态；它作为有语义的异常类型，使调用方和测试能够区分生命周期违规与普通 `ValueError`。

已冻结的 lifecycle 规则：

- 只允许显式列出的 transition；
- 不允许跳过 step phase；
- committed step 不可倒退；
- terminal run 不可恢复成 running；
- run status 不承载 step 内部执行细节。

### 4.3 Runtime failure taxonomy

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/errors.py`

`RuntimeFailureKind` 将失败按语义分类，而不是把所有问题包装成一个通用异常。当前包含：模型 malformed/empty/refusal、invalid decision/action、tool error/configuration、reducer invariant、checkpoint read/write/version、context overflow、repeated action、cancelled 和 safety limit。

`RecoveryDirective` 描述 Runtime 对一类失败的默认控制策略：

- `retry_attempt`：同一 step 的新 attempt；
- `feedback_and_continue`：将安全错误反馈给 Agent，再继续决策；
- `partial_stop`：保留已提交成果并产生 partial result；
- `fail_run`：系统性失败，run 进入 failed；
- `cancel_run`：取消并保留已提交成果。

重要边界：failure taxonomy 是 Runtime 的控制语义，不是 Tool provider 的原始异常结构。Day 3 的 Tool Runtime 需要先正规化 provider error，再映射到这里。

### 4.4 Decision、Action、Observation 与 Delta

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/protocols.py`
- `opinion_search_agent/src/opinion_search/domain/opinion/decisions.py`

四个核心对象承担不同职责：

| 对象 | 表示什么 | 为什么不能合并 |
|---|---|---|
| `DecisionEnvelope` | 模型在某个 run/step/attempt 提出的领域动作 | Decision 尚未通过 Runtime 校验，不能直接执行 |
| `ActionRequest` | 已校验并解析、具有稳定 `action_id` 的执行请求 | 它是 Runtime 承诺执行的动作，不是模型原始输出 |
| `ObservationEnvelope` | 特定 action 实际产生的环境结果 | 它描述发生了什么，但无权决定 State 如何变化 |
| `StateDelta` | Domain processor 接受后提出的状态变化 | 它是变化集合，不是完整新状态，最终仍需 Reducer 验证和应用 |

所有 envelope 都携带：

- `run_id`；
- `step_id`；
- `attempt`。

Action、Observation 和 StateDelta 还携带相同的 `action_id`。这些字段用于关联、恢复和拒绝串错数据。领域字段只存在于泛型 payload 内，Runtime envelope 不知道 OpinionSearch 的 query、Gap 或 Candidate。

### 4.5 StepRecord

`StepRecord` 是单 step 的事务恢复对象。它保存当前 phase 以及截至该 phase 必须已经存在的 payload：

| Phase | 必须存在的 payload |
|---|---|
| `opened` | 无 |
| `deciding` | 无 |
| `decision_accepted` | decision |
| `action_running` | decision、action |
| `observation_ready` | decision、action、observation |
| `reducing` | decision、action、observation |
| `committed` | decision、action、observation |

模型 validator 会检查：

- payload 不能早于对应 phase 出现；
- phase 所需 payload 不得缺失；
- envelope 的 run/step/attempt 必须与 StepRecord 一致；
- Observation 的 action ID 必须与 ActionRequest 一致。

StepRecord 只保存恢复正确性需要的信息，不承担 trace 查询、指标聚合或 Observability 平台职责。

### 4.6 OpinionSearch domain decisions

当前动作空间固定为四种 discriminated union：

- `SearchDecision`：query、目标 Gap、搜索目的；
- `ReadDecision`：Candidate ID、目标 Gap、阅读 focus；
- `ReflectDecision`：assessment、next focus、关联 Gap；
- `FinishDecision`：answer candidate、resolved/unresolved Gap IDs。

设计重点：Decision 是 domain intent，不等于 ToolCall。`search` 和 `read` 以后会由 action resolver 转成工具调用；`reflect` 和 `finish` 可以是内部 action。

### 4.7 SearchRequest

相关文件：

- `opinion_search_agent/src/opinion_search/app/contracts.py`

`SearchRequest` 只保存任务语义，例如 question、topic、time range、focus、language 和 domain filters。Runtime hard limit 不属于任务领域契约，因此没有 `budget_profile`；第一版只有一种输出时也没有 `output_mode`。

### 4.8 Day 1 验证证据

测试覆盖文件：

- `tests/unit/runtime/test_lifecycle.py`；
- `tests/unit/runtime/test_protocols.py`；
- `tests/unit/runtime/test_errors.py`；
- `tests/unit/domain/opinion/test_decisions.py`；
- `tests/unit/app/test_search_request.py`。

已验证行为包括：合法和非法 transition、终态不可逆、phase/payload 对齐、关联 ID 一致性、JSON round-trip、四种 decision 判别、extra fields 拒绝，以及 provider 字段不会进入 Runtime/domain contract。

## 5. Day 2：Deterministic Harness、Reducer 与恢复

### 5.1 节点目标

Day 2 将 Day 1 的静态协议变成可执行的异步 Agent Harness。核心目标不是“让脚本跑起来”，而是建立唯一 State 写入口、明确事务提交点，并证明 run 能够在关键崩溃窗口从磁盘 checkpoint 恢复。

### 5.2 最小 OpinionSearch State

相关文件：

- `opinion_search_agent/src/opinion_search/domain/opinion/state.py`

`OpinionSearchState` 是当前领域权威状态，保存：

- 原始 `SearchRequest`；
- `open_gap_ids`；
- `resolved_gap_ids`；
- `candidate_source_ids`；
- `read_source_ids`；
- `reflections`；
- 单调递增的 `revision`。

当前是恢复骨架所需的最小状态，并非最终舆情领域模型。Evidence、Claim、Source 等对象计划在后续整合节点加入。

状态模型已建立的不变量：

- tuple 字段内部不允许重复；
- 同一个 Gap 不能同时 open 和 resolved；
- read source 必须已经是 candidate；
- 模型 frozen，调用方不能原地修改。

`OpinionSearchDelta` 只表达本次变化：新增 candidate、标记 source 已读、解决 Gap、追加 reflection。它不包含新的完整 State，也不能直接覆盖已有字段。

### 5.3 Pure Reducer

相关文件：

- `opinion_search_agent/src/opinion_search/domain/opinion/reducer.py`

唯一领域写入公式为：

```text
new_state = reduce_opinion_state(old_state, accepted_delta)
```

Reducer 的实际语义：

- 拒绝读取未知 Candidate；
- 拒绝解决非 open Gap；
- 对所有追加集合执行稳定顺序的去重；
- 解决 Gap 时同时从 `open_gap_ids` 移除并加入 `resolved_gap_ids`；
- 只有领域内容真实变化时才将 revision 加一；
- no-op delta 返回原来的 state；
- 不执行模型调用、工具调用、网络或文件 I/O。

这一边界保证 Model、Tool、Observation processor 和 Loop 都不拥有 State。

### 5.4 RunState 与 step transaction

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/transaction.py`

`RunState` 将 Runtime metadata 和泛型 domain state 装在同一个可 checkpoint 的恢复根对象中。它保存：

- `run_id` 和 `status`；
- `domain_state`；
- `next_step_index`；
- 当前 `active_step`；
- 已提交 `committed_steps`；
- 已提交 `committed_action_ids`；
- `continuation_pending`；
- terminal `stop_reason`；
- failed run 的 `RuntimeFailure`。

关键不变量：

- active step 不能已经 committed；
- committed_steps 中只能有 committed step；
- 所有 step 必须属于当前 run；
- step ID 在 run 内唯一；
- committed action ID 不重复，且顺序必须与 committed steps 完全一致；
- `next_step_index = committed step count + 1`；
- created run 没有运行历史；
- terminal run 没有 active step 或 pending continuation，并且必须有 stop reason；
- 只有 failed run 可以携带 failure。

事务函数按 phase 严格推进：

```text
start_run
-> open_step
-> mark_deciding
-> accept_decision
-> start_action
-> record_observation
-> mark_reducing
-> commit_step
-> apply_continuation
```

每个函数都返回经过完整 Pydantic 校验的新对象，不原地修改旧对象。

### 5.5 Commit boundary 与 effectively-once state effect

`commit_step` 是当前 Runtime 最关键的原子语义边界。一次成功提交同时完成：

1. 调用 Reducer 生成新 Domain State；
2. 将 active StepRecord 变成 committed；
3. 清空 active step；
4. 追加 committed step；
5. 追加 stable action ID；
6. 推进 next step index；
7. 设置 `continuation_pending=True`。

如果相同 action ID 已经存在于 `committed_action_ids`，并且 correlation 与原 committed step 一致，重复 commit 会直接返回当前 State，不再次应用 delta。

这保证的是 **effectively-once state effect**，不是外部请求的严格 exactly-once：

- 外部工具可能在返回前已经产生效果，而进程随后崩溃；
- Runtime 无法通过本地事务回滚外部服务；
- Runtime 通过稳定 action ID、adapter/result cache 和 committed action set 避免重复影响本地权威状态；
- 未来真实 Tool adapter 应尽可能把 action ID 用作幂等键，但不能对所有供应商承诺 exactly-once。

### 5.6 continuation_pending 的作用

State 已提交后，Runtime 仍需要判断：继续下一 step、正常完成，还是 partial stop。如果在 commit 后、completion decision 前崩溃，没有显式标志就无法知道应该重新提交还是执行 continuation。

`continuation_pending=True` 封住这个故障窗口：

- resume 看到它时不会打开新 step；
- `classify_resume` 返回 `EVALUATE_CONTINUATION`；
- Runtime 基于最后一个 committed step 的 Decision 和 Observation 重新计算完成判定；
- 判定是确定性的，因此可以安全重复；
- continuation 应用后标志被清除，或者 run 进入 terminal status。

### 5.7 Resume classification

`classify_resume` 不依赖进程内游标，仅根据 checkpoint 中的 RunState 决定下一动作：

| 持久状态 | ResumeAction |
|---|---|
| run 为 created | `START_RUN` |
| run 已 terminal | `RETURN_RESULT` |
| continuation pending | `EVALUATE_CONTINUATION` |
| 没有 active step | `OPEN_STEP` |
| opened/deciding | `REQUEST_DECISION` |
| decision accepted | `RESOLVE_ACTION` |
| action running | `EXECUTE_ACTION` |
| observation ready/reducing | `REDUCE_OBSERVATION` |

模型脚本也通过持久化的 `next_step_index` 选择 Decision，而不是使用进程内自增 cursor。否则进程重启后 fake model 会与 checkpoint 脱节，测试不能代表新进程恢复语义。

### 5.8 Explicit async AgentLoop

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/loop.py`

`AgentLoop` 是显式 orchestration loop，不把状态变化交给图框架隐式管理。它依赖小型协议：

- `ModelClient`；
- `ContextCompiler`；
- `DecisionValidator`；
- `ActionResolver`；
- `ActionExecutor`；
- `ObservationProcessor`；
- `CompletionEvaluator`；
- Reducer；
- `CheckpointStore`；
- `IdFactory`；
- cancellation check；
- 用于故障注入的 loop hook。

Loop 只负责顺序和控制流。它不直接创建 Candidate、解决 Gap 或追加 Reflection；领域变化由 Observation processor 构造 Delta，再由 Reducer 应用。

每个可恢复边界都会先保存 checkpoint，再触发测试 hook：

- run started；
- step opened；
- deciding；
- decision accepted；
- action running；
- observation ready；
- reducing；
- step committed；
- continuation applied；
- run terminated。

Hook 当前只用于 deterministic crash injection，不是 Observability event pipeline。

### 5.9 Completion Control

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/completion.py`

模型产生 `finish` 只代表结束提案，不能直接把 run 改成 completed。Domain Completion Policy 返回以下 verdict：

- `accept_complete`；
- `reject_and_continue`；
- `accept_partial`；
- `safety_stop`。

`RunResult` 只允许 terminal RunStatus。failed result 必须带 `RuntimeFailure`，其他 terminal result 不允许带 failure。

Day 2 当时的最小 OpinionSearch policy（已由 Day 5 rich policy 取代）：

- 仍有 open Gap：拒绝 finish 并继续；
- Gap 已解决但没有任何 read source：接受 partial；
- Gap 已解决且至少有 read source：接受 complete。

Premature finish 的 rejection reason 保存在 finish Observation 中，并由下一轮 Context Compiler 读取。它不会伪装成 Evidence、Reflection 或工具结果写入领域事实。

### 5.10 JSON Checkpoint

相关文件：

- `opinion_search_agent/src/opinion_search/runtime/checkpoint.py`

Day 2 的初始 Checkpoint 根结构如下；当前 schema 已升级为 version 3，并增加不透明 `execution_profile`，详见 12.3：

```json
{
  "schema_version": 3,
  "execution_profile": "profile-<opaque-digest>",
  "state": {
    "run_id": "...",
    "status": "running",
    "domain_state": {},
    "active_step": {},
    "committed_steps": [],
    "committed_action_ids": [],
    "continuation_pending": false
  }
}
```

写入过程：

1. 将完整 Pydantic RunState 转成 JSON-safe payload；
2. 在目标目录创建临时文件；
3. 写入、flush 并对文件执行 `fsync`；
4. 使用 `os.replace` 原子替换目标 checkpoint；
5. 失败时清理临时文件，并抛出 typed `CheckpointWriteError`。

读取过程：

1. 读取并解析 JSON；
2. 验证根节点为 object；
3. 严格检查 `schema_version == 3`；
4. 检查 execution profile 与当前 app composition 兼容；
5. 检查 state payload 存在；
6. 使用传入的具体 Pydantic state type 完整重建和验证。

同步磁盘 I/O 通过 `asyncio.to_thread` 包装，避免阻塞 async AgentLoop。损坏文件、缺失字段和不兼容版本分别产生清晰的 checkpoint error。

### 5.11 Deterministic fake vertical slice

相关文件：

- `opinion_search_agent/src/opinion_search/models/contracts.py`；
- `opinion_search_agent/src/opinion_search/models/fake.py`。

Fake 组件不是临时 mock 拼接，而是 Day 2 离线 contract 的可替换实现：

- `MinimalContextCompiler` 从 RunState 产生结构化 FakeContext；
- `ScriptedModelClient` 按持久化 step index 返回 Decision；
- `FakeDecisionValidator` 检查 Gap 和 Candidate 是否存在，并验证 finish 声明与 State 一致；
- `FakeActionResolver` 在 finish 时调用 Completion Policy；
- `FakeActionExecutor` 按 action ID 缓存 Observation，并记录执行次数；
- `FakeObservationProcessor` 将 Observation 转成 OpinionSearchDelta；
- `FakeCompletionEvaluator` 从 committed finish Observation 中读取 verdict；
- `DeterministicIdFactory` 生成可跨进程重建的 step/action ID。

稳定 ID 形式：

```text
step_id   = {run_id}:step:{step_index}
action_id = {step_id}:attempt:{attempt}:action
```

### 5.12 三个关键崩溃窗口

相关测试：

- `tests/integration/test_checkpoint_resume.py`。

#### 窗口 A：ACTION_RUNNING 后崩溃

Checkpoint 已经保存 accepted Decision 和 stable ActionRequest，但工具尚未返回可恢复 Observation。

恢复行为：

- `classify_resume -> EXECUTE_ACTION`；
- 使用 checkpoint 中原来的 action ID；
- action 允许再次执行；
- adapter 应通过相同 action ID 尽可能复用或幂等处理结果。

#### 窗口 B：OBSERVATION_READY 后崩溃

工具结果已经完整保存，但 Reducer 尚未提交 State。

恢复行为：

- `classify_resume -> REDUCE_OBSERVATION`；
- 不再调用工具；
- 从保存的 Decision 和 Observation 重新生成 Delta；
- Reducer 应用后提交 step。

#### 窗口 C：STEP_COMMITTED 后崩溃

Domain State、committed step 和 committed action ID 已经保存，但 continuation 尚未应用。

恢复行为：

- `classify_resume -> EVALUATE_CONTINUATION`；
- 不重新执行 action；
- 不重新应用 Delta；
- 根据 committed finish 结果完成 run，或清除 pending 标记后打开下一 step。

### 5.13 Cancellation 与 safety limit

Loop 每轮根据持久化 State 检查 cancellation。取消时：

- run 进入 `cancelled`；
- active uncommitted step 被丢弃；
- 已 committed Domain State 保留；
- 产生 terminal RunResult；
- 保存 terminal checkpoint。

`max_steps` 是 Runtime safety config，不进入 SearchRequest。达到上限后：

- run 进入 `partial`；
- 已提交成果保留；
- stop reason 明确说明达到最大 committed steps。

### 5.14 Day 2 验证证据

新增或直接相关测试：

- `tests/unit/domain/opinion/test_state.py`；
- `tests/unit/domain/opinion/test_reducer.py`；
- `tests/unit/runtime/test_transaction.py`；
- `tests/unit/runtime/test_completion.py`；
- `tests/unit/runtime/test_checkpoint.py`；
- `tests/integration/test_offline_loop.py`；
- `tests/integration/test_checkpoint_resume.py`。

验证过的关键行为：

- Reducer 确定性、不可变、去重和 no-op；
- 完整五步离线 run 正常 completed；
- 过早 finish 被拒绝，rejection 在下一轮 context 中可见；
- max step 产生 meaningful partial；
- cancellation 保留已经 committed 的 State；
- ACTION_RUNNING 恢复保持相同 action ID；
- OBSERVATION_READY 恢复不重复执行 action；
- STEP_COMMITTED 恢复不重复 State effect；
- checkpoint 可以只依赖 JSON 和具体 state type 重建；
- 损坏文件和错误 schema version 被明确拒绝。

最终全量结果：

```text
207 passed in 0.28s
```

## 6. Day 3：Tool Runtime 核心

### 6.1 节点目标与范围

本节点把“执行工具”从某个具体 Fake handler 提升为独立 capability runtime。它解决的是：如何用稳定内部协议描述工具、如何在调用 adapter 前完成校验、由谁决定 timeout/retry，以及如何确保 provider 私有对象和异常不会泄漏到 AgentLoop 或 Domain State。

本次已经实现：

- provider-neutral Tool contracts；
- ToolRegistry；
- ToolExecutor；
- retry、timeout 和 cancellation 语义；
- deterministic Fake Search/Reader adapters；
- unit tests 和 adapter contract tests。

在核心完成后，Tool Runtime 又正式接入 Day 2 Harness；随后 Serper、Jina Reader 和 MCP adapter 在不修改 AgentLoop、transaction、checkpoint 与 Reducer 核心代码的前提下完成接入。

相关文件：

- `opinion_search_agent/src/opinion_search/tools/contracts.py`；
- `opinion_search_agent/src/opinion_search/tools/registry.py`；
- `opinion_search_agent/src/opinion_search/tools/executor.py`；
- `opinion_search_agent/src/opinion_search/tools/adapters/fake.py`；
- `opinion_search_agent/src/opinion_search/tools/capabilities/web.py`；
- `opinion_search_agent/src/opinion_search/domain/opinion/actions.py`；
- `opinion_search_agent/src/opinion_search/domain/opinion/action_resolver.py`；
- `opinion_search_agent/src/opinion_search/domain/opinion/processor.py`；
- `opinion_search_agent/src/opinion_search/app/action_executor.py`。

### 6.2 Tool contracts

#### ToolDefinition

`ToolDefinition` 保存一个 capability 的稳定身份：

- `name`：稳定名称，例如 `search.web` 或 namespaced MCP tool；
- `description`：模型可理解的用途；
- `capability`：Runtime 内部分类，例如 `search` 或 `read`；
- `input_model`：用于参数校验的 Pydantic model class。

`model_spec()` 只导出：

- name；
- description；
- input JSON schema。

它不会把 adapter 对象、capability metadata 或 provider 配置暴露给模型。

#### ToolCall

`ToolCall` 表示 Runtime 对 capability runtime 的稳定请求：

- `action_id`；
- `tool_name`；
- JSON-safe arguments。

ToolCall 的 action ID 来自 Day 2 的 ActionRequest identity。工具 retry 不得生成新的 action ID。

#### ToolInvocation

`ToolInvocation` 表示 Executor 对 adapter 的某一次尝试：

- 保留原 action ID 和 tool name；
- `attempt` 从 1 开始；
- arguments 已经被目标工具的 `input_model` 转换为强类型 Pydantic 对象。

这里的 attempt 是同一 Runtime action 内部的工具尝试次数，不是 Day 2 StepRecord 的 attempt。工具 retry 不会创建新的 Agent step。

#### ToolAdapterResponse 与 ToolResult

Adapter 成功时只返回 `ToolAdapterResponse`：

- JSON-safe normalized payload；
- 可选 artifact references。

Executor 再补充 action ID、tool name 和实际 attempts，形成最终 `ToolResult`。这样 adapter 无权改写 Runtime identity。

Payload 使用 Pydantic `JsonValue` 约束，任意 SDK response object、HTTP response 或自定义 provider object 不能直接进入 ToolResult。

#### ToolError

当前稳定错误种类为：

- `unknown_tool`；
- `invalid_arguments`；
- `timeout`；
- `rate_limited`；
- `server_error`；
- `authentication`；
- `permission`；
- `not_found`；
- `unreadable_content`；
- `cancelled`；
- `unknown_provider_error`。

`ToolError` 保存 action ID、tool name、稳定 kind、安全 message 和已经发生的 attempts。`retryable` 是可 checkpoint 的派生字段，由 error kind 计算；构造或恢复时如果传入不一致的值会被拒绝，provider 不能任意填写。

`ToolAdapterError` 是 adapter 向 Executor 报告已经正规化失败的异常边界。字段只有稳定 kind 和可安全反馈的 message；原始 provider exception 不会自动进入结果。

### 6.3 ToolRegistry

Registry 保存 `ToolDefinition -> ToolAdapter` 的进程内绑定，负责：

- 注册稳定工具名称；
- 拒绝重复注册；
- 按名称解析 definition 和 adapter；
- 未知名称抛出 typed `UnknownToolError`；
- 按名称排序，确定性导出 definitions；
- 可按内部 capability 筛选；
- 只导出 model-visible specs。

Registry 不负责 timeout、retry、provider normalization 或 State 更新。替换 Fake、HTTP 或 MCP adapter 时，Registry 和 Executor 的实现不需要改变。

### 6.4 ToolExecutor 固定流程

Executor 的执行顺序是：

```text
ToolCall
  -> Registry.resolve(tool_name)
  -> input_model.model_validate(arguments)
  -> construct ToolInvocation(action_id, attempt, typed arguments)
  -> asyncio timeout boundary
  -> adapter.invoke
  -> normalize success or failure
  -> retry decision
  -> ToolResult or ToolError
```

关键所有权：

- Registry 决定调用哪个 adapter；
- Pydantic input model 决定 arguments 是否有效；
- Executor 决定 timeout、retry 和 backoff；
- Adapter 只负责外部协议翻译和 provider error normalization；
- Agent 模型不决定底层 retry；
- Tool output 不修改 OpinionSearch State。

参数校验发生在 adapter 之前。未知工具或 invalid arguments 的 `attempts=0`，证明没有外部调用发生。

### 6.5 Retry decision table

当前默认 policy 支持 `max_attempts`、每次尝试的 `timeout_seconds` 和确定性指数 backoff base。

| ToolErrorKind | 是否自动重试 | 原因 |
|---|---:|---|
| `timeout` | 是，有限次数 | 临时网络或服务延迟可能恢复 |
| `rate_limited` | 是，有限次数 | 等待后可能恢复 |
| `server_error` | 是，有限次数 | 远端临时故障可能恢复 |
| `unknown_tool` | 否 | Registry/configuration 问题 |
| `invalid_arguments` | 否 | 重发相同参数不会改变结果 |
| `authentication` | 否 | 配置问题，重试无意义 |
| `permission` | 否 | 权限不会因立即重试而改变 |
| `not_found` | 否 | 相同资源当前不存在 |
| `unreadable_content` | 否 | 相同读取方式不会自动修复内容 |
| `cancelled` | 否 | 必须尊重取消 |
| `unknown_provider_error` | 否 | 错误语义未知，采取保守失败 |

每次 retry：

- 保持相同 action ID；
- ToolInvocation attempt 递增；
- 不创建新的 Agent step；
- 不修改 RunState；
- 只有最终 ToolResult/ToolError 才进入后续 Observation 边界。

### 6.6 Timeout 与 cancellation

每次 adapter invocation 都位于独立 `asyncio.timeout` 范围内。超时被正规化为 `ToolErrorKind.TIMEOUT`，并按 RetryPolicy 决定是否再次尝试。

外部对 Python task 的 cancellation 不会被 `except Exception` 吞掉，而是直接传播 `asyncio.CancelledError`。因此取消可以立即中断正在执行的 adapter 或 backoff，不会被误认为 provider failure 后继续 retry。

### 6.7 Unexpected provider failure boundary

如果 adapter 没有遵守合同而抛出未知普通异常，Executor 会：

- 将其正规化为 `unknown_provider_error`；
- 使用固定安全 message；
- 不把原始 exception message 放入 ToolError；
- 保守地不重试。

这避免 token、endpoint、SDK internals 或其他敏感 provider detail进入下一轮模型 Context。

### 6.8 Fake Search/Reader adapters

Fake Web adapters 使用与真实 HTTP Web adapters 相同的公开契约。

`FakeSearchAdapter`：

- 输入 `SearchArguments(query, max_results)`；
- 从确定性 query index 读取结果；
- 输出正规化 `SearchResults`；
- 未命中 query 返回成功的空 items，而不是异常；
- 按 `max_results` 截断。

`FakeReaderAdapter`：

- 输入 `ReaderArguments(url)`；
- 成功时返回 URL、title、content 和 artifact reference；
- 未知 URL 正规化为 `not_found`；
- 已标记不可读 URL 正规化为 `unreadable_content`。

`search.web` 和 `read.web` 的定义由 factory 产生，Fake adapter 本身不注册全局对象，也不依赖 AgentLoop。

### 6.9 Trust boundary

当前工具边界已经保证：

- arguments 在外部调用前验证；
- result payload 必须 JSON-safe；
- provider 原始对象不能进入 ToolResult；
- unexpected exception detail 不自动反馈模型；
- adapter output 只是 untrusted external data；
- ToolResult 尚不能直接更新 Domain State。

当前 Tool-backed 接线已经经过：

```text
ToolResult / ToolError
  -> ObservationEnvelope
  -> OpinionSearch Observation processor
  -> OpinionSearchDelta
  -> existing pure Reducer
```

### 6.10 验证证据

新增测试：

- `tests/unit/tools/test_contracts.py`；
- `tests/unit/tools/test_registry.py`；
- `tests/unit/tools/test_executor.py`；
- `tests/contract/test_fake_tool_adapters.py`。

新增 38 个测试，验证：

- stable name 与 strict schema；
- JSON-safe payload；
- computed retryability；
- duplicate/unknown registry behavior；
- deterministic schema export；
- adapter 前 argument validation；
- success normalization；
- timeout retry；
- rate-limit/server retry；
- non-retryable error；
- stable action identity；
- exhausted retry metadata；
- unexpected exception sanitization；
- task cancellation propagation；
- Fake Search/Reader contract。

全量结果：

```text
245 passed in 0.41s
```

同时通过 `python -m compileall -q src tests` 和 `git diff --check`。

### 6.11 Tool Runtime 与 Agent Harness 正式接线

接线后的完整执行路径为：

```text
AgentDecision
  -> state-aware validation
  -> OpinionSearchActionResolver
  -> ToolAction | ReflectAction | FinishAction
  -> AgentLoop wraps stable ActionRequest
  -> OpinionActionExecutor
  -> search/read: ToolCall with ActionRequest.action_id
  -> ToolRegistry / ToolExecutor / ToolAdapter
  -> ToolObservation containing ToolResult or ToolError
  -> ObservationEnvelope
  -> OpinionSearchObservationProcessor
  -> OpinionSearchDelta
  -> existing Reducer and commit_step
```

#### Stable Web capability schemas

`SearchArguments`、`SearchHit`、`SearchResults`、`ReaderArguments` 和 `ReadResult` 已从 Fake adapter 移到 `tools/capabilities/web.py`。这些是 Search/Reader capability 的内部正规化 schema，Fake、Serper 和 Jina 必须共同满足，而不是让 Domain 依赖某个 adapter 类。

#### Typed planned actions

OpinionSearch resolver 产生三类动作：

- `ToolAction`：只用于 `search/read`，保存 decision action、稳定 tool name 和 JSON-safe arguments；
- `ReflectAction`：保存 internal reflection 和目标 Gap；
- `FinishAction`：保存 Completion Policy 已产生的 verdict。

Resolver 此时不生成 action ID。AgentLoop 仍按照 Day 2 规则创建稳定 `ActionRequest.action_id`，随后 `OpinionActionExecutor` 用这个 ID 构造 ToolCall。这样 checkpoint 内只有一个 action identity，不需要修改 AgentLoop 接口。

#### Search 与 Read 的当前最小状态映射

Search ToolResult 经过 `SearchResults` 验证后，把每个 normalized URL 加入 `candidate_source_ids`。在完整 CandidateSource 模型尚未进入 State 前，当前最小实现临时使用 canonical URL 作为 candidate ID。

ReadDecision 将这个 candidate URL 传给 `read.web`。Read ToolResult 必须满足：

- tool name 为 `read.web`；
- normalized ReadResult URL 与 Decision 中的 candidate ID 完全一致。

满足后 processor 才产生 `mark_source_ids_read` delta。网页 content 和 artifact reference 仍保存在 committed Observation/ToolResult 中，不会由 ToolExecutor 直接写入 State。

#### Internal reflect 与 finish

`reflect` 和 `finish` 不经过 ToolRegistry：

- ReflectAction 产生 ReflectObservation，processor 验证内容仍与 accepted Decision 一致，再生成解决 Gap 和追加 reflection 的 delta；
- FinishAction 产生 FinishObservation，其 verdict 由 CompletionEvaluator 用于 continuation control，domain delta 是 no-op。

因此“所有 Action 都必须是 ToolCall”没有成为错误抽象。

#### ToolError feedback

ToolError 被保存在 committed ToolObservation 中，但 processor 产生 no-op domain delta：

- Tool failure 不伪造成 Candidate、Evidence 或 Reflection；
- step 仍然 committed，避免无限重放同一失败；
- minimal context compiler 将安全 ToolError message 放入下一轮 `last_tool_feedback`；
- Agent 可以在下一个逻辑 step 改变 query、URL 或行动方向。

#### 正式链路上的 crash semantics

新增测试重新证明：

- checkpoint 停在 `ACTION_RUNNING` 时，恢复后 ToolCall 使用 checkpoint 中同一个 `ActionRequest.action_id`；工具可能重新执行；
- checkpoint 停在 `OBSERVATION_READY` 时，ToolResult 已经持久化，恢复后不会再次调用 Search adapter，而是直接进入 processor/reducer；
- ToolResult 和 ToolError 都能经过 JSON checkpoint 在新进程语义下恢复。

#### Checkpoint round-trip 缺陷及修复

接线测试发现 `ToolError.retryable` 最初使用 Pydantic computed field：写 checkpoint 时字段会被序列化，但恢复时 `extra="forbid"` 会拒绝该字段。修复后它成为持久化的派生字段：加载时根据 kind 验证一致性，并拒绝被篡改或不一致的 retryability。

这说明 standalone Tool tests 不能代替 Harness checkpoint integration tests；能够返回 JSON 不等于能够完整恢复泛型 RunState。

#### 接线验证证据

新增测试：

- `tests/unit/domain/opinion/test_action_resolver.py`；
- `tests/unit/domain/opinion/test_processor.py`；
- `tests/integration/test_loop_with_tools.py`。

它们验证：

- search/read Decision 正确映射为 ToolAction；
- reflect/finish 保持 internal action；
- ToolCall 复用外层 ActionRequest action ID；
- Search/Reader 真实经过 Registry/Executor/Fake adapter；
- search result URL 进入 Candidate State；
- read result 只标记被请求的 Candidate；
- premature finish feedback 保留；
- ToolError committed、domain no-op 且下一轮 context 可见；
- ACTION_RUNNING 和 OBSERVATION_READY 的正式 Tool 恢复语义。

接线后全量结果：

```text
261 passed in 0.77s
```

### 6.12 HTTP transport、状态正规化与依赖边界

完成日期：2026-08-19。

新增文件：

- `opinion_search_agent/src/opinion_search/tools/http.py`；
- `opinion_search_agent/tests/unit/tools/test_http.py`。

`HttpTransport` 是 provider adapter 依赖的最小异步接口。真实实现 `HttpxTransport` 把 `httpx.Response` 转换成内部 frozen `HttpResponse`，只保留 status、普通 headers、可选 JSON body 和 text。Provider SDK/HTTP client 对象不会穿过 adapter boundary。

外层 `ToolExecutor` 已经拥有每次尝试的 timeout，因此 `HttpxTransport` 不再建立第二套相互竞争的 timeout/retry policy。HTTP status 的稳定映射为：

| HTTP status | ToolErrorKind |
|---|---|
| 401 | `authentication` |
| 403 | `permission` |
| 404 | `not_found` |
| 408 | `timeout` |
| 429 | `rate_limited` |
| 5xx | `server_error` |
| 其他非 2xx | `unknown_provider_error` |

错误 message 只包含 provider 名、正规化原因和 status code，不包含原始 response body，避免凭据、代理页或远端调试信息进入模型上下文。

项目 runtime dependencies 新增 `httpx>=0.28,<1` 与 `jsonschema>=4.23,<5`；没有引入供应商 SDK或 Agent framework。

### 6.13 公共 URL 正规化与边界

新增文件：

- `opinion_search_agent/src/opinion_search/tools/url.py`；
- `opinion_search_agent/tests/unit/tools/test_url.py`。

`normalize_public_url()` 统一执行：

- 只接受 HTTP/HTTPS；
- 拒绝 URL credentials；
- hostname 转小写和 IDNA ASCII；
- 删除默认端口和 fragment；
- 缺失 path 时补 `/`；
- 拒绝 localhost、非 global IPv4/IPv6，以及 `127.1`、十进制整数和十六进制等 legacy IPv4 literal 表达。

该函数用于 source identity 和读取边界，防止同一 URL 因大小写、默认端口或 fragment 被当成多个 Candidate，也阻止显式本地地址进入真实 Reader 请求。当前它不执行 DNS resolution，因此不是完整的网络层 SSRF 防护；DNS rebinding 和解析后私网地址检查属于未来真实 Environment/Sandbox 或 hardened transport 的责任。

### 6.14 Action-result cache 与外部副作用语义

新增或修改文件：

- `opinion_search_agent/src/opinion_search/tools/cache.py`；
- `opinion_search_agent/src/opinion_search/tools/executor.py`；
- `opinion_search_agent/tests/unit/tools/test_cache.py`；
- `opinion_search_agent/tests/unit/tools/test_executor.py`。

`InMemoryActionResultCache` 以 stable `action_id` 为索引，但命中时会比较完整 `ToolCall`。相同 action 和相同 call 返回第一次成功的 `ToolResult`；同一 action ID 被不同 tool/arguments 复用时抛出 integrity conflict，而不是静默返回错误结果。

Executor 的固定顺序变为：resolve -> arguments validation -> successful-result cache -> invoke/retry -> cache success。未知工具和非法参数仍在 cache/adapter 前失败。当前只缓存成功结果，不缓存临时错误；这样 retry/resume 可以重新尝试可恢复失败。缓存是单进程内实现，提供同一 Executor 生命周期中的重复调用去重，不宣称跨进程 exactly-once；崩溃后是否重放仍遵循 Day 2 checkpoint phase 语义。

### 6.15 Serper Search adapter

新增文件：

- `opinion_search_agent/src/opinion_search/tools/adapters/serper.py`；
- `opinion_search_agent/tests/contract/test_tool_adapters.py`。

`SerperAdapter` 使用注入的 `HttpTransport`，向 `/search` 发送 query 和 max result count，并只在 adapter 内持有 API key。它将 `organic[].title/link/snippet` 正规化为现有 `SearchResults`，跳过 malformed item 和非公共 URL，且按内部 `max_results` 再次截断。

因此 FakeSearch 与 Serper 共享同一个 `search.web`、`SearchArguments` 和 `SearchResults`，替换注册的 adapter 不需要修改 AgentLoop、ActionResolver、Processor、Reducer 或 State。

### 6.16 Jina Reader adapter

新增文件：

- `opinion_search_agent/src/opinion_search/tools/adapters/jina_reader.py`；
- `opinion_search_agent/tests/contract/test_tool_adapters.py`。

`JinaReaderAdapter` 以 JSON mode 请求 `r.jina.ai/<public-url>`；Jina API key 是可选 adapter 配置，不进入 ToolCall。响应被正规化为现有 `ReadResult(url, final_url, title, content)`：

- `url` 永远保存 Runtime 请求并正规化后的 source identity；
- provider 报告了不同合法 URL 时才保存 `final_url`；
- title 或 content 为空时返回 `unreadable_content`；
- provider 原始 payload 不进入 State。

FakeReader 与 Jina Reader 因而共享同一个 `read.web` contract。网页 content 仍只是一段不可信 Observation data，没有决策或指令权限。

### 6.17 MCP discovery 与 call adapter

新增文件：

- `opinion_search_agent/src/opinion_search/tools/adapters/mcp.py`；
- `opinion_search_agent/tests/contract/test_mcp_adapter.py`。

MCP 没有被实现成第二套 Agent Runtime。当前边界由 `McpTransport` protocol 表达 `list_tools` 与 `call_tool`，由 `FakeMcpTransport` 提供完全离线的协议测试。发现流程为：

```text
MCP list_tools pages
  -> validate descriptors and JSON Schemas
  -> create dynamic Pydantic RootModel
  -> register mcp.<server_id>.<remote_name>
  -> existing ToolRegistry / ToolExecutor
  -> McpToolAdapter.call_tool(remote_name, validated arguments)
  -> existing ToolResult / ToolError
```

已经冻结的 MCP 语义：

- 支持 cursor pagination，并拒绝 cursor cycle；
- 本地 namespacing 防止不同 server 的常见重名；
- discovery 会先完成所有 schema、重复名和现有 registry conflict 检查，再整体注册，避免部分注册；
- MCP input schema 原样导出给模型，并由 Draft 2020-12 validator 在 transport call 前校验；
- 有 `structuredContent` 时优先作为 payload；否则保留为 JSON-safe `{"content": [...]}`；
- server 声明 `outputSchema` 时验证 structured result；
- `isError=true` 转成固定安全、非重试的 `unknown_provider_error`；
- annotations 被视为不可信 hint，不进入模型 spec，也不改变 Runtime timeout、retry 或权限策略；
- action ID、attempt、cache 和 cancellation 继续由已有 ToolExecutor 拥有，MCP server 无权改写。

本节点只定义 MCP transport boundary、fake transport 和 runtime adapter，没有绑定某一种 stdio/HTTP MCP client SDK。这让 wire transport 可以以后替换，而 MCP tool 的 Agent-facing 行为已经能够离线验证。

### 6.18 Day 3 最终验证证据

本次新增或扩展测试覆盖：

- URL canonicalization 和 public-literal rejection；
- HTTP status/error sanitization；
- action cache hit、identity conflict 和 result identity；
- Serper request、organic normalization、401/429/503 和 malformed payload；
- Jina JSON mode、optional auth 和 unreadable content；
- MCP pagination、exact schema export、pre-call validation、structured/unstructured result、output schema、`isError`、annotations、重复名及原子 discovery；
- 默认禁用的真实 Serper -> Jina search/read smoke。

最终从独立 package 根目录执行：

```text
cd opinion_search_agent
pytest -q -W error
305 passed, 1 skipped in 0.51s

python -m compileall -q src tests
git diff --check -- . ../docs
```

唯一 skip 的明确原因是没有设置 `RUN_LIVE_TOOL_TESTS=1`。该测试还要求 `SERPER_API_KEY`，`JINA_API_KEY` 可选。本次没有把离线 fake HTTP contract test 冒充成真实联网成功。

## 7. Day 4：Context Compiler 与 Working Memory

### 7.1 节点目标与边界

完成日期：2026-08-20。

Day 4 解决工具结果和交互历史持续增长后，下一次模型调用应看到什么的问题。它没有引入无限 `messages.append()`，也没有让 Memory 成为第二份 State，而是建立：

```text
Committed Domain State
  -> pure Working Memory projection
  -> collect typed ContextSections
  -> Gap-aware deterministic selection and semantic deduplication
  -> section-boundary compaction
  -> trust-aware rendering and measurement
  -> bounded CompiledContext
```

本节点只消费当前最小 OpinionSearchState 中已有的 request、Gap IDs、Candidate URLs、read URLs 和 reflections。Evidence、Claim、Source 与结构化 contradiction 仍由 Day 5 增加，Day 4 没有为了未来提前修改领域 State。

相关实现文件：

- `opinion_search_agent/src/opinion_search/memory/models.py`；
- `opinion_search_agent/src/opinion_search/memory/projector.py`；
- `opinion_search_agent/src/opinion_search/context/models.py`；
- `opinion_search_agent/src/opinion_search/context/selector.py`；
- `opinion_search_agent/src/opinion_search/context/compactor.py`；
- `opinion_search_agent/src/opinion_search/context/compiler.py`；
- `opinion_search_agent/src/opinion_search/models/fake.py`。

### 7.2 Working Memory 是纯派生视图

`WorkingGoal` 完整保留 SearchRequest 的 question、topic、time range、focus、language 和 domain filters。`WorkingMemory` 保存：

- `state_revision`；
- stable goal；
- 第一个 open Gap 作为 `current_gap_id`；
- open/resolved Gap IDs；
- pending Candidate IDs；
- read source IDs；
- committed reflections。

Projector 的 pending candidates 通过 `candidate_source_ids - read_source_ids` 按原顺序计算。它不读取文件、网络、时间或进程 cursor，不保存 Tool payload、completion rejection 或 Runtime step。相同序列化 State 必须产生相同序列化 Memory。

Memory 模型还独立验证 tuple 唯一性、current Gap 必须等于首个 open Gap、pending/read 不得重叠。Checkpoint 没有新增 Memory 字段；resume 总是重新投影。

### 7.3 ContextSection 控制语言

Context 被拆成四层：

| Layer | 内容 | 当前策略 |
|---|---|---|
| L0 `l0_instructions` | Agent 身份、动作协议、外部内容不可信规则 | required、trusted、never compact |
| L1 `l1_task` | SearchRequest、Decision schema、Tool specs | required、trusted、never compact |
| L2 `l2_memory` | current/open/resolved Gap、Candidate、read sources、reflection | Gap-aware priority，可按 section 删除 |
| L3 `l3_recent` | bounded recent Decision、Observation、ToolError、finish rejection | 高保真窗口，按类型压缩或删除 |

每个 `ContextSection` 具有 stable ID、layer、title、content、0-100 priority、required、trust、provenance refs 和 compaction mode。Priority 表示信息价值，trust 表示内容边界；高优先级网页不会因此获得指令权限。

L0/L1 由模型 validator 强制 required、trusted、never compact。`ContextPlan` 保存最终 selected、dropped、compacted IDs 和测量结果，但只是当前模型调用的解释性计划，不是 trace event 或持久化平台数据。

### 7.4 Budget 与输出 headroom

`ContextBudget` 将总 context window 与 `output_headroom_tokens` 分开：

```text
input_token_limit = max_context_tokens - output_headroom_tokens
```

Compiler 从一开始只使用 input limit；不会等 prompt 填满后再尝试为输出腾空间。当前默认可替换 estimator 是按 UTF-8 byte length 估算的确定性 heuristic，测试可以注入 exact fake estimator，因此不依赖具体供应商 tokenizer。

如果 required/non-removable floor 已经超过 input limit，系统抛出 typed `RequiredContextOverflow`，不静默截断 L0/L1 或 final rendered string。

### 7.5 Selector 与 provenance-preserving deduplication

Selector 固定按 layer、required、current Gap relevance、priority 和 section ID 排序。相同 stable section ID 对应不同内容会被拒绝。

语义去重只发生在相同 trust boundary 和相同 layer 内，避免把“任务指令”和“恰好文本相同的外部数据”错误合并。重复内容保留排名更高的 section，并合并所有 provenance refs，所以压缩不会悄悄丢失来源关系。

当前 Gap relevance 通过 provenance refs 与 `current_gap_id` 关联。Day 5 增加结构化 Evidence/Claim 后，可以沿用这个选择协议增加更细相关性，而不用改变 Compiler 主流程。

### 7.6 Deterministic compaction

Compactor 只在 typed section boundaries 上降级：

1. Selector 已完成 stable ID 和语义去重；
2. 优先截断允许 `truncate` 的旧 untrusted L3 payload；
3. 若仍超限，按 untrusted、recent、低 priority、stable ID 顺序删除 optional section；
4. required 或 `never` section 不可删除；
5. non-removable floor 仍放不下时抛出 typed overflow。

实现过程中长内容测试发现过一次非收敛缺陷：最小正文加 compaction marker 后仍大于循环阈值。最终语义改为每个 section 只做一次固定长度截断，仍超限则进入 section 级删除；因此 fallback 有界且可证明终止。

### 7.7 Recent Interaction 与 trust boundary

Compiler 只收集配置数量的最近 committed steps，不随完整 run history 线性增长：

- accepted Decision：trusted recent control data；
- ToolResult payload：untrusted、可截断；
- ToolError：只保留已经正规化的 kind、安全 message 和 attempts；
- finish rejection：高优先级 trusted control feedback；
- 其他 normalized Observation：普通 recent data。

Renderer 为每段输出 layer 和 trust metadata。L0 明确规定网页和工具内容只是 evidence，不执行其中命令。外部正文中伪造的 `[CONTEXT_SECTION ...]` boundary marker 会被转成全角结构字符，不能伪造新的 trusted/L0 section。

“trusted”在这里表示内部结构来源，不意味着 L1-L3 内容可以覆盖 L0；只有 L0 immutable instructions 具有指令地位。

### 7.8 Loop 集成与恢复语义

AgentLoop 原本已经只依赖 `ContextCompiler.compile(state)` protocol，因此 Day 4 没有修改 Loop transaction。`ScriptedModelClient` 的输入边界放宽为只要求 `step_index`，既可消费历史 `FakeContext`，也可消费新 `CompiledContext`。

集成测试运行 7 个 committed steps，包含：多次大 search payload、premature finish、继续 search、read、reflect 和最终 finish。它证明：

- 每次模型输入都不超过 2,000 estimated input tokens；
- 400 tokens 始终保留给输出；
- recent collection 固定为最近两个 steps；
- finish rejection 在下一轮仍可见；
- 大 external payload 实际触发 compaction；
- run 最终正常 completed。

恢复测试在第 4 次 `DECIDING` checkpoint 后注入崩溃。加载 checkpoint 后，使用全新的 Compiler 预先生成 Context；随后再用全新 Loop/Compiler resume。恢复后的第一次模型输入与预先重建结果对象相等且 JSON byte-for-byte 相同。这证明恢复不依赖任何进程内 Memory cache。

### 7.9 Day 4 验证证据

新增测试和 fixtures：

- `tests/unit/memory/test_projector.py`；
- `tests/unit/context/test_models.py`；
- `tests/unit/context/test_selector.py`；
- `tests/unit/context/test_compactor.py`；
- `tests/unit/context/test_compiler.py`；
- `tests/integration/test_loop_context_growth.py`；
- `tests/fixtures/context/long_run.json`；
- `tests/fixtures/context/prompt_injection_page.json`。

最终验证：

```text
cd opinion_search_agent
pytest -q -W error
332 passed, 1 skipped in 0.64s

python -m compileall -q src tests
git diff --check -- . ../docs ../opinion_search_guide
```

唯一 skip 仍然是 Day 3 已明确 gated 的真实 provider smoke，与 Day 4 无关。

## 8. 当前已经冻结的核心决策

以下决策已经由实现和测试共同依赖，后续修改必须同步更新 contract tests 和本文件：

1. 使用 Python 和显式 async single-Agent loop；
2. RunStatus 与 StepPhase 分离；
3. Decision 不能直接执行，必须经过 validation 和 action resolution；
4. Decision、ActionRequest、Observation 和 StateDelta 是四个独立阶段；
5. Runtime correlation 使用 run ID、step ID、attempt 和 stable action ID；
6. Domain State 只能通过 pure Reducer 更新；
7. Working Memory 和 Context 以后只能是 State 的派生视图；
8. committed action set 提供 effectively-once state effect，不虚假承诺外部 exactly-once；
9. checkpoint 保存完整恢复状态，而不是仅保存 Domain State；
10. finish 是 proposal，必须经过 Completion Control；
11. completion rejection 是控制反馈，不是领域 Evidence；
12. hard max steps 属于 Runtime safety config，不属于 SearchRequest；
13. fake model 必须根据持久状态确定输出，不能依赖仅存在于内存的 cursor；
14. checkpoint 和 StepRecord 服务 Runtime recovery，不扩张为 Observability Infra。
15. ToolCall 保留 Day 2 产生的 stable action ID，retry 只递增 tool attempt；
16. ToolRegistry 负责发现和 adapter 绑定，ToolExecutor 负责 validation、timeout 和 retry；
17. 只有 timeout、rate limited 和 server error 默认自动重试；
18. provider output 必须先正规化为 JSON-safe ToolResult/ToolError；
19. Python task cancellation 必须立即向上传播；
20. ToolResult 仍是环境输入，不能绕过 Observation processor 和 Reducer 修改 State。
21. Search/Reader capability schema 独立于 Fake、HTTP 或 MCP adapter；
22. ToolCall 必须复用 AgentLoop 已生成的 ActionRequest action ID；
23. reflect/finish 是 typed internal action，不强制伪装成 ToolCall；
24. ToolError 进入 committed Observation 和下一轮控制反馈，但不进入领域事实；
25. ToolResult/ToolError 必须通过完整 RunState checkpoint round-trip。
26. Fake、Serper 和 Jina 共享 provider-neutral Web capability schemas，替换 adapter 不修改 Loop。
27. 外层 ToolExecutor 统一拥有 timeout/retry；HTTP transport 和 MCP transport 不建立第二套控制策略。
28. 同一 Executor 内，相同 ToolCall 的成功结果按 action ID 去重；identity conflict 必须显式失败。
29. MCP tool 必须 namespaced 注册，输入 schema 在 transport 前验证，annotations 不具有策略权限。
30. MCP 与 HTTP provider output 都是 untrusted Observation data，不能绕过 processor/Reducer。
31. Working Memory 只能从 committed Domain State 纯投影，不进入 checkpoint，也没有独立写入口。
32. Completion rejection 和 ToolError 属于 bounded Recent Interaction，不伪造成领域 Memory 事实。
33. L0/L1 是 required trusted non-removable sections；输出 headroom 在输入分配前扣除。
34. Priority 与 trust 是正交维度；高价值外部内容仍然不具有指令权限。
35. Semantic dedup 不能跨 layer/trust 合并，并且必须保留合并后的 provenance。
36. Context overflow 只能在 typed section boundaries 上降级；禁止截断最终 rendered string。
37. Resume 从 checkpoint State 重新投影 Memory 和 Context，相同输入必须得到相同 JSON。
38. Recent Interaction 使用固定 step window，Context 体积由 budget 而不是 run history 长度约束。

## 9. 当前已知限制

以下是当前实现边界，不代表缺陷已经修复或功能已经完成：

- Day 2 历史基线测试仍保留原 `FakeActionExecutor`；新的正式集成路径已经使用 ToolRegistry/ToolExecutor；
- Brave、Jina 和 `deepseek-v4-flash` adapter 已通过离线 provider contract tests；Brave→Jina tool smoke 已使用真实 provider 通过，完整 live Agent harness 已贯通并返回 meaningful partial；
- MCP 已有 discovery/call adapter 和 fake transport；具体 stdio/streamable HTTP client transport 尚未绑定；
- URL helper 拒绝显式非公共地址，但不执行 DNS 解析后的私网检查；
- action-result cache 当前为单进程内存实现，不提供跨进程副作用去重；
- Context Compiler 已完成 section allocation、budget、selection 和 compaction，但当前 estimator 是确定性 heuristic，不是特定模型的精确 tokenizer；
- Reader content 被确定性切分并按 focus 选择最多 8 个可定位 Evidence block；这不是语义抽取模型。Jina 正文现写入有 2MB 上限的内容寻址本地 artifact，Observation inline content 限为 64KB，通用 HTTP transport 流式接收上限为 2.5MB；未进入 inline 窗口的正文只能通过 artifact 审计，当前没有 artifact retrieval action；
- `source_kind`、Claim 和 StakeholderPosition 是模型 proposal 经引用完整性校验后的领域对象；本地规则可以验证 provenance 存在，不能仅靠字符串规则证明语义蕴含关系。`source_kind` 因此只是 untrusted analytic label，不能作为 Completion 的来源质量证明；
- RequiredContextOverflow 已接入 Runtime partial stop；极小 context window 下不会截断 L0/L1；
- checkpoint 原子替换针对单文件恢复，不是远程、多租户或分布式 checkpoint service；
- model/decision failure 最多进行配置数量的同 step retry；外部 action 尚未发生，因此 retry 增加 step attempt 并重新生成 action ID；
- terminal partial checkpoint 只保留 stop reason 和已经 committed 的成果，不新增 aborted-step history 或 Observability event store。
- 首次 `deepseek-v4-flash` live Agent 曾在 6 个 committed steps 后连续收到空 Decision并以 partial 安全停止；后续取消 provider 输出 token 硬限制、完成 Opinion Context V1 与 Evidence ID repair 后，真实 live run 已在 14 个 committed steps 后正常完成四个舆情维度。

## 10. Day 5 完成后的纵向闭环

Day 5 已用真实 OpinionSearch domain 把前四天机制串成以下纵向闭环：

```text
Search/Read Observation
  -> CandidateSource / Source / Evidence
  -> Claim support and contradiction
  -> InvestigationGap transitions
  -> Working Memory projection
  -> bounded CompiledContext
  -> CompletionPolicy and cited brief
```

当前已可从 CLI 运行 offline、live 和 resume。Offline fixture 在 10 个 committed steps 内读取 1 个 primary、1 个 reporting、1 个 analysis source，形成 3 个 Evidence、一个跨两来源支持的事实 Claim、一个同时具有 supporting/contradicting Evidence 的 contested attributed-statement Claim，以及一个有引用的 StakeholderPosition，最终生成 cited Markdown brief。

## 11. 面试复述基线

截至 Day 2，应能独立解释下面这段话：

> OpinionSearch Agent 的 Harness 用两层生命周期管理整个 run 和单步事务。模型只产生尚未被信任的 domain Decision；Runtime 校验后将其解析为带稳定 action ID 的 ActionRequest。执行结果先成为 Observation，再由 domain processor 生成 StateDelta，最后由 pure Reducer 作为唯一入口更新权威 State。每个可恢复边界都保存完整版本化 checkpoint，resume 只根据持久状态分类下一动作。稳定 action ID、committed action set 和幂等 Reducer保证 effectively-once 的本地状态效果，但不对外部服务虚假承诺 exactly-once。模型的 finish 只是 proposal，必须经过 Completion Policy，commit 后的 `continuation_pending` 则封住状态已经提交但完成判定尚未应用的崩溃窗口。

完成 Tool Runtime 核心后，还应能解释：

> ToolDefinition 描述稳定 capability，Registry 只负责名称到 adapter 的解析，Executor 才拥有参数校验、timeout、retry 和 cancellation 语义。一次 Agent action 的所有工具 retry 保持相同 action ID，只增加 ToolInvocation attempt。Adapter 只能返回 JSON-safe normalized response 或 typed safe error；未知异常会被清洗，工具输出仍然是不可信环境数据，必须经过 Observation processor 和 Reducer 才能影响领域 State。

完成 Day 3 后，还应能进一步解释：

> Brave、Jina 和 MCP 都只是统一 Tool Runtime 的 adapter。Brave/Jina 分别正规化到稳定 SearchResults/ReadResult；MCP discovery 把远端 JSON Schema 转成动态验证模型并以 server namespace 注册。HTTP/MCP transport 不拥有 Agent 控制流，timeout、retry、action identity 和成功缓存仍由 ToolExecutor 统一管理。外部内容和 MCP annotations 都是不可信输入，没有指令或策略权限。离线 contract tests 证明 adapter 可替换而 Loop 不变；真实 provider smoke 仍默认 gate，但已单独显式执行并保存验证结果。

完成 Day 4 后，还应能解释：

> Full State 是唯一权威事实，Working Memory 是 committed State 的确定性派生视图，Compiled Context 则只服务一次模型调用。Compiler 将信息分成 L0-L3，先预留输出 headroom，再按当前 Gap、priority、trust 和 provenance 选择内容。Compactor 只在 section boundary 上截断或删除 optional data，L0/L1 不会被网页正文挤出；外部 payload 即使优先级高也始终处于 untrusted section。Memory 不写 checkpoint，resume 后用相同 State 和配置重新编译，集成测试证明结果 JSON 完全一致且长轨迹 context 始终受固定 budget 约束。

完成 Day 5 后，还应能解释：

> Search snippet 只能创建导航用 CandidateSource；read 成功后，processor 才创建 Source 与带 source/gap/locator 的 Evidence。模型在 reflect 中只能用已存在的 Evidence ID 提议 Claim 和 StakeholderPosition，Reducer 再验证所有引用并作为唯一写入口合并支持与反驳关系。Finish 仍只是 proposal；CompletionPolicy 会检查 committed Gap、Source、Evidence、Claim 和 contradiction，最终 brief 只从 State 渲染引用、remaining gaps 和公开 Web 局限。`deepseek-v4-flash` adapter 只把 CompiledContext 转成一个结构化 Decision，空响应、拒答、畸形 JSON、timeout、rate limit、认证和错误请求都先正规化为 typed ModelError，再由 Runtime 决定同 step retry、partial 或 failed。

## 12. Day 5：OpinionSearch 深度整合、模型与应用入口

### 12.1 实现范围

完成日期：2026-08-20。

本节点新增或完成：

- rich `InvestigationGap`、`CandidateSource`、`Source`、`Evidence`、`Claim`、`StakeholderPosition` 和 `OpinionSearchDelta`；
- search/read/reflect Observation processor 与纯 Reducer；
- rich Working Memory projection 和 Context sections；
- OpinionSearch CompletionPolicy 与 `SearchOutcome` cited Markdown brief；
- OpenAI-compatible `/chat/completions` adapter，默认模型 `deepseek-v4-flash`；
- typed model failure、同 step decision retry 和 context-overflow/repeated-action stop；
- offline/live/resume app composition 与 `python -m opinion_search` CLI；
- deterministic opinion fixture、offline demo、resume demo、model contract 和 recovery matrix tests。

### 12.2 领域事实链与不变量

实现后的写入链是：

```text
SearchResults snippet
  -> CandidateSource
ReadResult content
  -> Source + deterministic focus-ranked Evidence blocks
Reflect proposal with existing Evidence IDs
  -> Claim / StakeholderPosition / Gap outcome delta
Pure Reducer
  -> authoritative OpinionSearchState
```

已经由模型与测试冻结的约束：

- Candidate/Source ID 使用 canonical requested URL，provider 私有 ID 不进入 Domain；
- Search result 在 Candidate 创建前执行公共 URL 正规化和 domain include/exclude host 过滤，exclude 优先；
- Source 必须来自已存在 Candidate，Evidence 必须引用 Source 和 Gap；
- Claim supporting/contradicting Evidence 不能重叠，status 由引用关系派生；
- Claim/ClaimProposal 不能没有任何 Evidence；零证据主张无法进入 State 或 brief；
- StakeholderPosition 至少引用一个已存在 Evidence；
- resolved Gap 必须有 source-backed Evidence，blocked Gap 必须保留原因；
- 相同 claim text 产生稳定 claim ID；同一 Claim 可以通过多个 reflect 合并 supporting/contradicting Evidence；
- search/query 和 read/source attempt 记录在对应 Gap，重复 query/URL 在 action 前被拒绝；
- Reflect 的 `next_focus` 经 Delta/Reducer 写入 `current_focus`，Working Memory 和下一轮 Context 从 committed State 确定性重建它；
- current Gap 从 open gaps 中按最高 priority 确定，tuple 顺序只用于同优先级稳定 tie-break；
- Working Memory 只投影 committed rich State，Evidence、Claim 和网页派生文本在 Context 中仍保持 untrusted；
- brief 不采用模型未提交的自由文本作为事实源，只从 State 的 Claim、Position、Evidence、Source 和 Gap 渲染。
- brief 对用户、模型和网页派生文本做 Markdown/HTML 转义，并对 link destination 单独编码 Markdown 分隔符；public URL normalizer 拒绝原始空白/控制字符并对 path/query 做 canonical percent-encoding。

### 12.3 模型边界与恢复语义

`OpenAICompatibleModelClient` 发送 CompiledContext、JSON Mode 和输出 headroom，使用 Pydantic discriminated union 解析一个 `AgentDecision`。当前错误正规化包括：

- empty、refusal、malformed、timeout、rate limit、server error：允许 bounded same-step retry；
- authentication、invalid request/configuration：不重试并安全失败；
- state-aware invalid decision：携带安全反馈进入同一 step 的下一 attempt；
- repeated query/read：停止为 meaningful partial，避免无信息增益循环；
- RequiredContextOverflow：保留已 committed State 并 partial stop；
- reducer/processor invariant：failed，不把不一致 State 写入 checkpoint。

模型、Brave 和 Jina 等携带 credential 的 endpoint 必须使用公开 HTTPS；只有模型 adapter 可以在显式 development opt-in 下连接 loopback HTTP。API key 不进入异常、State、checkpoint 或 artifact。

一次 decision retry 保持 `step_id`，增加 `attempt`；因为 Action 尚未开始，随后生成的 action ID 包含新 attempt。`StepRecord.failures` 随 active/committed step checkpoint round-trip，下一次 Context 将其编译成高优先级 trusted control feedback。

Checkpoint schema 当前为 version 3。存储外层包含由 app composition 计算出的不透明 execution profile ID：resume 会拒绝 offline/live 混用，也会拒绝模型或 tool composition 发生变化的 live checkpoint；具体 provider 名称、base URL 和密钥不进入 Runtime State 或 checkpoint 明文字段。

### 12.4 应用装配与 CLI

Offline 和 live builder 共享：

```text
AgentLoop
  + OpinionContextCompiler / WorkingMemory projector
  + OpinionSearchDecisionValidator
  + OpinionSearchActionResolver / CompletionPolicy
  + OpinionActionExecutor
  + ToolRegistry / ToolExecutor
  + OpinionSearchObservationProcessor / Reducer
  + JsonCheckpointStore
```

差异只在 adapter：offline 使用 ScriptedModel、FakeSearch、FakeReader；live 使用 `deepseek-v4-flash`、Brave Search 和 Jina Reader。CLI 的 offline、live、resume 没有 demo-only 执行旁路。密钥只从环境读取并使用 `SecretStr` 保存，`.env` 与 `.opinion_search/` 已加入 package `.gitignore`。

CLI 的 `--include-domain`/`--exclude-domain` 可重复使用；它们进入 SearchRequest 后由 processor 强制执行，而不是依赖模型自行生成 `site:` 查询。Live Jina adapter 将完整正文写入 checkpoint 同目录的 `artifacts/`，返回内容寻址 ref；checkpoint 中的 reader payload 只保留受限 inline 正文。

Opinion Context V1 的 CompletionPolicy 不再信任模型自报的 `source_kind`。它要求事实基线具有 fact Claim，四个语义维度分别由对应 Claim/Position/Narrative 支撑，并要求 semantic coverage 实际引用至少两个 distinct Source records；CONTESTED Claim 至少跨两个不同 URL-level Source record。当前多样性是 URL 记录级，而不是 publisher/entity 级，不能声称已识别转载联盟或共同原始出处。

### 12.5 验证证据

最终离线验证：

```text
pytest -q -W error
369 passed, 2 skipped in 2.20s

python -m compileall -q src tests
rg archive imports under src/tests -> no matches
```

两个 skip 是显式 gated 的真实测试：

- `RUN_LIVE_TOOL_TESTS=1`：Brave -> Jina search/read；安全修复后最新复验 `1 passed in 2.92s`；
- `RUN_LIVE_AGENT_TESTS=1`：`deepseek-v4-flash` 驱动完整 live Agent。

完整 live Agent smoke 已真实执行并得到 `1 passed in 113.34s`。其验收允许 complete 或 meaningful partial；本次实际是 partial：6 个 committed steps、4 个 Source、32 条 Evidence，停止原因为模型连续返回空 Decision并耗尽同 step recovery。默认全量测试仍将两项标记为 skip，是为了避免每次本地回归消耗外部额度，不代表未运行。

手工使用 Python 3.12+ 和 `PYTHONPATH=src` 运行 offline CLI，得到 completed brief；随后对同一 checkpoint 执行 resume，输出逐字一致。系统默认 `python` 指向 3.10 且 package 未安装时无法导入，这与 README 要求的 Python 3.12+ 和 editable install 前提一致。

### 12.6 Recovery Matrix 证据映射

| Failure | 当前行为 | 验证位置 |
|---|---|---|
| malformed/empty/refused model | typed error；同 step retry | model contract + recovery e2e |
| invalid candidate | trusted feedback；同 step repair | recovery e2e |
| duplicate query/read | partial stop before tool action | decision/recovery tests |
| tool timeout/rate/server | ToolExecutor bounded retry | Tool Executor tests |
| unreadable page | committed ToolError；不创建事实 | adapter/loop integration tests |
| provider response/artifact 超限 | 流式中止或 typed content-too-large；不创建事实 | HTTP/artifact/adapter tests |
| search 返回越界 domain | processor 丢弃，不能成为 Candidate | processor contract tests |
| 非 HTTPS credential endpoint | composition 时拒绝；loopback model 需显式 opt-in | model/tool adapter tests |
| provider 跨域 redirect | Tool HTTP transport 不自动跟随，credential 不发生第二跳 | HTTP transport tests |
| premature finish | CompletionPolicy rejection | offline/context integration tests |
| context overflow | partial with committed state | recovery e2e |
| action 前 crash | resume reuses stable action identity | checkpoint integration tests |
| observation 后、commit 前 crash | resume 不重复 tool call | checkpoint/tool integration tests |
| commit 后 crash | continuation resume 不重复 state effect | checkpoint integration tests |
| 关闭 Gap delta 重放 | exact replay 为 no-op，修改 closed Gap 失败 | reducer unit tests |
| 错误 execution profile resume | checkpoint load 前拒绝，不调用 provider | checkpoint/CLI tests |
| Markdown payload 注入 brief | 字段转义，保留纯文本证据 | brief unit tests |
| cancellation | cancelled with committed state | offline loop tests |
| hard step limit | partial with committed state | offline loop tests |

### 12.7 下一步

Day 5 的确定性离线闭环已完成，真实 provider 调用链也已贯通。后续应优先改善真实模型从 read 转向 reflect/finish 的稳定性，再观察查询策略、来源分类和 completion 质量，而不是继续增加模型路由、Eval 平台或其他 Infra 层。

### 12.8 Brave Search 切换与真实验证

2026-08-20 将 live search composition 从 Serper 切换为用户已有的 Brave Search API：

- 新增 `BraveSearchAdapter`，调用官方 `/res/v1/web/search`，使用 `X-Subscription-Token`；
- `web.results[].title/url/description` 正规化为 provider-neutral `SearchResults`；
- endpoint、HTTP error、malformed payload、非公共 URL 和 result limit 均有 contract tests；
- `LiveConfig` 改为要求 `BRAVE_SEARCH_API_KEY`，同时兼容已有 `OPINION_MODEL_BASEURL` 拼写，标准名 `OPINION_MODEL_BASE_URL` 优先；
- live execution profile 升为 `opinion-search-live-v3`，防止旧 provider composition 的 action-running checkpoint 被错误恢复；
- Jina API key 保持可选，实际 smoke 使用无 Key Jina 成功读取正文。

真实证据：Brave→Jina 工具链安全修复后最新复验 `1 passed in 2.92s`；`deepseek-v4-flash + Brave + Jina` 完整 Agent harness test `1 passed in 113.34s`，实际 Outcome 为 meaningful partial。凭据值没有打印、写入 checkpoint、artifact、trace 或文档。

Brave 使用自定义 `X-Subscription-Token`。审查发现 HTTPX 自动跨域 redirect 不会像 `Authorization` 一样移除该 header，因此通用 Tool HTTP transport 改为 `follow_redirects=False`；3xx 由 adapter 正规化为 provider error。MockTransport 回归测试证明不会发生携带 token 的第二跳。

### 12.9 空 Decision 诊断

为区分 provider 连通性故障和推理模型的输出预算问题，先对实际 OpenCode Go `deepseek-v4-flash` endpoint 连续执行 3 次最小结构化 Decision 请求。三次均为 HTTP 200、`finish_reason=stop`，且 `content` 都包含可由 `AgentDecision` schema 解析的 JSON；因此 API key、base URL、模型 ID 和 JSON Mode 的基础配置可用。

随后用持久 checkpoint 重新执行完整 live Agent，稳定复现空 Decision。provider 的安全元数据显示：

```text
finish_reason='length'
content_state=blank
reasoning_chars=8800
prompt_tokens=28087
completion_tokens=2000
```

结论：这不是认证、endpoint 或 HTTP API 失败，而是当前 live 配置给模型 2,000 个 completion token；长上下文下，推理模型把整个输出额度耗在 reasoning，达到 length stop 时没有生成最终 `content`，adapter 因而无法取得 Decision JSON。`reasoning` 不能被当作可执行 Decision：它既不满足领域 schema，也不应进入 State、trace 或错误日志。

为让后续故障可判定，model adapter 的 empty-response 错误现在只保留安全元数据：finish reason、content 是 null/blank、reasoning 字符数和 prompt/completion token 数，不保存 reasoning 正文、原始 provider body 或凭据。对应 contract test 已覆盖该安全边界。下一步修复应同时增加推理模型的输出 headroom、压缩输入上下文，并为 length-stop 设计更短的同 step repair prompt；不能只做盲目重试。

### 12.10 不设置 provider 输出上限的 live 实验

按用户决定，OpenAI-compatible 请求不再发送 `max_tokens` 或 `max_completion_tokens`；`output_headroom_tokens` 仍只用于 Context Compiler 的输入预算，为模型输出保留窗口空间。这里的“不限制”表示本项目不再施加 2,000-token 硬上限，provider 和模型自身仍可能实施上下文或生成上限。对应 request-body contract test 明确断言两个限制字段都不存在。因为模型调用语义发生变化，live execution profile 升为 `opinion-search-live-v4`，避免旧 action-running checkpoint 在不同参数语义下恢复。

真实完整运行不再出现空 Decision，并成功从 read 阶段生成结构化 reflect Decision，验证了此前的空响应确由 2,000 completion token 截断导致。本次运行在 5 个 committed steps（1 search、4 read）后进入 reflect，形成 5 个 Candidate、3 个 Source 和 24 条 Evidence；Evidence 覆盖 `gap-primary` 8 条、`gap-independent` 16 条，但没有覆盖 `gap-narrative`。最终一次 reflect 提议至少包含了缺少 Evidence 的 `gap-narrative`，state-aware validator 正确拒绝，最终以 `Decision recovery was exhausted: reflect decision resolves a gap without evidence` meaningful partial 结束。该结果表明下一问题位于 reflect 决策反馈的精确性和模型的 gap/evidence 对齐，而不是模型 API 或输出长度。

### 12.11 Reflect 的 Gap–Evidence 对齐复核

使用上述 terminal checkpoint 构造等价的 step 6 / attempt 2 deciding state，并用生产配置重新编译 Context，得到以下只读证据：

```text
estimated_input_tokens=23155
selected_sections=49
dropped_sections=0
compacted_sections=0
evidence_sections_selected=24/24
evidence_ids_visible=24/24
failure_feedback_visible=true
gap-primary evidence=8
gap-independent evidence=16
gap-narrative evidence=0
```

因此本次失败不是 Context Compiler 丢失 Evidence，也不是模型看不到上一 attempt 的错误。现有上下文把每条 Evidence 的 `gap_ids` 逐项提供给模型，但没有提供确定性的 Gap→Evidence 覆盖摘要；现有 validator 反馈也只有 `reflect decision resolves a gap without evidence`，没有返回具体 missing gap、eligible gap 或纠正动作。第二次 attempt 需要在 24 条 Evidence 中自行重新聚合这一结构关系，修复信号不足。

下一步应保持 validator 的证据门禁不变，并增强 harness/context：生成确定性的 Gap→Evidence ID 索引；让 Reflect schema 明确 `target_gap_ids` 只能取覆盖数大于零的 open gaps；让 validator 错误返回 missing gap IDs 和当前 eligible gap IDs。之后用 contract test 验证反馈不包含 Evidence 正文，再执行一次 live run 观察是否能提交 reflect 并进入 finish。

## 13. Opinion Context V1：舆情语义重构

### 13.1 问题与边界

2026-08-21 根据真实 live failure 重新审视 workload：原 Context 与领域状态仍接近通用 Research Agent，使用 `ReadDecision.target_gap_id` 直接填充 `Evidence.gap_ids`。这混淆了“为什么读取来源”和“正文实际说明什么”。一篇为独立报道而读取的页面可能同时包含事实、主体立场、主流叙事和反叙事；旧模型却把全部 excerpt 强制归入唯一 acquisition Gap。

本节点保留 Agent Loop、四动作空间、Tool Runtime、transaction 和 checkpoint/resume，只重构 OpinionSearch domain、Working Memory、Context 和 Completion。实施计划保存在 `docs/superpowers/plans/2026-08-20-opinion-context-v1.md`。

### 13.2 新领域关系

默认调查维度改为：

- `gap-factual-baseline`：可验证事实与事件基线；
- `gap-stakeholder-positions`：主体公开立场；
- `gap-dominant-narratives`：dominant 或 emerging framing；
- `gap-counter-narratives`：批评、反叙事和实质分歧。

来源独立性不再作为一个伪装成问题的 Gap，而是 Completion quality gate。

新关系为：

```text
Search/Read target_gap_id
  -> acquisition intent
ReadResult
  -> Evidence(source, excerpt, locator, acquired_for_gap_id)
Reflect
  -> GapAssessment(evidence IDs, outcome, rationale)
  -> Claim / StakeholderPosition / Narrative
Reducer
  -> InvestigationGap.evidence_ids semantic coverage
```

`Narrative` 是独立于事实 Claim 的观察对象，kind 为 `dominant`、`emerging` 或 `counter`，并必须引用 Evidence。它表示公开 framing 的存在，不表示该 framing 为真。

### 13.3 Reflect 与校验

旧 `target_gap_ids`/`blocked_gap_ids` 被显式 `GapAssessmentProposal` 取代。每个 assessment 包含 gap ID、`open/resolved/blocked` outcome、Evidence IDs 和 rationale。resolved 必须有 Evidence；所有 ID 必须已经存在于 committed State。

对四个默认舆情维度还施加 semantic record gate：

- factual baseline resolved 必须由 fact Claim 的 Evidence 支撑；
- stakeholder positions resolved 必须由 StakeholderPosition 的 Evidence 支撑；
- dominant narratives resolved 必须由 dominant/emerging Narrative 支撑；
- counter narratives resolved 必须由 counter Narrative 支撑。

validator feedback 只返回 unknown/known opaque Evidence IDs、缺少的 semantic record 和 eligible dimension IDs，不返回网页 excerpt、模型 reasoning 或 credential。

### 13.4 Opinion Working Memory 与 Context

Projector 为每个 Gap 生成确定性的 coverage cell：status、semantic Evidence IDs 和 distinct Source IDs。Compiler 在单条 Evidence 前提供整张 opinion coverage map。模型提出的 SourceKind 不进入 trusted coverage，因为“已经 commit”不等于“已经由 Runtime 验真”。

为防止模型把稳定哈希 ID 改写成 `evidence-25` 等顺序别名，Context 还包含一个可信 Evidence ID catalog。该 catalog 只包含 runtime 生成的 opaque Evidence ID 和 acquisition gap ID，不包含 URL、excerpt 或其他外部文本；网页 Evidence 仍处于独立 untrusted sections。L0 明确说明 acquisition provenance 不等于 semantic coverage，并要求逐字复制 Evidence ID。

Context 的信任边界进一步按内容来源拆分：Gap status、Evidence ID、Source ID、attempt count 和引用关系是 trusted structural metadata；模型产生的 search query、current focus、reflection、Gap resolution rationale、历史 accepted Decision prose 与 Reflect observation 即使已经 commit/checkpoint/resume，也仍处于 untrusted section。查询历史会保留给 Agent 避免重复搜索，但单独渲染为 untrusted；新增测试通过真实 Delta→Reducer→JSON resume 路径证明恶意文本在恢复前后不会进入任一 trusted section。

### 13.5 Completion 与 Brief

Complete outcome 现在要求：四个默认维度均 resolved；factual baseline 有 fact Claim；stakeholder、dominant narrative 和 counter narrative 均有与该 Gap Evidence 相交的语义对象；semantic coverage 至少引用两个 distinct Source records；contested Claim 保持跨 URL-level Source 多样性。`ReadDecision.source_kind` 保留为分析标签，但不参与完成授权。

Reducer 对相同稳定 `position_id` 的新 Evidence 做确定性 union，使模型补充立场 provenance 不会触发 identity conflict；相同稳定 `narrative_id` 若被改成另一 kind，则由 state-aware validator 在 action 前拒绝并作为同 step decision repair，而不是落到 Reducer 后把整个 run 标成 FAILED。对应 recovery test 已验证第一次冲突、第二次修复能够正常提交。

Brief 新增 `Public narratives` 与 `Opinion coverage`，分别展示 framing 及其 citations、每个调查维度的状态和语义 Evidence 来源。输出仍明确只总结可访问的 public-Web source，不推断全网情绪比例、触达或传播规模。

### 13.6 Checkpoint 与执行兼容性

领域 checkpoint JSON 形状发生变化：`Evidence.gap_ids` 变为 `acquired_for_gap_id`，Gap 增加 semantic `evidence_ids`，State 增加 Narrative，Reflect 与 Delta 改为 GapAssessment。因此 checkpoint schema 升为 4；offline execution profile 升为 v2，live profile 升为 v5，旧 checkpoint 会在 load 边界明确拒绝，不进行隐式迁移或错误恢复。

### 13.7 真实验证

第一次 Opinion Context V1 live run 已能提交 3 次 reflect，产生 5 个 Claim、1 个 StakeholderPosition 和 1 个 dominant Narrative，但最终把 opaque Evidence ID 改写成 `evidence-25` 等编号而 partial。这证明 acquisition/semantic 分离生效，同时暴露 ID 可复制性问题。

加入精确 Evidence ID catalog、L0 舆情语义规则和 known-ID repair feedback 后，第二次真实 `deepseek-v4-flash + Brave + Jina` run 完成：

```text
status=completed
committed_steps=14
candidates=10
sources=4
evidence=32
claims=10
stakeholder_positions=2
narratives=3
reflections=4
gap-factual-baseline=resolved (16 evidence)
gap-stakeholder-positions=resolved (2 evidence)
gap-dominant-narratives=resolved (3 evidence)
gap-counter-narratives=resolved (6 evidence)
```

三类 Narrative 为 dominant、emerging 和 counter。32 条 Evidence 的 acquisition provenance 主要仍是 factual baseline（24）和 counter-narratives（8），但 semantic Gap coverage 跨越四个维度，直接验证了两种关系已经分离。Offline run 完成且 resume outcome 逐字一致。

### 13.8 审查收口与最终验证

Opinion Context V1 完成后进行独立 Critical/Important review，发现并收口三类信任与恢复问题：

1. Completion 曾信任模型提出的 `source_kind`，且可能统计未参与语义结论的来源。现在完成门槛只统计被 Gap semantic Evidence links 实际引用的 distinct Source records，至少需要两个；未链接的第二 Source 不能满足门槛。
2. committed reflection、current focus、resolution rationale、历史 Decision prose 和 attempted search query 曾有被提升为 trusted context 的风险。现在 trusted 区只保留 Runtime 确定的 status、ID、relation 和 count；所有模型/网页派生文本跨 commit、checkpoint 与 resume 均保持 untrusted。
3. 相同 Position/Narrative 身份的补充或冲突曾可能在 Reducer 才报错并终止 run。现在 Position Evidence 做确定性合并，Narrative kind conflict 在 state-aware decision validation 阶段拒绝并同 step retry。

最终验证证据：

```text
ruff check src tests
All checks passed!

pytest -q -W error
375 passed, 2 skipped

python -m compileall -q src tests
passed

existing live checkpoint + current CompletionPolicy
accept_complete
```

两个 skip 是显式 gated 的真实 Tool/Agent provider smoke，不是失败。已完成最终复核，未发现残余 Critical 或 Important 问题。
## 14. Runtime Recovery 加固（深化主线 A）

实施计划：[`superpowers/plans/2026-08-21-runtime-recovery-hardening.md`](./superpowers/plans/2026-08-21-runtime-recovery-hardening.md)。以下全部是已进入仓库并通过验证的事实。

### 14.1 ActionResolver 失败的同 step 修复

新增事务函数 `repair_accepted_decision(state, failure)`：仅接受 `DECISION_ACCEPTED` phase，返回同 run/step、`attempt+1`、phase=DECIDING 的新 StepRecord，rejected Decision/Action/Observation 通过整步重建清除，prior failures 保序追加。`AgentLoop` 的 `RESOLVE_ACTION` 分支把 ActionResolver 的 `ValueError` 归一为 `INVALID_ACTION`，走与 model/validation 修复相同的最大决策尝试策略：未耗尽则 repair 回 deciding，耗尽时若已有 committed step 则 `partial`、否则 `failed`。观察与 Reducer 错误保持 fail-closed：仍有处理器/Reducer 异常必 terminal `FAILED` 的断言测试。

验证：`test_repair_accepted_decision_*`、`test_invalid_action_repairs_same_step_and_commits_attempt_two`（一个 committed step、attempt=2、首失败 kind=invalid_action、attempt 1 未触发 executor、run 非 failed）、`test_invalid_action_exhausted_without_committed_step_fails_run`、`test_processor_failure_is_terminal_failed`、`test_reducer_failure_is_terminal_failed`。

### 14.2 跨进程 JsonActionResultCache

新增 `tools/persistent_cache.py::JsonActionResultCache(directory)`，实现既有 `ToolResultCache` 协议，不改 `execute()`/adapter 签名。每 action_id 一个条目，文件名 = `sha256(action_id UTF-8)` + `.json`，任意 action_id 都不能成为路径。payload 仅 `schema_version/action_id/call/result`，UTF-8、sort_keys、compact，先写临时文件再 flush+fsync+`os.replace`。读取校验根对象、schema_version、action_id、ToolCall、ToolResult；损坏/截断升为类型化 `ToolCacheReadError`（不会伪装成 miss）；stored call/result 身份不匹配升为 `ToolCacheConflictError`。相同条目 put 幂等；同 action 不同条目冲突不覆盖。get/put 用进程内 `asyncio.Lock`；只保证单机原子性，不承诺两进程并发调用同一未缓存 action 的互斥（已写入 docstring）。offline/live service 均在 `checkpoint_path.parent/"action_results"` 构造该 cache 注入 ToolExecutor；checkpoint 与 cache payload 不会携带 provider credential（断言校验键集合）。

### 14.3 ACTION_RUNNING 跨进程恢复复用结果

`tests/e2e/test_action_running_recovery.py` 显式构造 `ACTION_RUNNING` state：先经 cache-backed executor 执行该 ToolCall 一次（计数 adapter 调用 1），**不**把 Observation 写入 state（模拟 cache 写后、`OBSERVATION_READY` checkpoint 前的崩溃），用 `JsonCheckpointStore` 持久化，再用全新进程的 registry/adapter/executor/cache/loop resume。断言：fresh adapter 调用 0；committed step 记录含 cached ToolResult 的 Observation；action ID 与 ACTION_RUNNING 一致；reduction 只 commit 一次；revision 只递增一次；cache 条目不变；resume 结果与未中断 control run 的 status/revision 一致。负向：同 action_id 不同参数命中 cache identity conflict 且不触发 adapter。文档明确这是 at-most-once 复用已持久化成功，不声称通用 exactly-once。

### 14.4 异步取消

新增 `runtime/cancellation.py`：`CancellationSignal`(is_cancelled/wait_cancelled)、`EventCancellationSignal`(幂等 cancel)、`NeverCancelledSignal`，替换原同步 `CancellationCheck`，不再保留两套取消机制。`AgentLoop` 用 `_await_operation` 私有助手包裹一次 model 与一次 ActionExecutor await 的竞态：已取消则直接取消；否则 create op task + cancel-wait task，`FIRST_COMPLETED`；取消胜出则 cancel op task 并 await 其结束（只抑制 `CancelledError`），run 走 `cancelled` 终态；否则取消 wait task、返回 op 结果或传播其类型化异常。不捕获 `BaseException`。验证：取消于 model 调用前（model 调用数 0）、model 阻塞中（op task 被取消、无 decision accepted）、tool adapter 阻塞中（无 Observation/Delta 提交）、正常完成不取消、已提交 step 后取消保留 committed Domain State、terminal checkpoint 重载仍 `cancelled` 同 stop_reason；`-W error` 下无 pending task 告警。本实现只取消本地协程，不声称远端回滚。

### 14.5 Terminal Run Bundle

新增 `app/run_bundle.py::RunBundleWriter(checkpoint_path)`：`write_report(outcome) -> Path`，目标始终 `checkpoint_path.parent/"report.md"`，与 checkpoint 相同原子写语义；不复制 `artifacts/`；只写 `SearchOutcome.markdown`（+ 一个终止换行），不序列化任何配置/secret。CLI（offline/live/resume）在输出 markdown 前先原子写 report，并把报告路径打到 stderr；exit code 语义不变。验证：offline 创建 run.json/report.md（reader 有 artifact 时另有 artifacts/）、resume 重写字节一致、report 内容等于 markdown+尾换行、写失败返回 `RunBundleError` 且不破坏既有 report、成功后无 `.tmp` 残留、report 不含配置 serialization。实际 `PYTHONPATH=src` 下 offline CLI 演示：run.json、report.md、action_results/ 生成，resume stdout 与 report 字节逐字一致，exit 0。

### 14.6 Recovery Matrix

`tests/e2e/test_recovery_matrix.py` 扩为显式覆盖每行（CREATED→start run、RUNNING 无 step→open、OPENED/DECIDING→call model、DECISION_ACCEPTED→resolve 不重叫 model、ACTION_RUNNING cached→reuse 不触发 adapter、cache miss→执行只读 tool 不换 action ID、OBSERVATION_READY/REDUCING→build/replay delta 不调用 tool、COMMITTED+continuation→评估完成不重放 reducer、terminal→直接返回不调用组件），逐行断言组件调用数/step ID/attempt/action ID/revision/终态。既有 `test_checkpoint_resume.py`（ACTION_RUNNING、OBSERVATION_READY、STEP_COMMITTED）与 `test_loop_with_tools.py` 继续通过作为补充。

### 14.7 验证证据与边界

```text
pytest -q            419 passed, 2 skipped (live-gated)
ruff check src tests All checks passed!
compileall -q src tests  passed
offline CLI+resume   report.md / stdout 字节一致
checkpoint schema    CHECKPOINT_SCHEMA_VERSION 保持 4，未改 execution profile
```

未覆盖/限制：JsonActionResultCache 单机原子性（不提供跨进程分布式锁）；取消不承诺远端回滚；report 是 terminal Domain State 的确定性投影，可被覆写。下一主线 Tool/MCP 依赖本线稳定的 action identity、failure ownership 与恢复边界。
## 15. Tool / MCP 可靠执行（深化主线 B）

实施计划：[`superpowers/plans/2026-08-21-tool-mcp-reliability.md`](./superpowers/plans/2026-08-21-tool-mcp-reliability.md)。官方 MCP SDK v2，实际解析版本 `mcp==2.0.0`（依赖声明 `mcp>=2,<3`）。以下为已进入仓库并验证的事实。

### 15.1 Registry provider binding 契约

新增 `tools/routing.py`：`ProviderId`（`^[a-z][a-z0-9_-]*$`，1..64）、`ProviderBinding(provider_id, adapter)`、`RegisteredTool(definition, providers)`。`ToolRegistry.register(definition, adapter)` 保持兼容（provider id `default`）；新增 `register_provider(definition, provider_id, adapter)`。规则：首个 provider 创建工具；同一工具后续 provider 仅允许 ToolDefinition 完全相等；同名不同定义或同一 provider id 重复抛 `DuplicateToolError` 且不产生半注册；`definitions()`/`model_specs()` 每工具只返回一份（多 provider 字节一致）；`resolve()` 返回定义与全部 provider bindings；provider id/adapter 不进入 model specs。

### 15.2 Retry/fallback/circuit 责任归属 Executor

`RetryPolicy.max_attempts` 显式改名为 `max_attempts_per_provider`，新增 `max_backoff_seconds>0`；backoff = `min(base*2^(local_attempt-1), max_backoff_seconds)`；`ToolAdapterError` 增加可选 `retry_after_seconds>=0`（不进 safe message），delay=`min(max(exp, retry_after), max_backoff)`。

`ToolExecutor` 现在拥有：参数校验 → 缓存查找 → 每个 provider（按注册序）：circuit gate → 同 provider 至多 `max_attempts_per_provider` 次（仅 timeout/rate_limited/server_error 重试，含 backoff）→ 成功写缓存并 close circuit → 失败按 frozen fallback 表决定 stop-immediately / 下一 provider。`ToolInvocation.attempt` 是全局物理调用计数；`ToolResult/ToolError` 的 `attempts` 为总物理次数；`action_id` 跨 provider/retry 恒定；`CancelledError` 不捕获原样向上传播；cache identity conflict 是编程错误不转 ToolError；fallback 不产生新 step/action。新增 `tools/circuit.py`：`ProviderCircuitBreaker`（in memory、注入单调时钟、按 tool/provider 独立）、仅 timeout/rate_limited/server_error/unknown_provider_error 计入并可能 open；auth/permission 不 poisoned；closed→open→half-open(单探针)→success 复位/失败重 open。Circuit 只在内存，进程重启即重置，非 Domain State/checkpoint。

### 15.3 MCP discovery allowlist + schema pin

`register_mcp_tools(registry, transport, *, server_id, bindings)` 现在必须显式给 `tuple[McpToolBinding, ...]`（remote_name、local_description、capability、expected_input_schema_sha256、可选 expected_output_schema_sha256）。本地名仍 `mcp.<server_id>.<remote>.<name>`；local description 只来自 app config，绝不取 remote。`canonical_schema_hash` = UTF-8、sort_keys、compact JSON 的 SHA-256（hex）。发现严格原子：分页完所有页并检测 cursor 环 → 拒绝重复 remote name → 校验 allowlist 每个 remote 恰好出现 → 校验 schema 与 hash（不匹配只报 remote name + expected/actual hash，不带 schema body）→ 检查 Registry 冲突 → 全部通过才一次性注册；任何失败 Registry 字节级不变。annotations/remote description/content/`_meta` 无策略权威，annotations 被排除、远程 prose 不进 ToolDefinition。

### 15.4 官方 SDK v2 stdio transport

新增 `tools/adapters/mcp_sdk.py`：`McpStdioConfig`（command/args/cwd + 显式 `env: dict[str, SecretStr]`，不继承整个进程 env）、`McpHttpConfig`（streamable_http，公开 HTTPS 或 dev 标记下的 loopback HTTP）、`SdkMcpTransport` 实现既有 `McpTransport` 协议，每个 `list_tools`/`call_tool` 用 `mcp.Client`（v2 高层 API，非 `ClientSession`）开一个客户端上下文、映射一页/一次调用后关闭，明确不支持状态化 session 复用。stdio 用 `stdio_client(params)` 作为 Transport 传入 `Client`；content blocks 经 `model_dump(mode="json")` 校验为 JsonValue；SDK 连接/协议错误归一为安全 `McpToolDiscoveryError`/`ToolAdapterError`，不泄露 command env、headers、响应体或异常 repr。本地 fixture `tests/fixtures/mcp/read_only_server.py` 用 `MCPServer` 暴露一个只读 `search_fixture`，经真实 stdio discover/call 全链路验证，并回显 allowlist env token 与进程 env 是否泄漏。已确认 `mcp==2.0.0` 的 `ListToolsResult`/`CallToolResult`/`Client` 字段形态后实现；不使用 v1 符号。

### 15.5 MCP 经 Registry/Executor 的 e2e

`tests/e2e/test_real_mcp_tool.py`：本地 stdio server → `SdkMcpTransport.list_tools` → allowlist/schema pin → `register_mcp_tools` → model spec（含 local description，不含 remote）→ registry 一个 definition/一个 provider → `ToolExecutor` ToolCall → `McpToolAdapter` → `SdkMcpTransport.call_tool` → `ToolResult`（structured payload 过 output schema 校验，action_id 不变）。同 action_id 精确重放由 cache 命中且不再 spawn/call server；同 action_id 不同参数抛 identity conflict。

### 15.6 OpinionSearch provider fallback 组合

新增 `build_offline_fallback_service(...)`：offline 注册两个确定性 fake provider（primary 恒抛 retryable SERVER_ERROR，secondary 成功返回契约等价的 SearchResults/ReadResult），证明 fallback 生效且 provider 顺序确定。live 默认保持每 capability 单 provider（search.web→Brave、read.web→Jina），不要求第二家付费搜索；execution profile 由 provider id 参与计算从而在组合改变时阻止不兼容 resume，且保持 opaque 不泄露 provider 名/密钥。Agent Decision 不命名 provider。`config.py` 未新增未请求的二次 provider 字段（计划允许可选）。

### 15.7 验证证据与边界

```text
mcp SDK           mcp 2.0.0 (mcp>=2,<3)，仅 tools/adapters/mcp_sdk.py 与测试使用 SDK 类型
retry/fallback    全局 attempt 计数、action_id 恒定、同 provider retry 后 cross-provider fallback、auth 不重试
circuit           threshold=3/cooldown=30 默认；timeout/rate_limit/server/unknown 计毒，auth/permission 不计
MCP smoke         真实 stdio discovery+call 通过，env allowlist 生效且不泄漏进程 env
pytest -q         468 passed, 2 skipped (live-gated)
ruff/compileall   All checks passed
```

未覆盖/限制：live 无默认付费 secondary provider；stateful MCP session 复用未实现（stateless read-only）；circuit 仅内存、重启重置；offline fallback 是验证组合而非 live 默认。Text doctype；SDK `mcp` 无需 CLI extra。下一主线 Context/Memory 依赖本线的 trust origin 与 bounded catalog 语义。
## 16. Memory / Context 长轨迹正确性（深化主线 C）

实施计划：[`superpowers/plans/2026-08-21-context-memory-hardening.md`](./superpowers/plans/2026-08-21-context-memory-hardening.md)。以下为已进入仓库并验证的事实。

### 16.1 Content origin 与 trust

`ContextContentOrigin` = runtime / app_config / user_task / model / tool / provider。`ContextSection` 新增必填 `origin`。强制的 trust 矩阵：model/tool/provider origin 永远不能 trusted；L0/L1 只允许 app_config/user_task 且必须 trusted、required、NEVER。模型/工具/provider 文本即使在 commit/checkpoint/resume 后仍是 untrusted。renderer 的开头标记现在为 `[CONTEXT_SECTION id=... layer=... origin=... trust=...]`，嵌入的伪造标记继续被转义。

混合区段拆分（不再一个 trusted section 混入 prose）：active decision failure 拆为 control（kind/directive/attempt，runtime/trusted）与 message（model/untrusted）；tool error 拆为 control（tool_name/kind/attempts/retryable/action_id，runtime/trusted）与 message（provider/untrusted）；completion rejection 拆为 control（disposition=reject_and_continue，runtime/trusted）与 reason（model/untrusted，保守处理）。

### 16.2 ProvenanceIndex

新增 `domain/opinion/provenance.py`：`build_provenance_index(state)` 纯函数，返回 `ProvenanceIndex`（`EvidenceProvenance`：evidence_id/source_id/acquired_for_gap_id/semantic_gap_ids/supporting_claim_ids/contradicting_claim_ids/position_ids/narrative_ids）。record 顺序 = committed state.evidence 顺序；`evidence_ids_for_gap`、`source_ids_for_gap`、`unlinked_evidence_ids` 决定论可用；未知 Evidence 引用 fail-closed。acquisition 与 semantic 关系分开：仅 acquisition 不构成语义链接。

### 16.3 Working Memory 语义投影

`WorkingEvidence` 新增 semantic_gap_ids/supporting|contradicting_claim_ids/position_ids/narrative_ids；projector 每次投影只 build 一次 ProvenanceIndex，并用它填 WorkingEvidence 与 OpinionCoverageCell 的 source_ids。Working Memory 仍可删除并重建得到相等结果；不改变 Full Domain State。

### 16.4 Bounded Evidence catalog

新增 `context/catalog.py`：`EvidenceCatalogPolicy(required_evidence_limit=64, history_chunk_size=64, coverage_sample_limit_per_gap=16)`，是 app compiler 配置、不 checkpoint。`partition_evidence_catalog` 按 relevance 选出 bounded required（当前 gap 的 semantic evidence > 最新 unlinked > acquired-for-current > contested > 其余，组内最新优先），再按 committed 顺序还原、其余按顺序分 history chunk。compiler 用 `memory.evidence-catalog.current`（required/trusted/runtime/NEVER/bounded）与 `memory.evidence-catalog.history.<n>`（optional/trusted/runtime/drop）；`memory.opinion-coverage` 渲染 bounded 视图（gap_id/status/evidence_count/source_ids/sample_evidence_ids，每 gap ≤16）。catalog entry 只含 evidence_id/source_id/acquired_for_gap_id/semantic_gap_ids，无 excerpt/prose。

### 16.5 Semantic-gap aware selection

Evidence excerpt 区段的 provenance_refs 现包含 evidence_id、source_id、acquired_for_gap_id、全部 semantic_gap_ids、支持/反驳 claim IDs、position/narrative IDs；Claim/Position/Narrative 区段额外带上各自证据的 semantic Gap IDs，使通用 selector 的 current-gap 相关性识别到语义覆盖而非只靠 acquisition。Compiler 赋 priority（semantic-current 98 > contested 97 > other-semantic 96 > unlinked 95 > acquired-current 94 > 其余 90），不放 Domain State。

### 16.6 Deterministic hash 与 section measures

`CompiledContext.content_sha256` = 最终 rendered UTF-8 的 lowercase SHA-256；`ContextPlan.section_measures` 每 selected section 一个正 estimate（`render_sections((section,))`）。校验：measures 与 selected IDs 同序一一对应、hash 与 rendered 严格一致；estimator 不同只会改 measures/总估算，不改变 selection 时 hash 不变。这些元数据只在 CompiledContext（transient 模型输入），不进 Domain State 或 checkpoint。

### 16.7 100-step 长轨迹压力测试

`tests/integration/test_context_long_trajectory.py`：合法类型化状态，4 个默认 Gap、100 个 committed StepRecords、80 Source/Candidate、640 Evidence、Claim/Position/Narrative 跨四维、一个 open current Gap、最新 unlinked Evidence、contested Claim 与 counter Narrative、old/recent Evidence excerpt 内嵌伪造 section 标记。断言：固定 80K budget 下 10/50/100 步都编译成功且 est ≤ limit；recent interaction 步数 ≤ recent_step_limit；required catalog ≤64；coverage sample ≤16；最新 unlinked 可见；contested/counter Evidence 可见且 untrusted；L0/L1 不变；恶意内容只在 untrusted 且不能伪造真实标记；typed JSON resume 得到相同 rendered/plan/hash；WorkingMemory 丢弃重建相等；50→100 步不触发 required overflow。stress 连续跑两次 hash 一致（b97f3e…）。

### 16.8 Prompt injection matrix

`tests/security/test_context_injection_matrix.py` 覆盖 14 条注入路径：search snippet、reader/evidence excerpt、MCP structured、MCP unstructured、模型 query（经 Reducer 持久化）、current focus、reflection、gap resolution note、accepted Decision prose、ToolError provider message、DecisionValidationError（含模型 id）、completion rejection reason、checkpoint JSON resume、伪造 `[CONTEXT_SECTION ...]` 标记。统一断言：含哨兵的每个 selected section 都 untrusted、origin 为对应 model/tool/provider、L0/L1 干净、rendered 转义伪造标记、trusted control 区段不含哨兵、JSON resume 不改变 origin/trust、dedup 不跨 trust/layer 合并。

### 16.9 Completion / Brief 使用 ProvenanceIndex

`completion.py` 与 `brief.py` 改为用 `build_provenance_index(state)` 统一源：Evidence→Source ID、Gap 语义 source IDs、Claim/Position/Narrative 证据定位与 coverage 引文。完成阈值、source-kind 策略、Markdown 措辞与编号保持不变；回归 fixture 输出与重构前字节一致。

### 16.10 验证证据与边界

```text
pytest -q -W error    520 passed, 2 skipped (live-gated)
ruff check src tests   All checks passed!
compileall -q src tests passed
100-step stress       hash 两次一致；required catalog=64；est ≤ 80K budget
offline CLI           completed，run.json+report.md+action_results，resume 字节一致
checkpoint schema     CHECKPOINT_SCHEMA_VERSION 仍为 4；CompiledContext hash/measures 不落盘；WorkingMemory 仍不 checkpoint
```

未覆盖/限制：token estimate 为启发式（`HeuristicTokenEstimator`），不代表具体模型 tokenizer 精确数；stress 用固定 80K budget 且 fixture 固定 640 evidence；没有引入 embedding/向量检索/模型 summary/跨 run memory/trace 平台/Evaluation 或新的 Domain action。
## 17. Deepening Review Remediation（修复记录）

实施计划：[`superpowers/plans/2026-08-21-deepening-review-remediation.md`](./superpowers/plans/2026-08-21-deepening-review-remediation.md)。本段只记录修复后已通过验证的事实；修复前的接受声明以本节为准。

### 17.1 取消不再丢弃已观测 Observation

`AgentLoop.run()` 顶部的取消检查仅在 `resume_action is not REDUCE_OBSERVATION` 时终止；`OBSERVATION_READY` 与 `REDUCING` 都归类为 `REDUCE_OBSERVATION`，因此取消到达时该 step 仍完成 processor/reducer/commit 恰好一次，然后下一轮才可终止。新增 hook 取消测试：OBSERVATION_READY 与 REDUCING 两种场景下 final status=cancelled、committed steps=1、revision=1、committed action ID 恰好一次、tool 未再调用、terminal checkpoint 重载 Domain State 一致。无需新 phase/flag，`terminate_run` 未改。

### 17.2 half-open probe 始终释放

`ProviderCircuitBreaker.record_failure()`：probe in flight 时，poisoning 失败 → OPEN(重新计时)，非 poisoning 失败（auth/permission/not-found 等）→ CLOSED 且 consecutive_failures=0、probe_in_flight=False；非 poisoning 不计入健康计数。Executer 级测试证明后续 ToolCall 仍到达 provider（attempts=1），不会永远收到 “all providers unavailable”。

### 17.3 MCP content-block 元数据剥离

`SdkMcpTransport._dump_content()` 改为显式投影：对 SDK content block 做 `model_dump(mode="json")` 后**删除顶层 `meta`/`_meta`/`annotations`**（字段名与别名都删），剩余值经 `JsonValue` 校验；非 JSON block 转为安全 `ToolAdapterError`，不出 raw SDK/Pydantic 异常。`McpToolAdapter.invoke()` 强制：descriptor 声明了 output schema 而 `structured_content is None` 时 fail closed（安全 message，不含正文与 schema body）。规则表（声明/有/无 structured）全部有测试：声明+缺 → 失败；声明+有效 → 成功；声明+无效 → 失败；未声明+缺 → unstructured 成功；未声明+有 → structured 成功。不删除 pinned 应用 output schema 中合法的 `meta` 键。

### 17.4 MCP HTTP 端点与 client 生命周期

`McpHttpConfig` 生产路径复用 `normalize_secure_provider_endpoint()`（拒绝缺失 host、userinfo、loopback、非全局 IP、link-local/private literal；非法端口；空白/控制字符）；开发 loopback 仅允许 `allow_insecure_loopback=True` + `http` + hostname 恰为 localhost/127.0.0.1/::1 + 无 userinfo。执行侧 `_client()` 用同一 normalize 结果连接，保证验证与执行一致；`httpx2.AsyncClient` 由 `async with` 显式持有，正常与异常路径都关闭（测试用受控 fake transport 证明，不经公网）。stdio 分支独立，不引用 HTTP client。

### 17.5 Trusted coverage 语义正确且有界

`memory.opinion-coverage` 的每个 cell 现在是：`gap_id/status/evidence_count/source_count/sample_evidence_ids(≤limit)/sample_source_ids(≤limit)`；`sample_evidence_ids` 只取 `cell.evidence_ids`（真正的 semantic 链接），不再混入 unlinked/acquisition-only；`source_ids` 从 required rendered 区段移除（WorkingMemory.OpinionCoverageCell.source_ids 仍完整，属于纯投影）。300→3000 semantic Evidence/Source 增长测试证明 required coverage 恒定有界、计数精确、sample 上限生效、重复编译与 JSON resume 字节/hash 一致。

### 17.6 Dedup 保留 origin；L0 只允许 app_config

`select_context_sections()` 的 dedup key 加入 origin（trust+origin+layer+normalized content），不同 origin 的同文 untrusted 区段不再合并（model/tool/provider 各自保留 producer 归属与 provenance refs）；同 origin 相同文本仍可去重；trusted/untrusted、不同 layer 永不合并。`ContextSection` 校验：L0=app_config only；L1=app_config 或 user_task；L0/task.request 仍是 trusted/required/NEVER。注入矩阵新增 model-reflection vs tool-excerpt 同文不合并测试。

### 17.7 Hermetic MCP 子进程生命周期

fixture `tests/fixtures/mcp/read_only_server.py` 支持测试专用 allowlist env `MCP_FIXTURE_LIFECYCLE_PATH`：启动写 started 标记（仅含生成 instance id），finally 原子替换为 closed 标记（绝不写 env/token/command/credential）。测试用唯一 tmp_path 生命周期文件、真实 stdio transport 调用两次、短有界 deadline 等待 closed、断言两次 instance 唯一且各自 closed；确定性失败（超时即失败）。不再调用 ps/pgrep/shell/网络；保留真实 stdio discovery/call e2e。

### 17.8 验证证据

```text
targeted remediation suite  164 passed (-W error)
pytest -q -W error          545 passed, 2 skipped (live-gated)
ruff check src tests        All checks passed!
compileall -q src tests     passed
offline CLI                 run.json/report.md/action_results 生成；resume report 字节一致
checkpoint schema           CHECKPOINT_SCHEMA_VERSION=4；execution profile 未改
```

未变化的限制：只读工具 at-most-once 复用窗口；circuit 仅内存、进程重启重置；MCP 无状态 session（不复用）；token 估算为启发式。修复未新增依赖、未改 `RunStatus`/`StepPhase`/动作空间/checkpoint schema/execution profile，未触碰 `archive/`。

## 18. Review follow-up: recursive MCP content projection

二次 review 遗留的 MCP 内容投影缺陷已修复并验证。本节记录修复后的事实，覆盖 §15/§17.3/§17.8 中“顶层去 metadata”表述的修订。

### 原问题

`mcp_sdk._project_content_block()` 旧实现先对整块调用 `model_dump(mode="json")` 再删最外层 `meta`/`_meta`/`annotations`，存在两个缺陷：

1. **只过滤最外层**：`EmbeddedResource.resource` 等嵌套 `TextResourceContents` 的 `meta`/`_meta` 原样进入 `McpCallResult` → `ToolResult.payload` → 未来可进入 cache/checkpoint 与模型 Context；远端协议元数据可形成注入 laundering 路径。
2. **过滤前序列化**：metadata 位于被删字段却先被 `model_dump(mode="json")` 尝试序列化，含不可序列化对象时抛出 `pydantic_core.PydanticSerializationError`；`_dump_content()` 只捕获 `ValidationError`，原始 SDK 异常穿透 adapter 边界，破坏稳定错误契约。

### 投影策略（先过滤、后验证）

`_project_content_block()` 改为递归 Python-mode 投影，不再对整块做 JSON 序列化：

- `BaseModel`：按 `type(block).model_fields` 逐字段用 `getattr` 取 Python 值（不触达序列化），字段名或其 `alias`/`validation_alias`/`serialization_alias` 命中 `{meta, _meta, annotations}` 即丢弃；`__pydantic_extra__` 额外字段按同规则递归。
- `dict`/`Mapping`：逐 key 丢弃 metadata key，递归投影 value。
- `list`/`tuple`：逐元素递归。
- JSON 标量：原样保留。
- 其余对象：原样携带；由 `_dump_content()` 的最终 `TypeAdapter(JsonValue).validate_python()` 判定，失败归一为安全错误。

`_dump_content()` 显式捕获 `pydantic.ValidationError` 与 `pydantic_core.PydanticSerializationError`（pydantic 2.12.5 顶层不导出后者，`pydantic.SerializationError` 亦不存在，已核实），统一转换为 `ToolAdapterError(UNKNOWN_PROVIDER_ERROR, "The MCP server returned a non-JSON content block.")`——固定消息，不含对象 repr、secret、远端 payload 或 Pydantic 内部细节；`from exc` 仅保留调试链，不进 ToolError.message（executor 只取 `safe_message`）。

### 关键取舍

- 沿用实例 `model_fields` 会触发 pydantic 2.12 的 `PydanticDeprecatedSince211`（全量测试用 `-W error`），改为 `type(block).model_fields` 类级访问，无警告。
- metadata 字段中的不可序列化对象（如 `object()`）在删除前不被任何序列化触达，调用成功；非 metadata 公开字段不可序列化时整块安全失败——即“先删 metadata，再验证 JSON”，不存在再次全对象序列化的问题。
- 未引入 `bytes→base64` 等隐式转换：binary resource body 等非 JSON 公开内容按契约安全失败，与既有“MCP content 只接受 JsonValue”边界一致。
- 过滤范围严格限定在 content-block 投影（`_dump_content`）；应用级 `structured_content` 键名 `meta` 不受影响（由 output schema 决定），不误删 pinned schema 合法字段。

### 新增测试（tests/contract/test_mcp_sdk_transport.py）

1. 真实 `mcp.types.EmbeddedResource` + `TextResourceContents._meta`：type/uri/mime_type/text 保留，JSON dump 中无 `meta`/`_meta`/`annotations`/敏感值。
2. 多层 dict/list：`items[]._meta`、`child.annotations` 全层删除，公开内容保留。
3. metadata 内放 `object()`：投影成功、公开内容保留、无 `PydanticSerializationError`。
4. 非 metadata 公开字段（BaseModel fixture 与 dict 两种）放不可序列化对象：`ToolAdapterError`、kind=UNKNOWN_PROVIDER_ERROR、固定消息、不含 repr/secret/payload 字样；原始异常不穿透。
5. 既有顶层 TextContent/ImageContent 行为测试继续通过。
6. transport→Registry→Executor 端到端：投影后的 EmbeddedResource 进入 `ToolResult.payload` 无任何 metadata。

### 实际测试结果

```text
pytest -q tests/contract/test_mcp_sdk_transport.py        27 passed（+5 新测试，-W error 亦通过）
pytest -q tests/unit/tools                                 103 passed
pytest -q -W error                                         550 passed, 2 skipped（live-gated）
ruff check .                                               All checks passed!
compileall -q src tests                                    passed
```

首次修复前 5 个新测试全部失败，证据：嵌套 `resource.meta` 出现在投影 dump；metadata 含 `object()` 时抛出 `pydantic_core.PydanticSerializationError: Unable to serialize unknown type` 原样穿透。checkpoint schema 4、execution profile、动作空间、`RunStatus`/`StepPhase` 均未变；未触碰 `archive/`。

### 循环内容收口

后续边界复核发现，自引用 `dict`/`list` 会在最终 JsonValue 校验前令递归投影抛出原始 `RecursionError`。投影器现在维护仅覆盖当前递归路径的对象 identity 集合：同一路径再次遇到相同容器即判定为循环；共享但无环的子对象仍可在不同分支正常投影。显式循环错误和极深无环输入触发的 `RecursionError` 均在 `_dump_content()` 边界归一为同一个固定 `ToolAdapterError`，不暴露内部异常或远端对象。新增自引用 dict、自引用 list 和共享无环对象 contract tests，验证稳定错误种类、安全消息和路径集合语义。验证结果：MCP contract tests `30 passed`，全量测试 `553 passed, 2 skipped`，Ruff 与 compileall 通过。

## 19. Web 演示控制台（浏览器启动/观察/取消调查）

为“自己用一用、向面试官现场演示”新增零新依赖的本地 Web 演示层。Runtime、Domain、行动空间、checkpoint schema 均未改动；唯一的产品代码改动是 `build_live_service` 增加可选 `hook` 透传参数（向后兼容）。

### 实现范围

- `opinion_search/src/opinion_search/web/`：`server.py`（stdlib `http.server` + SSE）、`index.html`（单文件前端，内联 CSS/JS）、`__main__.py`（`python -m opinion_search.web`）。
- `tests/e2e/test_web_server.py`：8 个真实起服务的端到端测试。
- `app/service.py`：`build_live_service(checkpoint_path, config, *, hook=None)` 透传给 `_build_loop`。
- `README.md` 新增 “Web demo console”；`.gitignore` 增加 `.opinion_search_web/`。

### 核心流程

```text
浏览器提交表单 -> POST /api/runs {mode, question, ...}
  -> SearchRequest 校验 -> RunRecord（内存注册表）
  -> 后台 daemon 线程 + 独立 event loop：build_(offline|live)_service(hook=_ProgressHook)
  -> AgentLoop 每个 CheckpointBoundary 触发 hook.after_checkpoint
  -> _emit() 将紧凑事件广播到全部 SSE 订阅队列 + 写 2000 条上限的历史
  -> GET /api/runs/{id}/events 以 `data: <json>\n\n` 流式推送；
     晚订阅者重放完整历史，终态事件全局唯一
  -> terminal（run 的 checkpoint 与 report.md 均已落盘后才发出）
  -> 前端渲染 step 时间线 + 最终 Brief（内置迷你 Markdown 渲染）
取消：POST /api/runs/{id}/cancel -> loop.call_soon_threadsafe(signal.cancel)
  -> Runtime 在安全边界 terminate_run(status=CANCELLED)
```

### 关键契约与不变量

- 事件序列化：`boundary`/`status`/`step_index`/`phase`/`step_id`/`attempt`/`decision`/`action`/`observation`/`committed_steps`/`stop_reason`（pydantic `model_dump(mode="json")` + 递归截断长字符串到 600 字符）。
- 终态事件（`type=terminal`）是“run 全部完成”的唯一证据：包含 `status`/`stop_reason`/`markdown`/`source_urls`/`remaining_gap_ids`，且在 checkpoint 与 report 写入**之后**才发出（曾因先发事件后写 report 造成测试竞态，已调整顺序）。
- 正常完成路径不经过 `terminate_run`（loop 在 `EVALUATE_CONTINUATION` 走 `apply_continuation(target_status=COMPLETED)`），因此边界序列以 `continuation_applied` 收尾；`run_terminated` 只在失败/取消/超步数出现。前端与测试都不得假设 `run_terminated` 必现。
- 取消信号跨线程发送必须用 `loop.call_soon_threadsafe(signal.cancel)`（`asyncio.Event.set()` 非线程安全），loop 未运行时直接 `signal.cancel()` 打标记。
- 每个 run 使用独立 daemon 线程 + 独立 event loop；`EventCancellationSignal` 在该线程内创建，避免 loop 绑定错误。
- checkpoint 复用标准 `JsonCheckpointStore`：`<runs-dir>/<run_id>/run.json` + `action_results/` + `report.md`（RunBundleWriter 原子写）。
- live 模式从 `--env-file`（默认 `.env`）合并 `KEY=VALUE` 行到 `os.environ`（`setdefault`，已有环境变量优先）；缺失 `OPINION_MODEL_API_KEY`/`BRAVE_SEARCH_API_KEY` 时返回 400 与缺失项名称，任何响应都不含密钥值。
- HTTP/1.1 + SSE：心跳 `: keep-alive` 15s；客户端断开静默清理订阅；单文件 `index.html` 由 `GET /` 直接返回。

### 重要设计取舍

- **stdlib only，不引入 FastAPI/uvicorn**：项目保持最小依赖；`http.server` + `queue` + SSE 足够支撑演示规模，面试时可解释全部实现。
- **复用 `LoopHook` 而非侵入 loop**：进度推送是 Runtime 已有 seam 的一次组合，不是新协议；web 层不触碰 checkpoint/事务语义。
- 事件广播 + 有界历史：解决“run 秒级结束、浏览器 SSE 尚未连接”的竞态——晚订阅者从历史重放完整时间线。
- 每 run 一线程 + 独立 loop：规避 `asyncio.Event` 与 `call_soon_threadsafe` 的 loop 绑定问题；`ThreadingHTTPServer.daemon_threads=True` 保证进程退出时子线程不悬挂。
- 事件中 decision/action/observation 带完整 JSON（长字段截断），前端按 boundary 分组展示，不预设展示 schema，后续加字段不破坏页面。

### 失败与恢复语义

- run 线程内任何异常统一转换为 `terminal {status:"failed", error}`（含 `CheckpointError`、provider 错误、模型错误），流正常关闭；快照/列表中可见 `error` 字段。
- SSE 连接中断（浏览器刷新/关闭）只移除该订阅，历史保留，重连可完整重放。
- `RunBundleError` 被吞（report 是便利产物，不影响 run 终态）；checkpoint 失败则进入 failed 终态。
- cancel 与快速完成的竞态是合法的：终态可能是 `cancelled` 或 `completed` 之一（测试断言两者皆可）。

### 测试与验证证据

```text
pytest -q tests/e2e/test_web_server.py    8 passed
pytest -q -W error                        561 passed, 2 skipped（live-gated）
python -m compileall -q src tests         通过
```

- 覆盖：index/healthz；offline run 全边界流（十步 committed + continuation_applied）；终态事件全局唯一（晚订阅重放）；终态后 snapshot 与 run 列表；请求校验（非法 mode/缺 question/空串/非 JSON/未知 run 404）；cancel；live 缺密钥 400（无网络）；checkpoint + report 落盘断言。
- 手工冒烟：`python -m opinion_search.web --port 8907` 起服务，curl 提交 offline run，SSE 重放完整边界序列 + terminal，`<runs-dir>/<run_id>/` 下生成 `run.json`/`report.md`/`action_results/`，报告内容与 CLI 输出一致。

### 已知限制

- 运行列表只存内存（重启服务即清空），但每个 run 的 checkpoint/report 已落盘，可覆盖；未做历史页/恢复 UI。
- 无鉴权、绑定 127.0.0.1：设计上只服务本机演示，不暴露公网。
- 取消是“安全边界终止”，不保证已提交 step 回滚（与 Runtime 语义一致）；UI 直接展示 Runtime 终态。
- live 模式依赖真实 provider 与密钥；.env 解析只支持无引号/无续行的简单 `KEY=VALUE`。
- 迷你 Markdown 渲染器只覆盖 Brief 用到的语法（标题/加粗/列表/代码），不做完整 Markdown。

### 对下一节点的影响

- 新增的任何 LoopHook 事件或 terminal 负载字段都会自动出现在 SSE 流中（前端按 type 分支处理，未知字段不报错）。
- 若未来做 run 历史页，可从 `<runs-dir>/<run_id>/report.md` + `run.json` 离线重建快照，无需改动本层。
- `build_live_service` 的 `hook` 参数已固化为可选关键字；调用处（CLI 无 hook）行为不变。

### 19.1 补充：独立开发者控制台（/dev）

用户页改为产品形态后，原始 Runtime 细节收敛到独立页面 `GET /dev`（`web/dev.html`，单文件、零依赖）：

- 运行列表：轮询 `/api/runs` + `/healthz`（3s），显示 run_id/mode/status/question/error；
- 单 run 详情：snapshot JSON、cancel 按钮、`report.md` 直链；
- 事件时间线：「跟随事件流」按需连接 SSE，服务端历史重放保证看到完整 CheckpointBoundary 序列；decision/action/observation 边界着色。

新增端点：`GET /api/runs/{run_id}/report` → 终态后以 `text/markdown` 返回 report.md 原文；未到终态返回 404（report 由 RunBundleWriter 在终态写入）。静态页改为通用 `_send_page(page)`。验证：web e2e 10 passed（含 /dev 页面与 report 端点断言），全量 563 passed, 2 skipped，dev.html 内联 JS 通过 `node --check`。

### 19.2 补充：用户页历史调查与重启恢复

用户首页新增「最近的调查」区块（最近 8 条：状态徽章 + 问题 + 时间），点击回看完整报告或重新接入进行中 run 的 SSE。服务端配套：

- `create_run` 时写 `meta.json`（run_id/mode/question/created_at）到 run 目录；
- `get_run` 内存 miss 时从磁盘 bundle 恢复为只读 `RestoredRunRecord`（解析 report.md 头部 Question/Run status/Stop reason 与 Sources 区 URL），subscribe 重放 terminal 事件，cancel 为 no-op；
- `GET /api/runs` 合并内存与磁盘记录并按 created_at 排序。

关键点：恢复不触碰 checkpoint 格式（仍由 JsonCheckpointStore 负责）；无 meta.json 的历史目录回退用 report.md 头部，mode 记 unknown。验证：web e2e 11 passed（含双服务器实例重启恢复测试：第二实例仅凭磁盘列出 run、snapshot 含 markdown 与来源、SSE 以 terminal 收尾），全量 564 passed, 2 skipped，index.html 内联 JS 通过 node --check。

### 19.3 补充：Typed SearchOutcome 与无损报告恢复

用户页此前把 `report.md` 当作接口协议：JavaScript 依赖英文二级标题、列表格式和来源链接正则反向拼出报告卡片，服务重启时 Python 也从 Markdown 猜测 status、question 与 source URLs。这导致展示格式与数据契约耦合，任何标题调整都可能静默破坏 UI 或恢复结果。

Domain 现新增冻结、禁止额外字段的 `SearchReportView` 及其子模型，显式覆盖 time scope、final conclusion、claims、stakeholder positions、narratives、gap coverage、evidence appendix、remaining gaps 和 sources。`build_search_outcome()` 先从 committed `OpinionSearchState` 与 `ProvenanceIndex` 生成这一 typed read model，再由同一对象确定性渲染 Markdown；来源关系统一映射为 `S1...Sn`，没有两套独立业务推导。该 report 仅是 State 的只读投影，不参与 Reducer，也不成为第二事实源。

`RunBundleWriter` 在 `report.md` 之外各自原子写入 `outcome.json`。terminal SSE 与 snapshot 直接包含 `report` JSON；服务重启优先校验并恢复 `outcome.json`，不再解析 Markdown。仅对升级前没有 sidecar 的历史 bundle 保留 `report=None` 的 legacy Markdown fallback。用户页优先渲染 typed report，证据审计附录默认折叠，旧 parser 只服务历史兼容。

验证证据：领域/Run Bundle 定向测试 8 passed；除本地端口 Web 组外的 unit/contract/integration/e2e 共 546 passed、2 个 live-gated skipped；真实本地 HTTP/SSE/重启恢复 Web E2E 11 passed；`git diff --check`、`compileall` 与 index.html 内联 JavaScript 语法检查通过。

## 20. Web 公开事件调查升级（S0–D，2026-09-10）

> 关联设计：canonical design §18；执行计划：`docs/superpowers/plans/2026-09-10-web-event-investigation.md`。本节只记录已进入仓库并经过验证的事实。

### 20.1 已实现并有测试的契约

- **上下文完整性**：`structured_context` 的 `input.material` 与 Compiler 的 `memory.questions`/`memory.findings` 不可丢弃；超限时抛 `RequiredContextOverflow`，审查调用捕获后降级为未核查（`partial`），不会在丢失原文后照样成功。
- **发布协议**：新增 `finalizing` 中间态；报告写入完成后才发布终态；`snapshot` 提供 `report_pending`；`resume` 可从终态 checkpoint 重新发布。取消发生在产生材料前也会写最小报告。
- **更新语义**：`ReflectDecision.retirements`（显式理由）替代 `retire_finding_ids`；`State.retired` 记录；报告差异区分 `pending_reevaluation` 与 `withdrawn`。
- **必答问题**：`required_questions(request)` 确定性抽取；`_cover_required` 为计划遗漏的用户问题补建 issue；State 校验器保证覆盖。
- **证据完整性**：`verify_evidence` / `verify_state_integrity`；Reader/Retrieve 边界与发布前校验 `start/end/excerpt` 与 content hash。
- **回应覆盖**：`FindingProposal` 新增 `response_target/covered/uncovered/coverage_reason`；校验器约束 direct/partial/attributed；`response_search_complete` 要求问题级实质查找完成且候选已处理。
- **来源独立性**：报告新增 `independent`/`independent_source_count`，正文重复版本标记为“不作为独立证据”。
- **预算**：规划前启动，等待澄清期间 `Budget.pause()`，恢复不归零。
- **查询有界**：Resolver 不再静默 `[:600]` 截断，超长查询要求拆分。

### 20.2 Web 主链

- 新增 `Manager.evidence/versions/diff/report/markdown`、`web/investigation.html`、`web/assets/{api,ui,evidence,report,app}.js` 与 `style.css`。
- 端点：`POST/GET /api/investigations`、`GET /api/investigations/{id}`、`/events`(SSE)、`/report`(md)、`/evidence/{eid}`、`/versions`、`/diff`、`POST /clarify|cancel|resume|update`。
- 更新入口为页面内表单路由 `#/i/{id}/update`（不依赖原生 `window.prompt`），提交后原地转入进度页。
- 旧首页移至 `/legacy`，新首页 `/`；静态资源 `no-store` 便于本地迭代；路径穿越被拒绝。
- 旧 `action_resolver` 搜索载荷保持两字段，兼容既有契约测试。

### 20.3 测试与验证证据

```text
pytest tests/investigation -q                    36 passed
pytest tests/e2e/test_investigation_web.py -q     5 passed
pytest -q -m "not live"                          613 passed, 2 deselected
node --check（5 个前端模块通过）
```

实际浏览器操作（ZCode in-app browser，隔离服务 127.0.0.1:8917，离线模式）：提交明确事件自动开始 → 进度页经 SSE 实时切换到报告 → 打开证据面板定位到正确版本原文（标题/链接/获取与发布时间/字符区间/版本）→ 补充新进展生成新版本 → 版本比较显示“修订判断/判断未变/补充依据”，旧版报告与旧引用不变。截图 artifact 见会话产物目录。

浏览器回归发现并修复的两个真实前端缺陷：`el()` 事件名大小写导致元素级 click 处理器失效；进度页在快照转为终态后未切换到报告视图。另将原生 `window.prompt` 改为页面内表单以提升可测性。

### 20.4 版本与恢复（D 阶段补充）

- **重查记录**：Read/Retrieve 每次处理一个已见 URL 时生成 `SourceCheck(url, version_id, checked_at, changed)`；`changed` 只在同 URL 出现新内容哈希时为真。报告 `checks` 与页面重查区展示，旧版引用不受影响。
- **同 URL 变文**：内容哈希变化不覆盖旧 artifact，而是追加新的 `SourceVersion`，并在报告来源里标记 `discovery="changed_page"`。旧证据的 `start/end/excerpt` 仍对旧文本通过 `verify_state_integrity`。
- **跨进程排他**：`CaseLock` 对 `cases/{case_id}/active.lock` 持 `fcntl.flock(LOCK_EX|LOCK_NB)`；同事件第二个进程 `create` 抛 `CaseBusy`。测试用真实子进程持有锁验证，不依赖同进程内对象。
- **恢复不重放**：`resume` 从 checkpoint 恢复，已提交的 tool action（delta 已写入）不再执行；`finalizing` 中断后 resume 只重新发布，不重跑调查步骤。
- **provider 失败不失真**：`build_report` 分别统计 `search_failures`/`read_failures`；`no_material_change` 仅在确有成功观测且无变化时为真。markdown 明确“抓取失败不代表没有新进展”，避免把不可用当成“无新进展”。

### 20.5 已知限制与未验证

- 真实联网发现质量已实测（见 §20.7）：来源与证据真实可核，但“核心结论”仍未确认，达不到 90%/95% 门槛。10 个保留案例的固定材料语义回放与人工评分仍未执行；案例登记表 `tests/investigation/cases/registry.json` 全部 `blocked`（无虚构材料替代）。
- Reviewer 仍是与主 Agent 相同配置的独立调用，不构成独立事实来源或人工审查。
- SSE 采用轮询快照而非事件总线；R05/R07 的部分“实质覆盖/转述关系”仍依赖模型判断，机制测试只覆盖结构约束。
- 前端在 Playwright 可操作性检查下点击会超时，浏览器验收通过页面内 DOM click 与坐标点击完成（真实联网实测同样如此）。

### 20.6 对下一节点的影响

- 真实联网与人工验收仍待材料与评分就绪；在补齐前不得据机制测试宣称调查质量达标。
- §20.7 的两个 stop_reason 指向下一优先项：模型决策的结构化成功率（partial 覆盖字段、schema 匹配）与“核心结论”复核门，而不是继续加机制测试。
- 任何旧格式 run 不得由新流程 resume；格式判断集中在 `Manager.resume` 的 execution profile 检查。

### 20.7 真实联网实测记录（2026-09-11）

模型网关 `https://opencode.ai/zen/go/v1`、模型 `mimo-v2.5`、Brave 搜索、Jina 读取；本地服务 `127.0.0.1:8917`（live），浏览器实际点击完成全链。

- **网关适配**：该网关对推理请求要求 `x-opencode-session` 头（缺省返回 400 `MissingSessionID`）；`GET /models` 对无效 key 也返回 200，不能作为凭据校验。新增通用能力 `OPINION_MODEL_EXTRA_HEADERS`（JSON 对象）与 `OpenAICompatibleModelClient(extra_headers=...)`，合并进请求头且拒绝覆盖 `Authorization`/`Content-Type`/`Accept`；有契约与配置测试。
- **实时冒烟**：`RUN_LIVE_TOOL_TESTS=1 RUN_LIVE_AGENT_TESTS=1 pytest tests/e2e/test_real_web_smoke.py -m live` → 2 passed（真实 Brave + Jina + 模型）。
- **父调查**（事件：重庆燃气计费异常争议，2024）：5 次搜索、35 条候选、仅读取 1 个来源、8 条证据、0 条已核查判断，终态 `partial`；`stop_reason = "Decision recovery was exhausted: use retrieve to revisit a page already fetched in this version"`。失败明细含 `invalid_decision`（partial 回应未给未覆盖项）与 `model_malformed_response`（决策 schema 不匹配）。
- **子调查（补充进展）**：3 个来源、15 条证据、7 条判断，产出真实时间线（2024-04-19 发布会、04-26 退费 1182 件约 285.85 万元、05-06 换董事长）与 `修订判断/判断未变/新增判断`；终态 `partial`，`stop_reason = "core conclusions must be active and supported by a current review"`。
- **浏览器全链**：提交 → 进度 → 报告（真实来源与证据、诚实的“部分完成”与停止原因）→ 证据抽屉（定位到不可变原文的字符区间并高亮）→ 补充新进展 → 版本比较（逐问题修订/未变/新增）。Playwright 定位点击仍超时，改用页面内 DOM click 完成。
- **结论**：来源、证据、版本与恢复语义在真实联网下成立且不虚构；短板是模型决策成功率与“核心结论”复核门——前者导致一次运行只读到 1/35 个候选，后者使已有多来源判断仍无法升级为核心结论。两项都需要后续处理，不能用机制测试替代。

### 20.8 换模型实测暴露并修复的三个真实缺陷（2026-09-11）

切到 `deepseek-flash` 后连续三次真实联网运行分别失败，逐一定位并修复（均有测试）：

- **决策提示未声明 JSON**：`deepseek` 系列在 `response_format=json_object` 下要求提示里含 “json” 字样，否则 400（`Prompt must contain the word 'json'`）。`PLAN_INSTRUCTIONS`/`REVIEW_INSTRUCTIONS` 原本没有，已在两处补上 “Return exactly one JSON object matching the schema.”，并加提示守卫测试 `tests/investigation/test_decision_prompts.py`。
- **退休路径缺导入**：`ReflectDecision.retirements` 经 `reduce_state` 落地时 `NameError: utcnow`，会直接让 worker 崩溃；原因是该分支从未被测试覆盖。已补导入，并在 `test_update_reevaluation.py` 增加 `reduce_state` 级退休/去重测试。
- **证据校验异常未收口**：`verify_evidence` 在读取/重取时抛 `ValueError`（原文与保存文本不一致）会中断整轮运行。已把 read/retrieve 的校验失败降级为 `ToolError` 观察记录（`_read_material` 抽取 + `except (ValueError, ContextOverflowError)`），使模型可继续，并在 `test_evidence_integrity.py` 增加该降级测试。
- **模型输出容错**：模型常在 JSON 决策后追加说明、第二个 JSON 对象或 `<tool_calls>` 块，原先要求整段恰为一个 JSON 文档会误判为 schema 不匹配。客户端改为取首个平衡 JSON 对象（`_first_json_object`），仍拒绝完全无 JSON 的响应；有参数化测试。

验证：`pytest -q -m "not live"` → **625 passed, 2 deselected**。

**未完成（配额阻塞）**：`deepseek-flash` 的完整联网结果尚未观察到——修复后的下一次运行被工作区模型周额度拦下（全部模型返回 429 `GoUsageLimitError: Weekly usage limit reached. Resets in 2 days`）。因此上述修复只经单测验证，未经一次完整 deepseek-flash 联网运行验证。

### 20.9 传输重试、超时与预算可配置（2026-09-11）

额度恢复后继续实测，发现失败模式集中在**供应商瞬时故障**（HTTP 500、空响应、请求超时）而非决策语义错误，但每次瞬时故障都会消耗循环的 decision-recovery 预算（默认 2 次），使调查在材料齐全后仍以 `partial` 结束。

- **传输层重试**：`OpenAICompatibleModelClient` 新增 `max_transport_attempts` 与 `retry_backoff_seconds`，对 `TIMEOUT`/`SERVER_ERROR`/`EMPTY_RESPONSE` 退避重试；schema 不匹配等**语义**失败仍交给循环的决策恢复，不再混淆两类失败。库默认 `max_transport_attempts=1`（不改变原语义），`LiveConfig.model_transport_attempts` 默认 3（env `OPINION_MODEL_TRANSPORT_ATTEMPTS`）。
- **可配置超时**：`OPINION_MODEL_TIMEOUT_SECONDS`（默认 60；慢模型可调高）。
- **可配置预算**：`OPINION_INVESTIGATION_SECONDS`/`_MODEL_CALLS`/`_SEARCHES`/`_READS`/`_CONSOLIDATE_SECONDS`（`Manager.budget_limits()` 读取，未设置即沿用原默认；已存在的 run 读回自身 limits，恢复不改变原始预算）。

验证：`pytest -q -m "not live"` → **635 passed, 2 deselected**。

**实测进展**：修复后同一事件的联网运行产出 10 个来源 / 47 条证据 / **39 条判断** / 3 个问题 `answered`，并在 1200s 墙钟耗尽时以“未复核判断保持限定”诚实收尾（`model` 仅用 53/80，瓶颈是模型速度而非调用数）。据此把该事件的重跑预算调高后继续观察。

**首个完整完成的联网调查（2026-09-11）**：同一事件在 `OPINION_INVESTIGATION_SECONDS=2400`、`OPINION_INVESTIGATION_MODEL_CALLS=120` 下终态 `completed`（耗时 1530s，16 搜索 / 16 读取 / 59 次模型调用），产出 13 个来源 / 74 条证据 / 24 条判断 / **8 条核心结论**，6 个问题全部 `answered`，独立来源 13 个（含重庆市政府 `cq.gov.cn`、财新 `m.caixin.com`、中新网、澎湃、重庆日报）。审计停止原因自述为“必答问题均有明确处置且有效判断通过证据复核，但不构成真值保证”。报告如实并列了官方与企业的**两套统计口径**（联合调查组 3837 件/337.9 万元 与 企业公告 1182 件/285.85 万元）并标注净利润增速 824% 与专项审计 895.77% 的差异，未做单一化。浏览器端渲染核心结论、证据按钮与限制说明正常。

结论更新：`deepseek-flash` 在“提示声明 JSON + 输出取首个 JSON 对象 + 瞬时故障重试 + 可配置超时/预算”之后可以跑出完整且可核查的联网调查；此前的 `partial` 主要是模型速度撞上墙钟预算，而非流程缺陷。仍非质量终判，人工 90%/95% 评分与 10 个保留案例语义回放未做。

**更新的真实实测（同一事件，`completed` 父版之上补充进展）**：首次子调查终态 `partial`，20 个来源 / 93 条证据 / 0 条判断，`stop_reason = "Decision recovery was exhausted: a partial response must name the uncovered component"`——模型反复给出不合规的 `partial` 回应（未给未覆盖部分），两次恢复用尽。据此做了**可执行的纠错**：校验器消息改为直指字段（`"response='partial' must list the unanswered parts in 'uncovered', or set response to 'direct'/'non_substantive'"`；`coverage_reason` 同理），并在 `INSTRUCTIONS` 里前置声明覆盖字段契约。

**纠错后的子调查（重跑）**：终态 `partial`，但已不再因校验失败中断——19 个来源 / 96 条证据 / 6 条判断 / **5 条核心结论**，6 个问题 `answered` + 1 个 `unavailable`，6 条复查记录 / 7 条版本变化；`stop_reason = "Material or review limitations remain; inspect the issue-level caveats."`，即**主动**因材料/复核限制保持部分完成（非崩溃）。浏览器版本比较对父版逐问题给出 `尚未重新评估`×4 / `修订判断`×2 / `新增判断`×1（新增项为“拟处罚金 1200 万元是否落地”），符合 R03 语义。

验证：`pytest -q -m "not live"` → **636 passed, 2 deselected**。

## 21. 工作台 P0–P1：契约冻结、投影与可信主链修复（2026-09-11）

> 阶段状态：P0 verified；P1 implemented_unverified（API/投影/回归已验证，实际浏览器主路径 NOT_RUN）。

### 21.1 P0 基线与复现检查

- 基线确认：改动前 `tests/investigation + tests/e2e/test_investigation_web.py` = **47 passed**（需以无代理环境运行：沙箱 `HTTP_PROXY` 会使 httpx 发送 absolute-form 请求行，服务器原只按 origin-form 匹配 → e2e 全部 404。该环境问题已转为服务器兼容修复，见下）。
- 四个缺陷锚点（`api.js` 断流直接 close、`report.py` 以 `duplicate_of is None` 冒充独立、`report.js` 暴露 evidence_id、`_publish` partial 覆盖 latest / `Budget.pause()` 丢已用时长）均先以测试复现再修复。
- 预算契约确认：请求次数不重置与时间不重置是两项独立契约，新增 `test_pause_folds_elapsed_time_into_accumulated_budget` 与旧格式 budget.json 兼容测试。

### 21.2 数据与不变量

- `WorkbenchSnapshot`（`opinion-workbench/1`）：`investigation/workbench.py` 纯投影，输入为已发布 report.json，输出确定性（同一报告 → 同一 `snapshot_id`）；字段与模块白名单见 canonical design §19.1。模块状态枚举 ready/provisional/insufficient/unavailable/not_applicable；本阶段仅产生 ready/insufficient。
- 关键不变量：时间线中无法解析为 ISO 日期的 `event_time` 单独列出、不参与排序；材料分布按“文档×已知发布日期”计数、同 URL 多版本不多算、未知日期单列；来源关系 `duplicate/unverified` 二值，“未识别重复”不等于已验证独立；引用在页面层只呈现局部序号（引N），内部 evidence_id 仅作为程序引用键。
- `latest.json`（最近发布可读结果）与 `latest_completed.json`（最近完整结果，仅 completed 更新）职责分离；partial 快照携带 `latest_completed_run_id`。
- `budget.json` 新增 `accumulated_seconds`：pause 将当前窗口折算进累计值；旧格式无该字段按 0 读取。

### 21.3 接口与页面

- 新增 `GET /api/investigations/{id}/workbench`（`snapshot_id` 锚定，不匹配 409）；`GET .../{id}` 携带 `workbench_revision`；`GET .../evidence/{eid}` 携带 `relations`。
- 前端：新增 `workbench.js`（三视图 tab：事件总览/报道对照/议题与核查 + 完整报告入口）；`api.js` 断线先补取快照再有界退避重连（5 次），连接状态与调查状态分开显示；`app.js` 按路由令牌丢弃旧响应；取消失败不再把本地状态改成已取消；`evidence.js` 显示材料-判断关系并在关闭后归还焦点。
- 服务器同时接受 absolute-form 请求目标（RFC 7230），修复代理环境下本地访问 404。

### 21.4 验证

- `pytest tests/investigation tests/e2e/test_investigation_web.py -q`（无代理环境）→ **59 passed**（含新增 `test_workbench_projection.py` 7 项、预算 2 项、发布指针 2 项、e2e workbench 1 项）。
- `pytest -q -m "not live"`（无代理环境）→ **648 passed, 2 deselected**。
- 真实运行（offline 固定材料，端口 8918）：completed run 的 workbench 返回 5 模块状态、4 个“引N”引用、时间线 1 节点、发布分布 2026-01-10×2、关系计数（2 页面/2 版本/0 重复/2 未核实）；错误 snapshot_id 返回 409；evidence relations 返回支持关系；页面与 4 个 JS 资源 200；`node --check` 6 个 JS 全部通过。
- **NOT_RUN**：实际浏览器主路径操作（环境无浏览器自动化工具）；真实联网调查与人工质量评分（未委托、未消耗额度）。

### 21.5 已知限制与下一步

- facets（rule_change/billing_remedy 等）、EventNode 双时间口径模块、SearchTask/CoverageRecord、定向补查幂等创建、图表统计均未实施（P2–P4）。
- 历史条目与版本列表仍以 run_id 前 8 位作辅助标识（非主标题）；完整报告视图的“回应覆盖”等旧区块保留在完整报告 tab，未强行迁移。
- 实施指南要求 P1 退出须通过实际浏览器操作验收，当前以 API 级验证 + JS 语法/投影测试替代，浏览器主路径保持 pending。

## 22. 工作台 P2–P4：事件侧重点、定向补查与统计成员绑定（2026-09-11）

> 阶段状态：P2 / P3 / P4 implemented_unverified（机制与 API 验证完成；实际浏览器主路径 NOT_RUN，真实联网与人工评分未消耗额度）。P5 门槛未达成，未把代码完成当作 P5 通过。

### 22.1 数据与不变量

- **EventProfile**：facets ∈ {rule_change, service_change, billing_remedy, investigation_correction, general}，由计划提议、`presentation.confirmed_profile` 程序确认（未知名丢弃、general-only 不建档、用户必答问题不受影响）；随 State（`profile` 字段，缺省 None 兼容旧 checkpoint）提交并写入 report/workbench。State 校验 `profile.question_refs ⊆ issues`。
- **Facet 模块（确定性）**：`presentation.FACET_MODULES` 四类侧重点 → 四个白名单模块；模块数据可用（绑定问题存在 active finding）才 ready，否则 insufficient 且缺口文案固定（旧规则不补写；受理渠道≠已退费、金额不明不填 0；计划恢复与已恢复分开；启动调查/结论/落地三分）。`highlights()` 只取 facet 模块且最多 3 个，ready/provisional 优先。
- **Provisional 语义**：`publication_state != 终态` 时所有数据可用的模块（基础 + facet）一律 provisional；运行中每次 checkpoint 写 `workbench-provisional.json`，发布/失败/取消后删除或被 report.json 取代。
- **SearchTask 最小契约**：SearchAttempt 增加 `task_id`（uid(search-task, issue, query, page)）、`target_gap`、`discovery_mode`；Reducer 按决策的 target_gap 判定 targeted/discovery；Compiler 注入 `memory.coverage`（每问题 attempts/errors/outcomes + 近期 gaps），提示词声明"重复方向改为换别名/原始出处/机构域名/材料类型"。
- **材料成员口径**：发布分布按“URL=文档”计数，成员绑定 url→version_ids；点击成员数 == 显示计数（测试覆盖同 URL 两版本计 1 的场景）。

### 22.2 接口与页面

- `GET .../materials?snapshot_id&issue_id&offset&limit`（limit≤100）：同一快照内按议题成员筛选（finding 的 evidence/contradicting → version_ids），未知议题 409、负分页 400。
- update 契约：`issue_ids`/`finding_ids` 必须属于父版 report，否则 ValueError(409)；`client_request_id` 以内容哈希（payload+parent_id）幂等，同 key 异内容 409，注册表 `cases/<case>/requests.json`；补查意图持久化于子 run `draft.followup`；并发创建仍由 CaseLock 排除。
- diff 响应新增 `comparability`（same_case、两版 cutoff/status、口径变化标注位）。
- 前端：总览新增“本事件重点模块”卡（facet 模块 + 状态徽标 + 选择理由 + 缺口说明）；报道对照新增“搜索覆盖（本次已查范围，非全网召回率）”；发布分布日期桶可展开成员链接；进度页新增“查看阶段工作台（待核查）”入口（无报告 tab、无下载/补查按钮、显示“阶段投影：内容未经最终审查”徽标）；补查表单支持勾选父版问题并以 `crypto.randomUUID` 生成幂等键。

### 22.3 验证

- `pytest tests/investigation tests/e2e/test_investigation_web.py -q`（无代理环境）→ **74 passed**（新增：facets 确认/差异/回退/insufficient 缺口/provisional/highlights 上限 7 项；定向补查引用校验/幂等/持久化/搜索任务/Compiler 覆盖/运行中投影 7 项；分布文档计数与成员绑定 1 项；e2e materials 与 diff comparability 断言）。
- 真实运行（offline，端口 8918）：公交问题 → facets=[rule_change]、模块 rule-comparison(ready)、highlight=rule-comparison；水费问题 → facets=[billing_remedy]、模块 billing-remedy(ready)；同一工作台呈现不同重点（W02 场景）。materials 总数=2、issue 过滤=1、分页正常。定向补查：issue_ids 引用通过创建 201，同 key 重放返回同一 run_id，同 key 异内容 409。
- JS：6 个模块 `node --check` 通过。
- **NOT_RUN / pending**：实际浏览器主路径（无浏览器自动化工具）；真实联网调查与人工 90%/95% 评分（未委托额度）；观点构成图表（按计划保留 pending，需归因/去重/分类评估先行）；P5 的固定材料语义回放仅覆盖 offline 脚本夹具，10 个正式案例仍为 blocked 槽位。

### 22.4 已知限制与下一步

- facets 目前只影响模块选择与总览重点，搜索词生成尚未按 facet 分支（P3 的“让缺口影响下一次搜索”已具备 coverage 注入与 target_gap 通道，实际效果待真实模型运行观察）。
- 阶段投影为每 checkpoint 全量重建，规模上限未测；发布分布/覆盖数据尚无独立 metrics.py（当前由 workbench 纯函数承担，字段已按 MetricSnapshot 口径预留）。
- 10 个正式案例 registry 仍为 blocked；T0/T1 案例材料与人工标注到位后才能执行 P5 门槛。

## 23. 工作台实际浏览器主路径验收（2026-09-11，P1/P5 补验）

> 阶段状态：P1 verified（浏览器主路径补验完成）；P5 浏览器项完成，联网与人工评分项仍 NOT_RUN。

### 23.1 方式

Playwright（仓库外托管 Node 工作区安装，不进入项目依赖）驱动真实 Chromium headless，访问本地 8918 服务器真实页面，按用户路径操作并逐步断言；脚本与截图存于托管工作区 `browser_acceptance.js` 与 `/tmp/ops-browser/`（11 张截图 + steps.json）。项目源码零新增依赖。

### 23.2 结果：17/17 步通过

首页表单创建 → 进度页（无百分比、含“查看阶段工作台（待核查）”）→ 阶段投影徽标可见并可返回 → 终态工作台总览（重点模块 rule-comparison 卡）→ 点击“引N”打开证据抽屉（真实保存原文摘录）→ 关闭后焦点回到触发元素 → 报道对照（材料条目 + 来源关系徽标）→ 议题与核查 → 完整报告（无内部 evidence_id chip）→ 定向补查表单（勾选父版问题 + 幂等键）创建子 run → 版本比较渲染差异 → 水费事件经同一 UI 呈现 billing-remedy 重点（无 rule-comparison）→ 历史项以事件文本而非哈希为标题 → 刷新恢复同一视图。

### 23.3 浏览器验收发现并修复的三个真实缺陷

纯 API/机制测试均未暴露，说明该层验收不可省：

1. **终态工作台白屏**：`app.js` 残留对已删除变量 `paintConnection` 的赋值，渲染即抛 ReferenceError——此前 API 验收全绿是因为从未执行这段前端代码。
2. **证据抽屉无法打开**：`evidence.js` 的 `let triggerCounter` 位于 `return` 之后成死代码，`open()` 触发 TDZ 错误。
3. **内部 ID 泄漏残留**：完整报告“核心回答”与“事件时间线”两处 chips 未传引用标签映射，仍显示原始 evidence_id。

### 23.4 验证命令

- 浏览器：`node browser_acceptance.js`（BASE_URL 指向本地服务器）→ `17/17 steps passed`。
- 修复后 6 个前端模块 `node --check` 通过；后端无改动。
- 未覆盖：SSE 真实断线恢复（需断网注入）、320px 窄屏与键盘全键盘走查——留作后续浏览器验收扩展。

## 24. 参考版式落地与自包含 HTML 导出（2026-09-11）

> 阶段状态：verified（机制测试 + e2e + 真实浏览器 23/23 步）。用户确认的目标：页面随事件变化 + 可直接产出可打开/分享的 HTML。

### 24.1 设计取舍（明确拒绝的路径）

用户提出“直接产生 HTML”。采纳的是**投影的渲染出口**，不是“让模型写页面”：

- 拒绝：模型输出 HTML/CSS/脚本/组件名/像素布局/百分比。理由与实施指南 §3.3 一致（外部材料不可信、统计必须可复算、每事件一套页面无法回归）。
- 采纳：同一份 `opinion-workbench/1` 快照可产出在线页面 / 自包含 HTML / Markdown / JSON；内容自适应由 facet 模块与投影决定，模型只提议领域内容。

### 24.2 实现

- **共享样式 `web/assets/workbench.css`**：在线页 `<link>` 引用；导出时由 `export.render_page` 读取同一文件内联，保证两种呈现版式一致（无复制维护）。类名前缀 `os-*`。
- **`investigation/export.py`**：纯模板渲染，输入 workbench 投影 + report（取 evidence/sources/source_relation_counts）+ `evidence_context`（manager 提供 before/after）。不使用 JS、不用外部资源；`html.escape` 全量转义；外链仅 http/https（`_safe_url`）；引用角标 `[n]` 以 `#cite-n` 锚点跳转“引用与原文”；缺失正文/缺证据时显示"保持未知"而非相近原文。
- **`Manager.page()` + `_evidence_context()`**：先经 `workbench()` 校验 snapshot 锚定（不匹配 409），再一次性读取归档正文切片（`verify_evidence` 失败即跳过，不伪造）。
- **接口**：`GET /api/investigations/{id}/page`（`snapshot_id` 锚定；`download=1` 返回 `Content-Disposition: attachment`）；前端顶栏提供“打开静态页 / 下载 HTML / 下载 Markdown / 版本比较”。
- **版式重建**（`workbench.js` 重写）：左侧调查导航、眉标（facets + 状态）、标题行（补查入口）、范围行 + 检索范围折叠（搜索覆盖）、摘要内联引用角标、材料分布可按日期筛选（点击即筛报道列表）、议题块（依据/反驳引用 + 对照相关材料 + 补查缺失依据）、常驻证据核查栏（选中材料 → 原文片段高亮 + 关系 + 仍缺 + 补查入口）、引用与原文附录、底部材料集口径。

### 24.3 浏览器验收发现并修复的缺陷

1. **哈希链接被静默丢弃**：`ui.js` 的 `el()` 仅对 http/https 设置 `href`，导致 `#/...` 入口（版本比较、查看上一完整结果）渲染成无 href 的空锚点，点击无反应——纯 API 验收不可见。
2. （同批）补齐新布局下遗漏的“版本比较”入口与补查表单的问题预选（`?issue=` 直达并勾选对应问题）。

### 24.4 验证

- `tests/investigation/test_page_export.py` 7 项：自包含/内联样式、快照绑定、无内部 ID、转义注入文本（`<script>` → 实体）、上下文与定位、缺证据与模块缺口的诚实呈现、阶段投影标记、offline 虚构材料标记。
- `pytest -q -m "not live"`：见本轮回归结果（后端无回归）。
- 浏览器 23/23 步：新增“导出被服务为 text/html”“导出自包含且无内部 ID”“附件下载头”“静态页在独立页面渲染成功”，以及新布局的侧栏/证据栏/日期筛选/议题/引用附录。
- **未覆盖**：断网注入的 SSE 恢复、320px 窄屏、全键盘走查；导出页在极端材料量下的体积（未压缩）。

## 25. 工作台视觉打磨与两处真实缺口修复（2026-09-11）

> 阶段状态：verified（测试全绿 + 浏览器 23/23 + 1440px 截图复核）。

### 25.1 视觉改造（用户反馈“间距和设计不好”）

- **间距体系**：`.os-page` 内定义局部令牌 `--os-gap-xs/sm/md/lg/xl`（6/10/16/24/32）与 `--os-pad-x`；断点只改 `--os-pad-x`，避免各处魔法数字（此前 18/20/22/24 混用）。
- **页面容器**：工作台加卡片外壳（`max-width: 1400px`、圆角 14px、边框），并让 `body.wide` 把 `main` 放宽到 1440px（此前被 `main{max-width:1040px}` 压窄，右侧证据栏挤压正文）。
- **顶栏**：导出/比较入口收进 `.os-tools` 药丸组（含分隔线），与品牌徽标分区，不再是一串裸文本。
- **眉标与范围行**：眉标改为“键—值 + 分隔点 + 状态徽标”结构；范围行用 `.os-meta-item`（标签 + 加粗值），并把重复的状态/演示徽标从范围行移到眉标，消除重复与换行。
- **分区层次**：研判摘要改为卡片（浅底 + 左侧强调条 + 判断间虚线分隔）；模块卡、议题卡、材料卡统一 `--os-radius` 与内边距；章节标题加 3px 强调条；正文段落限宽 `76–78ch`。
- **材料分布**：日柱卡改为固定宽 88px（此前 `flex: 1 1 76px` 会把单日卡片拉伸到整行、计数与柱子分离），柱高 68px 容器内底部对齐，日期只显示 `MM-DD`；导出页同步。
- **列表与证据栏**：材料卡加 hover 阴影与元信息行；证据栏改为带边框的浅底卡片、粘性定位、独立标题层级；引用角标改为上标样式并支持选中态。
- **基础页**：`style.css` 统一卡片圆角/内边距、输入聚焦环、按钮 hover、历史项 hover；页头链接层级与主题色统一。

### 25.2 打磨过程中发现并修复的真实缺口

1. **定向补查丢失事件侧重点**：子版本此前 `profile=None`，导致补查后“本事件重点模块”整体消失（浏览器截图才看出来）。改为继承父版已确认 profile（`profile=old_state.profile`），并加测试 `test_update_run_inherits_the_parent_event_emphasis`。
2. **导出页缺设计令牌**：导出只内联 `workbench.css`，而 `--bg/--panel/--ink` 等令牌定义在 `style.css`，脱离浏览器默认值就会失去配色（深色模式下更明显）。现导出同时内联 `EXPORT_BASE` + `style.css` + `workbench.css`。

### 25.3 验证

- `pytest -q -m "not live"`：全绿（含新增 facet 继承测试；导出 7 项）。
- 浏览器 23/23 步复跑通过（含导出与的新布局断言）。
- 1440×1000@2x 截图复核：总览 / 报道对照 / 议题与核查 / 静态导出四个视图。
- **未覆盖**：320px 窄屏与深色模式截图复核（CSS 已写暗色友好的令牌引用，但未实测）、全键盘走查。

## 26. 深色/窄屏/键盘打磨与 P4 增量（2026-09-11/12）

> 阶段状态：verified（非 live 全量回归 + 浏览器 23/23 + 走查 9/9 截图复核）。

### 26.1 视觉与可达性打磨（覆盖 §25.3 的未验证项）

- **深色模式**：令牌调优（accent 提亮为参考稿 `#96b7ff`，warn/danger/ok 同步提亮，panel/bg/line 拉开一档）；accent 实心主按钮在深色下文字翻转为深藏青；mark 高亮深色下改为暗琥珀底 + 亮琥珀字；`.badge` 的 `display:inline-block` 曾覆盖 UA `[hidden]`，连接状态徽标隐藏时仍渲染为顶部空胶囊——补 `[hidden]{display:none!important}`（线上与导出同源生效）。深色截图逐视图复核（总览/证据栏/引用/议题/导出）。
- **窄屏**：≤850px 证据栏 `order:-1` 提到单列最前（此前在整页最底部）；≤620px 工具组居中换行并去掉行首残留分隔线、区块头改上下堆叠、研判卡内边距收窄；走查中发现筛选行 label 被 flex 收缩至 CJK 一字一行，加 `flex:0 0 auto`。320px 无横向溢出（脚本断言）。
- **键盘**：全局 `a/button/summary:focus-visible` 2px 实线焦点环；证据抽屉打开时焦点移入"关闭"按钮、Esc 任意位置关闭、关闭后焦点回落触发 chip（回落逻辑原有）；抽屉收起时 `visibility:hidden` 移出 Tab 序（此前关闭的抽屉按钮仍可被 Tab 聚焦）。
- **验证**：走查脚本（`/tmp/os-polish/verify_polish.js`，Playwright）：Tab 6 次到导航钮、焦点环 2px solid、行内引用可键盘聚焦、抽屉焦点入内/Esc 关闭/焦点回落、320px 无溢出——全部通过。

### 26.2 P4-3：图表度量契约（`investigation/metrics.py`，新增）

- `METRIC_DEF_VERSION = "workbench-metrics-1"`；发布分布从 workbench.py 迁入 `metrics.publication_distribution`，新增 `metric_def_version` / `material_set_version`（版本集合哈希）/ `inclusion`（口径文本），成员绑定不变（同 URL 多正文版本按文档计）。
- 新增 `metrics.issue_involvement`：每议题"涉及材料"计数，成员 = 该议题 active finding 引用（支持 + 反驳）命中的**正文版本**，与 `materials` 端点及前端 coverage 过滤完全同一口径（显示计数 == 点击下钻成员数，W19）；同一版本在同一议题只计一次、跨议题允许重复；观点构成（百分比）仍按条件保持 pending。
- 投影 `views.issues.issues[].involved_materials`（count/members/members_hash/inclusion）；前端议题区按钮改为"对照相关材料（N 篇）"，导出议题区显示"涉及材料：N 篇（同一快照内的筛选口径，非公众讨论总量）"。
- 测试：`test_publication_distribution_carries_its_metric_definition`（定义版本/材料集版本稳定性与敏感性）、`test_issue_involvement_counts_match_the_drilldown_membership`（跨议题重复、未激活 finding 不计、与 coverage 过滤基一致）、`test_export_shows_per_issue_material_counts_from_the_snapshot`。

### 26.3 W18 前端入口：partial 不掩盖上一完整结果

- 后端 `snapshot.latest_completed_run_id`（§21 已有机制测试）此前无任何 UI 消费。现工作台顶部新增 `.os-version-note` 横幅："本版本{状态}；最近一次完整结果仍可查看：查看上一完整版本"，并注明"未复评的判断以当前页面为准，不视为已被上一版撤回"；`renderPending`（终态无报告）同步提供链接。浏览器断言横幅出现且 href 指向 `latest_completed_run_id`。

### 26.4 导出修复：`{cards}` 字面量

- `export.py` `_overview_section` 第二段字符串漏 `f` 前缀，静态导出渲染出字面量 `{cards}` 且重点模块卡从未被插入导出页。修复并加回归测试（`test_export_renders_facet_module_cards_instead_of_template_literals`）。

### 26.5 验证

- `pytest tests/investigation -q`：79 passed（含 4 项新测试）；`tests/e2e/test_investigation_web.py`：7 passed；`pytest -q -m "not live"`：675 passed, 2 deselected。
- 浏览器验收 23/23（`browser_acceptance.js`）；走查 9/9（新增 W18 横幅断言、W19 计数 == 下钻列表断言）。
- 导出页 grep：无 `{cards}`，模块卡与"涉及材料"计数出现。
- **未覆盖 / NOT_RUN**：真实联网调查与人工质量评分（额度与案例材料，P5 仍 blocked，registry 10 槽位全部 blocked）；观点构成图表按条件 pending；真实断网注入的 SSE 恢复演练未做（有界重连逻辑有机制测试）。

### 26.6 W 场景补强（2026-09-12）

- **W11 证据定位**：新增 `test_evidence_positioning_survives_emoji_and_combining_marks`——astral emoji（🙂🌙）与组合字符（e\u0301）文本上 `verify_evidence` 按码点切片校验通过，manager/export 的 before/excerpt/after 预切重组恒等于原文；被丢弃 emoji 的"近似原文"无法通过校验（fail closed）。前端只渲染预切文本，不存在 UTF-16 下标换算。
- **W17 对照页**：版本比较从"纯文本拼接"升级为逐条渲染——每条判断带"（核查：{核查结论} · 依据 N 条）"（不暴露内部 evidence_id），撤回原因逐条显示（`retired_reasons`），未复评仍是独立状态标签不叫撤回。浏览器断言：`.issue li` 含"核查："与"依据"（6 条）。
- **W12 断网注入演练**（此前仅有机制测试，无浏览器级验证）：真实 Chromium 从创建起 route.abort 全部 `/events` SSE——页面出现"连接中断，正在恢复…"横幅（脚本捕获到可见窗口），快照补取路径完成调查并渲染工作台，URL run 不变（未新建 run）。与 §21 的有界退避机制测试互补。
- **W23 宽度走查**：64 字长标题 run 在 768/1024px 无横向溢出（scrollWidth 断言），截图 `narrow768-longtitle.png`。
- 验证：`pytest -q -m "not live"` 676 passed, 2 deselected；浏览器验收 23/23；走查脚本 14 项全过。

## 27. 额度恢复后的首次 live 验证（2026-09-12）

> 阶段状态：verified（机制与溯源）；质量门槛 NOT_CLAIMED（仍达不到 90%/95%，理由见下）。

### 27.1 额度现状（更正 §20.9 的"额度耗尽"记录）

最小探测（各一次调用，不打印密钥）：模型网关 `opencode.ai/zen/go/v1` + `deepseek-flash` + `x-opencode-session` 头 → **200 OK**（43 tokens）；Brave → **200 OK**，本月剩余 **1,884 次**；Jina 无 key 走匿名档 → 200 OK。9/11 的"额度耗尽"只代表当时状态。注意 `.env` 的 `OPINION_MODEL_EXTRA_HEADERS` 是 **JSON 格式**；另发现一个 pytest 遗留服务进程占端口（`--env-file /dev/null`），重启服务时需先清理。

### 27.2 live 运行记录

- 事件：重庆燃气费计费争议的退费安排与整改进展（经 Web API `mode=live` 创建，runs 目录 `/tmp/os-polish/live-runs`，run `73e84650a9214f929ed16be1490c9f1d`）。
- 结果：**partial**；13 个真实来源（含官方通报/媒体，发布窗口 2024-04-14 — 2025-02-14，11 篇发布时间未知）、75 条证据（全部通过字符区间校验）、8 个问题（1 个 answered：2024 年首轮退费到账进度；7 个 open）、18 条 active 判断、**0 条核心结论**（复核门未通过任何核心断言）。
- 失败诚实计数：搜索失败 0、读取失败 3（UI 总览明示"缺失材料不代表没有新进展"）；来源关系全部标"未核实"，不冒充独立。
- stop_reason：`Decision recovery was exhausted: The model response did not match the decision schema.`——与 §20.7 一致，模型决策结构化成功率仍是质量瓶颈。模型本轮未提出可用 facets，投影如实回退 general 视图。
- 新契约在真实数据上生效：发布分布携带 `metric_def_version/material_set_version`；议题涉及计数（1–2 篇/题）与 `materials?issue_id=` 端点总数一致（W19 实测通过）；导出自包含、无内部 ID、Markdown/附件头正常。

### 27.3 浏览器验证

部分完成徽标、空研判卡（"尚无可对外核查的核心判断"）、读取失败提示、13 篇材料展开（"展开全部 13 篇"）、证据栏真实原文与关系——10 项断言全过（coverage 计数断言首跑误写为 ≥10，实为设计上默认折叠 4 篇 + 展开按钮，修正后确认）。截图 `/tmp/os-polish/live-shots/`。

### 27.4 尚未完成（与 P5 门槛对照）

- 案例材料仍 blocked：registry 10 槽位无真实快照与人工标注，固定材料语义回放无法执行。
- 核心结论 0 条 → 人工 95% 断言支持评分无分母；必答问题仅 1/8 answered，远达不到 90% 门槛。
- 结论：**不得宣称 P5 通过**；live 链路的机制、溯源、诚实状态呈现验证通过，质量瓶颈（决策 schema 成功率、核心结论复核门）与 §20.7 判断一致，是下一步模型侧/提示侧工作的对象。

## 28. 决策恢复修复与 live 复验（2026-09-12）

> 阶段状态：verified（离线 685 passed + 同题 live 复验 completed）。单次对照，不构成质量结论。

### 28.1 病因取证（run 73e84650 检查点）

42 步里 7 次 invalid_decision：`read requires an allowed discovered candidate` ×5、未知 issue/evidence 引用 ×1、第九问题 ×1；致命一步为 schema 不匹配但 pydantic 原因被丢弃。`max_decision_attempts=2` 下一步两败即整轮 partial。

### 28.2 修复（commit "decision-recovery resilience"）

- **可观测性（P0）**：schema 失败消息携带 pydantic/JSON 具体原因（字段路径+期望）+ 内容头样本（≤160 字符入 failure；完整样本进服务日志 warning）。
- **输出上限（P1）**：请求显式 `max_tokens`（新 `OPINION_MODEL_MAX_OUTPUT_TOKENS`，默认 4096）；`finish_reason=length`（含推理耗尽导致的空正文）在传输预算内翻倍上限重试，耗尽后给出带安全诊断的 EMPTY_RESPONSE——不再烧决策预算。
- **决策预算（P1）**：默认 `max_decision_attempts` 2→3（新 `OPINION_MAX_DECISION_ATTEMPTS`）。注意：live 执行 profile id 内嵌该参数，旧未完成 live run 的恢复会被显式拒绝（契约性不兼容，非静默转换）。
- **read 反馈（P2）**：URL 先规范化（协议大小写/尾斜杠）再对候选匹配；拒绝消息拆分三种原因并附最多 3 个合法候选 URL 提示；INSTRUCTIONS 明示"逐字复制候选 URL、页面内链接先 search"与"问题总数 ≤8"。

### 28.3 同题 live 复验（run 014aa9b7，事件同 §27）

| 指标 | 修复前 73e84650 | 修复后 014aa9b7 |
|---|---|---|
| 终态 | partial（约 1/4 预算即死于 schema） | **completed** |
| stop_reason | Decision recovery was exhausted | 必答问题全部有处置、active findings 通过证据审查 |
| 问题 | 8（1 answered） | 5（**全部 answered**） |
| 核心结论 | 0 | **8**（含日期/数字/诚实的"无统一退费方案文本"表述） |
| 证据 / 来源 | 75 / 13 | 67 / 13 |
| 失败 | 0 搜索 / 3 读取 | 0 搜索 / 7 读取（如实计数） |

浏览器断言 10/11 通过（唯一 FAIL 为脚本旧断言，对应"coverage 默认折叠 4 篇"的设计行为，展开后 13 篇已单独验证）。导出/Markdown/附件头正常。

### 28.4 边界

单次对照存在模型随机性；结论限定为"决策恢复链路修复后，同题 live 可达 completed 且复核门真实通过"。90%/95% 门槛仍需案例回放与人工评分（registry 仍 blocked）。

## 29. 低门槛澄清契约：用户永远可以往前走（2026-09-12）

> 阶段状态：verified（离线回归 691 passed，含新增 `tests/investigation/test_clarify_proceed.py` 3 项；browser_acceptance 23/23）。首页文案与系统行为同步按"降低开始门槛"调整。

背景：首页按用户反馈改为邀请式文案（"一句话就能开始，缺什么系统会再问你"，commit 76d9cb2 后重做 b28338b）；用户随后指出系统侧也必须适配，否则文案只是空头承诺。系统侧缺口：live 首跑一次追问 5 个问题（run 09e78bcf 澄清页实测）、纯退让回答（"不知道"）会被原样存储并再次追问、追问轮数无上限。

### 29.1 系统行为变化

- **追问收敛（prompt）**：`PLAN_INSTRUCTIONS`（service.py）限定每轮最多 3 问、只问会改变搜索方向的细节、不得重问澄清记录中已回答的内容；记录显示用户无法确定事件时，选最常见理解直接出计划。
- **退让兜底（机制）**：`clarify()` 识别纯退让回答（`_DEFER_ANSWER`：只知道/不清楚/你看着办/随便/按你的理解等整句匹配，含具体内容的回答不误伤），或在第 `_MAX_PLANNER_CLARIFY_ROUNDS=2` 轮后，置 `plan_hint="proceed_on_assumption"`；`_investigate` 据此给 planner 追加 `PROCEED_ON_ASSUMPTION_INSTRUCTIONS`（禁止再回澄清、选最常见理解、把理解写进 subject 措辞）。`draft.json` 新增 `clarify_rounds`（create 初始化 0）。时间范围澄清不在此列（已有"不限时间"出口）。
- **假设可见（契约）**：`build_report` 新增 `scope_notes` 参数；manager 四处发布投影（running/failed/cancelled/final）传入 `_assumption_note(data)`，假设以"用户未能明确事件对象，系统按最合理的理解继续调查：<subject>；这一理解可能与用户实际所指事件不同。"拼入 `scope_limitation`（Markdown、静态导出、工作台 limitations 同源展示）。
- **前端**：澄清页（非时间阶段）在输入框下提示"不确定的问题可以直接回答"不知道"——系统会按最合理的理解继续调查，并在报告限制中注明这一假设。"

### 29.2 验证与边界

- `test_clarify_proceed.py`：纯退让正则不误伤含内容回答；"不知道"→ 跳过追问直接 completed 且 scope_limitation 含假设；两轮正常回答后第 2 轮强制继续（monkeypatch scripted planner）。
- PROCEED 指令对 planner 的实际遵从度属 live 行为，未在本次验证（live 额度预算保留）；机制层面（提示注入、hint 持久化、注记落报告）为离线可验证事实。


## 30. 2026-09-12 审查第一轮修复（F01/F02/F04/F05/F10 与演示案例错配）

> 阶段状态：verified（离线 non-live 回归 702 passed, 2 deselected；新增定向补查、证据核验、演示双 kit 测试；真实 Chromium + CDP 检查 F01/F02/F10 主路径通过）。本节点对应 [2026-09-12 审查](./opinionsearch-workbench-review-2026-09-12.md) 第一轮范围，未实施 F03/F06/F07/F08/F09/F11。

### 30.1 F01：导出入口契约修复

- `web/assets/ui.js` 的 `el()` 不再只接受绝对 http(s) URL 或 hash；新增 `safeSameOriginPath()`，仅允许以单个 `/` 开头且解析后 origin 与当前页面一致的同源路径，仍拒绝 `javascript:`、`data:`、`//host` 与控制字符。
- 真实页面中“打开静态页 / 下载 HTML / 下载 Markdown”的 href 现分别为 `/api/investigations/{id}/page?snapshot_id=...`、`/page?download=1...`、`/report`。
- 浏览器真实点击验收：打开静态页在新标签渲染；HTML 附件包含当前 workbench snapshot_id；Markdown 附件包含当前报告 subject；三者均从真实用户点击触发，不以直接请求接口代替。

### 30.2 F02：引用独立选择与无回退证据栏

- `workbench.js` 的文章卡不再把整个 article 绑定到首条引用；引用按钮和文章卡键盘操作分别处理，引用点击使用 `stopPropagation()` 选择自身。
- 证据栏选中逻辑不再 `find(selected) || citations[0]`。无效选中、未选择、无引用材料或缺失引用各自显示明确状态，绝不回退到另一条原文；材料卡增加 `tabindex` 与 Enter/Space 键盘激活。
- 浏览器检查：同一篇文章点击第二条引用后，证据栏显示 `[2]` 而非 `[1]`；对材料卡派发 Enter 后能选择引用。

### 30.3 F04：定向补查进入 State 与编译上下文

- 领域模型新增 `UpdateIntent` / `UpdateTarget`，State 新增可选 `update_intent`。
- `Manager._investigate` 在父版更新时区分两类行为：
  - 用户勾选 `issue_ids` / `finding_ids` 时，只重开选中问题（selected finding 会自动映射到其 issue），未选中问题保留原状态与未过期旧判断；旧 `reviews` 随 State 复制，使未重开判断仍可参与完成判定。
  - 未提供定向目标时才沿用全量重做语义。
  - 子版 `aliases` 改为继承父版 State，而非来自默认 PlanProposal。
- `Compiler` 新增 `memory.update_intent` 受信区段（parent_run_id、issue_ids、finding_ids、finding→issue/evidence targets），模型在首轮动作前即可看到用户指定目标；`INSTRUCTIONS` 明确“先处理 update_intent，不重开无关问题”。
- `app.js` 的补查表单在内容签名不变时复用同一个 `client_request_id`，网络响应丢失后再次提交可命中服务端幂等；编辑关注点或勾选内容后生成新 key。

### 30.4 F05：正文核验状态进入在线与静态导出

- `Manager.evidence()` 返回 `verification`：`verified` / `unverified`（摘录与归档正文不一致或越界）/ `unavailable`（artifact 不可读）/ `pending`（运行中）。验证失败仍保留报告摘录供追溯，但不再伪装成已定位原文。
- `Manager._evidence_context()` 对每条证据显式给出状态与理由；`export.py` 新增 `_excerpt_block()`，只有 `verified` 才输出 `<mark>`，否则在引用位置输出“未与归档正文比对”的说明并展示保存摘录。
- 在线“引用与原文”视图改为逐条读取 evidence API 的核验状态后再渲染高亮，和证据栏保持一致。
- 回归：`test_evidence_endpoint_and_export_report_a_verification_failure` 篡改 artifact 后在线端点、workbench 上下文与静态页引用位置均标记不可核验；导出单测覆盖 verified / missing / unverified 三种上下文。

### 30.5 F10：工作台阅读状态进入 URL 路由

- `workbench.js` 新增路由状态归一化与 `workbenchRouteHash()`；`view` / `issue` / `date` / `role` / `evidence` / `material` 与 `snapshot` 写入 hash，app.js 在渲染终态工作台时读取并传给组件。
- 刷新恢复同一 run/snapshot 的视图、筛选、选中引用；无效 issue/date/role/evidence 显示明确提示，不套用其他筛选或回退首条证据。
- 浏览器检查：切到“报道对照”并选择第二条引用后刷新，仍停留在报道对照且证据栏保持 `[2]`。

### 30.6 F12（演示错配部分）：两套互不混用的离线材料

- `offline.py` 拆分 bus 与 water 两套完整 fixture，`fixture_for_request()` 依据任务文本在规划前确定性选择；SearchAdapter / ReaderAdapter / OfflineModel 使用同一 kit。
- 水费 kit 的计费、复核、退费材料与对应 facet/finding 互不复用；更新时仍使用水费 kit 的补充说明。
- 回归：`test_bus_and_water_offline_kits_stay_separate`、`test_water_update_uses_water_fixture_response`；首页离线模式文案说明两套案例按输入切换。

### 30.7 验证证据与边界

- `pytest tests/investigation tests/e2e/test_investigation_web.py -q`：108 passed。
- `pytest -q -m "not live"`：702 passed, 2 deselected（命令均在 `opinion_search_agent/` 下，虚拟环境 Python，`PYTHONPATH=src`）。
- 真实 Chromium `--headless=new` + 本机 CDP 手工检查脚本：确认 F01 三个导出入口（含真实点击打开静态页与两个附件下载，内容分别绑定 snapshot_id / subject）、F02 第二引用选择与材料键盘激活、F10 刷新恢复；输出 `BROWSER_CHECKS_OK` 与 `DOWNLOAD_CHECKS_OK`。
- 未验证 / 未实施：F03 内容适配、F06 复合问题逐项完成约束、F07 覆盖分配与来源关系、F08 信息层次、F09 材料对照关系、F11 快照版本语义，以及 F12 的澄清兜底/对象纠正入口部分；真实联网调查与人工质量门槛仍待 P5。本节点不得被引用为这些项的通过证据。

## 31. 2026-09-12 审查第二轮实现（F03/F06/F07/F09）

> 阶段状态：verified（离线 non-live 回归 720 passed, 2 deselected；定向/Web 测试 126 passed；真实 Chromium CDP 主路径含结构化模块字段、复合问题组件、材料摘要与证据关系）。真实联网质量门槛仍为 NOT_CLAIMED。

### 31.1 F03：专项模块内容适配

- `domain/investigation/models.py` 新增 `ModuleField` 白名单与 `MODULE_FACET_FIELDS` / `REQUIRED_MODULE_FIELDS` / `FACET_MODULE_TYPES`；`FindingProposal.module_fields` 只允许模型为已确认 facet 模块填写合法字段，未知字段在模型校验阶段拒绝。
- `confirmed_profile()` 现在利用 `issues` 按问题措辞建立 `EventProfile.question_refs`；专项 relevance 不再默认读取全部问题。`facet_modules()` 只收集与模块主题相关（或携带该模块结构化字段）的 active finding，并按字段白名单组装：
  - 规则：旧值、新值、适用对象、生效时间、过渡安排；
  - 服务：受影响服务、时间段、替代安排、恢复进展；
  - 计费：计费口径、适用范围、办理路径、办理时限、退还/整改安排、实际执行证据；
  - 调查：已采取行动、结果与承诺、判断变化。
- 发布状态收紧：终态仅当必需字段齐备、无字段冲突且来源判断全部 `supported` 才 `ready`；字段缺失/冲突/未形成字段为 `insufficient`；判断未 review 为 `provisional`，partial 中的未审查判断不能获得可发布含义。未知字段保留“未知”槽位，不挪用无关事实。
- 前端与静态导出渲染结构化字段；总览消费 `overview.highlights`，实际最多 3 个重点模块。
- 离线 bus/water fixture 分别携带规则/计费模块字段，保证两类事件在同一套页面中长出不同内容。

### 31.2 F06：复合问题逐项处置

- 新增 `QuestionComponent` / `ComponentAssessment`；`Issue.components` 保存复合问题子项，`QuestionProposal.components` 允许计划阶段显式拆分。
- `Manager` 在生成 issue 时对顿号/分号/“以及”枚举的问题自动派生 components；定向重开时子项状态重置为 open。
- `Validator` 要求：复合问题标记 answered/disputed 时必须逐项处置；components 引用必须属于当前证据；answered/disputed 子项必须有依据；not_found/unavailable 子项必须有边界说明；answered 整题不得保留非 answered 子项。
- Reducer 合并子项处置；Completion 对未处置子项、或 answered 问题中非 answered 子项返回 partial。
- Workbench/export 议题区显示每个子项的状态、文字、依据与说明。
- 审查降级护栏：`unbacked_specifics()` 对 finding 中的数字/日期/百分比做确定性核对，未在支持摘录中出现时，reviewer 的 `supported` 自动降为 `partial`；审查 prompt 同步要求 concrete number/date/percentage/named measure 逐项有摘录支持。这针对长复合 finding 被“大意正确”整体放行的问题。

### 31.3 F07：可解释覆盖分配与来源关系

- Compiler 的 `memory.coverage` 与 workbench 的 search coverage 现按问题列出：已尝试 purpose 及候选/失败计数、未尝试方向、失败未出候选方向、本轮 target_gap。方向计数只解释查过什么，不作为固定配额或召回率。
- 前端“查看检索范围”和静态导出显示已查/未尝试/失败方向及补查缺口。
- 新增 `SourceRelationProposal` / `SourceRelation`：类型限 same_text / repost / excerpt / followup；basis evidence 必须属于关系两端版本，否则校验拒绝；reflect 可一次提交，Reducer 持久化。
- report 来源新增 `relation` / `relation_status`（`program_hash_duplicate` / `model_proposed` / `unverified`）/ `relation_evidence_ids` / `relation_explanation`；`source_relation_counts` 增加 repost/excerpt/followup/model_relation_count。模型关系页面上明确标注为“提出、待人工复核”，不包装成已验证独立。
- 内容哈希重复仍为 duplicate；提出依赖关系的来源 `independent=False`，重复通报不作为多个独立支持。

### 31.4 F09：报道对照中的主张与判断关系

- workbench materials 新增程序派生字段：`summary`（优先第一条相关已审查判断，否则引用摘录）、`summary_source`、`summary_kind`、`subjects`、`issue_questions`、`judgments`（active finding 的支持/反驳关系、引用与 kind）。
- 材料卡展示受约束摘要、表达主体、相关议题、支持/反驳判断与“定位判断”入口；不再只是标题和引用列表。
- evidence API 的 relations 增加 `issue_question`、`finding_text`、`kind`、`stakeholder`、`active`；前端将 inactive 关系标为“历史判断”；静态导出同步输出材料摘要、主体、议题与判断关系。

### 31.5 验证与边界

- `pytest tests/investigation tests/e2e/test_investigation_web.py -q`：126 passed。
- `pytest -q -m "not live"`：720 passed, 2 deselected。
- 真实 Chromium CDP：F01/F02/F10 既有主路径继续通过；新增检查结构化模块字段（bus 的新值/未知旧值、最多 3 个重点）、议题子项处置、材料摘要/主体/议题/定位判断；输出 `BROWSER_CHECKS_OK`。
- 未实施：F08 信息层次重排、F11 快照版本语义、F12 的澄清兜底/对象纠正交互；真实模型质量、10 案例回放与人工 90%/95% 门槛仍 blocked。本节点不构成 P5 通过。

## 32. 2026-09-12 审查第三轮实现（F08/F11/F12）

> 阶段状态：verified（离线 non-live 回归 726 passed, 2 deselected；定向/Web 测试 132 passed；真实 Chromium CDP 检查既有主路径、F08 窄屏信息层次与下载入口）。真实联网质量门槛仍为 NOT_CLAIMED。

### 32.1 F08：信息层次与窄屏证据成本

- 事件头部改为中文侧重点标签（规则调整/服务变化/计费补救/调查纠正），不再把 facet 英文枚举和内部 snapshot hash 放在用户眉标；同时显示“报告生成”和“查找截止”两个不同时间。
- `body.workbench` 隐藏外层重复品牌栏；`body.wide > main` 只约束外层容器，避免嵌套 main 叠加 padding。
- 当前研判摘要只在“事件总览”渲染；切换到报道对照、议题与核查、引用与原文时直接进入目标内容，不再每个视图先经过同一段长摘要。
- ≤850px 下右侧证据栏默认隐藏，标题行“查看证据核查”按钮按需展开；打开后焦点进入关闭按钮，关闭后焦点回到触发按钮；窄屏点击引用会自动展开证据栏。390px 视口 CDP 验证：摘要不再阻塞其他视图，证据栏默认隐藏且可开关。
- 标题行的“补查新进展/返回调查进度”和“查看证据核查”分组排列，窄屏可换行。

### 32.2 F11：快照内容版本、投影版本和时间语义

- 新增 `PROJECTION_VERSION = "workbench-projection-2"`；`workbench_revision()` 现在绑定 run_id、cutoff、state_revision、status、投影策略版本和 report 内容哈希。同一 report 的 status 变化或投影策略变化都会产生不同 snapshot_id。
- `_publish` 在写 report 后固化 `workbench.json`；`Manager.workbench()` 与 `snapshot()` 优先读取该不可变投影，不再每次 GET 用当前代码重算终态。旧 run 没有该文件时回退重建并标记 `projection_source="rebuilt_from_report"`。
- report 增加 `started_at`、`lookup_cutoff`、`generated_at` 三个独立字段；Manager 发布时写入真实开始时间和生成时间，State.cutoff 保持查找截止语义。Workbench、Markdown、report.js 与静态导出分别展示这三个时间。
- materials 新增 `document_key` / `document_version_count`；workbench 与静态导出按页面归组，同 URL 的多个正文版本在文档内折叠展开；页面计数改为“N 个页面 / M 个正文版本”，与发布日期分布图的“同 URL 多版本按一个文档计”一致，同时保留正文版本下钻。

### 32.3 F12：兜底假设的对象纠正入口与确定性继续

- 新增 `_assumption_fallback_plan()`：当 `plan_hint=proceed_on_assumption` 且 planner 仍返回 clarification 时，程序用 subject 和三个有界问题替换本次 clarification，保证“用户回答不知道/澄清轮数耗尽”后一定继续，不能靠提示词自觉。
- 进度页在 `plan_hint` 为假设继续时显示醒目说明：“系统按某某对象继续调查，可能不同”，并提供“更正调查对象（取消本轮）”入口；已提交材料仍保留在历史记录。
- completed/partial 工作台在 scope_limitation 标记假设时显示“更正调查对象”入口，可进入补查表单描述正确对象。
- 离线测试 `test_deferred_clarification_replaces_a_persistent_planner_question` 覆盖 planner 持续反问时的程序级 fallback。

### 32.4 验证与边界

- `pytest tests/investigation tests/e2e/test_investigation_web.py -q`：132 passed。
- `pytest -q -m "not live"`：726 passed, 2 deselected。
- 真实 Chromium CDP：既有 F01/F02/F10/F03/F06/F09 检查继续输出 `BROWSER_CHECKS_OK`；新增 `F08_CHECKS_OK`（外层头部隐藏、总览摘要存在、其他视图摘要为 0、390px 证据栏默认隐藏并可开关）；下载检查 `DOWNLOAD_CHECKS_OK`。
- 未覆盖：真实大量材料的 320/768/1024 全页视觉走查、live 质量与 10 案例回放、人工 90%/95% 门槛；本节点不构成 P5 通过。

## 33. 固定材料机制回放案例（2026-09-12/13）

> 阶段状态：verified（机制回放 3 项通过；定向/Web 测试 135 passed；non-live 729 passed, 2 deselected）。真实材料与人工质量仍为 blocked。

### 33.1 两套完整回放案例

- `tests/investigation/replay_cases/index.json` 新增 `night-bus-rule` 与 `water-billing-remedy` 两个 case，分别冻结请求、来源标题、facet、模块状态、必需结构化字段、finding 关键词、禁止串入词、复合问题组件、搜索 purpose，以及定向补查后的字段变化。
- `tests/investigation/test_replay_cases.py` 通过真实 Manager 离线运行完整链路：
  - 父版：材料、问题、判断、facet 模块字段、组件、搜索方向与禁止项；
  - 子版：problem 定向补查后目标字段出现预期变化，fixture 不串案。
- 两个 case 明确标记 `quality_claim=mechanism_only`，并断言 `cases/registry.json` 的十个真实材料槽位仍保持 `blocked`。

### 33.2 边界

- synthetic fixture 覆盖的是机制与语义契约，不是 live 搜索质量，也不是人工 90%/95% 断言支持率。
- 下一阶段如需推进 P5，必须先冻结真实公开原文快照并获得人工标注；届时可复用本回放案例结构，替换 materials/expected 并保留同样的隔离断言。

## 34. 补充布局走查（2026-09-13）

> 阶段状态：verified（CDP 视口走查，无横向溢出；未做真实长材料的截图级视觉评审）。

使用 64 字级中文长标题的离线 bus run，在 320 / 390 / 768 / 1024 / 1280px 视口下检查：

- `document.documentElement.scrollWidth` 均不超过视口宽度，无横向溢出。
- ≤850px 时证据栏默认 `display:none`，>850px 时恢复为常驻右栏；窄屏信息层次改造在 320/390/768 均生效。
- 长标题在 320px 最多约 5 行，头部、状态与“补查新进展/查看证据核查”动作保持可见；总览摘要正常换行。
- 其他视图的摘要高度为 0（前一条 F08 CDP 检查在 390px 覆盖），验证“切视图直接进入目标内容”不是仅靠 CSS 隐藏。

边界：这些是机制/布局走查，不是真实长材料、十余篇来源、多时点的完整人工视觉评审；真实材料走查仍属 P5 未完成项。

## 35. 固定材料模型回放 harness（代码层，2026-09-13）

> 阶段状态：harness verified（定向/Web 138 passed；non-live 732 passed, 2 deselected）。真实模型执行 NOT_RUN，未消耗模型预算。

### 35.1 契约

- `build_loop()` 支持显式注入 `search_adapter` / `reader_adapter`；若提供 frozen adapters 且未提供 model，则仍使用配置中的 live model/reviewer，若提供 explicit model/reviewer 则用于测试或脚本回放。原 live/offline 分支行为不变。
- `Manager` 新增可选 `loop_builder` 注入点，默认仍为 `build_loop`；工作台 API 与 create 契约不变。
- 新增 `investigation/replay.py`：
  - `ReplayMaterial` / `ReplayCase` / `load_replay_case()`：支持内联 `content` 或 `snapshot_path` + sha256 校验；快照不存在、hash 不一致、未知 role 都拒绝。
  - `ReplaySearchAdapter`：所有 search purpose 只返回冻结材料，模型仍选择 query/purpose/target_gap。
  - `ReplayReaderAdapter`：只读取冻结 URL 的原文；未知 URL 拒绝，不访问 live 页面。
  - `replay_loop_builder()` 与 `run_replay_case()`：用真实模型/审查器跑正常 loop 和 report 管线，只是把 Brave/Jina 替换成冻结材料；支持 manifest 中的 `clarification_answers`。

### 35.2 测试

- `test_load_replay_case_checks_snapshot_hash`：sha256 错误拒绝。
- `test_replay_adapters_only_serve_frozen_materials`：搜索只返回冻结条目、读取只接受冻结 URL。
- `test_build_loop_can_run_on_frozen_adapters_with_a_scripted_model`：用 scripted model/reviewer 跑完整 AgentLoop，验证 sources/evidence/reflection/review/finish 都从冻结 adapters 落地；程序数字护栏也在该测试中被实际触发并促使模型修正测试文本。

### 35.3 边界

- 这只是固定材料模型回放的能力入口，不是本次已执行的真实模型结果；真正运行需要模型 API 预算与案例材料决定。
- 不调用 Brave/Jina，不改变 web 产品模式，不把 synthetic replay 与真实材料 registry 混同。

## 36. 报告质量 S0/S1 与首个真实材料候选（2026-09-13）

> 阶段状态：无付费实现完成；真实模型对照、人工质量评分和联网发现仍为 `NOT_RUN`。本节执行入口为 `opinionsearch-report-quality-next-stage-guide-2026-09-13.md`。

### 36.1 会污染质量评价的语义问题

- 完成判定：required issue 的 component 为 `unavailable` 时会使报告保持 partial；父问题的 `disputed` 不再掩盖关键子项无法判断。
- 专项字段：不同字符串值默认保留为 `multiple`，Web 与静态 HTML 显示“多种有依据表述”及引用；只有 finding 带明确反驳证据时才投影为 `conflict`。终态存在多种表述时模块保持 `insufficient`，等待核对时间和范围。
- 数字护栏：确定性检查从“数字是否出现”收紧为数字、倍率与单位组合核对，支持万元/元等可比较换算；完整对象、时间和因果仍由独立 reviewer 检查，未声称正则已完成事实核验。
- 回放生命周期：真实模型回放强制每份材料使用 `snapshot_path + sha256`；超时、缺少澄清答案或其他异常会取消 worker 并等待短暂退出，避免调用端直接遗留活动调查。

### 36.2 `billing-dev-v1` 本地材料批次

- 从既有重庆燃气真实运行产物中核对并冻结 8 份公开文本，共 31,138 字符；manifest、URL、标题、获取时间、可获得发布时间、角色和 sha256 位于 `opinion_search_agent/artifacts/report-quality/2026-09-13-s1/`。
- 材料按 T0（2024 年调查与公司清退披露转述）和 T1（2025 年再次调查、企业回应及后续监管安排）登记；预标注包含 5 个必答问题、候选断言、来源依赖和禁止结论。
- `tests/investigation/cases/registry.json` 将其标为 `materials_collected_local_unreviewed`。正文快照因尚未确认对外再分发条件而被 Git 忽略；manifest 和预标注可审计，但在缺少本地 snapshots 的 checkout 不能执行该真实材料回放。
- 预标注明确为 `model_preannotation / UNREVIEWED`，`expected` 保持空对象。该案例不能计入人工 90%/95% 门槛，也不能证明退款到账、整改全面生效或用户总体满意。

### 36.3 预算与待执行边界

- 批次 `2026-09-13-s1` 的外部预算为 0；模型、Brave、Jina 实际调用均为 0。发现本地凭据不视为付费授权。
- 下一批建议上限仍为：当前 Agent 冻结材料 40 次模型请求/1,200 秒，单次摘要基线最多 2 次模型请求，Brave/Jina 为 0；需在批次授权后执行。
- S3 当前 Agent 与单次摘要对照、S4 人工原子断言评分、S5 T0→T1 更新与真实浏览器长材料走查、S6 多案例及联网发现全部未执行。

### 36.4 验证记录

- `pytest tests/investigation -q -p no:cacheprovider`：139 passed。
- `pytest -q -m "not live" -p no:cacheprovider --maxfail=1`：740 passed, 2 deselected。
- Web API e2e：7 passed；沙箱内首次因 localhost bind 被拒绝，允许临时本地端口后通过。
- `node --check` 与 `git diff --check` 通过。

## 37. S3 单次摘要基线与外部调用边界（2026-09-13）

> 阶段状态：baseline harness implemented；真实 Agent/基线模型调用 `BLOCKED`，外部请求数 0。

- 新增 `investigation/baseline.py`，以同一 `ReplayCase` 的完整冻结正文构造一次性摘要输入；材料使用稳定的 m01…mNN 编号和一基行号，预标注、expected 与评分表不会进入模型上下文。
- 输出契约包含按问题处置、原子断言、回应覆盖、执行层级、关键未知和范围限制。answered/disputed 与全部 claim 必须有材料行号；程序拒绝未知材料、越界、空定位和无引用断言，并保存 input、输出、解析后摘录、Markdown、预算与失败信息。
- `test_quality_baseline.py` 使用注入模型验证输入隔离、引用定位和持久化；真实案例输入估算 16,490 tokens，低于 30,000 输入上限，因此没有为基线单独截断材料。
- 建立批次 `artifacts/report-quality/2026-09-13-s3/batch.json`，上限为 Agent 40 次、baseline 2 次，Brave/Jina 为 0。尝试启动 Agent 前，自动审批要求用户明确允许把任务和 8 份冻结公开文本发送至配置的 `opencode.ai` 兼容模型网关；调用被拒绝且没有发出网络请求，批次保持 `BLOCKED`。

## 38. Codex 冻结材料参考报告（2026-09-13）

> 阶段状态：reference completed / `UNREVIEWED`；生产 Agent 与同模型摘要对照仍为 `BLOCKED`。

- 用户要求在项目模型不可请求时直接用当前 Codex 得到结果。Codex 逐份读取 `billing-dev-v1` 的 8 份冻结正文，生成 `artifacts/report-quality/2026-09-13-s3/runs/codex/run-001/{report.json,report.md,self-check.md,validation.json}` 与批次 `comparison.md`。
- 参考报告形成 5 个必答回答、8 条核心断言、5 项回应覆盖和 6 项关键未知。核心判断是：2024 年有一轮问题认定和公司所称清退，2025 年监管再次认定整改不力，后续材料支持持续治理而不足以证明个案全面结案。
- 程序遍历结构化报告全部 citation：46 次引用、26 个唯一位置、覆盖 m01—m08，均未越界且对应非空原文；Markdown 34 次引用也全部可解析。该结果只证明引用结构，不是语义人工通过。
- 自检主动降低 m08 时间表述：正文没有发布时间，仅页面 URL 路径含 `20260616`，因此报告不把 2026 年 6 月写成已由正文确认的发布日期。
- `comparison.md` 明确说明不能比较生产 Agent 与单次摘要。Codex 参考报告可作为人工审核草案和 Web 长内容样例，但不能证明 planner/retrieve/reviewer/completion 的生产链路质量。
- 本节点回归：`tests/investigation` 142 passed；全仓 non-live 743 passed, 2 deselected；`git diff --check`、JavaScript syntax 和 JSON 解析通过。

## 39. 单次调查生产链路诊断（2026-09-14）

> 阶段状态：实现完成并通过离线、API 与实际浏览器验收；真实联网运行和跨 run 统计 `NOT_RUN`。

### 39.1 诊断计算与持久化

- 新增 `investigation/diagnostics.py`，以 `opinion-investigation-diagnostics/1` 输出九段链路：scope / discovery / acquisition / sources / evidence / analysis / review / completion / runtime。
- 诊断是 State、StepRecord 和 budget 的确定性派生视图，不打综合质量分。它区分 critical/warning/info，并保留稳定 signal code、问题说明、建议动作和有限的复现细节。
- 覆盖信号包括：必答 issue/component 未解决、provider 搜索失败、未读候选、Reader 失败、读取后未保存正文、单域名/单来源角色、来源关系未核实、发布时间未知、终态无证据、来源未被当前判断引用、证据摘录过宽、终态无 finding、主体不足、回应覆盖缺失、finding 未审查/未通过、完成状态不一致、决策重试和预算接近上限。
- 观点图启用条件在诊断中保持 false：当前材料没有代表性抽样框且来源关系未全部核实，只能描述材料内主张构成，不能解释为公众观点占比。
- Hook 每个 checkpoint 把诊断写入 `draft.progress` 与 provisional workbench；发布报告将最终 runtime checkpoint、动作分布、重试和预算固化到 report/workbench。取消前无领域 checkpoint 时使用显式 `domain_checkpoint_missing`，不伪造空链路为正常。

### 39.2 Web 与导出

- 新增 `GET /api/investigations/{id}/diagnostics`；终态返回 report 中固化版本，运行中返回最近 checkpoint 的持久化诊断。
- 在线 workbench 导航新增“链路诊断”，显示九个阶段、阻塞/待处理计数、阶段指标和建议动作。诊断视图独占主内容宽度，不保留无关的证据侧栏；`view=diagnostics` 刷新后可恢复。
- 自包含 HTML 导出增加同一诊断章节；旧报告没有诊断时显示“历史版本没有链路诊断数据”，不尝试补造历史遥测。
- 进度页显示当前阻塞/待处理数量，并强调结构信号不代表事实正确率。
- workbench 投影策略升级为 `workbench-projection-3`，因此新增诊断的页面获得新的内容绑定 snapshot id。

### 39.3 已知缺口与验收

- StepRecord 目前没有分步耗时和 token usage；每次生产诊断显式给出 `fine_grained_cost_latency_unavailable`。本轮没有扩张 Runtime 协议去补这些字段。
- 本能力不做跨 run 聚合、长期时序、外部告警、人工质量评分或真实联网发现能力评估；也没有调用模型、Brave 或 Jina。
- 故意退化测试验证能同时识别 unresolved issue、未读候选、来源集中/关系未知、回应缺失、未审查和 completion mismatch；正常 offline 公交链路记录 6 个 committed steps（search/read/reflect/review/finish）、0 次决策重试及 search/read/model 预算。
- `pytest tests/investigation -q -p no:cacheprovider`：144 passed。
- `pytest tests/e2e/test_investigation_web.py -q -p no:cacheprovider`：7 passed（沙箱内回环 bind 被拒后，在允许本地端口的同命令环境通过）。
- `pytest -q -m "not live" -p no:cacheprovider --maxfail=1`：745 passed, 2 deselected。
- 实际浏览器访问临时 8920 服务，完成离线调查 → 打开链路诊断 → 刷新深链接；页面显示 9 个阶段、0 个阻塞、1 个待处理、运行预算与三个解释信号，刷新后仍保持诊断视图。第一次截图发现证据栏压缩诊断卡，随后改为诊断视图隐藏证据栏并复验通过。

## 40. PagePlan 驱动的搜索与 Web 编排（2026-09-14）

> 阶段状态：核心契约、Agent Context、completion、workbench 与静态 HTML 已实现，并通过离线、Web API 与实际浏览器验收；真实模型/Brave/Jina 调用仍为 `NOT_RUN`。

### 40.1 契约与状态边界

- 新增 `investigation/page_plan.py`，格式 `opinion-page-plan/1`、策略 `public-event-framework-1`。它从 `EventProfile + Issue + active Finding.module_fields` 确定性重建，不写入 State/checkpoint，避免产生第二份可漂移事实状态。
- 固定区块为事件总览、争议/主张/回应、材料与来源关系、证据与原文、链路诊断、终态完整报告；确认的 rule/service/billing/investigation facet 在总览后插入独立专项视图。通用事件不显示空专项页。
- 每个专项模块暴露 required/present/missing fields、关联 issue 和状态。只有与 required Issue 关联的模块才生成 search target；展示候选侧重可以保持 optional，不强制无关调查工作。

### 40.2 搜索、完成与呈现连接

- Context Compiler 增加受保护的 `memory.page_plan`。Agent prompt 要求优先使用 required `search_targets`，复制 target_gap、绑定 issue_id 并选择建议 purpose；明确禁止为完成卡片而推断字段。
- Completion 增加 required module gap 检查。问题处置、finding、evidence 和 review 均满足但必需专项字段仍缺时，终态只能是 partial；字段齐备后仍要经过原有判断审查，PagePlan 本身不证明内容正确。
- 链路诊断增加 `required_page_modules_incomplete`，把 PagePlan 未闭合与普通“报告质量不好”区分开，并给出原始 search targets；终态缺失为 critical，运行中为 warning。
- Workbench 投影升级为 `workbench-projection-4` 并固化 `page_plan`。在线导航读取计划，新增 focus 视图；总览回到核心研判、时间线和材料分布。静态 HTML 使用相同章节顺序与专项模块，旧 projection 缺 PagePlan 时保留旧顺序兼容。

### 40.3 当前验证与边界

- 新增 `test_page_plan.py`，覆盖通用 fallback、不同事件页面组合、required target、字段闭合、optional facet、Compiler 同源计划以及 completion 降级。
- 相关专项测试 39 passed；完整 investigation 测试 152 passed；Python/JavaScript 语法与 `git diff --check` 已通过最终检查。
- Web e2e 7 passed；随后仅增强 PagePlan 响应断言，最终复跑所需 localhost 权限因自动审批模型容量不足被拒，故该增强后的单次套件标记为 `NOT_RERUN`。全仓 non-live（包含增强前同一 7 项 e2e）753 passed, 2 deselected；核心字段另由 152 项 investigation 测试和实际浏览器验收覆盖。
- 实际浏览器在临时 8921 服务完成两条离线调查：公交页面导航为“规则与适用影响”，水费页面为“计费、复核与补救”；两页保持相同可信骨架但专项字段不同。`view=focus` 刷新恢复成功，自包含 HTML 也显示相同专项导航和章节。临时服务已停止，用户现有 8918 未改动。
- 上述均为合成材料与机制验收，不代表真实模型搜索报告质量提高；本轮没有调用模型、Brave 或 Jina。

## 41. V1 范围冻结与问题驱动的模块必填字段（2026-09-14）

> 阶段状态：边界文档和首项正确性修复已实现；真实模型、Brave、Jina、真实联网质量验收仍为 `NOT_RUN`。

### 41.1 唯一 V1 边界

- 新增 `docs/opinionsearch-v1-scope-and-acceptance.md`，把 V1 定义为本地单用户、可恢复、证据驱动的公开 Web 事件调查工具；交付目标是可供研究人员继续审核的调查初稿。
- V1 只收敛一条 Web 主链路：事件输入与必要澄清 → 动态问题 → 缺口搜索与正文取证 → 主张/回应/执行分析 → 独立审查 → 明确终态 → Web 核查 → 按需更新和版本比较。
- 新增功能只允许解决调查正确性、真实报告质量证据或 Web 主路径可用性。社交采集、全网声量/情绪/代表性饼图、持续监测、多 Agent、多用户、分布式调度、向量数据库/跨事件 RAG、平台化、任意 HTML、框架迁移和新 CLI 流程均进入 Backlog。
- 收口以三个真实案例、90% 必答问题、95% 重要断言支持或降级、100% 引用定位结构、关键禁止错误、T0/T1 更新、实际浏览器主路径和至少一次最新生产代码真实联网调查为准。通过只说明有限场景可用。

### 41.2 模板不得扩大用户问题

- 原 PagePlan 在一个 facet 关联必答 Issue 后，会把该模块静态字段集整体升级为 required。例如用户只问“新规则是什么”，系统也可能强制搜索适用对象和生效时间，并因模板空位把报告降为 partial。
- `page_plan.py` 现在为每类专项模块保留一个语义锚点字段，并从关联 Issue 的 question、components 和 origin_questions 确定性触发其他字段。模块要求新增 `required_field_basis`，每个搜索 target 同时保存 `basis_issue_ids`，使“为什么需要查这个字段”可以回指用户问题。
- PagePlan 的缺口闭合只读取与该 facet 关联 Issue 的 active module fields，防止另一个无关问题中的同名字段误将必答缺口标为完成。呈现层仍可展示任意显式、带证据的专项字段；只对通用文本摘录按问题相关性过滤。展示信息和完成证明因此保持不同职责。
- `facet_modules()` 接收 PagePlan 生成的每模块 requirements，Workbench 投影升级为 `workbench-projection-5`。在线页面、静态 HTML、Agent Context、diagnostics 和 completion 继续消费同一个可重建计划，没有新增可变事实源。

### 41.3 回归发现与修正

- 首次完整回放暴露两个边界问题：过严的问题过滤隐藏了更新 Issue 中显式的过渡安排；“执行”这个宽泛词又把计费问题误判为要求执行结果。
- 修正后，显式 `module_fields` 可以跨问题展示，但不能跨无关问题闭合 required gap；计费 `execution_status` 只由到账、实际执行、落实或完成退费等明确语义触发。
- 新增覆盖：窄问题只要求锚点字段、用户明确询问时扩展字段、无关 Issue 字段不能闭合缺口、更新字段仍能展示，以及多种有依据表述与明确冲突分开处理。

### 41.4 验证与限制

- 定向回放、PagePlan、事件模块、页面导出和链路诊断：44 passed。
- 完整 investigation：154 passed；全仓 non-live：755 passed, 2 deselected。全仓测试在沙箱内首次运行到 Web e2e 时仅因禁止绑定 `127.0.0.1` 中断；允许临时回环端口后同一套件完整通过。
- Python `compileall` 与 `git diff --check` 通过；Web JavaScript 文件分别通过 `node --check`。
- 本节点没有调用模型、Brave 或 Jina，也没有触碰用户现有 8918 服务。它修复的是范围和完成语义，尚不能证明真实报告质量达到 V1 门槛。

## 42. S3 有余额模型批次启动记录（2026-09-14）

> 阶段状态：配置和批次账本完成；外部执行在进程启动前被自动审批拒绝，实际外部请求为 0。

- 用户明确说明已在 `.env` 配置有余额的模型 API key，并授权继续执行。只读预检确认 `OPINION_MODEL_API_KEY`、`BRAVE_SEARCH_API_KEY`、HTTPS 模型端点和 `deepseek-flash` 模型配置可以由 `LiveConfig` 解析；没有输出任何密钥或额外 header 的值。
- 新建隔离批次 `artifacts/report-quality/2026-09-14-s3-live/batch.json`，冻结案例仍为 `billing-dev-v1`，记录 manifest/preannotation 哈希、Git revision 和 dirty 状态。总账上限为 Agent 40 次模型请求、baseline 2 次；冻结回放的 Brave/Jina 上限均为 0。
- 生产 Agent 计划复用 `run_replay_case()` 与正常 planner/decision/reviewer/report 管线，输出根目录独立于 8918。执行命令在进程启动前被自动审批系统拒绝；拒绝原因是审批模型 at capacity，不是项目模型网关、凭据或 Agent 运行失败。
- 批次已标为 `BLOCKED`，usage 保持 model/search/read 全部 0。根据审批返回要求，不用替代命令绕过；只有在向用户说明后获得新的明确授权，才能重新提交同一外部动作。
- 用户在获知首次拒绝后明确回复“允许重新提交冻结材料模型对照”。第二次提交仍在进程启动前被同一自动审批服务以审批模型 at capacity 拒绝。两次均没有启动项目 Python 进程或发出外部请求；当前阻塞已从“等待用户授权”更新为“执行环境审批服务不可用”，不能归因于项目 API key、余额或模型网关。
- 用户在第二次拒绝披露后再次要求继续执行；第三次提交仍以相同的审批模型 at capacity 原因在进程启动前被拒绝。连续三次阻塞条件一致，批次保持 `BLOCKED`，不再在同一状态下重复提交或尝试间接执行。

## 43. 首次生产模型对照失败与收敛修复（2026-09-14）

> 阶段状态：S3 真实模型批次已执行并判定 `FAIL`；基于失败的代码修复已通过机制测试，真实模型复跑 `NOT_RUN`。

### 43.1 实际运行结果

- 用户开启 unrestricted execution 后，第四次提交真正启动。Agent 组使用 `.env` 的 `deepseek-flash`，冻结 Search/Reader，Brave/Jina 各 0 次；生产 planner、Decision、Processor、Reducer、reviewer、completion 和 report 管线保持不变。
- Run `88944351cb90499d8d2cd18a4b362535` 实际使用 40/40 次模型请求、764.557 秒、11 次 search、8 次 read、3 次 retrieve，读取全部 8 份正文并保存 44 个 Evidence。44/44 的正文哈希、start/end 与 excerpt 机器复核一致。
- 22 个已提交步骤中没有 reflect/review/finish，最终 0 Finding、0 Review、0 Conclusion，6/6 必答问题和 17/17 必答子项仍 open。系统正确发布 partial，但核心回答为空，因此质量闸门为 `FAIL`。
- 单次摘要基线使用同一任务和完整材料，输入约 18,661 tokens。第一次 4,096 输出上限截断，第二次 8,192 上限仍被推理消耗；安全元数据显示 23,847 reasoning characters、8,192 completion tokens、blank final content。两次请求耗尽，未生成可评分报告。
- 批次模型请求共 42 次，达到预设上限；token 总账和费用仍不可用。原始 Agent 报告、workbench、budget、baseline failure、结构校验和 `comparison.md` 均保存在 `artifacts/report-quality/2026-09-14-s3-live/`。

### 43.2 根因与范围内修复

- 核心失败位于“已取得证据 → 形成 Finding”的 Loop 收敛：提示词要求 reflect，但程序允许模型不断换词搜索。冻结 Search 首次返回 8 个候选后，后续 10 次搜索没有增加材料，仍消耗模型决策请求。
- 新增纯领域函数 `required_reflection_reason()`：没有 active Finding 时，若已有至少 4 个正文版本和证据，或连续两次搜索结果为 duplicate 且已有证据，下一动作必须 reflect。产生首个 Finding 后释放闸门，允许继续按缺口取证。
- Compiler 增加可信且不可压缩的 `memory.next_action_constraint`；Validator 使用同一规则拒绝其他动作和空 reflect。该规则属于舆情调查领域，不进入通用 AgentLoop。
- 修复三个配置 wiring：`model_max_output_tokens` 现在传给模型客户端；`build_loop()` 使用 `LiveConfig.max_steps` 和 `max_decision_attempts`，不再硬编码 100/2。

### 43.3 验证与证据边界

- 新增测试覆盖：足量证据触发 reflect、连续 duplicate 触发、空 reflect 被拒绝、产生 Finding 后释放、受保护 Runtime context，以及生产 max steps/decision attempts/output cap 生效。
- 定向测试 18 passed；完整 investigation 160 passed；全仓 non-live 761 passed, 2 deselected。Python `compileall`、Web JavaScript `node --check` 与 `git diff --check` 通过。
- 本次不能比较 Agent 与基线的语义质量，因为两组都未生成可评分内容。失败证明当前版本不可形成有价值报告，并为修复提供了真实生产证据；它不证明修复有效，下一批只能做一次受限复跑。

## 44. 首次收敛修复的真实复跑与状态机细化（2026-09-14）

> 阶段状态：首次修复真实触发但复跑仍 `FAIL`；第二版搜索/读取/研判状态机已完成机制验证，真实模型复跑 `NOT_RUN`。

### 44.1 受限复跑

- 新批次 `2026-09-14-s4-convergence-rerun` 只运行 Agent，初始输出上限 16,384、max steps 20、decision attempts 3、模型请求上限 24，Brave/Jina 为 0。
- 实际使用 9 次模型请求、3 search、1 read、1 retrieve，保存 1 份正文和 6 个证据；6/6 定位通过。配置 wiring 生效，本轮没有 length truncation。
- 连续两次 duplicate 后，受保护 context 和 Validator 确实阻止继续搜索并要求 reflect。模型随后尝试生成带证据 Finding，证明闸门进入真实生产链路。
- 三次恢复未产生合法决定：第一次违反动作约束；第二次 reflect 的 component status 超出 schema；第三次使用 response=`not_found`，但没有完成该分类要求的机构定向、事件回应和后续搜索。Run 以 `Decision recovery was exhausted: missing-response assessment requires successful scoped response searches` 结束，仍为 0 Finding 的 partial。

### 44.2 第二版状态机

- 首次策略在只有 1 份正文时直接要求 reflect，容易诱导模型过早处置全部问题。`required_next_action()` 现在把 duplicate 场景分流：有未读候选时要求 read；候选已读完时要求 reflect；正文及证据达到 4 份时直接要求首次 reflect。
- Runtime constraint 明确：首次 reflect 只提交当前证据支持的 Finding，只为能够处置的问题提交 assessment；其他问题保持省略，not_found 必须满足原有范围搜索前提。
- Validator 继续执行同一约束；产生首个 active Finding 后释放 acquisition gate。没有增加状态字段、第二事实源或通用 Runtime 规则。

### 44.3 验证与边界

- 第二版定向测试 20 passed；完整 investigation 161 passed；全仓 non-live 762 passed, 2 deselected。Python `compileall` 和 `git diff --check` 通过。
- 两次真实 Agent 运行均未形成可评分内容，当前生产质量结论仍为 `FAIL`。根据本轮停止条件不继续追加模型请求；第二版策略的真实效果仍须在下一次明确批次中验证。

## 45. 两天收尾执行计划（2026-09-14，仅文档）

- 用户要求今天明天完成收尾。核对本地时间约 9月14日21:00 后，新增 `docs/opinionsearch-two-day-closeout-plan-2026-09-14.md`：9月15日14:30 功能冻结、18:00 交付。
- 保留 V1 三真实案例与人工90%/95%等门槛；两案例只是开发关口。截止时按 V1_LIMITED_PASS / EXPERIMENTAL_CLOSED_LOOP / ENGINEERING_ONLY 明确交付，不以截止时间降低质量标准。
- 先验证现有第二版收敛修复，再按实际失败做有限契约修正；全量 InvestigationBlueprint/SearchNeed/SearchTask 等对象框架进入 Backlog。最小需求视图复用现有领域状态，避免第二事实源。
- 检查确认：真实材料登记目前仅一个案例有快照且为 UNREVIEWED；ReplaySearchAdapter 对不同查询返回同组材料。因此冻结模型验证与实际 Brave/Jina 发现验收必须分开，T0/T1 更新不能由两个无关联 create 代替。
- 计划列明各阶段时间、依赖、模型调用上限（合计最多146，条件批次不必执行）、独立材料采集预算、人工核查分母、浏览器步骤及失败停止规则。该预算仅为后续执行上限，本次未调用模型或搜索 Provider。
- 同步 canonical design、V1 边界与历史执行计划的当前入口。未修改生产代码、未重跑测试、未执行浏览器验收；计划不是验收结果。

## 46. 两天收尾真实执行：阶段性判断、预算收敛与第二案例（2026-09-15）

> 阶段状态：生产链路从 Evidence 推进到 reviewed Finding，但三个真实模型批次均未形成完整结论；当前质量等级仍低于 V1_LIMITED_PASS。人工评分、保留案例真实联网和最终浏览器验收尚未完成。

### 46.1 批次与真实结果

- 建立隔离批次 `artifacts/report-quality/2026-09-15-closeout/`，记录代码指纹、模型/外部请求硬上限、阶段状态与每次运行产物。C0 冻结 8 份重庆燃气材料哈希；未接触用户已有 8918 服务。
- C1（run `5acbf6c65f754cf498a788fdd1a13c1d`）使用 18 次模型请求、4 份正文、16 条 Evidence，因 component status、未知 ID 与最后一次 Provider error 未提交 Finding，判定 FAIL。
- C3（run `0bbef5541a894609bf75d3b77251af23`）使用 24 次模型请求、7 份正文、37 条 Evidence，提交并审查 8 条 Finding；1 条 supported、7 条 partial。模型预算在 finish 前耗尽，6 个问题与 17 个子项仍 open，0 Conclusion。该轮只证明 Evidence→Finding→Review 阻塞已修复，状态为 PASS_WITH_LIMITATIONS，不计 V1 质量通过。
- C5 新增真实规则调整开发案例 `powerbank-flight-rules-dev-v1`：6 份国内航班充电宝新规、地区执行、机场服务和后续监管公开正文带 sha256 快照，T0 为前 4 份、T1 为后 2 份；案例问题、禁止结论和来源依赖均为 `model_preannotation/UNREVIEWED`。
- C5（run `60fda700b0464b97966decc0a84a97a4`）实际读取 5 份正文、保存 25 条 Evidence，形成 17 条 active Finding；6 条保持 supported review 并进入阶段性判断，11 条在最终 Reflect 后失去当前 review。6 个必答问题只处置 3 个，0 Conclusion，判定 FAIL_REPORT_CLOSURE。
- C6 T0（run `e42fc0b8d08048678ef92b2801af7b46`）只开放两份 2024 年材料，使用 16 次模型请求，得到 2 份正文与 15 条 Evidence，但 0 Finding。模型在两次 Retrieve 后连续提交 3 次空结论 Finish，且发生两次 Provider server error。T1 因父版本无判断而停止，判定 FAIL_T0_NO_FINDINGS；不能把 parent_id 机制测试冒充判断变化验收。

### 46.2 真实失败驱动的通用修复

- `ComponentAssessment.status` 允许 `open`；第一次强制 Reflect 必须创建 1–4 条原子 Finding，合法 issue/evidence ID 在受保护 Runtime section 中完整列出。部分覆盖时允许父问题和未覆盖子项保持 open，禁止用未知 ID 或不满足搜索条件的 not_found 补齐。
- `workbench-projection-6` 与 report 增加阶段性判断语义：partial 且无 Conclusion 时，只把拥有当前 supported review 的 active Finding 投影为 `interim_findings`，页面明确显示“已核查阶段性判断（调查未完成）”。它不升级为核心结论，也不隐藏未完成问题。
- 预算收敛同时由 Context 和动作边界执行。模型调用达到上限三分之二后：无 Finding 只能 Reflect 并生成有证据判断；存在未审查 Finding 只能 Review；所有当前 Finding 已审查后只能 Finish。这样阻止继续搜索耗尽预算，也阻止审查后再次改写使 review 失效。Completion 仍决定 complete/partial，门禁本身不把未知变成答案。
- Planner 提示明确 facet 只能使用 canonical identifier；对旧/不稳定模型翻译出的简短中文 facet 标签，程序仅按产品词表映射到现有白名单，任意新类别仍丢弃。Read 指令同时明确来源角色按实际发布/转述关系判断，政府域名转载新闻不能只凭域名标为 original。
- 新增 `run_replay_update_case()`：在同一 Manager root 对已有 parent 创建关联更新，复用正常 update intent、父状态、锁、checkpoint 和原子发布，仅替换为 hash 校验冻结 Search/Reader。超时与异常仍取消 worker；两次无关联 create 不再是可接受的更新验收方式。

### 46.3 证据边界与冻结决定

- A C3 与 B C5 的 37/37、25/25 Evidence 定位均从归档正文重新验证；T0 的 15/15 也通过。引用结构通过不代表断言正确或样本完整。
- B 的公开材料以机构来源为主，因此页面只能分析规则、执行、回应与缺口；`stance_distribution_eligible=false`，不得绘制公众观点比例或声称总体满意。
- 新的程序收敛门禁、facet 恢复和来源角色提示只完成确定性测试。遵守批次同类失败停止规则，没有再次付费复跑 B 或 T0，因此真实修复效果仍为 NOT_RUN。
- 截至本节点，批次已使用 82 次模型请求、10 次材料搜索、6 次正文读取。C7 保留案例、C9 浏览器和 C10 人工签字仍决定最终交付等级。

## 新 Harness / Report Contract 纵切（实现记录）

> **历史条目（2026-09-24 按代码校正）**：从本节起至文末「报告级综合结论与 Review 硬化」
> 各节（含「Live Harness 首次真实运行」「Planner / ResearchAgent 边界调整」
> 「动态 ResearchAgent 与 Reviewer 硬化」「表现层升级」「观感 P0 优化」「P1 表现层增强」
> 「P2 内容压缩与可视化质量」「P2 Live 验证成功」「P3 部分支持与总体状态展示」
> 「全中文化与证据原文渲染修复」）记录的，都是 2026-09-16 前后那次**多角色流水线纵切**：
> `opinion_search/harness/`（Legal Action Kernel / HarnessEngine / ResourceLedger /
> Planner → ResearchAgent → EvidencePacket → Analyst → Reviewer / Synthesizer /
> ContentBuilder）以及 `LlmController` / `LlmResearchAgent` / `LlmAnalyst` / `LlmReviewer`。
>
> 该纵切已于 2026-09-21 评估后整体归档至 `opinion_search_agent/archive/harness-pipeline/`，
> **不属于当前实现**。当前生产路径是 `runtime/loop.py` 一套 AgentLoop，见 §0 与 canonical design。
>
> 例外：`report_contract/` 与 `presentation_skill/` 两个模块保留在当前代码库并有单测覆盖，
> 但当前 CLI 与 Web 生产路径均未引用它们（`investigation/` 使用自己的 workbench / export /
> report）。归档决策见 §0 的 D1 条目与归档 README。

本轮新增一个新的低耦合纵切，不替换旧单 Agent 主路径。

### 已实现

```text
opinion_search_agent/src/opinion_search/report_contract/
├── contracts.py
├── registry.py
├── projector.py
├── renderer.py
└── validator.py

opinion_search_agent/src/opinion_search/harness/
├── actions.py
├── checkpoint.py
├── content_builder.py
├── coverage.py
├── engine.py
├── ledger.py
├── live_search.py
├── llm_roles.py
├── mock.py
├── models.py
├── planner.py
├── ports.py
├── role_schemas.py
├── search.py
└── state.py

opinion_search_agent/src/opinion_search/presentation_skill/
├── __init__.py
└── llm_planner.py

opinion_search_agent/scripts/
├── report_contract_preview.py
├── harness_preview.py
└── run_harness.py
```

### 已跑通

```text
ContentDocument
→ PresentationPlan
→ Validator
→ Deterministic Renderer
→ HTML
```

以及：

```text
Planner
→ Scheduler
→ ResearchAgent
→ EvidencePacket
→ Analyst
→ FindingDraft
→ Reviewer
→ ReviewRecord
→ HarnessState
→ CoverageMatrix
→ GapAudit
→ ContentDocument
```

### 已支持

- Legal Action Kernel
- HarnessState
- HarnessEngine
- ResourceLedger
- JsonHarnessCheckpoint / resume
- FakeSearchProvider
- BraveJinaSearchProvider
- LlmAnalyst / LlmReviewer / LlmController
- GenericPlanner
- LlmPresentationPlanner
- ModuleRegistry 共 39 个模块
- 空值状态
- 模块到视觉编码选择
- 自包含 HTML 渲染

### 验证

```text
targeted tests: 21 passed
non-e2e suite: 748 passed, 1 failed
```

失败项：

```text
tests/investigation/test_budget_recovery.py::test_budget_limits_come_from_env_without_losing_defaults
```

该失败为既有环境变量预算测试问题，不是本轮新增代码导致。

e2e 测试仍受当前 base_url fixture / httpx 环境问题影响，不纳入本轮验证结论。

### 已知限制

- live 模式尚未用真实 API key 运行。
- LLM Controller 是可选层，默认仍使用确定性 Controller。
- BraveJinaSearchProvider 使用同步桥接调用异步适配器，后续可迁移为全异步。
- Live 搜索质量、LLM 输出质量和真实报告质量尚未评估。
- 新路径尚未替换旧单 Agent 主路径。

## Live Harness 首次真实运行（2026-09-16）

使用 `scripts/run_live_fixed.py` 加载 `.env`，修复当前环境 `NO_PROXY` 的 IPv6 解析问题后，真实调用 Brave / Jina / LLM，完成一次 live Harness 运行。

事件：

```text
重庆轨道交通票价机制调整
```

运行结果：

```text
7 个 ResearchTask
41 条 Finding
41 条 Review
Review verdict 全部为 supported
5 个 Content Section
event-summary / event-timeline / issue-map / position-matrix /
response-coverage / source-structure / evidence-index 均为 ready
```

使用统计：

```text
plan = 1
dispatch_research = 7
analyze = 7
review = 7
finish = 1
```

产物：

```text
artifacts/harness-live.html
artifacts/harness-live.plan.json
artifacts/harness-live.trace.json
artifacts/harness-live.content.json
artifacts/live-run5.log
```

质量观察：

- 真实官方文件、文号、时间线和票价结构可以被检索、抽取和审查。
- Reviewer 在第一轮运行中成功识别过两条 partial Finding。
- 当前 GenericPlanner 仍是通用问题模板，查询质量依赖事件名和任务目标。
- ContentDocument builder 已修复一个 Evidence 对应多条 Finding 时只保留一条的问题。
- 当前运行耗时数分钟，仍有查询去重、模块聚合和结果压缩空间。

## Planner / ResearchAgent 边界调整

为避免 Planner 把注意力放在填充查询计划 schema，新 Harness 增加了最小规划契约：

```text
ResearchBrief
IssueIntent
PlanningOutput
```

实现行为：

- Planner 输出自由文本 `ResearchBrief.content`
- Planner 输出最小结构 `IssueIntent[]`
- Planner 不再输出 query plan
- `ResearchTask` 仍只包含 objective、source_goals、report_module、data_shape
- `HarnessEngine` 把 `ResearchBrief` 传给 ResearchAgent
- ResearchAgent 根据任务和 brief 动态决定实际 query
- 实际 query 由 ResearchAgent 执行时记录

验证：

```text
tests/unit/harness tests/unit/report_contract tests/unit/presentation_skill
21 passed
```

fake CLI 仍可运行：

```text
scripts/run_harness.py --mode fake
```

## 动态 ResearchAgent 与 Reviewer 硬化

新增：

```text
LlmResearchAgent
ResearchQueryOutput
SearchTraceEntry
normalize_query
Reviewer batching / fallback
ContentDocument provisional module handling
```

### 实现行为

- Planner 仍只输出 ResearchBrief + IssueIntent，不输出 query plan。
- ResearchAgent 在运行时调用 LLM 生成 query。
- Query 会做规范化去重。
- 实际执行 query 记录到 EvidencePacket.search_trace。
- LlmReviewer 按 batch_size 分批审查。
- Reviewer 对单个 Finding 失败时降级，不会中断整个 run。
- 未通过审查的 Finding 不再让整个模块为空。
- 如果模块部分 Finding 通过审查，模块标记为 provisional，并只展示 supported 子集。
- HarnessTrace 现在记录 ResearchBrief。

### 真实运行结果

事件：

```text
重庆轨道交通票价机制调整
```

动态 query 运行结果：

```text
search_trace_entries = 28
findings = 56
reviews = 56
supported = 50
partial = 6
```

使用真实 trace 重新投影后：

```text
event-summary      provisional
event-timeline     provisional
issue-map          ready
position-matrix    ready
response-coverage  provisional
source-structure   provisional
evidence-index     ready
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## 页面标题重复修复

问题：

```text
ContentBuilder 在 Finding 没有 module_payload 时，
会把每个 item.title 填成模块标题。
结果：
event-summary 下 9 个标题全部是“事件概况”
issue-map 下 8 个标题全部是“议题与争议”
position-matrix 下 8 个标题全部是“立场矩阵”
```

修复：

- cards / timeline fallback 改为从 Finding 文本生成独立短标题
- source-structure / categorical fallback 改为使用来源标题和 label/value
- comparison / matrix fallback 改为使用“判断/来源”语义列
- 保留 Finding text 作为正文

验证：

```text
25 passed
```

重新投影真实 trace 后：

```text
event-summary 标题不再重复
issue-map / position-matrix 使用判断列
source-structure 使用来源分布列
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## 事件脉络流程化修复

问题反馈：

```text
事件总览里的事件概况只是几组事实堆叠，没有顺序，不能快速看出事件发展脉络。
```

修复：

- 将 event-timeline 提升到“事件总览”中的第一个模块
- event-summary 保留为后续补充要点
- timeline renderer 支持箭头连接符
- timeline item 会按时间排序
- 无法解析时间的 item 保持稳定顺序并排在最后
- timeline 保留标题、正文、来源元信息

真实 trace 重新投影后：

```text
事件总览
├── event-timeline  事件时间线（带箭头，按时间排序）
└── event-summary   事件概况（补充事实）
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## 表现层升级：多视图、渐进披露、前端美化

针对“文字太多、内容太少、渲染单一”的反馈，完成：

### Content / Presentation 模型

- ContentSection / PlannedSection 支持 `view_id` 和 `view_title`
- ContentModule 支持 `view_id`
- item payload 支持 `summary` / `detail`
- fallback payload 自动生成摘要和详情

### ContentBuilder

- 从 Finding 文本生成 `summary`
- 保留完整文本为 `detail`
- 按语义 section 生成视图：
  - 总览
  - 议题与观点
  - 回应与处置
  - 来源与证据

### Renderer

- 新增 view tabs 切换
- cards / timeline 支持“展开详情”
- 时间线继续使用箭头和排序
- 新增现代化前端样式：
  - 背景渐变
  - 圆角卡片
  - hover 反馈
  - 状态徽标
  - 响应式布局

### Presentation Skill

新增：

```text
references/frontend-patterns.md
```

内容包括：

- 渐进披露
- 多视图切换
- 视觉层次
- cards / timeline / chart 规范
- 状态展示规范
- 反模式禁止

真实验证：

```text
25 passed
```

重新投影的真实页面：

```text
artifacts/harness-live-fixed.html
```

页面包含：

```text
视图：总览 / 议题与观点 / 回应与处置 / 来源与证据
展开详情：7 处
```

## 观感 P0 优化

目标：

```text
首屏抓住重点
模块先给结论
详细内容点击展开
视图可分享
```

实现：

- ContentBuilder 自动生成 `current-judgments` 模块，取 top 5 supported findings
- 总览视图顺序变为：
  ```text
  current-judgments
  event-timeline
  event-summary
  ```
- 每个模块显示模块级摘要
- cards / timeline 支持“展开详情”
- Renderer 增加“展开全部 / 收起全部”
- Renderer 增加 URL hash 视图切换
- 视图可直接分享，例如 `#issues`、`#response`
- 新增现代化前端样式

真实 trace 重新投影结果：

```text
overview modules: current-judgments / event-timeline / event-summary
module summaries: 8
expandable details: 9
expand/collapse all: enabled
url hash switching: enabled
```

验证：

```text
25 passed
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## P1 表现层增强

### Analyst 模块字段

EvidencePacket 新增：

```text
report_module
report_title
data_shape
```

ResearchAgent 会把这些字段带入 packet。  
LlmAnalyst 现在收到模块上下文，并被要求输出模块可渲染的 `module_payload`：

```text
event-summary      title / summary / detail
event-timeline     time / title / text
issue-map          议题 / 状态 / 说明
position-matrix    主体 / 立场 / 目标 / 依据
response-coverage  问题 / 回应 / 未覆盖
source-structure   label / value / display
```

### Renderer 增强

- source-structure 支持分布聚合
- 2-5 个类别使用 donut 图
- 类别多时使用 bar 图
- position-matrix 优先按“主体/立场/目标/依据”列渲染
- 保持 timeline 箭头和排序
- 保持多视图、摘要、展开详情、hash 视图

### 模型兼容性

角色 schema 从 `extra="forbid"` 改为 `extra="ignore"`，容忍模型网关偶尔返回的：

```json
{"type": "json_object", ...}
```

### 验证

```text
25 passed
```

已有真实 trace 重新投影后：

```text
donut: 2
matrix tables: 4
expandable details: 9
view tabs: enabled
```

## P2 内容压缩与可视化质量

### Finding 相似度去重

新增基于字符 bigram Jaccard 的近似去重：

- 先按规范化文本去重
- 再按相似度阈值 0.82 去重
- 减少语义重复的 Finding 展示

### Item 重要度排序

- item payload 增加 `_importance`
- cards 按 `_importance` 降序展示
- table renderer 跳过以下划线开头的内部字段

### source-structure 来源角色聚合

问题：

```text
BraveJinaSearchProvider 之前用 task.source_goals[0] 作为来源角色，
导致所有 source-structure item 都是“原始来源”。
```

修复：

- 新增 `infer_source_role(title, url)`
- gov.cn / 公告 / 通知 -> original
- 搜狐 / 新浪 / 腾讯 / 百家号 -> reporting
- 其他公开网页 -> unknown
- source-structure 现在按真实来源角色聚合和画图

### response-coverage 专门渲染

- 新增 coverage card
- 显示问题、回应状态、未覆盖项、理由
- 状态 badge：
  ```text
  direct
  partial
  non_substantive
  not_found
  unknown
  ```

### 验证

```text
25 passed
```

已有真实 trace 重新投影后：

```text
donut: 1
coverage-grid: 1
coverage-badge: 1
expandable details: 9
```

## P2 Live 验证成功

使用 detached runner 重新跑通 live：

```text
scripts/run_detached.py --target scripts/run_live_fixed.py --log artifacts/live-run11.log
```

真实运行结果：

```text
7 dispatch_research
7 analyze
7 review
41 Finding
38 supported
3 partial
```

关键改进生效：

### position-matrix

Analyst 输出真实字段：

```text
主体 / 立场 / 目标 / 依据
```

### response-coverage

Analyst 输出真实字段：

```text
问题 / 回应 / 未覆盖
```

Renderer 渲染为 coverage cards 和状态 badge：

```text
direct
partial
```

### source-structure

Analyst 输出类别分布：

```text
政府官方文件 = 3
媒体报道 = 3
信息平台 = 1
```

Renderer 自动渲染 donut。

### 页面统计

```text
donut: 2
coverage-grid: 2
coverage-badge: 8
expandable details: 15
```

产物：

```text
artifacts/harness-live.html
artifacts/harness-live.plan.json
artifacts/harness-live.trace.json
artifacts/harness-live.content.json
artifacts/live-run11.log
```

### 稳定后台运行

新增：

```text
scripts/run_detached.py
```

使用 Python 双 fork + os.setsid 运行长任务，避免 shell 超时重置杀掉 live 运行。

## P3 部分支持与总体状态展示

### 部分支持 Finding

- provisional 模块现在同时展示 supported 和 partial Finding
- partial Finding 增加：
  ```text
  _review_status = partial
  _review_reason = 审查看法
  ```
- Renderer 显示：
  ```text
  部分支持
  审查看法
  ```
- 不再把 partial Finding 直接从页面隐藏。

### 总体状态条

页面 header 新增模块状态统计：

```text
完整
阶段性
证据不足
不可用
未发现
待调查
已省略
```

用户可以在首屏看到报告完整度，而不是只看到“partial”。

### 核心判断排序

current-judgments 现在按：

```text
Evidence 数量
```

降序取 Top 5。

### 最新投影统计

```text
review-badge: 2
summary-pill: 3
coverage-badge: 8
donut: 2
expandable details: 16
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## 全中文化与证据原文渲染修复

### 问题

1. 前端仍显示内部字段：
   ```text
   module-type = event-summary / position-matrix
   visual=cards · data_shape=cards; preferred visual is allowed
   ```

2. “证据与原文”展示：
   ```text
   evidence_id
   source_version_id
   locator
   原始 Markdown / 图片链接
   ```

### 修复

- 移除前端 `module-type`
- 移除前端 `visual-note`
- 页面状态改为中文：
  ```text
  partial -> 部分完成
  completed -> 已完成
  cancelled -> 已取消
  ```
- 页脚改为中文：
  ```text
  内容契约 → 呈现方案 → 确定性渲染
  ```

### 证据与原文重做

现在证据卡片只展示用户需要的信息：

```text
来源标题
原文摘要
展开原文
```

不再显示：

```text
evidence_id
source_version_id
locator
```

并清理 Markdown：

- 图片语法
- 链接语法
- 标题星号
- 加粗/下划线标记
- 多余空白

### 验证

```text
25 passed
```

重新投影后：

```text
module-type: 0
visual-note: 0
evidence-card: 5
evidence-id: 0
```

产物：

```text
artifacts/harness-live-fixed.html
artifacts/harness-live-fixed.plan.json
artifacts/harness-live-fixed.content.json
```

## 报告级综合结论与 Review 硬化

### 新增 Synthesizer

新增：

```text
SynthesisJudgment
SynthesisOutput
DeterministicReportSynthesizer
LlmReportSynthesizer
```

Synthesizer 输出：

```text
headline
summary
key_judgments
uncertainties
watch_points
```

HarnessEngine 现在会在 ContentDocument 生成前调用 Synthesizer。

### ContentDocument

新增模块：

```text
executive-summary
```

总览视图顺序变为：

```text
executive-summary
current-judgments
event-timeline
event-summary
```

`executive-summary` 展示：

```text
事件总述
关键不确定性
后续关注
```

`current-judgments` 优先使用 synthesis.key_judgments。

### Reviewer 程序硬化

新增：

```text
review_checks.py
```

规则：

- Finding 必须有已保存 Evidence
- Finding 中的数字、日期、文号必须在支持摘录中出现
- 否则 supported 自动降级为 partial

### Finding 压缩

- 每个模块按证据量排序
- cards / table / matrix 默认保留 Top 6
- timeline 默认保留 Top 8
- 相似 Finding 去重并合并 Evidence

### 验证

```text
27 passed
```

现有真实 trace 重新投影后：

```text
executive-summary 已生成
current-judgments 使用 synthesis key_judgments
模块顺序：
executive-summary / current-judgments / event-timeline / event-summary /
issue-map / position-matrix / response-coverage / source-structure / evidence-index
```

---

## 2026-09-28 代码规范化与工程基础设施梳理 (Interview Readiness)

### 实现范围

1. **代码洁净度治理**：
   - 修复 `domain/investigation/engine.py`（移除未使用的 `date` 与 `Observation` 导入）。
   - 修复 `investigation/context.py`（移除未使用的 `ContextBudget` 导入）。
   - 修复 `investigation/export.py`（移除未使用的 `url` 与 `link` 变量声明）。
   - 修复 `investigation/presentation.py`（移除未使用的 `FACET_MODULE_TYPES` 导入）。
   - 修复 `investigation/service.py`（移除未使用的 `LiveConfig` 与 `PlanProposal` 导入）。
   - 修复 `investigation/workbench.py`（移除未使用的 `report_json` 序列化变量）。
   - 修复 `web/__init__.py` 与 `web/__main__.py` 的文件末尾换行符。
   - `ruff check` 达到 0 errors / 0 warnings。

2. **核心 Runtime 类型硬化 (PEP 544 Conformance)**：
   - `runtime/completion.py`：为 `CompletionPolicy` 与 `CompletionEvaluator` 中的参数泛型添加 `contravariant=True`。
   - `runtime/cancellation.py`：将 `CancellationSignal.wait_cancelled` 返回类型明确声明为 `Coroutine[Any, Any, None]`。
   - `runtime/loop.py`：为 `_await_operation` 中的 `wait_task` 补全 `asyncio.Task[None]` 类型注解。
   - `runtime` 模块通过 `mypy --ignore-missing-imports` 静态检查，0 issues。

3. **工程工具链与标准化入口**：
   - `pyproject.toml`：添加 `[tool.ruff]`（line-length 120, isort 配置）与 `[tool.mypy]` 严格模式配置。
   - 根目录 `Makefile`：提供标准化的 `install`, `lint`, `format`, `typecheck`, `test-fast`, `test`, `demo`, `web`, `clean` 目标。
   - `.github/workflows/ci.yml`：建立标准 GitHub Actions CI 流水线（自动跑 Ruff, Mypy, Pytest）。
   - `.gitignore`：屏蔽 `.workbuddy-ai/`, `**/.pytest_tmp/`, `**/.pytest_run/`, `**/.pytest_iso2/`, `**/.ruff_cache/`, `artifacts/*.log`。
   - 根目录 `README.md`：建立工业级项目门面（架构分层图、技术栈、核心不变量、Quickstart）。

### 验证证据

- `make lint`：0 errors (All checks passed)
- `make typecheck`：`Success: no issues found in 9 source files`
- `pytest tests/unit -q`：441 passed in 31.97s
- `pytest tests/contract tests/integration tests/security -q`：128 passed in 8.74s
- `make demo`：离线确定性 Demo 跑通，正常输出 4 个 gap 闭环的 OpinionSearch Brief 并持久化。


---

## 2026-10-13 边界收敛与搜索约束透传

### 实现范围

1. **边界决策**：项目边界收敛为第①层 Runtime 与第②层 Tool/Context 的深度实现；`investigation/`、`report_contract/`、`web/`、`app/` 冻结新功能，只做缺陷修复。
2. **旧 opinion 路径的搜索约束透传**：`OpinionSearchActionResolver` 从持久化的 `TaskFrame` 投影 `freshness`（有界时间窗口）与 `search_lang`（由 TaskFrame 语言映射）。`country` 与 `offset` 不下发。域名约束仍在候选入库时后过滤。
3. **时间范围解析修复**：`parse_temporal_scope` 接受 `YYYY-MM-DD/YYYY-MM-DD`。该格式是 README 与 CLI 示例承诺的写法，修复前会被静默降级为 UNSPECIFIED，即用户的显式时间约束被丢弃。
4. **执行 profile 升级**：旧 opinion 路径的 action payload 变化，因此 offline `v2→v3`、offline fallback `v1→v2`、live `v5→v6`。旧 checkpoint 按 D6 只读保留，恢复时报 `execution profile does not match`。
5. **测试卫生**：`tests/investigation/test_update_versions.py` 的子进程测试补齐管道关闭，消除 `-W error` 下的 ResourceWarning。

### 核心流程与不变量

- Brave 请求参数只来自 Tool 层的 `SearchArguments` 校验结果，resolver 不拼接 provider 语义。
- `freshness` 只在 `TemporalScope.is_bounded` 为真时出现。无时间约束的 run 不产生该字段。
- `TaskFrame` 在 run 创建时用 `anchor_date` 锚定一次，resume 不重新推导，因此同一 run 的 freshness 在恢复后保持一致。

### 设计取舍

- 旧路径保留"两字段稳定 payload"的注释语义被放弃，取而代之的是 profile 升级。代价是旧 run 不能续跑；收益是搜索约束可审计地进入 action identity 与缓存键。
- 域名约束没有前置到 Brave 请求。原因是旧路径的 `site:` 前置会改变查询语义并占用查询长度，当前由后过滤保证正确性；前置化留作后续实验。

### 验证证据

```text
tests/unit + contract + integration + security + e2e: 615 passed, 2 skipped（需真实 provider 的 live 门控）
tests/investigation (-W error):                      179 passed
离线 demo（--time-range 2026-08-01/2026-08-20）:     退出码 0；checkpoint 中出现 freshness=2026-08-01to2026-08-20、search_lang=zh-hans
旧 offline checkpoint 执行 resume:                   报 execution profile does not match，未重放
```

真实 Brave 的 `freshness=YYYY-MM-DDtoYYYY-MM-DD` 参数已在后续 live 核验中确认：请求返回 200，8 条结果的 `page_age` 全部落在 2026-08-01 至 2026-08-20 之间（查询 "公交 夜班车 调整"，`search_lang=zh-hans`）。该核验为单次手动调用，未纳入自动测试。

### 已知限制

- 域名约束仍为后过滤，搜索结果数量仍会因域名过滤而减少。
- `country` 未使用。
- 时间解析只接受 ISO 区间与少数相对表达；无法识别的显式 `time_range` 当前被静默降级为 UNSPECIFIED，尚未决定是否改为请求校验失败。

### excerpt 选择离线基准（未合入代码）

- 新增 `opinion_search_agent/scripts/excerpt_recall_bench.py`：离线重放 28 个冻结正文（`artifacts/` 中的 live 读取正文与对抗材料），按事件 must-hit 关键词标注计算金标对（页面含事实且关键词成立）。焦点取标注项的 fact 描述，近似真实 gap 问题。
- 金标对 33 个，每个代表 3%；关键词标注存在循环风险，结论只能用于相对比较。
- 基线（HEAD 的 `_select_evidence_excerpts`）：25/33 = 76%（fact 焦点）；16/33 = 48%（泛化事件焦点）。
- 试验 BM25（块内 IDF 与长度归一化）：两种焦点下均为 25/33 与 16/33，无增益。已撤回，不合入代码。
- 试验 `max_blocks` 3→5：26/33（+1 对）；未采纳，证据数量增加的成本未经评估。

### 对下一节点的影响

- excerpt 选择的语义（召回瓶颈）仍待用户决定，本节点未改动。
- 评测集与离线评测脚本尚未建设；按边界决策，评测只能是 `scripts/` 下的离线脚本，不进入 Evaluation 平台。

---

## 2026-10-15 证据优先解耦、自主视觉档案编排与收敛机制深化（M1–M6）

### 实现范围

1. **M1 展示与取证解耦（Evidence-First Module Rendering）**：
   - `investigation/presentation.py` 与 `investigation/workbench.py` 移除“缺少 4 个必填 `module_fields` 即整块折叠隐藏已核实 `Finding`”的展示门控，保留所有已核实原子判断及结构化条目分组。
   - `investigation/context.py` 的 `INSTRUCTIONS` 将 `module_fields` 降级为可选补充元数据，显式优先要求模型将未处置 `Evidence`、`undisposed_counter_evidence` 与 `numeric_conflicts` 转化为原子 `Finding`。
2. **M2 & M3 自主视觉档案编排与图谱化渲染（Visual-First Autonomous Dossier）**：
   - 激活 `report_contract/{contracts.py,registry.py,projector.py,renderer.py}` 与 `presentation_skill/llm_planner.py`：新增 `VisualEncoding.DEBATE_VERSUS` 与 `VisualEncoding.RESPONSE_SCORECARD`，支持在 `ContentDocument → PresentationPlan → render_html` 管线中生成自包含高对比度视觉档案 `dossier.html` 与 `presentation_plan.json`。
   - 图形化与结构化视觉组件：
     - **三层交互式 SVG 节点拓扑关系图（`_render_relation_graph`）**：映射 `参与主体/信源节点 → 核心争议子议题 → 事件总枢纽`，支持点击/悬停高亮关联路径与底部节点穿透详情面板。
     - **正反阵营交锋天平竞技场（`_render_debate_versus`）**：顶部拔河权重条（Tug-of-War Bar）动态展示正反证据引证占比，左右并列核心主张、引证句与数值要点。
     - **三栏立场光谱泳道看板（`_render_matrix`）**：按 `质疑/批评阵营`、`中立/事实观察`、`支持/回应辩护` 三栏分流展示主体表态。
     - **横向演进里程碑流向链（`_render_timeline`）** 与 **卡片核心要点自动拆解（`_extract_structured_summary`）**，消除长段落文字墙。
   - `LlmPresentationPlanner` 支持动态模块提案（`DynamicModuleProposal`）与 `unbacked_specifics` 确定性数值锚定护栏；`Manager._publish_dossier_artifacts` 在 `live` 模式且预算充足时自动调用 `LlmPresentationPlanner`，异常或预算耗尽时确定性回退至 `build_presentation_plan`。
   - `web/server.py` 与 `web/assets/{api.js,workbench.js}` 暴露 `/api/investigations/{id}/dossier` 与 `/api/investigations/{id}/presentation-plan` 并在工作台顶栏提供“打开视觉档案 / 下载视觉档案”入口。
3. **M4 收敛阶段死锁修复（Consolidation & Response Coverage）**：
   - `domain/investigation/engine.py` 新增 `_issue_has_read_errors`，当某议题检索方向受页面读取错误阻塞时允许诚实以 `not_found`/`unavailable` 收口，避免无限重搜。
   - `investigation/service.py` 的 `ConsolidationValidator` 与 `investigation/context.py` 的 `Compiler.compile` 在模型预算进入最后 1/3 收敛储备期且仍存在未关停 `required` 议题或 `partial` 审查结论时，放行有界 `reflect` 与 `retrieve`。
4. **M5 页面噪音过滤、增量 FTS5 索引与引语/日期重排**：
   - `investigation/storage.py` 新增 `_is_noise_chunk` 过滤站点导航/页脚/免责声明噪音，移除每次 `retrieve()` 全表删除重建 FTS5 的开销（改为按 `version_id` 增量入库），并在 `Corpus.retrieve` 中叠加 `cjk_2gram_overlap`、直接引语（`“…”`/`「…」`）、年份日期与精确数值密度加权。
5. **M6 证据质量与争议信号计算（Evidence Quality Signals）**：
   - `domain/investigation/engine.py` 新增 `evidence_quality_signals(state)`，自动计算 `domain_saturation`、`near_duplicate_sources`、`undisposed_counter_evidence` 与 `numeric_conflicts` 并注入 `memory.coverage`。
6. **舆情痛点驱动的底层深化（Domain-Driven Agent Infra Hardening）与全景架构展示页**：
   - **长报道多视角首读摘录提取与证据生命周期压缩**：`investigation/service.py` 的 `_read_material` 联合匹配 `decision.focus + issue.question + open components`；`domain/opinion/processor.py` 增强引语/量纲/回应高价值信号加权与分块去重；`investigation/context.py` 的 `Compiler.compile` 对已引用证据、未处置反方证据及数值冲突证据强制使用 `CompactionMode.NEVER`，对未引用边缘证据、来源元数据及历史观测启用 `CompactionMode.TRUNCATE`。
   - **确定性同源通稿去重与独立信源簇计权**：`domain/investigation/engine.py` 的 `reduce_state` 新增 `_auto_detect_syndicated_relations`（摘录二元词 Jaccard $\ge 0.75$ 自动生成 `repost/same_text` 溯源关系）；`report_contract/projector.py` 新增 `_build_source_cluster_map`（Union-Find），在正反拔河权重条与关系拓扑图中按去重后的独立信源簇数量计权。
   - **相对时间自动锚定**：`report_contract/projector.py` 新增 `_anchor_relative_time`，结合 `SourceVersion.published_at` 将“昨日”、“10月13日”等相对时间换算为标准 ISO 日期并保留原文标注。
   - **系统全景架构与数据流交互网页**：生成 `artifacts/architecture_showcase.html`，可视化呈现 AgentLoop 10 阶段事务状态机、端到端数据流管道、四层代码架构与舆情痛点映射表。

### 验证证据

```text
tests/unit/domain/opinion + tests/unit/report_contract + tests/unit/presentation_skill + tests/investigation: 270 passed
真实案例端到端重放验证:
- cb39508854dd491a8d9752fae46e2ec6（罗永浩吐槽野人先生冰淇淋事件）: 生成 13 个视觉模块（含 relation_graph, debate_versus, position_matrix, response_scorecard），Corpus.retrieve 召回 5 条高密度引语/数值证据，识别 numeric_conflicts=1, undisposed_counter_evidence=5
- 9b1bf7d631804cffbfc85a00086aef52（三九胃泰中秋广告争议事件）: 生成 14 个视觉模块，Corpus.retrieve 召回 5 条核心证据，识别 domain_saturation=1, undisposed_counter_evidence=5
```



## 确定性回放（Decision Journal + Replay，S1–S5）

### 实现范围

- `runtime/replay_record.py`：`StepJournalRecord` / `ModelCallRecord` 记录结构、`canonical_json` 与 `fingerprint`（sha256）、`Divergence`、`compare_step_records` / `compare_journals`（按执行顺序返回第一处分歧）。
- `runtime/recording.py`：`DecisionRecorder` 管理单 step 的 model call 缓冲与 in-flight 侧文件；`RecordingModelClient` 记录每次 decide 的结果（决策或 `ModelClientError`）；`JournalingCheckpointStore` 包装 checkpoint store，保证 journal 的 commit 记录先于 checkpoint 落盘。
- `runtime/replay.py`：`replay_records` 只替换 model 与 action executor（回放端只读录制内容，缺失即抛 `ReplayMissingRecordError`），其余 compiler、validator、resolver、reducer、completion 均为生产实现；回放产出的 journal 与原记录逐 step 比较。
- `runtime/journal.py`（S2）新增公共方法 `rewrite`，供 in-flight 对齐使用。

### 核心流程

1. 每次 decide 前后，`RecordingModelClient` 以 `fingerprint(context)` 作为 `context_hash`，把 outcome 追加到 `<journal>.inflight`（每条 model call 一条，同步 fsync）。
2. step 提交时，`prepare_save` 先把 `StepJournalRecord` 追加到 `journal`，随后 `inner.save` 写 checkpoint，最后 `after_save` 在无 active step 时删除 in-flight 文件。
3. `load` 时 `reconcile_load` 对齐三方：journal 比 checkpoint 多 1 条则截断（commit 后 checkpoint 前崩溃）；少或多超过 1 条则拒绝；按 active step 的 attempt 与 phase 计算应有 model call 数，保留对应前缀，不足则该 step 标记 `complete=False`。

### 关键契约与不变量

- 每个 decision attempt 恰好一次 model call，因此已完成 model call 数为 `(attempt-1) + [phase 不在 OPENED/DECIDING]`。提交时 `complete` 的 step 必须满足 `len(model_calls) == attempt`，否则记录失败。
- journal 的 `step_index` 严格递增（沿用 S2 的 I1）；checkpoint 版本保持 v4 不变。
- 回放不调用真实 model 或 tool；上下文哈希不一致、action 或 action_id 不一致、状态指纹不一致分别产生带 step 与字段的 divergence。
- `complete=False` 的 step 不可回放，回放返回 `UNREPLAYABLE` 而不是误报分歧。

### 设计取舍

- 选择独立 journal 而非扩展 checkpoint 到 v5：checkpoint 兼容性不变，回放材料可独立归档或删除。
- in-flight 文件使 resume 后的续跑 step 仍可完整回放；代价是每次 model call 增加一次 fsync 写入。
- 回放通过 `build_loop` 注入组件，不在回放模块内复制 loop 逻辑，保证回放与生产共用同一状态机。

### 失败与恢复语义

- journal 追加失败抛 `JournalWriteError`，run 终止；下次 load 按上述对齐规则恢复。
- 崩溃发生在 commit 的 checkpoint 写入之后、in-flight 清理之前：下次 load 因 active step 为空而丢弃残留 in-flight 文件。
- 缺失记录的回放请求抛异常，不降级为真实调用。

### 测试与验证证据

```text
tests/unit/runtime/test_journal.py: 13 passed（S2）
tests/integration/test_decision_replay.py: 6 passed
  - 正常录制 5 step 后回放 MATCHED
  - 同一 journal 连续回放 3 次结果完全相同
  - 篡改 step 2 的 context_hash → divergence(step=2, field=model_calls[0].context_hash)
  - 篡改 step 3 的 state_fingerprint → divergence(step=3, field=state_fingerprint)
  - 缺失最后一条记录 → ReplayMissingRecordError
  - commit 的 checkpoint 写入前注入崩溃 → resume 后 journal 为 5 条且全部 complete，回放 MATCHED
全量 pytest: 822 passed, 2 skipped（live 测试）
跨进程确定性: PYTHONHASHSEED=1 录制、PYTHONHASHSEED=777 回放 → matched 5；另一 seed=5 录制的 journal 与 seed=1 字节级一致
```

### 已知限制

- ruff 未在项目 venv 中安装，静态检查仅通过 `compileall`，未运行 lint。
- 回放已在 live 模型与真实 tool 的录制上验证（见文末「收口节点：真实模型回放验证与离线质量门禁（2026-10-17）」）；离线 fake 装配保留为最快的回归层。
- journal 不记录时间戳与分步耗时；这不影响回放正确性，但诊断仍停留在 StepRecord 层。

### 对下一节点的影响

- live 路径已接入 `RecordingModelClient` / `JournalingCheckpointStore` / `DecisionRecorder`（`build_live_service` + `scripts/live_record_replay.py record`），`ReplayCodec` 使用 live 决策与观察的 `TypeAdapter`。
- 后续若 StepRecord 字段或 `CompiledContext` 的序列化形状变化，会改变 `context_hash` 与 `state_fingerprint`，需要同步更新测试期望。

## 收口节点：真实模型回放验证与离线质量门禁（2026-10-17）

### 解决的问题

1. 旧已知限制写着「回放只在离线 fake 装配上验证」，说明不了确定性回放对真实 provider 也成立。
2. 对外引用的三个质量数字（检索召回 60%、忠实性 71%、对抗点 2/3）是一次性人工统计，没有命令可以重跑。
3. journaled run 只写 checkpoint，不产 `report.md`，读结论要翻 domain_state。

### 已实现的语义

- **真实 provider 录制 + 回放**：`scripts/live_record_replay.py` 的 `record` / `replay` 子命令，真实 Brave 搜索 + Jina 读取 + `deepseek-flash`（`https://api.deepseek.com/v1`）。`artifacts/live-run-deepseek-20261017`（9 步）与 `artifacts/live-run-deepseek-envcheck-20261017`（13 步）两次运行各回放 3 次全部 `matched`，journal 的 md5 在回放前后不变（回放只读）。另在 `artifacts/live-recorded-run` 上验证了篡改 `context_hash` 会 `diverged`、删除末条记录会 `ReplayMissingRecordError`。
- **离线质量门禁**：`src/opinion_search/evaluation/{bundle,metrics,gate,__main__}.py` + `evaluation/corpus.json` + `evaluation/annotations/*.json`，入口 `python scripts/quality_gate.py [--check]`。四个冻结案例（对抗 s5-b 运行、埋点对抗运行、两次 OpinionSearch 真实轻路径运行），不调用模型、不访问网络。
- 门禁复算结果与历史人工统计一致：检索召回发现层 7/10、已读层 6/10（历史 6/10）、忠实性 10/14、系统自评 6/14、对抗点 2/3；人机一致率 9/10，唯一分歧是必中清单第 7 项（大河网「河声」评论：候选池确有 `news.qq.com` 转载，历史人工判定为未覆盖）。分歧照实打印，不把规则调成「刚好等于历史数字」。
- 门禁把「对抗 2/3」里丢的那一分显式化：反方稿被读、被摘 5 条证据，但 0 条进入判断层；被放大 10 倍的数字没有进判断层，却以原始摘录留在报告末尾的证据附录里——通过是「这一轮没轮到综合」，不是「有数字校验收拦截」，附录中出现这两个数字也被记进基线。
- **数字矛盾检测（机制层）**：`src/opinion_search/domain/numeric.py` 只做一件事——同一钱指标是否在两个文档里相差一个数量级。取数字前 18 字窗口当指标名，去掉年份与「高达/达/为/约/超」词尾，按最长公共后缀（至少 3 字）聚类（`公司销售费用` 与 `年销售费用` 因此归到同一组），只在跨文档、且比值四舍五入到整十次幂（容差 0.02）时报告。喂 10 篇冻结对抗材料报出 5 条冲突、覆盖 4 个指标（营业收入 316.03 vs 3160.3、销售费用 90.89 vs 900、归母净利润 34.21 vs 342.1、推广费 50 vs 501.9），两轮真实运行的证据集零误报。门禁把它记为第四条 `layer: mechanism` 检查，与报告层三条分开统计（报告层仍 2/3，机制层 3/4）。
- **数值台账进运行时（报告层显性化）**：`State.numeric_ledger` 在每次 `read` 时由 `service._read_material` 用 `extract_quantities` 落库（对抗材料十篇共 52 条），`reduce_state` 按 `observation_id` 幂等合并（重复读同一版本不会翻倍）；`numeric_audit.conflicts(state)` 复用同一套后缀聚类，`describe()` 生成「指标 / 两个值 / 两个来源」的行，`build_report(..., numeric_conflicts=...)` 把它写进 `report.json` 的 `numeric_conflicts`，`markdown()` 在「来源与证据」之前渲染「## 数据口径存疑」。报告只说「相差 10 倍，请核实」，不判断哪一方正确、不改写、不删稿。边界：冻结的 2026-09 对抗运行早于该字段，它的历史报告仍是 2/3；重跑会自动带上这一节。
- **`record --report`**：复用 `build_search_outcome` + `RunBundleWriter`，与 served 入口同一条路径，在 checkpoint 旁写出 `report.md` 与 `outcome.json`。
- **`.env.example`** 落地环境变量的完整清单与 `NO_PROXY` 的坑；CI 追加 `quality_gate.py --check` 与 `pytest tests/quality`。

### 测试命令与结果

```
python scripts/quality_gate.py --check   # quality gate: baseline reproduced exactly
pytest tests/quality -q                  # 6 passed
pytest tests/unit/domain/test_numeric.py -q  # 8 passed
pytest tests/investigation/test_numeric_audit.py -q  # 5 passed（冻结对抗材料 → 台账 → 报告节）
```

### 已知限制

- 门禁保证的是「给定这些冻结运行，数字可重算、可回归」，不保证标注本身正确，也不证明换模型或换搜索引擎后仍然成立。
- ~~s5-b 的 11 个已读来源里有 4 个没有冻结快照，25 条证据不可核。~~ **2026-10-18 更正**：快照一直在运行时的 case store（`artifacts/live-runs/investigations/cases/f20cdcc60d854c4eb02a7fd7e8d3a488/artifacts/`）里，早前的不可核是把 `materials_dir` 指向对抗材料目录造成的误判。改正后 s5-b 64/64 精确命中，语料扩到 6 次运行 / 2 个事件，合计 208/208。
- 两条 `OpinionSearch` 案例只覆盖 opinion 域（没有 findings / review 层），只作为当日真实运行的回归指纹。
- 数字矛盾检测目前只是**离线机制证据**，未接进 `investigation` 运行时，不改变任何一次真实运行的行为；覆盖面也窄：只抓「同一指标 × 跨文档 × 整十次幂」，同文档自相矛盾、同义不同词、非整十次幂的放大都抓不到。

### 对下一节点的影响

- 结构化 QueryPlan + 第二引擎（破 `news.qq.com` 66% 聚合站偏向）仍是最有价值的下一步。
- 数字矛盾检测的下一步是接进 `investigation` 的综合前校验：发现冲突就写进 finding 的 `contradicting_ids` 或报告的缺口说明，并补同文档矛盾与非整十次幂的用例。
- 对抗埋点可以按 `evaluation/annotations/sanjiu-adversarial.json` 的模式扩到多案例，形成真正的回归套件。

## 质量层专项：引语溯源与确定性护栏（2026-10-18）

### 解决的问题

D4 的忠实性数字（人工 10/14、系统 6/14）指向的失败模式是"摘"不是"编"，但此前没有任何可重算的证据。对冻结 s5-b 的 26 个引号片段做分类后确认：16 条在绑定摘录内、8 条原文有但没被摘、2 条在所有已读原文里都找不到、0 条因无快照而不可核。**引语这一层此前既没被度量、也没被守。**

### 已实现的语义

- `src/opinion_search/evaluation/metrics.py: quote_support(bundle)`：把引语分为 `in_excerpt` / `recoverable` / `absent_from_doc` / `doc_unavailable` 四类并进基线，同时给出"确定性回填上限"（61.5% → 92.3%）。
- `src/opinion_search/investigation/quotes.py`：`quoted_spans` / `missing_from_excerpts` / `unbacked_quotes` / `locate`，纯字符串比较，无模型、无网络。
- `src/opinion_search/investigation/service.py` review 分支：`Executor._documents(state)` 取回该判断所引用版本的全部原文；`unbacked_quotes` 命中的引语由程序追加进降级理由（"引语「…」未在支持摘录或已读原文中出现"），与既有的 `unbacked_specifics`（数字/日期/百分比）共用同一条降级通道。
- 只在"该判断引用的所有版本都能取到原文"时才判定，避免把"取不到"误判成"编造"。

### 测试与验证

- `tests/unit/test_quotes.py`：6 个用例（两种引号、去重、短引号忽略、present/absent 分离、摘录与原文结论相反、跨行定位返回精确区间）。
- `pytest tests/unit tests/quality tests/investigation` → 670 passed；`tests/contract tests/integration tests/security` → 134 passed；`scripts/quality_gate.py --check` → baseline reproduced exactly；ruff All checks passed。

### 已知限制

- 护栏只抓"原文里根本没有"的引语（本轮 26 条里 2 条）；占大头的"原文有、摘录没摘"（8 条）靠回填解决，而回填只在 reflect 阶段对新写入的判断生效。
- 92.3% 已由门禁逐条实测（用运行时同一个 `locate` 在冻结正文上定位，8/8 可回填）；仍需一次 live run 验证端到端效果。
- 引语识别是正则（成对引号、至少 5 字）；跨段引语、书名号、转述不在此列。
- 护栏挂在 review 阶段，若该次运行的 review 被预算截断，护栏不会生效。

### 对下一节点的影响

- 引语回填已随本节点落地：`Executor._record_findings`（reflect 阶段）用 `quotes.locate` 取精确区间，写成 `Evidence` 并通过新增的 `Observation.finding_evidence` / `FindingEvidence` 由 reducer 挂回 `finding.evidence_ids`；`tests/investigation/test_quote_repair.py` 覆盖定位、绑定、以及"摘录已覆盖时不重复补"三种情形。
- 已把回填能力做成门禁指标（`quote_support` 里 recoverable 一律用生产 `locate` 复核）；剩余一步是放进一次 live run 端到端复测。
- 定位器只桥接空白与引号风格差异（`_variants` 把 ‘…’ 与 “…” 互换后再匹配，绑回的仍是原文自己的字符），其余字符必须逐字一致。
- 其后才是 open→not_found 收口与必中清单从 10 项扩到 30 项（样本量 1 是当前质量数字最大的短板）。

### 真实运行复测（2026-10-18）

用 DeepSeek 官方 API（`https://api.deepseek.com/v1`，key 取自 `~/.deepseek/secrets/secrets.json`）+ Brave + Jina 真跑了一次「罗永浩吐槽野人先生冰淇淋」，run `166742aa691b4e79acc5db5c9a47793b`，已纳入质量门禁语料（第 7 个案例，materials 指向该运行的 case store）。

- **生效的**：数值台账落了 19 条；报告里按预期出现「## 未收口的问题」；引用闭合 100%、摘录可核 15/15、判断有据 12/12。
- **未触发的**：这次运行 0 次 review 就结束了（步数上限先到），所以 reflect 时的引语回填与 review 时的引语护栏都没有场景。引语覆盖 11/13 = 84.6%，余下 2 条在所有已读正文里都找不到——正是护栏该拦的那类，但没跑到 review。
- **代价对比**：这次比冻结的同期运行（cb39）短得多，检索召回 7/12 发现、5/12 已读，低于 cb39 的 12/12 与 7/12。说明「更长/更贵的运行」换来的首先是召回，不是引语质量。
- **结论**：报告层与台账已端到端验证；引语护栏与回填仍需一次能进入 review 的更长运行才能确认。

### 质量修复与第二事件标注（2026-10-19）

- **摘录回填补齐**：`_record_findings` 去掉了「没有引语就跳过」的早退；当判断里含摘录没有的数字时，用新增的 `quotes.best_supporting_span`（数字 + 中文 bigram 重合度）把原文中最匹配该判断的一句绑成证据。上一轮 14 条 partial 里 13 条的成因都是「摘录没覆盖判断里的具体字句」。
- **重复搜索不再致命**：`Validator` 允许重复的 query 通过（reducer 记为 `duplicate`），只有同一 query 占满最近 3 次尝试才拒绝。此前重复 query 直接判无效，6 次重试耗尽会把整轮 run 终止在 partial（实测 41 步那次就是这样结束的）。
- **忠实性到 n=2**：新增第二事件（罗永浩吐槽野人先生，run `166742aa`）的 12 条人工标注：9 条完全支持、3 条部分支持、0 无中生有 = 75%，与三九胃泰的 10/14 = 71% 同量级。门禁新增「忠实性·第二事件」一行。
- 全量 `856 passed, 2 skipped`；ruff 干净；`quality_gate.py --check` 可复现。

