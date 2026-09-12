# Web 公开事件调查升级：执行计划与节点记录

> 关联：[交接文档](../../opinionsearch-web-investigation-handoff-2026-09-10.md) · Canonical Design: [`../../public-opinion-search-agent-design.md`](../../public-opinion-search-agent-design.md) · 实现记忆: [`../../opinion-search-agent-implementation-memory.md`](../../opinion-search-agent-implementation-memory.md)
>
> 工作目录：仓库根。执行顺序 S0 → A → B → C → D。阶段未满足退出条件前不标记 DONE。

## 0. 接手时的状态核对（对照交接文档第 1 节）

- 新增领域模型与后端编排代码仍在工作区（`domain/investigation/`、`investigation/`），未提交；Web 新接口未接入。
- 基线复现：`investigation.manager import OK`；四个既有测试文件 `40 passed`。
- 共享模块改动（framing/openai_compatible/brave_search/web capability）保留，未回退。
- 未跟踪的用户文件（`docs/opinion-agent-harness-learning-outline.md` 等）保持原样，未删除。

---

## S0：接管工作区，修复高风险基础契约

节点 / 日期：S0 / 2026-09-10

完成范围：

- 建立 `tests/investigation/`，20 个测试覆盖 R01/R02/R03/R04/R08/R14。
- R01 上下文完整性：`structured_context` 的 `input.material` 与主 Compiler 的 `memory.questions`/`memory.findings` 改为不可丢弃；超限时报 `RequiredContextOverflow` 或由审查降级为未核查，绝不静默丢失原文。
- R02 发布协议：终态先进入 `finalizing`，报告与版本完全写入后才切换为终态；`snapshot` 在报告写入前不返回 `report`，并提供 `report_pending`；中断后可 `resume` 重新发布。
- R03 更新语义：`ReflectDecision` 用显式 `retirements`（含理由）记录撤回；旧判断在更新初始化时置为“待复核”而非撤回；报告差异区分 `pending_reevaluation` 与 `withdrawn`。
- R04 必答问题：`required_questions` 从用户输入确定性抽取并写入 State；`_cover_required` 为计划遗漏的用户问题补建显式 issue；State 校验器拒绝丢掉用户问题。
- R08 证据完整性：新增 `verify_evidence`/`verify_state_integrity`，在 Reader/Retrieve 边界与发布前按 artifact 校验 `start/end/excerpt` 与 content hash。
- R09（部分）：Resolver 不再静默 `[:600]` 截断，超长查询改为明确要求拆分。
- R14：预算在规划前启动，等待澄清时暂停且不清零；`Budget.pause()`。

关键契约与不变量：

- 用户可见终态 ⇔ `report.json` 已完整写入。
- `State.required_questions ⊆ ⋃ issues.origin_questions`。
- 只有显式 `retirements` 才能把“旧判断消失”表述为撤回。
- 任何 Evidence 必须满足 `artifact_text[start:end] == excerpt` 且 hash 匹配。

修改文件与主要符号：

- `domain/investigation/models.py`：`QuestionProposal.covers`、`Issue.origin_questions`、`Retirement`、`RetiredFinding`、`State.required_questions`、`State.retired`、引用/覆盖校验。
- `domain/investigation/engine.py`：retirements 校验与归约、`_cover`/query 长度处理。
- `investigation/context.py`：`section(protected=)`、`structured_context`、`Compiler` 分段保护。
- `investigation/storage.py`：`verify_evidence`、`verify_state_integrity`、`Budget.pause`。
- `investigation/service.py`：审查上下文溢出降级、Reader/Retrieve 证据校验。
- `investigation/manager.py`：`required_questions`、`_cover_required`、发布协议、`_publish_failure`、预算起点。
- `investigation/offline.py`、`investigation/report.py`：retirements 适配、差异分类、必答问题展示。
- `domain/opinion/action_resolver.py`：旧搜索 action 载荷保持两字段兼容。

验证命令 / 环境 / 结果 / artifact：

```bash
PYTHONPATH=opinion_search_agent/src opinion_search_agent/.venv/bin/python -m pytest opinion_search_agent/tests/investigation -q
# 20 passed

.venv/bin/python -m pytest -q -m "not live"   # 于 opinion_search_agent/
# 590 passed, 2 deselected
```

失败及恢复语义：发布窗口崩溃 → draft 停在 `finalizing`，`resumable=true`，`resume` 由终态 checkpoint 重建报告；审查上下文超限 → 该批判断保持未核查并最终 `partial`；预算在澄清等待期间不计时、恢复不归零。

已知限制与尚未验证：真实联网质量、10 个保留案例语义回放、Web 主链与浏览器验收尚未执行；R05/R06/R07/R10/R11/R13/R15/R16 部分项顺延至 B/C/D。

下一节点的前置条件：S0 全部退出条件满足（新模块导入、合成单次调查可复现、审查不丢原文、必答问题不丢、hash/offset 可验证、发布/取消窗口有测试、共享模块回归通过）。

---

## A：建立业务基线（结构完成 / 材料 blocked）

节点 / 日期：A / 2026-09-10

完成范围：建立 `tests/investigation/cases/registry.json`，登记 10 个事件槽位（5 类 × dev/holdout），定义材料 provenance、stages 与 annotation 字段；`tests/investigation/test_case_registry.py` 校验完整性、类别覆盖、dev/holdout 划分，并断言 blocked 条目不含虚构材料、holdout 身份不进入生产代码。

退出条件状态：

- [x] 10 个案例登记完整；材料不可获得时明确 blocked，不用虚构替代。
- [x] 开发和保留案例分开；保留答案不进入主 Agent 提示词或生产代码（有断言）。
- [ ] 有来源可查的固定材料与双时点更新材料 —— **blocked**：未取得可核验公开原文快照。
- [ ] 旧版在固定条件下的失败点可定位 —— 待材料后执行。

结论：A 结构完成，但缺少真实材料，最终质量结论保持待验。

## B：可信单次调查 + Web 第一条主线（已完成并可浏览器复现）

节点 / 日期：B / 2026-09-10

完成范围：Manager 新查询方法（evidence/versions/diff/report/markdown）；`/api/investigations` 全系列端点；SSE 快照流；`investigation.html` 与拆分的前端模块；旧报告只读迁至 `/legacy`；旧格式 run 由 execution profile 拒绝续跑。

退出条件状态：

- [x] 浏览器提交明确事件自动开始；歧义/无效时间需要澄清（澄清表单 + 预算暂停有测试）。
- [x] 刷新草稿与进行中任务，恢复状态且不重复创建（snapshot/resume 有测试）。
- [ ] 长文章后半段能被新问题检索并定位 —— 机制测试覆盖（Corpus 字符区间）；真实长文回放待材料。
- [x] 重要结论可在页面展开正确版本原文（证据面板，浏览器验证）。
- [x] 取消/断线/失败/partial 状态可实际操作观察（取消/发布路径有测试）。
- [x] 旧报告仍只读浏览和下载，旧格式未完成任务被明确拒绝续跑。

验证：`tests/e2e/test_investigation_web.py` 5 passed；浏览器全链操作见 implementation memory §20.3。

## C：争议、回应与审查（领域契约完成 / 语义质量待验）

节点 / 日期：C / 2026-09-10

完成范围：`FindingProposal` 回应覆盖字段与校验（direct/partial/non_substantive/attributed）；`response_search_complete` 要求问题级有界查找完成且候选已处理；报告来源独立性 `independent_source_count`；六部分报告结构在 Markdown 与页面同时呈现。

退出条件状态：

- [x] 三篇转载同一通稿不会成为“三个独立证据”（正文重复 → `independent=false`，报告计数）。
- [x] “机构称已解决”不能变成无归因的已解决事实（attributed 必须有主体，有反例测试）。
- [x] 回应只涵盖周末而问题涉及工作日时判部分回答（partial 必须指出 uncovered，浏览器可见）。
- [x] 有回应页面读取失败时显示无法判断，不是未发现回应（read_errors 使 `response_search_complete` 为假）。
- [x] 未审查或审查失败的重要判断在对应位置降级，重大缺口导致 partial。
- [x] 主界面区分回应、解决、满意（回应覆盖单独呈现，scope_limitation 明确不推论满意）。

未覆盖：转述/引用等更细的来源依赖关系、“实质覆盖”的语义判断仍依赖模型，只做了结构约束。

## D：按需更新、版本与恢复（已完成，浏览器与故障测试验证）

节点 / 日期：D / 2026-09-10

完成范围：更新入口与版本继承/重开；`SourceCheck` 记录本轮对每个 URL 的有界复查（`url/version_id/checked_at/changed`）；同 URL 变文新增版本、旧引用继续定位旧文；`CaseLock` 跨进程排他；恢复不重跑已提交工具动作；provider 失败在报告与页面明确标注且不会被表述为“无进展”。

退出条件状态：

- [x] 新证据使旧判断修订，旧报告/正文 hash 不变（有测试断言父报告字节不变）。
- [x] 同 URL 变文产生新版本，旧引用仍定位旧文（`test_same_url_changed_text_adds_a_version_and_keeps_the_old_one`；浏览器显示“页面内容有变化”）。
- [x] 新发现旧材料、新发布材料、页面内容变化有明确区别（`discovery` 分类 + 复查记录）。
- [x] 无实质变化带本轮查找范围；provider 失败不显示为无进展（`search_failures`/`read_failures` + Markdown/页面警示）。
- [x] 中断更新不会替换旧报告，也不会把待复核判断写成撤回。
- [x] 跨进程同事件排他（子进程持有 `active.lock` 时另一进程 `create` 抛 `CaseBusy`）；崩溃恢复不重置预算、不重复提交 delta（恢复不重跑已提交工具动作；预算恢复有测试）。
- [x] 实际浏览器完成从提交到更新对比的全链。

仍未覆盖：真实联网下“页面内容变化时间未知”的完整时间语义、同 URL 变文在真实站点上的抓取差异判定、以及并发故障注入在真实 provider 重试路径上的覆盖。

验证：`tests/investigation/test_update_versions.py` 5 passed（含跨进程 flock 子进程测试）；`pytest -q -m "not live"` 613 passed, 2 deselected。

## 收尾：真实联网与人工验收

**真实联网已执行（2026-09-11）；人工评分与保留案例仍未执行**，不以合成结果替代；不宣称 90%/95% 达标。

已执行：模型网关 `opencode.ai/zen/go/v1` + `mimo-v2.5` + Brave + Jina，本地 `127.0.0.1:8917`(live)，浏览器完成 提交 → 进度 → 报告 → 证据抽屉 → 补充进展 → 版本比较。父调查 `partial`（5 搜索 / 35 候选 / 1 来源 / 8 证据 / 0 判断，stop=`Decision recovery was exhausted`）；子调查 `partial`（3 来源 / 15 证据 / 7 判断，真实时间线与 修订/未变/新增，stop=`core conclusions must be active and supported by a current review`）。

已核实：网关对推理请求要求 `x-opencode-session` 头；`GET /models` 对无效 key 也返回 200，不能作为凭据校验。为此新增通用 `OPINION_MODEL_EXTRA_HEADERS` 与客户端 `extra_headers`（拒改 `Authorization`）。

仍未执行 / blocked：10 个保留案例的固定材料语义回放与人工 90%/95% 评分；案例登记表全部 `blocked`。下一优先项（见实现记忆 §20.7）：模型决策结构化成功率与“核心结论”复核门。

**模型切换与缺陷修复（2026-09-11，见实现记忆 §20.8–20.9）**：切 `deepseek-flash` 的真实运行依次暴露并修复 决策提示未声明 JSON、退休路径 `utcnow` 未导入、证据校验 `ValueError` 未收口、模型输出后附说明/第二 JSON/`<tool_calls>` 的容错，以及把供应商瞬时故障（500/空响应/超时）与决策语义失败分离的传输重试；超时与预算改为可配置（`OPINION_MODEL_TIMEOUT_SECONDS`、`OPINION_INVESTIGATION_*`）。`pytest -q -m "not live"` 635 passed, 2 deselected。

**首个完整完成的联网调查**：同一事件（重庆燃气计费异常争议）终态 `completed`（1530s，16 搜索/16 读取/59 模型调用），13 来源 / 74 证据 / 24 判断 / 8 条核心结论，6 问题全部 `answered`，独立来源 13（含 `cq.gov.cn`、`caixin.com`）。报告如实并列两套官方/企业统计口径与 824% vs 895.77% 差异。补充进展的子调查首次 `partial` 于 `partial` 回应缺 `uncovered`；把校验器消息改为直指字段并在 `INSTRUCTIONS` 前置覆盖契约后重跑，子调查得到 19 来源 / 96 证据 / 6 判断 / 5 条核心结论，6 问题 `answered` + 1 `unavailable`，并**主动**以“材料或复核限制仍在”保持 `partial`；版本比较逐问题显示 `尚未重新评估`×4 / `修订判断`×2 / `新增判断`×1。人工 90%/95% 评分与保留案例回放仍未执行。


