# OpinionSearch 待决策清单

> 状态：已确认（用户同意全部推荐）；**D7–D11 已于 2026-09-21 被取代**  
> 用途：把需要产品或架构判断的事项集中列出  
> 回复方式：同意编号，或指出编号和修改意见
>
> **2026-09-24 按代码校正**：D7–D11 确认的「Controller / ResearchAgent / Analyst / Reviewer」
> 多角色流水线路线，已于 2026-09-21 评估后否决并归档，决策记录见
> `opinion_search_agent/archive/harness-pipeline/README.md`。当前实现是唯一 Runtime AgentLoop，
> 不划分角色。本清单其余条目仍然有效：D5（全局 Checkpoint 唯一权威）成立；
> D12（强制 Review）由 `ConsolidationValidator` 与 finish 校验落地；
> D13（发布保留段）由 `Budget` 的模型调用 2/3 阈值与 `ConsolidationValidator` 落地。

## A. 高替代成本核心

### D1 权威状态是否最小化

选项：

```text
A. 只保留最小权威状态，语义视图派生
B. Statement / Position / Demand / Response / Actor 也作为权威实体
```

我的建议：A。

最小权威状态建议：

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

派生视图建议：

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

### D2 Actor 是否先作为派生视图

选项：

```text
A. 先 ActorView，等需要稳定主体 ID 再升级
B. 一开始就建立权威 Actor
```

我的建议：A。

### D3 Statement / Position / Demand / Response 是否并入 Finding

选项：

```text
A. 先作为 Finding 语义字段或派生视图
B. 独立权威对象
```

我的建议：A。

### D4 Module / Metric / PagePlan / PresentationPlan 是否派生

选项：

```text
A. 派生，不作为第二事实源
B. 部分写入权威状态
```

我的建议：A。

### D5 Checkpoint 模型

选项：

```text
A. 全局 Checkpoint 唯一权威，task 状态内嵌
B. 全局 Checkpoint + 独立 ResearchTask Checkpoint
```

我的建议：A，首版避免双状态源。后续并行时再评估局部 Checkpoint。

### D6 旧数据兼容

选项：

```text
A. 旧 run 只读保留，新架构使用新 execution_profile
B. 旧 run 迁移后继续 resume
```

我的建议：A，降低首版迁移复杂度。

## B. 搜索 Harness

### D7 角色集

> **已取代（2026-09-21）**：不划分角色，唯一 Agent 每步提交一个决策。

选项：

```text
A. Controller / ResearchAgent / Analyst / Reviewer
B. 更少角色
C. 更多角色
```

我的建议：A。

### D8 Planner 是否并入 Controller

> **已取代（2026-09-21）**：无 Controller。计划是 AgentLoop 之外的一次模型调用
> （`investigation/manager.py` 的 `_propose_plan`），Loop 内的规划以
> `ReflectDecision.add_questions` 继续。

选项：

```text
A. 并入，Plan 是 Controller 的动作
B. 独立 Planner 角色
```

我的建议：A。

### D9 Analyst 是否内部两阶段

> **已取代（2026-09-21）**：无 Analyst 角色。证据分析是 `reflect` 决策，
> 一次提交 `findings` / `assessments` / `retirements` / `source_relations`。

选项：

```text
A. 一个 Analyst 角色，内部 Evidence Curation + Opinion Synthesis
B. 独立 Curator 和 Analyst 两个角色
```

我的建议：A。

### D10 Controller 自主程度

> **结论保留，主体更正**：由唯一 Agent（而非 Controller）在合法动作空间内自主选择下一步。

选项：

```text
A. Controller 在合法动作空间内自主选择下一步
B. 程序固定下一步
```

我的建议：A。

### D11 Scheduler 与 Controller 的关系

> **已取代（2026-09-21）**：无 Scheduler 与 Controller。覆盖建议由
> `required_next_action` 与 `memory.coverage` 提供，硬约束由 `Validator` 执行。

选项：

```text
A. Scheduler 给建议，Controller 选择
B. Scheduler 强制决定
```

我的建议：A，但硬门禁由 Harness 执行。

### D12 Review 门禁

选项：

```text
A. Analyst 输出后强制 Review，Review 通过后才进入 ready
B. Review 可选
```

我的建议：A。

### D13 Budget 与 publication reserve

选项：

```text
A. 统一 ResourceLedger + publication reserve
B. 沿用现有独立预算
```

我的建议：A。

## C. 输出、渲染与 Skill

### D14 HTML 输出形态

选项：

```text
A. 在线工作台 + 自包含静态 HTML
B. 只做静态 HTML
C. 只做在线工作台
```

我的建议：A。

### D15 渲染 LLM 是否进入主框架

选项：

```text
A. 不进入，主框架只产出结构化内容
B. 作为主框架角色
C. 作为主框架外可选能力
```

我的建议：C，实现上先 A，后续再加可选 PresentationPlanner。

### D16 Presentation Skill 何时引入

选项：

```text
A. 先做确定性 Renderer，再引入 Skill
B. Renderer 与 Skill 同时做
```

我的建议：A。

### D17 Presentation Skill 输出

选项：

```text
A. 只输出 PresentationPlan JSON
B. 允许输出 HTML
```

我的建议：A。

### D18 ModuleRegistry 范围

选项：

```text
A. 核心模块 + 社会舆情扩展 + 娱乐舆情扩展
B. 只做核心模块
C. 只做社会舆情
```

我的建议：A。

### D19 GenericModule

选项：

```text
A. 正式开放
B. 暂不开放
```

我的建议：A。

### D20 风险、趋势、建议模块

选项：

```text
A. 正式开放，标注分析性内容
B. 暂不开放
```

我的建议：A。

### D21 无平台数据时的情感 / 热度 / 平台分布

选项：

```text
A. 显示 unavailable，不推断
B. 用公开网页样本推算
```

我的建议：A。

## D. 验收与迁移

### D22 评估基线

选项：

```text
A. 对比现有单 Agent 输出
B. 只内部评审
C. 设定量化阈值
```

我的建议：A + C。

### D23 评估事件类型

选项：

```text
A. 一个社会舆情事件 + 一个娱乐舆情事件
B. 只用一个事件
C. 更多事件
```

我的建议：A。

### D24 旧路径是否保留

选项：

```text
A. 保留只读兼容，新路径先输出预览
B. 直接替换旧路径
```

我的建议：A。

### D25 文档更新

选项：

```text
A. 更新 canonical design、蓝图、实现记忆
B. 只更新本决策清单
```

我的建议：A。


## 确认记录

用户已同意 D1-D25 全部推荐。

## E. 项目边界

### D14 项目边界与产品冻结（2026-10-13 确认）

决定：

```text
A. 只深做第①层 Agent Harness/Runtime 与第②层 Tool/MCP/Context/Run-scoped Memory
   investigation/、report_contract/、web/、app/ 冻结新功能，只做缺陷修复
```

评测口径：采用“公开可验证问答集 + 离线脚本打分”。脚本位于 `scripts/`，不建设 dashboard、数据版本平台或 judge 服务，仍符合设计文档 §2.2 对 Evaluation 层的排除。

### D15 搜索约束透传（2026-10-13 已实施）

旧 opinion 路径将 TaskFrame 的时间窗口与语言透传到 Brave；域名约束仍后过滤。执行 profile 已升级，旧 run 只读保留。详见实施记忆 2026-10-13 节。
