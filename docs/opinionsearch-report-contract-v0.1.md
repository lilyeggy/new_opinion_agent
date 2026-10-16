# OpinionSearch Report Contract v0.1

> 状态：草案  
> 范围：公开网页舆情搜索 Agent 的报告内容契约、模块契约与渲染接口  
> 核心原则：内容与渲染分离；事实可追溯；空值合法；模块可组合；图表由程序计算

## 0. 文档定位

这份契约回答五个问题：

1. 一份高质量的舆情报告由哪些信息组成
2. 这些信息之间是什么关系
3. 哪些信息必须有证据
4. 哪些信息可以动态组合
5. 用户如何查看和追溯

它不是 HTML 模板，也不是页面代码。  
它定义的是语义内容、状态、证据和审查约束。  
HTML、工作台、Markdown、PDF 都只是这份契约的渲染结果。

## 1. 设计原则

1. Content Contract 与 Presentation Contract 分离
2. 事实性内容必须来自 reviewed、evidence-linked 的 Finding
3. 模块是语义单位，不是视觉组件
4. 固定 Shell、注册模块、GenericModule 三层组合
5. 缺失是合法状态，不允许为了视觉完整而编内容
6. 图表与比例必须由程序从结构化状态计算
7. 模型不能自由生成 HTML、CSS、JavaScript
8. 契约必须版本化，渲染方案绑定内容 revision

## 1.1 权威状态与派生视图（最终决定）

权威状态保持最小化：

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
ResourceUsage
State revision
```

以下对象作为派生视图，不作为第二事实源：

```text
ActorView
PositionView
DemandView
ResponseView
CoverageMatrix
GapAudit
ModuleInstance
Metric
PagePlan
PresentationPlan
ContentDocument
```

Statement / Position / Demand / Response 先通过 Finding 的语义字段或派生视图表达。  
Actor 先作为 ActorView。  
只有真实实现证明需要稳定主体 ID 后，才升级为权威 Actor。

## 2. 内容实体模型

### 2.1 Event

```text
Event
├── event_id
├── subject
├── aliases
├── event_type / facets
├── time_scope
├── region
├── summary
├── status
└── limitation_notes
```

### 2.2 Issue

```text
Issue
├── issue_id
├── question
├── required
├── origin_questions
├── components[]
├── status
├── note
└── evidence_ids[]
```

### 2.3 Component

```text
Component
├── text
├── status
├── evidence_ids[]
└── note
```

### 2.4 Actor（派生视图）

```text
Actor
├── actor_id
├── name
├── aliases[]
├── actor_type
│     official / organization / media / expert / public / other
├── role_in_event
└── evidence_ids[]
```

### 2.5 Statement / Position / Demand（Finding 语义视图）

```text
Statement
├── statement_id
├── actor_id
├── issue_id
├── text
├── claim_kind
│     fact / attributed / interpretation / request
├── stance
│     support / oppose / conditional / unclear
├── stance_target
├── event_time
└── evidence_ids[]
```

### 2.6 Response（Finding 回应覆盖视图）

```text
Response
├── response_id
├── actor_id
├── issue_id
├── response_type
│     direct / partial / non_substantive / not_found / unknown
├── covered[]
├── uncovered[]
├── coverage_reason
└── evidence_ids[]
```

### 2.7 Source / SourceVersion / SourceRelation

```text
Source
└── document_key

SourceVersion
├── version_id
├── document_key
├── url / final_url
├── title
├── role
│     original / reporting / commentary / official / unknown
├── published_at
├── fetched_at
├── content_hash
├── artifact_ref
├── duplicate_of
└── origin_url

SourceRelation
├── relation_id
├── source_version_id
├── related_version_id
├── relation
│     same_text / repost / excerpt / followup
├── basis_evidence_ids[]
└── explanation
```

### 2.8 Evidence

```text
Evidence
├── evidence_id
├── source_version_id
├── excerpt
├── locator
├── start / end
└── verified
```

### 2.9 Finding / Review

```text
Finding
├── finding_id
├── issue_id
├── text
├── kind
│     fact / attributed / interpretation / request
├── stakeholder
├── stance / stance_target
├── response / covered / uncovered / coverage_reason
├── event_time
├── evidence_ids[]
├── contradicting_ids[]
├── module_fields[]
└── active

Review
├── finding_id
├── finding_hash
├── verdict
│     supported / partial / contradicted / insufficient
├── reason
├── model
└── reviewed_at
```

### 2.10 Module / Metric

```text
Module
├── module_id
├── semantic_type
├── state
├── data_bindings[]
├── evidence_bindings[]
├── review_bindings[]
├── visual_encodings[]
└── empty_state

Metric
├── metric_id
├── name
├── value
├── denominator
├── inclusion
├── metric_def_version
└── members[]
```

## 3. 内容关系

```text
Event
 ├── Issue
 │    ├── Component
 │    ├── Finding
 │    │    ├── Evidence
 │    │    └── Review
 │    └── Response
 ├── Actor
 │    ├── Statement
 │    ├── Position
 │    └── Demand
 └── Source
      └── SourceVersion
           ├── Evidence
           └── SourceRelation

Module
 └── projects Finding / Evidence / Source / Metric
```

关系原则：

- Event 是根
- Issue 是调查维度
- Actor 是主体
- Statement / Position / Demand 必须归因
- Response 指向具体 Issue
- Evidence 是最小可追溯事实单元
- Finding 是 Issue 级 reviewed 判断
- SourceRelation 影响来源独立性
- Module 只做投影，不产生新事实

## 4. 模块系统

报告由三层组成：

### 4.1 固定 Shell

固定 Shell 提供稳定导航和阅读顺序，例如：

```text
事件总览
事件脉络
主体与关系
议题与争议
观点与立场
诉求与信号
回应与处置
进展与影响
风险与趋势
证据与来源
限制与未决
```

Shell 不是必填清单。  
没有内容的 Section 可以折叠、省略或只显示空值状态。

### 4.2 注册模块

只有注册模块可以进入正式报告。  
每个模块由 ModuleRegistry 管理，并由 ModuleContract 描述。

### 4.3 GenericModule

GenericModule 用于现有模块装不下的事件专项内容。

```text
GenericModule
├── title
├── summary
├── findings[]
├── citations[]
├── limitations
└── status
```

GenericModule 仍必须遵守：

- 事实 evidence-linked
- 对外 Finding reviewed
- 不能生成任意 HTML
- Renderer 使用统一结构渲染

## 5. ModuleContract

```text
ModuleContract
├── semantic_type
├── title
├── semantic_domain
├── applies_when
├── presence
│     required / optional / conditional / not_applicable
├── required_fields[]
├── optional_fields[]
├── data_bindings[]
├── evidence_requirements
│     min_evidence
│     required_source_roles[]
│     original_source_required
│     reviewed_finding_required
├── review_gate
│     none / required / supported_only
├── visual_encodings[]
├── selection_rules[]
├── fallback_visual
├── empty_state
├── priority
└── version
```

字段绑定结构：

```text
FieldBinding
├── field
├── data_type
├── source_entity
├── source_field
├── required
├── evidence_required
├── review_required
└── fallback
```

## 6. 核心 ModuleRegistry

| semantic_type | semantic_domain | presence | 主要数据来源 | 允许视觉 | 空值策略 |
|---|---|---|---|---|---|
| event-summary | 事件总览 | required | Event / Finding | cards / text | not_found |
| current-judgments | 事件总览 | conditional | reviewed Finding | cards | insufficient |
| key-limitations | 事件总览 | conditional | Diagnostics / State | cards / text | omitted |
| event-timeline | 事件脉络 | conditional | Evidence / Finding | timeline / list / table | not_applicable |
| material-distribution | 事件脉络 | optional | SourceVersion | bar / table | unavailable |
| source-structure | 传播与来源 | optional | SourceVersion | donut / bar / table | insufficient |
| source-relations | 传播与来源 | conditional | SourceRelation / Evidence | graph / table | unavailable |
| stakeholders | 主体与关系 | conditional | Actor / Statement | cards / matrix | not_found |
| issue-map | 议题与争议 | required | Issue / Finding | cards / comparison-table | not_found |
| claim-matrix | 议题与争议 | conditional | Finding / Evidence | comparison-table / matrix | insufficient |
| position-matrix | 观点与立场 | conditional | Actor / Position / Finding | position-matrix | insufficient |
| debate-comparison | 观点与立场 | conditional | Finding / Evidence | comparison-table / cards | insufficient |
| narrative-framing | 观点与立场 | optional | Finding / Source | cards / text | omitted |
| demands | 诉求与信号 | optional | Statement / Position | cards / list | not_found |
| attitude-signals | 诉求与信号 | optional | Statement / Finding | position-matrix / cards | insufficient |
| sentiment-distribution | 诉求与信号 | optional | Metric | donut / bar | unavailable |
| official-response | 回应与处置 | conditional | Actor / Response | cards / table | not_found |
| response-coverage | 回应与处置 | conditional | Response / Finding | comparison-table | insufficient |
| actions-taken | 回应与处置 | conditional | Finding / Evidence | cards / timeline | not_found |
| followup | 进展与影响 | optional | Finding / Source | timeline / cards | not_found |
| impact | 进展与影响 | optional | Finding / Evidence | cards / text | insufficient |
| risk-assessment | 风险与趋势 | optional | Finding / Analysis | risk-matrix / cards | omitted |
| trend-forecast | 风险与趋势 | optional | Finding / Analysis | trend-chart / cards | omitted |
| recommendations | 建议 | optional | Finding / Analysis | action-cards / list | omitted |
| evidence-index | 证据与来源 | required | Evidence / SourceVersion | evidence-drawer / table | unavailable |
| diagnostics | 系统 | optional | Runtime State | cards / table | omitted |

### 6.1 社会舆情扩展模块

| semantic_type | semantic_domain | presence | 说明 |
|---|---|---|---|
| policy-background | 政策与制度 | optional | 政策背景、制度依据、适用范围 |
| public-interest | 公共利益 | optional | 对公众、群体、区域的影响 |
| official-accountability | 责任与问责 | optional | 责任主体、追责、整改 |
| regulatory-response | 监管回应 | optional | 监管介入、调查、处置 |
| regional-impact | 区域差异 | optional | 地区执行差异与群体差异 |

### 6.2 娱乐舆情扩展模块

| semantic_type | semantic_domain | presence | 说明 |
|---|---|---|---|
| artist-statement | 艺人声明 | optional | 本人、工作室、律师声明 |
| agency-response | 经纪公司 | optional | 经纪公司、制作方回应 |
| brand-sponsor-response | 品牌与赞助 | optional | 品牌方、合作方、赞助方反应 |
| platform-response | 平台与节目 | optional | 平台、节目组、主办方回应 |
| fandom-reaction | 粉丝与圈层 | optional | 只记录公开可归因行为，不推断整体粉丝态度 |
| legal-rumor-check | 法律与辟谣 | optional | 法律行动、辟谣、事实核查 |
| commercial-impact | 商业影响 | optional | 代言、商务、档期、作品影响 |
| career-impact | 职业影响 | optional | 作品、出镜、行业影响 |

## 7. 空值状态

```text
not_applicable   本事件不适用
not_found        搜索后范围内没有
insufficient     找到但不足以支持结论
unavailable      供应商失败或来源不可访问
pending          尚未调查
omitted          可选模块无内容，直接省略
```

规则：

- not_applicable 默认隐藏，例外是用户明确关心的维度
- not_found 只在用户问题或必答模块中显示
- insufficient 显示当前缺什么
- unavailable 必须说明失败原因
- pending 只用于运行中页面
- omitted 不占视觉位置

## 8. 视觉编码

### 8.1 白名单

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

### 8.2 数据形态到视觉编码

| 数据形态 | 推荐编码 | 允许编码 |
|---|---|---|
| 文本与判断 | cards / text | cards / text |
| 时序事件 | timeline | timeline / list / table |
| 主体与议题 | position-matrix | matrix / comparison-table |
| 主张对照 | comparison-table | table / cards |
| 类别分布 | donut / bar | donut / bar / stacked-bar |
| 趋势 | trend-chart | line / area / bar |
| 关系 | relation-graph | graph / table |
| 证据 | evidence-drawer | drawer / table |

### 8.3 图表规则

- 图表数据只能由程序生成
- 必须有明确 denominator
- 必须有 inclusion 口径
- 必须可下钻到 members
- 观点占比只能称为样本观点分布，不能称为公众总体态度
- 公开网页样本不能推断全网热度
- 没有平台数据时，情感分布和热度趋势标 unavailable

## 9. 证据、引用与审查

### 9.1 证据要求

```text
事实性陈述   -> 直接 Evidence
归因性陈述   -> 明确 speaker + Evidence
数字/日期    -> 逐项 Evidence 支撑
官方回应     -> 原始声明或权威来源
结果与执行   -> 区分计划与已执行
分析/建议    -> 明确标注分析性，不写成事实
```

### 9.2 审查要求

```text
ready 模块中的每条对外 Finding 必须有当前 Review
核心结论只允许 supported Finding
partial / contradicted / insufficient 不得进入 ready 模块
未审查内容只能进入 provisional 状态
```

### 9.3 来源独立性

- 转载不能作为独立验证
- 同文、摘录、后续关系由模型在 reflect 中提出，由程序校验（两个端点必须是已知来源版本，且每条 basis evidence 必须来自这两个版本之一）
- 来源角色由页面的实际发布关系判断
- 域名只提供线索，不能单独决定角色

## 10. 动态组合与版本

### 10.1 内容 revision

报告投影必须绑定：

```text
content_revision
report_contract_version
module_registry_version
presentation_contract_version
```

### 10.2 动态规则

- Shell 版本固定
- ModuleRegistry 版本固定
- 模块可以增删、排序、折叠
- Module 可以由程序选择
- Agent 可以提出模块方向
- 新模块必须映射到注册模块或 GenericModule
- 模型不能生成组件名、HTML、CSS、脚本

## 11. 用户查看与追溯

用户应能看到：

- 每个判断的引用角标
- Evidence 原文与上下文
- SourceVersion 的发布时间、获取时间、来源角色
- 原始、转载、摘录、后续关系
- Review 状态与 verdict
- 模块状态
- 搜索覆盖与查找截止
- 版本变化与上一完整版本
- 未决问题和限制

## 12. 验收标准

1. 所有 required 模块有 state 或明确 empty_state
2. 所有对外事实都能追溯到 Evidence
3. ready 模块不包含 unreviewed Finding
4. 比例图具备可审计 denominator
5. GenericModule 可以正常渲染
6. partial / empty / unavailable 显示正确
7. 搜索覆盖与引用可追溯
8. 内容 revision 变化时，PresentationPlan 失效并可重建
9. Renderer 不接受模型生成的 HTML
10. 无平台数据时不生成全网热度或情感比例

## 13. 最终形态决策

本契约按最终目标形态定义，不以 V1 做功能裁剪。后续版本号只表示契约兼容版本和实现顺序，不表示模块范围。

1. Shell 分组采用本文件。
2. ModuleRegistry 采用完整模块集：核心模块 + 社会舆情扩展 + 娱乐舆情扩展。
3. 情感分布、热度趋势、平台分布等模块在无平台数据时显示 unavailable，不得推断。
4. HTML 输出同时支持自包含静态导出和在线工作台；两者共用 Content Contract 和 PresentationPlan。
5. GenericModule 正式开放。
6. risk-assessment / trend-forecast / recommendations 正式开放，必须标注为分析性内容。
7. Presentation Skill 正式作为独立表现层能力，只输出 PresentationPlan JSON；Renderer 确定性执行。
8. 所有模块都必须支持 applies_when、empty_state、visual_encodings、evidence_gate、review_gate。
9. 权威状态保持最小化，Actor / Position / Demand / Response / Module / Metric / PagePlan / PresentationPlan 为派生视图。
