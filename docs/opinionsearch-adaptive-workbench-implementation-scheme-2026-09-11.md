# OpinionSearch 事件工作台：实施方案（依据 implementation-plan-2026-09-11 生成）

> 日期：2026-09-11。
> 性质：本文是 `docs/opinionsearch-adaptive-workbench-implementation-plan-2026-09-11.md`（下称"实施指南"）的执行展开，供后续执行者（人或底层模型）据此直接完成代码修改。
> 本文只定义方案、范围、顺序与验收标准，不声明任何能力已实现。所有新增能力在对应阶段验证完成前均为待实施。
> 依据文件：仓库协作约定 `CLAUDE.md`、唯一 canonical design `docs/public-opinion-search-agent-design.md`、实现记录 `docs/opinion-search-agent-implementation-memory.md`（§20）、执行计划 `docs/opinion-search-agent-5-day-plan.md`、交互参考 `docs/design/professional-event-workbench.reference.html`。

---

## 1. 目标、范围与硬性约束

### 1.1 目标

把现有"顺序报告块"页面升级为**按事件组织的研判工作台**：统一工作台框架 + 三个主视图（事件总览 / 报道对照 / 议题与核查）+ 证据面板，内容随事件属性（facets）、用户问题、调查阶段与证据条件自适应。模型提出调查与内容建议；**程序约束页面结构、证据、统计、版本和交互**。

最终交付路径（实施指南 §14）：
**提交事件 → 必要澄清 → 看见调查与适配内容展开 → 比较报道与议题 → 核查原文 → 补查具体问题 → 对比前后判断 → 下载本版报告。**

### 1.2 硬性约束（违反任一条即视为偏离方案）

1. 继续 Python 显式单 Agent async loop、现有 HTTP 服务、原生 HTML/CSS/ES modules。**不引入 React/Vue/Next.js，不新建第二套后端/Runtime，不加 CLI 产品流程。**
2. 继续复用 Brave、Jina、不可变正文、事件内 FTS5/BM25、Processor → Delta → Reducer、checkpoint 与恢复。
3. 不采集社交平台、不做全网实时监测/营销/发布；不加多 Agent、多租户、云平台、分布式调度、向量数据库。
4. 保留 Markdown 下载与旧报告只读能力；不建 PDF/Word/分享系统。
5. 不修改、复制或引用 `archive/`；不清理既有工作区与运行产物；不运行 `git clean` / `git reset --hard`。
6. 模型不得输出 HTML/CSS/脚本/组件名/像素布局/统计百分比；前端只渲染白名单模块与结构化字段。
7. 领域新增字段：能安全兼容旧数据用显式默认；无法解释旧语义则升级格式并明确拒绝不兼容续跑；**不自动把旧未完成 run 转换后继续**。
8. 每个新字段必须有生产者、验证者、消费者和测试；每个重要实现节点同步更新实现记录（只追加已验证事实）。

---

## 2. 代码基线（已静态核对的修改落点）

以下路径均已确认存在于 `opinion_search_agent/`（相对于 `src/opinion_search/`）：

| 职责 | 文件 | 本轮角色 |
|---|---|---|
| 调查领域模型 | `domain/investigation/models.py` | 扩展实体与约束（EventProfile、EventNode、SourceRelation 等），不建平行系统 |
| 校验/提交/结束 | `domain/investigation/engine.py` | 扩展 Validator/Resolver/Processor；明显膨胀后再拆策略文件 |
| 上下文组织 | `investigation/context.py` | Compiler 增补问题/缺口/预算注入，不塞布局代码 |
| 动作执行 | `investigation/service.py` | 保留执行边界；检索/重试/预算计费在此层 |
| 正文/索引/锁/预算 | `investigation/storage.py` | Corpus、CaseLock、Budget（含暂停累计用时修复）、verify_evidence |
| 草稿/任务/版本 | `investigation/manager.py` | Manager（含 `_publish` latest 指针修复、update 契约扩展、幂等创建） |
| 报告与差异 | `investigation/report.py` | 在其邻近新增工作台投影，不从 Markdown 反向解析 |
| HTTP 与 SSE | `web/server.py` | 扩展 `/api/investigations`，保留既有语义 |
| 前端 | `web/assets/{app,api,report,evidence,ui}.js`、`style.css`、`web/investigation.html` | 渐进拆分改造；新增 `workbench.js`、`web/assets/modules/` |
| 测试基线 | `tests/investigation/`（含 `cases/registry.json`）、`tests/e2e/test_investigation_web.py` | 保留基线，新增契约测试 |

已确认的四个缺陷锚点（先写可复现检查，再修）：
- `api.js` 的 `source.onerror` 直接 close，`app.js` 进度订阅传空结束回调 → SSE 断流无恢复闭环。
- `report.py` 用 `source.duplicate_of is None` 设置 `independent` → "未发现重复"被当成独立来源。
- `report.js` 的 evidenceChips 直接显示 `evidence_id` → 内部 ID 泄漏。
- `Manager._publish` 对 completed 与 partial 都更新 `latest.json`；`Budget.pause()` 清空 `started_at`，snapshot 只计本次 started_at 后时间 → partial 掩盖上一完整结果、暂停丢失累计用时。

注意：`tests/investigation/cases/registry.json` 目前是 10 个 blocked 槽位，不是已完成的评测集。

---

## 3. 数据契约规格（字段级，供直接实现）

按实施指南 §6.2，**第一阶段只实现总览、规则对照、时间线、证据所需字段**，其余标记 pending。所有新实体放 `domain/investigation/models.py`，经 `engine.py` 校验提交，遵循 Processor → Delta → Reducer 链路。

| 契约 | 最小字段 | 生产者 → 验证者 → 消费者 | 阶段 |
|---|---|---|---|
| **EventProfile** | `facets: list[facet]`（取值 ∈ {rule_change, service_change, billing_remedy, investigation_correction, general}）、`rationale`、`question_refs`、`evidence_refs`、`config_version` | 模型建议 → engine 确认 facets 在允许集且不删除用户必答问题 → workbench 投影 | P2 |
| **EventNode** | `occurred_at`/`occurred_range`、`time_precision`、`description`、`finding_refs`、`evidence_refs`、`time_basis` | 模型 reflect 提议 → Processor 校验（不得纯靠标题生成）→ 总览时间线视图 | P2 |
| **SourceRelation** | `source_version_endpoints`、`relation_type`（duplicate/reprint/quote/independent_signal/unknown）、`supporting_evidence`、`review_state` | reflect 提议 → Processor 校验（unknown 合法）→ 报道对照视图 | P1 起逐步 |
| **QuestionComponent / ResponseAssessment** | 组件拆分、`response_finding_ref`、`coverage`（直接回答/部分回答/涉及但未实质回答/范围内未发现/无法判断）、`reason`、`evidence_refs`、`uncovered_check`（截止时间、定向查询记录、失败清单） | 扩展既有 Finding 回应字段 → Processor → 议题与核查视图 | P1 最小、P3 完善 |
| **SearchTask / CoverageRecord** | `task_id`、`issue_id`、`origin_question_refs`、`purpose`、`discovery_mode`、`query/constraints/page`、`target_gap`、`success_observation`、`outcome`、`related_candidate/source/evidence_ids`、`membership_policy_version` | service.py 执行层写入 → 可从提交记录确定性重建 → 缺口选择与覆盖展示 | P3 |
| **CorpusManifest** | 成员清单、发现渠道、纳入/排除理由、去重与范围版本 | 程序维护 → 统计口径核对 → 图表下钻 | P4 |
| **WorkbenchSnapshot** | `format: "opinion-workbench/1"`、`run_id`、`state_revision`、`snapshot_id`、`generated_at`、`publication_state`、`profile`、`modules[]`、`views`、`limitations` | workbench.py 纯投影 → 一致性校验 → Web API/SSE/前端 | P1 最小、P4 完善 |
| **ModuleView** | `module_type`（白名单）、`state`（ready/provisional/insufficient/unavailable/not_applicable）、`title`、`data_refs`、`selection_rationale` | PresentationPolicy 输出 → 前端只认白名单 → 各主视图 | P1 框架、P2 facet |
| **MetricSnapshot** | `metric_def_version`、`inclusion_rules`、`filters`、`material_set_version`、`member_ids` + `member_hashes`、`numerator/denominator`、`unknown_count`、`excluded_count` | metrics.py 程序计算（模型不可写百分比）→ 图表 | P4 |
| **FollowupIntent** | `parent_run_id`、`issue_refs`、`finding_refs`、`user_text`、`trigger_source` | Manager 持久化 → 校验父版引用 → 更新 run 创建 | P3 |

关键不变量：
- `not_applicable` 不得用于隐藏用户明确问题、核心事实冲突或供应商故障。
- `provisional` 模块不得进入核心断言；审查未通过只能降级不能删除。
- 快照三版本各自独立演进：领域 `schema_version=2`、checkpoint envelope、`opinion-workbench/1`。
- 已发布结果先完整写入版本产物，再原子更新 manifest/指针；崩溃半成品不可读为正式版本。

---

## 4. Web API 扩展规格

沿用既有接口语义（创建/列表、`/{id}` snapshot、`/{id}/events` SSE、evidence、report Markdown、versions、diff、clarify/cancel/resume/update），在此基础上最小扩展：

| 扩展 | 规格 | 阶段 |
|---|---|---|
| `GET /api/investigations/{id}/workbench` | 返回一致工作台投影；支持 `snapshot_id` 读取绑定快照，**不得静默切到最新** | P1 |
| `GET .../{id}/materials?snapshot_id=&issue_id=` | 同一快照内筛选 + 有界分页；总数与列表同口径；小集合首版可随投影返回 | P4（P1 可先随投影内嵌） |
| SSE 事件增补 | 增加 workbench revision/reference 字段；旧客户端可忽略 | P1 |
| evidence 接口增补 | 增加 relation/context 字段，保留旧字段；校验证据属于所选 run/版本/快照，拒绝跨事件引用 | P1–P2 |
| update 契约扩展 | 增加可选 `issue_ids`、`finding_ids`、`client_request_id`；校验父版引用；同 key 重试返回同一创建结果（幂等仅限本地 Web 创建，不同内容重用同 key 拒绝；并发创建仍受 CaseLock 约束） | P3 |
| diff 增补 | 增加 change basis 与 comparability（口径变化单列，不只比文本） | P4 |

结构化错误：至少区分 参数无效 / 引用不存在或不属于当前版本 / 事件忙 / 格式不兼容 / 快照不可用 / 供应商失败，映射 400/404/409/503，写入契约测试冻结。

只读不收费约束：workbench GET、materials 筛选、evidence GET、SSE 重连均不得触发调查动作。浏览器渲染文本必须转义，禁止插入模型生成的可执行 HTML。

---

## 5. 阶段任务分解、依赖与验收

依赖总链：**P0 → P1 → P2 → P3 → P4 → P5**。P1 内部任务顺序为 5.2.1 → 5.2.2 → 5.2.3 → 5.2.4；P2 依赖 P1 的 ModuleView 框架；P3 的 SearchTask 依赖 P0 冻结的预算契约；P4 依赖 P2 的终态投影稳定。额度不足时的降级顺序见 5.7。

每阶段完成时按实施指南 §12 模板归档：范围、验证命令/结果、产物路径、未验证项（`pending`/`blocked`，不估算百分比）、下一阶段最小任务。

### 5.1 P0：冻结基线与输入输出契约（优先级最高，一切后续工作的前置）

| # | 任务 | 落点 | 验证 |
|---|---|---|---|
| P0-1 | 确认 cwd、`git status`，保留已有修改；记录实现入口、配置（`OPINION_INVESTIGATION_*`）、现有报告样本 | 仓库根 | 记录归档 |
| P0-2 | 为四个缺陷锚点各写一个可复现的失败检查（见 §2 锚点清单），先红后改 | `tests/investigation/` 新增测试 | 检查在当前代码上复现失败 |
| P0-3 | 验证 Budget 暂停/恢复：请求次数不重置与时间不重置是**两项独立契约**；澄清/暂停/恢复不丢已用时长 | `investigation/storage.py` Budget、`tests/investigation/test_budget_recovery.py` | 新增用例失败复现后作为 P1 修复基准 |
| P0-4 | 保存至少两个现有不同类型报告的基线（无真实材料则明确标注待补，不得虚构） | 基线目录 | 基线可被后续投影对照 |
| P0-5 | 冻结 WorkbenchSnapshot 最小字段、模块状态枚举、引用规则（§3 表格中 P1 行） | 本文件 + canonical design 同步 | 契约写入文档并有字段级测试骨架 |
| P0-6 | 同步 canonical design 与实现记录的计划入口 | `docs/public-opinion-search-agent-design.md`、实现记录 | 文档 diff 归档 |

**退出条件**：明确现有/新增字段、兼容方式、最先修复的问题及可重现结果。**本阶段不启动任何 UI 重写。**

### 5.2 P1：一个可信的公共工作台（用户价值最高）

| # | 任务 | 落点 | 步骤要点 | 验收 |
|---|---|---|---|---|
| P1-1 | 来源统计改名 + SourceRelation 最小版 | `report.py`、`domain/investigation/models.py` | 废止 `independent` 布尔用于统计；来源数量与独立验证分开；未知保持未知；旧字段保留兼容但新页不使用 | W07 相关机制测试通过；对外只显示"收录文档数/正文版本数/已识别转载数/出处未知" |
| P1-2 | SSE 断线恢复闭环 | `web/assets/api.js`、`app.js`、`web/server.py` | 连接状态三态（连接中/中断恢复中/已断开）独立于运行状态；断线先补取 snapshot，再以有界退避重连，达上限给手动重试；run ID + 页面请求令牌丢弃旧响应；依据单调 `state_revision` 拒绝过期快照 | W12；快速切换事件不被旧响应覆盖 |
| P1-3 | 引用人类可读化 | `report.js`、workbench 投影 | 局部引用序号或来源短名；内部 evidence_id 只留在程序与开发者视图 | W11 主路径；页面无内部 ID |
| P1-4 | 通用工作台投影 + 三视图 + 证据联动 | 新增 `investigation/workbench.py`；`web/assets/workbench.js`、`web/assets/modules/`（timeline、issues、coverage）；`evidence.js` 焦点处理 | 纯投影从领域 State 生成 `opinion-workbench/1` 快照；总览/报道对照/议题核查三视图；点击判断/引用/报道定位证据；Unicode 由后端返回已切好的前文/引文/后文，或统一码点处理并测 emoji | P1 总验收（见下） |
| P1-5 | 诚实状态呈现 | 投影 + 前端 | 局部未知、失败影响、无日期组、单方材料（标"材料单薄"）显式呈现；禁止回退"相近原文"、禁止静默过滤无效引用 | W10、W13 |
| P1-6 | 保留主链回归 | `manager.py`、`server.py` | 新建、澄清、取消、历史、更新、版本、Markdown 全链不回归 | 既有 investigation 测试全绿 |

**P1 退出条件（实浏览器验收，不是 HTTP 200）**：一个已有调查可在真实浏览器完成"浏览现状 → 找到分歧 → 打开正确原文 → 提出补查入口可见"，且旧链无回归。命令：`python -m pytest tests/investigation -q`、`python -m pytest tests/e2e/test_investigation_web.py -q`、启动 Web 实操。

### 5.3 P2：两类事件长出不同内容（差异化价值）

| # | 任务 | 落点 | 步骤要点 | 验收 |
|---|---|---|---|---|
| P2-1 | 实现 `rule_change`、`billing_remedy` 两类侧重 + `general` 回退 | `domain/investigation/models.py`（EventProfile）、`engine.py`（确认规则）、投影层 PresentationPolicy | 模型提出 facets → 程序确认在允许集合且不删用户必答问题 → 候选模块 → 数据可用性检查 → 选择理由持久化；无适配用 general；多 facet 可并存 | W02、W03：两类事件同套页面呈现不同重点；输入不足回退；无事件专用 if/else、无硬编码答案、无样例文字泄漏 |
| P2-2 | 新旧规则对照 / 计费补救模块 | `web/assets/modules/`（rule-comparison 等）、领域证据输入 | 各模块有领域证据输入、降级状态（insufficient 显示具体缺口与补查入口）与选择理由；禁止模型补写旧规则值；"受理渠道 ≠ 已退费；金额不明不填 0" | W02 + 模块状态枚举测试 |
| P2-3 | 事件节点 vs 材料发布日期双口径 | EventNode、timeline 模块 | 节点点击按关联关系检索材料；日期柱点击按发布日期筛选；未知日期单列不乱排 | W05 |
| P2-4 | provisional 模块（运行中） | 投影 + SSE | **终态投影稳定后才做**；运行中展示同契约 provisional 模块，局部标待核查 | W13 |

**P2 退出条件**：两类不同事件在同一套页面显示不同重点；此处允许按 facet 分支，**不允许按具体事件名分支**。

### 5.4 P3：调查组织与定向交互（闭环）

| # | 任务 | 落点 | 步骤要点 | 验收 |
|---|---|---|---|---|
| P3-1 | SearchTask/CoverageRecord | `investigation/service.py`、领域 State | 按实施指南 §5.2 字段实现；基础发现与定向补查共用一个 loop；outcome 覆盖候选/空/无关/重复/读取失败/供应商错误 | 每次搜索可回答"为哪个缺口、哪个问题" |
| P3-2 | 缺口驱动下一动作 | 决策提示（`investigation/context.py`、相关 prompt） | 按实施指南 §5.3 六级可解释优先级；能用已有正文先 retrieve；同 query/page 无意义重复时转新别名/原始出处/机构域名/其他材料类型；工具瞬时错误重试计预算，不算"无材料" | 机制测试：优先级选择可解释、可重放 |
| P3-3 | 定向补查闭环 | `manager.py`（FollowupIntent）、update 契约、补查表单 | 从 completed/partial 父版发起；保留 issue、被质疑 finding、用户文字、父版关联；`client_request_id` 幂等；一事件仅一个活动调查，已有活动任务展示链接不并发 | W15：同 key 只建一个 run；跨事件引用拒绝；恢复不重置预算与已提交状态 |
| P3-4 | 补齐 `service_change`、`investigation_correction` 侧重 | 复用 P2 模块 | 复用已有模块，只加 facet 配置 | 两类新 facet 案例通过 W02/W03 同标准 |
| P3-5 | 顶部摘要逐条引用与审查状态 | 投影 | 防止投影重新夸大已限定判断 | 摘要每条可溯源 |

**P3 退出条件**：能解释每次搜索解决哪个缺口；一次用户追问进入正确新 run；失败不伪装成无进展。

### 5.5 P4：版本变化与有条件统计

| # | 任务 | 落点 | 验收 |
|---|---|---|---|
| P4-1 | 版本指针与快照一致性 | `manager.py`：`latest.json` 保留"最近发布可读结果"，新增 `latest_completed.json`；partial 默认打开时就近提供上一完整版本并展示未复评事项 | W14、W18：partial 不掩盖上一完整结果；failed/cancelled 不推进为新完整引用 |
| P4-2 | 差异依据与未复评展示 | diff 增补 change basis / comparability；对照页显示结论文字、理由与前后证据，不只是状态标签 | W17：修订/撤回有原因与前后依据；未复评不叫撤回 |
| P4-3 | 可下钻材料分布 + 议题涉及数量 | 新增 `investigation/metrics.py`、CorpusManifest、MetricSnapshot | 图表成员数 == 显示计数；同 URL 多正文版本不多算文档；比例服务端确定性计算；点击下钻一致（W19、W24） |
| P4-4 | 观点构成（有条件） | 仅当归因、去重、分类评估通过后上线；否则保留观点对照，模块标 `pending` | 不满足条件时**不显示百分比** |

### 5.6 P5：真实案例与完整 Web 验收

- 按三类证据分开执行并分别记录：①机制测试（fake/scripted）→ ②固定材料语义回放（真实模型、冻结正文）→ ③真实联网调查（真实模型/Brave/Jina）。
- 冻结模型、材料、预算和对照方法后再比较；界面改善用"完成核查任务的操作步骤/成功情况"说明，搜索质量用"必答覆盖和断言支持"说明。
- 实际浏览器主路径操作是独立验收项；接口测试、强制 click、截图存在不能替代。
- 材料/额度不足时：交付已通过子范围，列明未完成门槛；跳过记 `NOT_RUN`，**不得把 P1–P4 代码完成当作 P5 通过**。

### 5.7 额度不足时的降级顺序

保 P0/P1 可信主链 → P2 两类事件 → P3 定向补查。暂停：新增图表、`service_change`/`investigation_correction` 之外的更多侧重、装饰动效、额外可视化。保留至少一个真实事件的"已知—分歧—未知—证据—更新"完整体验；不为展示丰富度牺牲原文核查，不用扩大预算掩盖动作重复或审查失败。

---

## 6. 改动文件范围总表（按阶段）

**后端（新增文件先确认职责真实存在再建，不机械创建空文件）**
- 修改：`domain/investigation/models.py`（P1–P3 实体扩展）、`domain/investigation/engine.py`（校验/提交）、`investigation/storage.py`（Budget 累计用时）、`investigation/manager.py`（latest 指针、update 契约、幂等创建）、`investigation/report.py`（独立性统计、投影邻接）、`investigation/context.py`（P3 缺口注入）、`investigation/service.py`（P3 SearchTask）、`web/server.py`（API 扩展）
- 新增：`investigation/workbench.py`（P1）、`investigation/metrics.py`（P4，按需）、`investigation/presentation.py`（仅当策略确实需要独立文件）

**前端**
- 修改：`web/assets/api.js`（错误、连接恢复）、`app.js`（启动/路由，抽离首页与进度页）、`evidence.js`、`report.js`、`ui.js`、`style.css`（设计 tokens + 响应式，不为每个事件生成样式）、`web/investigation.html`
- 新增：`web/assets/workbench.js`（P1）、`web/assets/modules/timeline.js`、`coverage.js`、`issues.js`、`rule-comparison.js`（P2 起，按真实复用创建）

**测试**
- 扩展：`tests/investigation/`（budget_recovery、evidence_integrity、publish_protocol、update_* 等已有文件就近增补）、`tests/e2e/test_investigation_web.py`
- 新增：workbench 投影纯测试、模块白名单/状态测试、facet 选择测试、API 契约测试、前端纯投影测试与浏览器主路径脚本

**文档（每个重要实现节点同步）**
- `docs/public-opinion-search-agent-design.md`（稳定契约）、`docs/opinion-search-agent-implementation-memory.md`（只追加已验证事实）、本文件阶段状态

**明确不改**：`archive/`、既有运行产物、旧报告文件；`runtime/` 通用层不进舆情规则。

---

## 7. 测试与验收清单

### 7.1 场景到阶段的映射（W01–W24，通过条件以实施指南 §11.2 为准）

| 阶段 | 必须通过的场景 |
|---|---|
| P1 | W06（长文末尾否定）、W07（来源关系）、W08（多主体）、W09（复合问题）、W10（未发现回应/读取失败）、W11（证据定位 + Unicode/emoji）、W12（SSE 断线/晚加入/快速切换）、W13（provisional） |
| P2 | W01（明确/歧义事件）、W02（两类事件不同重点）、W03（混合/未知/不足回退）、W04（用户问题不入模板）、W05（双时间口径） |
| P3 | W14（取消/预算/崩溃恢复）、W15（补查幂等与跨事件拒绝）、W16（同 URL 变文/新发现旧文） |
| P4 | W17（判断变化对比）、W18（partial/failed/无新材料）、W19（筛选/图表/下载一致）、W21（旧格式兼容）、W22（索引重建）、W24（定向检索口径提示） |
| 全程 | W20（外部正文不能改 UI/规则/模板，安全测试）、W23（320/768/1024px、键盘、长标题、焦点管理） |

### 7.2 门槛（P5，沿用并补充）

- 引用、定位、版本与图表成员结构完整性 **100%**。
- 保留案例必答问题至少 **90%** 正确回答或恰当未知。
- 人工检查的重要断言至少 **95%** 得到引用支持或正确降级（标题、摘要、图表说明都计入）。
- 关键归因、转载、回应遗漏、更新反转、旧引用、断线恢复用例**全部通过**。
- 模块选择逐案有依据；必答内容可见，不适用模块不硬填。
- 问题数量、断言数量与错误类型一并报告；达不到门槛列明分母、失败用例与下一步，不得只写"总体效果良好"。
- 案例集：保留 10 个槽位（公共交通/公共设施/文旅服务/规则调整/回应修正各 2，dev/holdout 各 1）；T0/T1 严格分隔；当前 registry 为 blocked，取到真实材料并标注后才更新状态。

### 7.3 验证命令（从 `opinion_search_agent/` 运行，使用仓库已有 venv，不全局安装依赖）

```bash
python -m pytest tests/investigation -q
python -m pytest tests/e2e/test_investigation_web.py -q
python -m pytest -q -m "not live"
python -m opinion_search.web --host 127.0.0.1 --port 8918 --runs-dir /tmp/opinionsearch-workbench-acceptance
```

启动前确认端口与验收目录归属，避免碰到正在运行的调查。联网验证需有效配置与额度，使用已授权预算；不输出 `.env` 或密钥。

---

## 8. 执行规则与汇报

1. 每阶段开始：确认 cwd、`git status`、已有产物；读实施指南 §2 与相关源码，修正过时基线。
2. 小步实现：每一步说明用户可见变化与验证证据；结构测试、画布完成、历史联网成功、当前人工质量达标**分别记录**。
3. 用代码职责决定修改位置；不把舆情规则放通用 Runtime 或前端组件；模块可扩展只限本文几种 facet，不建任意低代码页面平台。
4. 不通过放宽引用、回应、审查门槛或假数据交付"看似完整"的页面；不删校验门提高 completed 比例。
5. 遇到不兼容存储格式、无法验证引用、无真实材料或额度耗尽：停止相关扩展，标记 `blocked` 并列明具体依赖，继续独立的已授权工作。
6. 阶段汇报使用实施指南 §12 模板（阶段与状态 / 完成的用户路径 / 代码与数据契约变化 / 运行的验证及产物 / 尚未运行的验证 / 材料预算恢复兼容限制 / 下一阶段最小任务）。

---

## 9. 风险与依赖提示

| 风险 | 应对 |
|---|---|
| 预算暂停/恢复语义未澄清就改 Budget | P0-3 先写复现测试，作为 P1 修复基准 |
| WorkbenchSnapshot 契约过早冻结导致返工 | P0 只冻结"最小字段 + 状态枚举 + 引用规则"；模块内容字段按阶段演进 |
| 投影层与 report.py 职责纠缠 | workbench.py 保持纯投影；不从 Markdown 反向解析；不做报告改写 |
| 按事件名写分支 | 代码评审检查点：只允许按 facet 配置分支 |
| 旧 latest.json 语义变更破坏既有数据 | 迁移前先读取现有目录；不覆盖旧 report.json；兼容视图只读生成并标明缺字段 |
| 额度不足掩盖质量问题 | 全程允许 `pending/blocked/NOT_RUN`，禁止把跳过记为通过、把历史测试当本次通过 |

---

*本方案为实施指南的执行展开，不建立第二套项目总设计；执行中若与实施指南冲突，以实施指南为准并在本文件记录偏差。*
