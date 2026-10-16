# OpinionSearch 深度化代码修改计划（内容与呈现解耦 + Presentation Agent 自主编排）

> 状态：已确认核心方向  
> 日期：2026-10-14  
> 适用定位：20 人以内小范围使用的个人深度项目（追求单机机制深度、舆情分析准确度与极致阅读体验，不建设分布式、多租户、重型向量集群或监控平台等生产级基建）

---

## 0. 核心病根诊断与顶层重构原则

### 0.1 已确认的系统级症结：下游渲染契约反向绑架了上游内容生成

通过对源码及两次真实联网运行产物（三九胃泰广告争议、罗永浩吐槽野人先生事件）的交叉核查，已确认当前系统存在严重的**“渲染反噬内容”**现象：

1. **真实查到的核心事实因未填 UI 槽位被判“材料不足”**：在三九胃泰运行产物（[`workbench.json`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/9b1bf7d631804cffbfc85a00086aef52/workbench.json)）中，模型已查出并提交了“华润三九回应正在安排撤下广告”、“客服称已通知立即下刊”等 `Finding`，但因未在 `ReflectDecision` 中同步填入 `module_fields["actions_taken"]` 槽位，[`investigation/presentation.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/presentation.py) 的 `facet_modules` 直接将该专项模块打为 `insufficient`，向用户展示“缺少专项字段：已采取行动”的报错框，反而把已有判断折叠隐藏。
2. **UI 填表负担压垮上游 `Evidence → Finding` 转化率（实测仅 50%）**：为了支撑前端的回应覆盖徽标、立场标签、4 个市政专项模块字段与复合问题子项，[`FindingProposal`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/models.py) 与 [`Validator.validate`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/engine.py) 叠加了十余项强校验。在罗永浩事件（[`report.md`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/cb39508854dd491a8d9752fae46e2ec6/report.md)）中，48 条已入库证据（含钟薛高重启、人民网评论、西贝传闻、野人先生 9月16日正式回应）仅转化出 4 条 `Finding`，3 个必答问题整段留白，模型宁可连续被拒 29 次 `finish` 也不敢轻易调用高报错风险的 `reflect`。
3. **固定题型模板框死非市政舆情，页面沦为千篇一律的列表**：现役工作台仅预置了 4 个市政公用事业 Facet（规则对照、服务可用性、计费补救、调查纠正），遇到商业品牌危机或社会热点（如罗永浩事件）直接退化为 `general` 列表；而另一套精心设计的 [`presentation_skill/`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/presentation_skill) + [`report_contract/`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/report_contract) 既未接入生产主链路，又仅赋予模型“在 1～2 个固定枚举间换 CSS 皮肤”的微弱权限，未能实现真正的按事件动态编排。

### 0.2 顶层重构原则：上游松绑专心查内容，下游交给 Presentation Agent 自主编排与重塑数据

本次修改将原有的 **“UI Schema 倒逼上游填表”** 彻底反转回 **“Content → Autonomous Presentation Agent → Verified Rendering”** 的正向闭环：

```text
[上游：Investigation Loop]
专心搜索、阅读、重检、提炼干净的原子 Finding 与 Review（彻底剥离 UI 槽位填表负担）
        │
        ▼ （只读已提交状态：Issues + Reviewed Findings + Sources + Evidence）
[下游：Presentation Agent (升级版 presentation_skill)]
阅读全量已审查判断，根据本事件特点自主决定：
1. 选哪几个专题板块与视觉积木（对比表 / 正反交锋卡 / 立场矩阵 / 回应计分卡 / 重点卡片）
2. 为当前事件动态定制模块标题与表格列头（如“西贝硬刚 vs 野人先生冷处理对照”）
3. 将长句 Finding 提炼重塑为单元格/卡片要点，并强制绑定 source_finding_ids
        │
        ▼
[护栏：Presentation Validator & Deterministic Guard]
1. 校验所有 source_finding_ids 真实存在且已通过审查，自动映射为可下钻的 [引N] 角标
2. 复用 unbacked_specifics 校验单元格内的数字/日期/百分比 100% 出自所绑定的 Finding
3. 校验不通过的单模块确定性回退为原始 Finding 卡片展示，永不丢内容、永不报空框
        │
        ▼
[终端：Deterministic HTML / Workbench Renderer]
固定报刊/暗夜大框架（Fixed Shell） + 动态组装的高可读性视觉积木
```

---

## 1. 明确不做的事（保持 20 人以内个人深度项目边界）

- 不引入分布式锁、多进程租约、外部关系型数据库或消息队列。
- 不引入外部独立向量数据库（Milvus / Qdrant）或重型 Embedding 服务。
- 不恢复已被否决的多 Agent 调查循环（`archive/harness-pipeline/`），调查过程保持唯一 `AgentLoop`。
- 不允许模型直接输出自由 HTML / CSS / JS 字符串，所有视觉输出必须经过结构化 JSON 计划与确定性渲染器。

---

## 2. 三层自适应呈现架构设计（回答“同框架、异元素”如何实现）

为了做到**“所有舆情事件的大框架统一稳定，但具体板块和内部视觉元素随事件灵活变化”**，表现层采用三层结构：

| 层级 | 控制主体 | 职责与不变性 | 具体形态说明 |
|---|---|---|---|
| **第一层：宏观大框架（Fixed Shell）** | 程序固定 | 保证跨事件的顶层阅读动线一致、视觉风格统一（报刊纸墨 / 暗室读档双模式） | 固定四大区域：① **首屏定性区**（事件主标题 + 一句话态势提要 + 核心判断卡 + 核查状态条）→ ② **脉络演进区**（事件时间轴 + 报道发布分布）→ ③ **核心博弈与深度拆解区（由 Agent 动态组装）** → ④ **底层证据卷宗区**（报道对照 + 原文高亮抽屉 + 折叠诊断） |
| **第二层：视觉积木库（Visual Primitives）** | 程序提供渲染原语 | 提供 7 种高表现力的通用容器，只定义“数据结构形态与排版样式”，不硬编码业务列名 | ① `ComparisonTable`（动态列头多维对照表）<br>② `DebateVersus`（正反交锋 / 双阵营对冲卡）<br>③ `StakeholderMatrix`（多方主体立场与诉求矩阵）<br>④ `ResponseScorecard`（公众质询 vs 官方回应覆盖计分卡）<br>⑤ `Timeline`（时序演进节点）<br>⑥ `BentoCards`（重点专题档案卡片组）<br>⑦ `DonutChart / BarDistribution`（程序计算的来源/时间分布图） |
| **第三层：专题策划与数据重塑（Presentation Agent）** | Agent 自主决策 + 程序护栏校验 | 根据当前事件查出的 `Finding` 集合，自主策划中部核心区的板块组合、自定义表头并将长句提炼入格 | 面对“地铁调价”自动生成《新旧票价与听证方案对照表》；面对“罗永浩吐槽野人先生”自动生成《野人先生冷处理 vs 西贝硬刚公关后果对照表》与《大V、品牌、官媒多方立场矩阵》 |

---

## 3. 具体代码修改模块与方案清单

### M1. 上游调查循环减负：剥离 UI 填表义务，释放内容转化率

#### 为什么要修改
- 当前 [`FindingProposal`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/models.py)、[`Validator.validate`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/engine.py) 与 [`completion`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/engine.py) 将表现层的 `module_fields`（18 个市政字段白名单）和 `required_module_gaps` 作为调查完成的前置条件，并在 `INSTRUCTIONS`（[`investigation/context.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/context.py)）中强迫模型优先围绕 `page_plan.search_targets` 填表。
- 这既限制了非市政舆情事件的搜索视野，又让 `ReflectDecision` 因字段联动校验过于繁琐而频繁被打回或少产判断。

#### 修改哪里（模块与符号）
- **`src/opinion_search/domain/investigation/engine.py`**：`Validator.validate`、`completion`。
- **`src/opinion_search/investigation/context.py`**：`INSTRUCTIONS`、`Compiler.compile`。
- **`src/opinion_search/investigation/page_plan.py`**：`build_page_plan`、`required_module_gaps`。

#### 设计方案与边界
- **解绑 `module_fields` 对调查完成的阻塞**：`completion()` 不再因 `required_module_gaps` 缺失而将本来已回答完所有用户必答问题的调查降级为 `ACCEPT_PARTIAL`；`module_fields` 在 `FindingProposal` 中仅作为可选附加信息保留向后兼容，不再写入主循环 Prompt 强迫模型填写。
- **放宽 `ReflectDecision` 的联动苛刻校验**：
  - 当模型提交 `FindingProposal` 时，核心校验收敛于引用真实性（`issue_id`、`evidence_ids`、`contradicting_ids` 存在且不自相矛盾）与基本归因（`attributed` 需有 `stakeholder`）；对于 `response` 评估，若未填写 `uncovered` 或 `coverage_reason`，允许程序按默认规则温和补全或提示，而非整批抛 `ValueError` 作废全部新生成的 `Finding`。
  - 对于含 `components` 的复合问题，允许模型在 `IssueAssessment` 中仅更新已查明子项的状态，或当父问题下已有审查通过的 `Finding` 覆盖子项时由程序辅助对齐状态。

#### 风险与验收标准
- **风险**：已有针对 `Validator` 拒绝非法 `module_fields` 或 `response` 组合的单元测试需要同步更新契约预期。
- **验收标准**：在冻结材料回放（三九胃泰与罗永浩案例）中，模型调用 `reflect` 的一次通过率显著提升，48 条证据下不再出现 3 个必答问题留白的情况。

---

### M2. 升级 `presentation_skill`：实现真正的自主版面策划与数据重塑 Agent

#### 为什么要修改
- 现有 [`LlmPresentationPlanner`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/presentation_skill/llm_planner.py) 只能接收已经定死模块和条目结构的 `PresentationPlan`，且输入载荷被剥离了条目内容（模型“蒙眼二选一”），切换 `selected_visual` 时因没有重塑 `items` 字段结构，在 [`renderer.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/report_contract/renderer.py) 中直接渲染出空白卡片或英文键名表头；同时同步 `asyncio.run` 在异步环境下会抛 `RuntimeError` 并被静默吞没。

#### 修改哪里（模块与符号）
- **`src/opinion_search/presentation_skill/llm_planner.py`**：`LlmPresentationPlanner`、`VisualChoice`、`VisualPlanOutput`、`PRESENTATION_INSTRUCTIONS`。
- **`src/opinion_search/report_contract/contracts.py`**：`PlannedModule`、`PresentationPlan`、`VisualEncoding`。
- **`src/opinion_search/report_contract/projector.py`**：`build_presentation_plan`。
- **`src/opinion_search/report_contract/validator.py`**：`validate_presentation_plan`。

#### 设计方案与边界
- **赋予 Presentation Agent“板块选型 + 自定义表头 + 数据提炼”三项自主权**：
  1. **输入升级**：向 `LlmPresentationPlanner` 输入事件主题、调查问题（`Issue`）列表、以及所有有效 `Finding`（含 `finding_id`、`text`、`kind`、`stakeholder`、`stance`、`response`、`event_time`、审查状态）与来源统计摘要。
  2. **输出 Schema（Composable Block DSL）**：允许 Presentation Agent 为中部“核心博弈与深度拆解区”自主规划 2～5 个动态专题模块，每个模块指定：
     - `title`（贴合本事件的中文专题标题，如《野人先生冷处理 vs 西贝硬刚：公关策略与后果对照》）
     - `selected_visual`（从 `comparison_table`、`debate_versus`、`position_matrix`、`response_scorecard`、`bento_cards`、`timeline` 中自主选择）
     - `table_columns`（当选用表格类积木时，由 Agent 自定义 3～5 个中文列头）
     - `items`（由 Agent 将相关 `Finding` 提炼重塑为适配该视觉积木的结构化条目，**每条必须携带非空的 `source_finding_ids: tuple[str, ...]`**）
- **程序确定性护栏（防幻觉与无损回退）**：
  - **引用穿透绑定**：程序根据每条 `item` 绑定的 `source_finding_ids`，自动汇总对应的底层 `evidence_ids` 与审查状态（`supported / partial`），渲染为可点击的引用角标与审查徽标；若引用的 `finding_id` 不存在或未通过基本核查，拒绝该条目。
  - **数字与日期保真校验**：复用 [`unbacked_specifics`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/service.py) 逻辑，检查重塑后的单元格文本中出现的任何具体数字、金额、百分比是否包含在其绑定的 `source_finding_ids` 原文中；若发现模型在提炼表格时编造或算错数字，自动将该模块回退为基于原始 `Finding.text` 的确定性卡片（`build_presentation_plan` 确定性基线）。
  - **遗漏兜底（Zero-Drop Guarantee）**：若某条已经通过审查的重要 `Finding` 未被 Presentation Agent 纳入任何动态专题模块，程序自动将其归入对应议题的兜底卡片中，确保**绝不因为排版而弄丢任何一条有效发现**。
  - **原生异步支持**：提供 `async def aplan(...)` 接口，消除事件循环冲突，并显式记录任何降级原因。

#### 风险与验收标准
- **风险**：模型在生成自定义表格行时可能漏绑 `source_finding_ids` 或产生字段缺失。
- **验收标准**：
  1. 单元与契约测试覆盖：当模型正常输出动态对比表与立场矩阵时，HTML 正确渲染自定义中文表头、内容与 `[引N]` 角标；当模型输出未绑定 `finding_id` 或篡改数字的条目时，护栏精准拦截并无损回退至确定性基线。
  2. 同一套渲染器在不改一行前端代码的情况下，输入“重庆轨道交通调价”与“罗永浩吐槽野人先生”两份状态，能自主生成模块标题、表格列头和视觉组件组合截然不同但同样清晰易读的两份报告。

---

### M3. 打通主链路并重构渲染器与工作台体验：消灭孤岛代码与工程噪音

#### 为什么要修改
- [`report_contract/renderer.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/report_contract/renderer.py) 目前与 [`investigation/manager.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/manager.py) 完全断连；而现役工作台（[`workbench.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/workbench.py) / [`export.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/export.py)）首屏堆砌了大量工程审计免责声明，时间轴只认 `YYYY-MM-DD`，且对多信源的不同表述（`variants`）一律判 `insufficient`。

#### 修改哪里（模块与符号）
- **`src/opinion_search/report_contract/projector.py`**：新增从 `investigation` 状态/报告到 `ContentDocument` 与默认 `PresentationPlan` 的转换器。
- **`src/opinion_search/report_contract/renderer.py`**：补齐 `debate_versus`（正反交锋双栏）、动态列头表格角标渲染、卡片字段自适应映射（Schema Adapter）。
- **`src/opinion_search/investigation/manager.py`**：在发布与页面导出链路接入 `presentation_skill` + `report_contract`。
- **`src/opinion_search/investigation/presentation.py`** 与 **`workbench.py`**：修复 `_timeline` 中文日期解析，将 `variants`（多源不同表述）由报错 `insufficient` 改为并列展示，将已有 `Finding` 但无 `module_fields` 的模块正常渲染为要点卡片。

#### 设计方案与边界
- **主链路合流**：在 `Manager` 完成调查生成报告后，自动构建 `ContentDocument`，调用 `LlmPresentationPlanner`（离线模式或调用失败时无缝使用确定性基线）生成 `PresentationPlan`，持久化为 `presentation_plan.json`，并支持直接通过 `report_contract/renderer.py` 导出报刊级自包含 HTML。
- **消除“有内容却报 `insufficient`”的假空框**：在 `investigation/presentation.py` 中，只要关联议题下已有有效 `Finding`，即使 `module_fields` 为空或存在 `variants`（多信源表述差异），也正常展示 `Finding` 要点与多口径并列对比，不再用“缺少专项字段；未用通用摘录填充”掩盖已查明的事实。
- **首屏信息降噪**：将检索尝试次数、筛选口径免责说明、9 阶段链路诊断等工程内部信息统一收进次级折叠抽屉或独立诊断视图，让首屏 100% 聚焦于“一句话定性 + 核心判断 + 演进时间轴 + 动态专题博弈区”。

#### 风险与验收标准
- **风险**：已有 Web E2E 测试检查旧版导出页面的特定选择器。
- **验收标准**：保持原有 API 路由与测试契约兼容；用本地已有的[三九胃泰](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/9b1bf7d631804cffbfc85a00086aef52/report.json)和[罗永浩事件](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/cb39508854dd491a8d9752fae46e2ec6/report.json)真实产物直接运行新渲染管线，验证生成的 HTML 页面无任何空白卡片、无英文键名表头、无虚假 `insufficient` 灰框。

---

### M4. 修复收束控制逻辑死锁：解除全局 `read_errors` 封锁，开放保留段本地重检

#### 为什么要修改
- 在 [`src/opinion_search/domain/investigation/engine.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/engine.py) 中，`response_search_complete(state, issue_id)` 检查 `if not RESPONSE_PURPOSES <= covered or state.read_errors: return False`。因为 `state.read_errors` 是全局列表，只要全过程有任意 1 个网页因反爬读取失败（实测每次必发），所有问题都永远无法合法标为 `not_found`。
- 在 [`src/opinion_search/investigation/service.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/service.py) 中，`ConsolidationValidator` 在模型调用达 `2/3` 后禁止一切 `retrieve`，导致审查发现某条判断因摘录不全被判 `partial` 时，无法从本地已存正文补取证据。

#### 修改哪里（模块与符号）
- **`src/opinion_search/domain/investigation/engine.py`**：`response_search_complete`、`_open_questions_guidance`。
- **`src/opinion_search/investigation/service.py`**：`ConsolidationValidator.validate`。

#### 设计方案与边界
- **按 `issue_id` 局部化读取错误判断**：`response_search_complete` 仅检查归属于当前 `issue_id` 的候选 URL 是否有未消化的读取失败；并在 `_open_questions_guidance` 中精确区分当前问题应标 `not_found` 还是 `unavailable`，不再给出自相矛盾的提示。
- **保留段允许针对 `partial` 判断的本地 `retrieve`**：当处于发布保留段且存在 `verdict == "partial"` 的判断、同时剩余模型调用预算 `>= 4` 时，允许执行一次零外部网络开销的本地 `RetrieveDecision` 以补齐漏摘的原文片段。

#### 风险与验收标准
- **验收标准**：单测验证当问题 A 存在读取失败而问题 B 搜索完整且无读取失败时，问题 B 可正常以 `not_found` 收口；保留段在存在 `partial` 审查结果时可合法执行 `retrieve` 补证。

---

### M5. 升级页面内证据抽取（In-Page Retrieval）：句子边界滑动切块与引语加权

#### 为什么要修改
- 实测忠实性审查中 **4/14 条 `partial` 100% 源于“原文有引语或日期，但摘录器没摘出来”**；同时在罗永浩事件（[`report.md`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/cb39508854dd491a8d9752fae46e2ec6/report.md)）中，甚至出现了把网页里的 `![Image 7...]` 图片链接和乱码 Base64 字符串当成 `Evidence` 摘入证据库的情况（见 `evidence-58cfd54273f64f5e493b`、`evidence-bb66590d54b4ec86d713`）！
- 根因在于 [`src/opinion_search/investigation/storage.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/storage.py) 的 `chunks()` 未过滤纯图片/乱码块且硬切边界容易劈断句子，`terms()` 对中文做无差别双字切分导致泛化词稀释核心实体权重。

#### 修改哪里（模块与符号）
- **`src/opinion_search/investigation/storage.py`**：`terms`、`chunks`、`Corpus`。
- **`src/opinion_search/domain/opinion/processor.py`**：`_select_evidence_excerpts`。

#### 设计方案与边界
- **清洗噪声块与句子感知滑动切块**：在 `chunks(text)` 中过滤纯 Markdown 图片标签、广告跟踪长链接与低信息密度乱码块（同时严格保持 `start` 与 `end` 指向原始 `content` 的真实字符偏移，确保 `verify_evidence` 100% 通过）；切分长段时优先对齐句号、问号、感叹号、分号与换行边界，并保留滑动重叠。
- **停用双字过滤 + 专名与直接引语加权**：过滤“表示、目前、相关、情况、进行”等高频无意义双字，增加 3-gram / 4-gram 词组特征；对 FTS5 召回的候选块，若包含中文引号直接引语（`“...”`、`「...」`）或明确日期/数值量纲，给予排序加权，确保核心原话优先进入 Top-5。
- **增量 FTS 索引**：按 `version_id` 增量写入 SQLite FTS5，避免每次 `retrieve` 全量删表重建。

#### 风险与验收标准
- **验收标准**：
  1. `verify_evidence(evidence, content)` 在所有新增切块上 100% 通过。
  2. 用罗永浩事件与三九胃泰真实网页原文测试，验证 `![Image ...]` 与乱码链接不再混入 Top-5 Evidence，且此前漏摘的官方回应原话与日期稳定召回。

---

### M6. 抑制单一聚合站垄断、近似通稿识别与反方/冲突证据显式提醒

#### 为什么要修改
- 实测候选 66% 被 `news.qq.com` 垄断；`Resolver.resolve`（[`engine.py`](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/engine.py)）只拼接 `SOCIAL_DOMAINS[:6]` 的 `-site:` 导致后续被禁站点白占搜索名额；`content_hash` 无法识别改标题的同稿转载；对抗测试中反方稿 5 条证据被模型 0 引用，真假营收数字（316.03 亿 vs 3160.3 亿）静默并存。

#### 修改哪里（模块与符号）
- **`src/opinion_search/domain/investigation/engine.py`**：`Resolver.resolve`、`reduce_state`、`_open_questions_guidance`。
- **`src/opinion_search/investigation/context.py`**：`Compiler.compile`。

#### 设计方案与边界
- **同域名配额与聚合站饱和提示**：在单次搜索或同一 `issue_id` 候选中，对已多次读取失败或占比过高的单一聚合域名（如 `news.qq.com`）在 `memory.coverage` 中发出饱和提示，引导模型转向原发媒体或机构词；优化 `-site:` 排除策略减少无效召回。
- **基于双字集合 Jaccard 的近似通稿检测**：在 `reduce_state` 入库 `SourceVersion` 时，若 `content_hash` 不同，计算与已有正文的 Bigram Jaccard 相似度；高于阈值（如 `>= 0.80`）时在上下文中提示“疑似同源通稿转载”，防止把同稿洗稿当作独立信源。
- **反方证据与跨源数值冲突提醒**：扫描未处置 `Evidence` 中的反驳/质疑词以及同议题下相同单位（`亿元`、`万元`、`%`）的显著数值差异，在 `memory.next_action_constraint` 或完成门控反馈中显式点名，要求模型在 `reflect` 中通过 `contradicting_ids` 或争议判断予以处置。

#### 风险与验收标准
- **验收标准**：在三九胃泰对抗回放样本上，未处置反方证据与“316.03 亿 vs 3160.3 亿”数值冲突能被确定性检出并注入上下文引导。

---

## 4. 实施路线图（按效果可见度与依赖顺序推进）

1. **第一步：先打通并升级 Presentation Agent 与渲染管线（M2 + M3 + M1 表现层解绑）**
   - 直接用仓库里现成的两份真实运行快照（[罗永浩事件](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/cb39508854dd491a8d9752fae46e2ec6/report.json)与[三九胃泰事件](file:///Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/artifacts/live-runs/investigations/runs/9b1bf7d631804cffbfc85a00086aef52/report.json)）作为输入，验证升级后的 `Presentation Agent` 能否在不改上游数据的情况下，为这两个事件自动编排出**定制化的对比表、多方立场矩阵、正反交锋卡**，并消除三九胃泰里的 `insufficient` 假空框。
2. **第二步：上游调查松绑与收束死锁修复（M1 调查层 + M4）**
   - 移除 `ReflectDecision` 的 UI 填表包袱，修复全局 `read_errors` 锁死 `not_found` 的 Bug，让模型把全部精力放在把 48 条证据转化为高质量 `Finding` 上。
3. **第三步：正文证据清洗、引语加权与反方/通稿核验（M5 + M6）**
   - 消灭 `![Image...]` 垃圾证据块，提升关键引语召回率，补齐近似通稿识别与反方/矛盾数字提示。
