# OpinionSearch Agent Harness 蓝图与决策记录

> 状态：**部分被取代（2026-09-24 按代码校正）**  
> 说明：本文件最初按「Controller / Research Agent / Analyst / Reviewer 多角色流水线」编写。
> 该路线已于 2026-09-21 评估后否决并归档，决策记录见
> `opinion_search_agent/archive/harness-pipeline/README.md`；当前实现是
> **唯一 Runtime AgentLoop + 两套领域组合**（`domain/opinion` 与 `domain/investigation`）。
> 本次校正已按代码改写涉及角色集、Controller 动作空间、Scheduler、ResourceLedger 的章节；
> 报告契约与渲染边界（§6–§10、§17）不涉及 Agent 拓扑，仍然有效。
> 唯一 canonical 项目设计是 `docs/public-opinion-search-agent-design.md`，本文不覆盖它。
> 规则：后续设计变更需要更新本文件，不能只停留在对话中。

## 1. 项目定位

OpinionSearch 是一个社会舆情搜索 Agent。

输入：

```text
一个具体的舆情事件
```

输出：

```text
一份结构化、可追溯、可审查、可渲染为 HTML 的舆情报告
```

它不是通用多 Agent 框架，也不是传统深度搜索 Agent。  
它的核心是舆情事件调查、证据链、观点与回应覆盖、审查和收束。

## 2. 最终目标不做 V1 裁剪

当前决策：

> 不再用 V1 对功能做裁剪。  
> Report Contract 和 Harness 架构按最终目标形态定义。

后续的版本号只表示：

- 契约兼容版本
- 实现顺序
- 数据结构迁移版本

不表示功能范围缩小。

## 3. 总体架构：搜索 + 渲染

```text
舆情搜索 Agent
├── 搜索 / Harness 部分（唯一 Runtime）
│   ├── runtime/   AgentLoop
│   │   ├── RunState / StepRecord / Decision-Action-Observation-Delta 信封
│   │   ├── step transaction + checkpoint / resume
│   │   ├── completion control + failure recovery
│   │   └── 领域注入协议接口（compiler / validator / resolver /
│   │       executor / processor / completion / reducer / store / id / hook）
│   ├── domain/opinion/        4 动作：search / read / reflect / finish
│   ├── domain/investigation/  6 动作：search / read / retrieve / reflect / review / finish
│   ├── context/   有界、可信度分层的上下文编译器
│   ├── memory/    Working Memory 派生投影
│   ├── tools/     Registry / Executor / 熔断 / 持久化缓存
│   └── models/    provider adapter
└── 渲染部分
    ├── Content Contract
    ├── Presentation Contract
    ├── Presentation Skill
    ├── PresentationPlan
    └── Deterministic Renderer
```

两部分共享：

- Content Contract
- ModuleRegistry
- Evidence / Finding / Review
- content revision

但它们职责分离：

```text
搜索 / Harness 负责有什么、真实不真实、是否经过审查
渲染负责怎么展示、怎么交互、缺失时怎么表现
```

## 4. 核心原则

1. 内容与渲染分离
2. LLM 只做局部语义判断
3. 全局、确定、可验证的事情归 Harness
4. Agent 不直接写权威状态，只提交 Proposal
5. 单写者状态提交链
6. 不是固定 workflow，而是有硬边界的 Agent 自主决策循环
7. 空值是合法状态
8. 图表数据只能由程序生成
9. 不为了页面完整而编内容
10. 实施后按效果评估，后续再决定优化方向

## 5. 搜索 Harness 边界

### 5.1 执行主体

不存在角色划分。**只有一个 Agent**，每一步只提交一个决策：

```text
domain/opinion         search / read / reflect / finish
domain/investigation   search / read / retrieve / reflect / review / finish
```

决策是语义意图，不是 ToolCall。`ActionResolver` 把通过校验的 `search` / `read`
决策翻译成带 `tool_name` 和 `arguments` 的内部动作；`reflect` / `review` / `finish`
解析为无外部副作用的动作。

"调查规划"不是独立角色，也不是独立阶段：`domain/investigation` 在进入 AgentLoop
之前由 `investigation/manager.py` 做一次计划模型调用，产出 subject、aliases 和
3–6 个必答问题；进入 Loop 之后，规划以 `ReflectDecision.add_questions` 的形式继续，
总量上限八个问题。

### 5.2 程序 Harness 服务

```text
Validator                    结构校验 + state-aware 校验
ConsolidationValidator       发布保留：模型预算后段强制 review → finish
Processor / Reducer          单写者状态提交链
ToolExecutor                 参数校验 / 同 provider 重试 / 跨 provider 回退 / 熔断 / 缓存
Context Compiler             有界、可信度分层的单次模型输入
CompletionPolicy             finish 闸门与终态判定
Budget                       模型 / 搜索 / 读取 / 总时间 / 收束时间
PagePlan / Projector         从权威状态确定性派生的报告与页面视图
```

### 5.3 控制方式

Harness 决定当前**合法动作空间**，Agent 在合法空间内自主选择下一步。
这不是固定顺序 workflow，但每一步是否合法由程序判定。

硬门禁（均已实现）：

- 必答问题仍 open 时 `finish` 被拒（`completion()` 返回 `reject_and_continue`），
  拒绝理由必须点名每个问题下未处置的证据、未读候选和合法出路；
- 核心结论必须是 active 且有当前 supported review 的 Finding，否则 `finish` 校验失败；
- 模型预算用掉 2/3 后进入发布保留段，只能 review 现有 Finding 或 `finish`；
- 未处置证据堆积（≥8 条）时，获取类决策被重定向为综合（`required_next_action`）；
- `response = not_found` 需要 scoped 回应搜索已完成且无读取错误，
  provider_failure 不能解释成 not_found；
- 没有证据时不能形成事实性 Finding（`evidence_ids` 至少一条，且必须存在于 State）；
- Agent 不能直接写 State，只能提交 Proposal。

### 5.4 单写者状态

```text
Agent Proposal
→ Validator
→ Processor
→ Delta
→ Reducer
→ Checkpoint
```

Global Domain State 是唯一权威状态。  
首版全局 Checkpoint 唯一权威。

## 6. Report Contract

Report Contract 已单独定义为：

```text
docs/opinionsearch-report-contract-v0.1.md
```

核心内容：

- Content 实体模型
- 内容关系
- 固定 Shell
- ModuleRegistry
- GenericModule
- ModuleContract
- 空值状态
- 视觉编码
- 证据、引用与审查规则
- 动态组合与版本
- 用户查看与追溯
- 验收标准

### 6.1 空值状态

```text
not_applicable
not_found
insufficient
unavailable
pending
omitted
```

### 6.2 视觉编码

```text
text
cards
timeline
comparison-table
position-matrix
relation-graph
distribution-chart
trend-chart
risk-matrix
evidence-drawer
action-cards
```

### 6.3 图表原则

- 图表数据只能由程序生成
- 必须有 denominator 和 inclusion
- 必须可下钻到 members
- 公开网页样本不能推断全网热度
- 无平台数据时，情感分布和热度趋势标 unavailable

## 7. 渲染边界

### 7.1 内容与渲染分离

```text
Content Contract
  有什么信息、依赖什么、能否发布

Presentation Contract
  用什么方式展示、怎么交互、缺失时怎么表现
```

### 7.2 渲染 LLM 策略

MVP 约束：

- 渲染 LLM 不进入主 Harness
- 主 Harness 只产出结构化 Content
- Deterministic Renderer 负责最终 HTML
- 未来可以增加独立 PresentationPlanner
- PresentationPlanner 只输出 PresentationPlan JSON
- PresentationPlanner 不生成 HTML / CSS / JavaScript
- PresentationPlanner 不修改 Finding / Evidence / Review
- PresentationPlanner 失败时 fallback 到默认 Renderer

## 8. Presentation Skill 框架

Skill 名称候选：

```text
opinion-report-presentation
```

输入：

```text
ContentContract JSON
PresentationContract JSON
ModuleRegistry
VisualEncoding whitelist
EventProfile
已发布的 reviewed content
产品偏好
```

输出：

```text
PresentationPlan JSON
```

禁止：

```text
HTML
CSS
JavaScript
任意组件名
新增事实
修改 Evidence / Finding / Review
绕过 ModuleRegistry 的模块
```

专业流程：

```text
1. Content Inventory
2. Narrative Priority
3. Module Selection
4. Visual Encoding
5. Empty State Planning
6. Citation Placement
7. Plan Validation
```

Skill 与主框架关系：

```text
主舆情 Agent / Harness
→ 发布 Content Contract
→ Presentation Skill 生成 PresentationPlan
→ Deterministic Renderer 生成 HTML
```

Skill 不进入搜索、分析、审查循环。  
Skill 失败不影响主 Harness。

## 9. Module 到 Visual 的映射原则

ModuleContract 包含：

```text
semantic_type
applies_when
presence
required_fields
optional_fields
data_binding
evidence_gate
review_gate
visual_encodings
selection_rules
fallback_visual
empty_state
priority
version
```

选择规则示例：

```text
类别分布 + 有效 denominator -> donut / bar
类别数 > 5 -> 优先 bar
时序事件 -> timeline
主体与议题 -> position-matrix
主张对照 -> comparison-table
关系 -> relation-graph
文本与引用 -> cards / evidence-drawer
无有效 denominator -> 降级 comparison-table
无平台数据 -> unavailable
```

## 10. HTML 输出边界

HTML 是渲染结果，不是内容源。

输出形态：

```text
在线工作台
自包含静态 HTML
Markdown
后续可扩展 PDF
```

HTML 必须支持：

- 引用角标
- Evidence 原文与上下文
- SourceVersion 元信息
- 来源角色与来源关系
- Review 状态
- 模块状态
- 搜索覆盖与查找截止
- 版本变化
- 未决问题和限制

模型不能生成任意 HTML / CSS / 脚本 / 组件名。

## 11. 实施顺序

以下顺序只表示实现依赖，不表示功能范围。

1. Report Contract 可执行化
2. ModuleRegistry 可执行化
3. Content Schema
4. PresentationPlan Schema
5. Deterministic Renderer 纵切
6. Presentation Skill 骨架
7. Harness Boundary 可执行化
8. Runtime AgentLoop 与领域动作空间纵切（`domain/opinion`）
9. 生产调查域纵切：计划调用 → Issue / Finding / Review → PagePlan（`domain/investigation`）
10. 端到端真实搜索与渲染

原第 8、9 项的「Research Agent 纵切」与「Analyst + Reviewer 纵切」属于已归档的多角色路线，
不再实施。Review 已作为 `domain/investigation` 的第六个决策动作实现，由主 Agent 主动发起。

## 12. 当前实施第一步

第一步先做：

```text
Report Contract
→ ModuleRegistry
→ Content Schema
→ PresentationPlan Schema
→ Deterministic Renderer 预览
```

目标：

- 先用 mock content 跑通内容到 HTML
- 验证 ModuleContract、空值、视觉编码和引用展示
- 再接搜索 Harness
- 不先引入真实模型和真实搜索

## 13. 评估方式

当前不做“方案好不好”的前置争论。  
先按本方案实施，再看效果。

评估关注：

- 页面是否比纯文本更直观
- 模块组合是否合理
- 空值和不适用是否清晰
- 图表是否真实、可审计
- 引用是否可追溯
- 搜索与渲染契约是否稳定
- 后续是否需要调整架构

## 14. 相关文件

```text
docs/public-opinion-search-agent-design.md              唯一 canonical 项目设计
docs/opinionsearch-report-contract-v0.1.md              报告契约
docs/opinionsearch-agent-harness-blueprint.md           本文件
docs/design/opinionsearch-agent-design-v0.1.html        多角色提案，已否决，仅存档
opinion_search_agent/archive/harness-pipeline/README.md 多角色路线归档决策记录
opinion_search_agent/src/opinion_search/report_contract/
```

## 15. 变更规则

后续每次架构或契约变更，必须更新本文件或对应契约文档。  
不能只停留在对话中。

实现事实、验证证据和已知限制再进入实现记忆文档。

## 16. 实现与切换策略

### 16.1 基本原则

不能只停留在文字阶段。  
需要通过可运行实现观察效果。  
如果效果不好，可以切换，但要控制替代成本。

因此实现必须遵循：

```text
稳定契约 + 可替换实现
```

### 16.2 可替换成本分级

高替代成本，尽早冻结：

```text
Content Contract
Domain State 模型
Evidence / Finding / Review 语义
单写者事务
Checkpoint 语义
```

中替代成本，保持接口稳定：

```text
领域决策动作空间
搜索覆盖记录与定向搜索 target
Review 路由与结论冻结规则
Budget 与发布保留段
```

低替代成本，允许先实现后替换：

```text
Presentation Skill
PresentationPlan 具体选择策略
VisualEncoding 具体渲染
页面布局和组件样式
Section 排序
```

### 16.3 实现隔离原则

1. Report Contract 只依赖 schema，不依赖 Harness 实现
2. PresentationPlan 只依赖 Content Contract 和 ModuleRegistry
3. Renderer 只依赖 PresentationPlan，不依赖搜索 Agent
4. Presentation Skill 不进入搜索、分析、审查循环
5. Harness 只通过接口产出 Content Document
6. Agent 不直接调用 HTML Renderer
7. 新能力优先放在独立包内，不直接改旧主路径
8. 旧路径保留只读兼容，直到新路径验证稳定

### 16.4 建议的接口边界

```text
ContentProducer
  -> ContentDocument

PresentationPlanner
  -> PresentationPlan

Renderer
  -> HTML / Markdown / Workbench

Harness
  -> ContentDocument
```

最终调用关系：

```text
Harness
→ ContentDocument
→ PresentationPlanner
→ PresentationPlan
→ Renderer
→ HTML
```

每一层都可以单独替换。

### 16.5 特征开关与执行隔离

实现时预留：

```text
harness_mode
presentation_mode
renderer_mode
```

用于在旧路径和新路径之间切换，但避免双写权威状态。

原则：

- 可以双读对比
- 不能双写权威状态
- 新路径先输出预览产物
- 效果确认后再成为默认路径

### 16.6 评估与退出条件

先实现，再观察。

评估维度：

- 页面可读性
- 模块组合合理性
- 空值状态清晰度
- 引用可追溯性
- 图表真实性和可审计性
- 搜索与渲染契约稳定性
- 替代和迁移成本

如果效果不达预期：

- 优先替换低耦合层
- 避免推翻高成本契约
- 用接口切换，不用全量重写

### 16.7 当前决策

按当前方案实施。  
先做可运行纵切。  
通过具体效果决定后续优化或切换。  
实现时避免与旧主路径严重耦合。

## 17. 高替代成本核心边界

高替代成本的对象需要尽早确定，但不是所有对象都值得成为权威状态。

> **适用范围（2026-09-24 按代码补注）**：§17 描述的是生产调查域 `domain/investigation` 的建模选择。
> CLI 与离线演示使用的 `domain/opinion` 按 canonical design §8.2，把 `Claim`、
> `StakeholderPosition`、`Narrative` 保留为 `OpinionSearchState` 的权威对象。
> 两套领域当前并行存在，本节结论只对前者成立。

### 17.1 应冻结为权威状态

```text
InvestigationRequest
EventProfile
ResearchPlan
Issue / Component
SourceVersion
SourceRelation
Evidence
Finding
Review
ResourceUsage / Budget usage
State revision
```

这些对象决定了：

- 调查目标
- 证据来源
- 事实边界
- 判断和审查
- 恢复和审计

### 17.2 应降级为派生视图

```text
ActorView
PositionView
DemandView
ResponseView
CoverageMatrix
覆盖与 next-action constraint
ModuleInstance
Metric
PagePlan
PresentationPlan
ContentDocument
```

这些对象应能从权威状态重建。

原则：

- 可以持久化用于诊断和性能
- 不能成为第二事实源
- 不能单独修改后绕过 Reducer
- 渲染层失效不应影响权威状态

### 17.3 不单独作为权威对象的语义

以下概念先不单独作为权威实体：

```text
Statement
Position
Demand
Response
```

建议先通过 Finding 的语义字段或派生视图表达：

```text
Finding.kind
Finding.stakeholder
Finding.stance
Finding.stance_target
Finding.response
Finding.covered
Finding.uncovered
Finding.coverage_reason
```

Actor 先作为派生 ActorView。  
只有在真实实现证明需要稳定主体 ID 后，再升级为权威 Actor。

### 17.4 必须冻结的语义

```text
单写者状态提交
Evidence 到不可变正文的定位
Finding 的 evidence-linked 约束
Review 与 Finding hash 绑定
SourceRelation 对独立性的影响
provider_failure 不等于 not_found
公开网页样本不推断全网热度或公众情感比例
```

### 17.5 版本与迁移

必须版本化：

```text
content_contract_version
module_registry_version
presentation_contract_version
state_schema_version
execution_profile
content_revision
```

高成本对象变更时：

- 必须提供迁移或兼容策略
- 不能通过静默重建改变已发布含义
- 旧版本只读保留
- 新版本显式升级

### 17.6 当前判断

当前方案方向合理。  
高成本部分需要收敛：

- 权威对象保持最小
- 语义视图按需派生
- 渲染和 Skill 不进入权威状态
- 先实现，再评估
- 用接口隔离，控制替换成本


## 18. 决策确认记录

用户已同意决策清单 D1-D25 的全部推荐。其中角色集相关三条已被 2026-09-21 决策取代
（见 `opinion_search_agent/archive/harness-pipeline/README.md`），其余仍然有效。

关键确认：

```text
权威状态最小化
Actor / Position / Demand / Response 先作为派生视图或 Finding 字段
Module / Metric / PagePlan / PresentationPlan / ContentDocument 为派生对象
全局 Checkpoint 唯一权威
Review 强制（现由 ConsolidationValidator + finish 校验实现）
Budget 与 publication reserve（现由 Budget + 2/3 模型调用保留段实现）
HTML 同时支持在线工作台和自包含静态导出
渲染 LLM 不进入主框架
Presentation Skill 只输出 PresentationPlan JSON
ModuleRegistry 包含核心 + 社会舆情 + 娱乐舆情
GenericModule 正式开放
风险 / 趋势 / 建议模块正式开放并标注分析性
无平台数据时情感 / 热度 / 平台分布标 unavailable
保留旧路径只读兼容
更新 canonical design、蓝图和实现记忆
```

已被取代，不再实施：

```text
角色集为 Controller / ResearchAgent / Analyst / Reviewer
Planner 并入 Controller
Analyst 单角色内部两阶段
```

## 19. 搜索边界：不自研爬虫

### 19.1 明确不做

```text
通用爬虫
代理池
反爬绕过
浏览器集群
大规模网页抓取
通用搜索引擎索引
网页排名模型
向量数据库
跨事件知识库
```

### 19.2 使用公开 API

搜索和读取基于：

```text
Brave Search API
Jina Reader API
本地已保存正文
本地 FTS
```

不在搜索基础设施上重新造轮子。

### 19.3 搜索质量属于 Agent / Harness

需要 Harness 负责的是：

```text
Query planning
Issue / source-role coverage
Query dedup
Source dedup
Repost / excerpt / followup relation
Saturation detection
Stop conditions
Evidence extraction
Finding dedup / compression
```

不需要 Harness 负责的是：

```text
网页抓取
页面解析引擎
搜索引擎排序
爬虫调度
反爬对抗
```

### 19.4 原则

搜索是 Agent 的工具，不是产品核心。

如果公开 API 在限定范围内找不到，系统应该输出：

```text
not_found
unavailable
partial
```

而不是为了填满报告去建设爬虫基础设施。

### 19.5 当前方向

继续使用公开 API。  
将质量改进集中在：

```text
计划的查询方向设计
搜索覆盖记录与未尝试方向提示
证据抽取与 Evidence → Finding 转化率
Review 与 finish 闸门的判定质量
```

而不是：

```text
抓更多页面
写更复杂爬虫
维护代理和反爬
```

## 20. 结构化输出边界

结构化输出不是目标。  
结构化输出只用于 Harness 必须执行的机器决策。

### 20.1 需要最小结构化的内容

```text
Issue / Component
required / optional
source_goals
预算和停止条件
证据 ID
Review verdict
状态更新 Proposal
```

这些字段影响：

- 覆盖调度
- 预算控制
- 状态提交
- 审查门禁

### 20.2 不应强制结构化的内容

```text
事件理解
调查假设
搜索策略
查询族设计
来源判断
分析叙述
风险解释
```

这些内容应该允许 Agent 在决策的自由文本字段里用更自由的方式表达，
只对 Harness 必须执行的机器判断保留最小结构化（见 §20.1）。

### 20.3 计划调用的职责边界

计划调用（`investigation/manager.py` 的 `_propose_plan`）不输出完整 query plan，
只输出最小结构：

```text
PlanProposal
  弱结构：
  - subject / region / aliases
  - clarification（事件无法识别时的中文问题，每轮最多三条）
  - facet_rationale

  questions[]（事件可识别时 3–6 条）
  最小结构：
  - question
  - required
  - covers（覆盖的原始用户问题）
  - components（顿号 / 分号 / 「以及」枚举出的子部分）
```

具体 query 由 Agent 在 Loop 内自行生成，不由计划调用预先写死。
计划调用在 AgentLoop 之外，只有一次重试，之后 run 直接 failed。

### 20.4 Agent 的搜索职责

Agent 在每一步决定：

```text
查询词
查询方向（purpose：original / positions / independent /
          official_response / event_response / followup）
来源选择
读取优先级
切换策略
停止时机
```

它记录实际执行过的 query（`SearchAttempt`，含 purpose、page、outcome、
target_gap、discovery_mode），供 Harness 去重和诊断。

### 20.5 Harness 的职责

Harness 只从最小结构里读取：

```text
Issue 覆盖与终态处置
搜索方向覆盖（unattempted_directions / failed_directions）
query / page 去重
预算消耗
Review 状态与结论冻结
```

不要求预先生成查询树、查询矩阵或复杂 DSL。

### 20.6 原则

```text
结构用于约束边界，不用于替代内容。
模型专注内容时，Harness 用少量契约做调度。
```
