# OpinionSearch Runtime 确定性回放方案

状态：已确认（D1=B，回放包含 resume 续跑段，分工接受）。S1–S5 已实现并通过验证（全量 822 passed）；S6 fixture 以集成测试形式覆盖；S7 文档已同步。本文只定义范围、契约、不变量、实施切分与验收标准，不包含实现代码。

## 1. 目标与非目标

目标：
- 对单次 run 的每个 step，记录足以重放的决策输入与输出（模型输出、tool 结果、Compiled Context 哈希、状态转移）。
- 提供一个只读回放入口：用记录的材料重新驱动 loop，逐 step 比对 State 演进，发现不一致即停止并定位到具体 step。
- 回放失败必须可解释：指出第一个分歧 step、分歧字段、期望值与实际值。

非目标：
- 不建设 trace 平台、dashboard、跨 run 聚合或指标存储（属于第 ⑤ 层，超出边界）。
- 不改变 OpinionSearch 的领域动作（`search` / `read` / `reflect` / `finish`）和舆情判断逻辑。
- 不引入 LangGraph 或其他隐藏状态演进的框架。
- 不做分布式或多 worker 的回放调度。

## 2. 范围界定

本方案只覆盖单次 run 的回放，包括：
- 从头开始的 run。
- 从 checkpoint resume 之后的续跑：续跑段的 step 必须与父段记录首尾衔接，回放需要能跨越 resume 边界。

父版本/子版本的 update 路径（`run_replay_update_case`）属于已有的冻结材料回放，本方案不改动它，二者并存，职责不同：
- 已有 `investigation/replay.py`：冻结外部材料（Search/Reader 结果），验证 Runtime 在固定输入下的产出，不校验决策序列。
- 本方案新增的 Runtime 回放：校验决策序列本身是否可复现。

## 3. 核心概念

- **Decision Journal**：每个 step 一条只追加记录，描述该 step 的全部决策输入输出。与 checkpoint 分离存放。
- **Replay Source**：回放时的输入来源，由 journal 提供模型输出、tool 结果和 context 哈希。
- **Divergence**：回放时某 step 的任一比对项与记录不一致。

## 4. 设计决策（待确认）

### D1 记录位置：独立 journal 还是扩展 checkpoint

- 方案 A：扩展 checkpoint 到 v5，把 step 记录写进 State。优点是单一来源；缺点是 checkpoint 体积随 run 增长，且触发 schema 升级与旧数据迁移。
- 方案 B（推荐）：新增每 run 一个的 append-only journal 文件，checkpoint 保持 v4 不变。优点是不破坏 checkpoint 兼容性，回放是只读审计产物，可独立删除或归档；缺点是需要保证 journal 与 checkpoint 的一致性（见第 6 节）。

推荐 B。若选 A，则需要单独的迁移步骤和兼容测试。

### D2 比对粒度

- 方案 A：只比对最终 State 的 hash。简单，但无法定位分歧 step。
- 方案 B（推荐）：逐 step 比对 Compiled Context 哈希、决策输出、tool 调用参数、observation 摘要与 State 转移后的 hash。分歧可定位到 step 与字段。

### D3 非确定性来源的处理

需要显式枚举并处理的来源：时间戳、UUID/ID 生成、并发完成顺序、外部 tool 返回、模型采样。
- 时间与 ID 通过 IdFactory、时钟协议注入，回放时使用记录值。
- 模型输出与 tool 结果在回放时从 journal 读取，不再调用外部服务。
- 并发 tool 调用的完成顺序必须按记录顺序提交，或只记录已提交顺序。

## 5. 契约与不变量

- I1：journal 中每个 step 的记录按 step_index 严格递增，且不重复。
- I2：一个 step 的记录只有在 commit_step 之后才可见；未提交 step 不得出现在 journal 的完成段中。
- I3：回放对同一 journal 的结果是确定的：多次回放得到相同的 divergence 结论或相同的最终 State hash。
- I4：回放过程不得调用真实模型或真实 tool。若需要而缺失记录，立即报错，不降级为重新调用。
- I5：journal 缺失、损坏或与 checkpoint 不一致时，回放失败并给出明确原因，不尝试修复。
- I6：Compiled Context 哈希只由 State 和编译参数决定，不包含时间戳或随机值。

## 6. 失败与恢复语义

- 写入顺序：step 提交时，先写 journal 完成记录，再写 checkpoint。若在两者之间崩溃，resume 时发现 journal 比 checkpoint 多出一个已完成 step，视为该 step 未提交，截断 journal 到 checkpoint 对应位置后重跑。反之（checkpoint 已写但 journal 缺失）视为一致性错误，拒绝 resume。
- journal 追加使用同步写入与 fsync，单条记录要么完整可读，要么被丢弃（读取时忽略末尾不完整行）。
- 回放不写 checkpoint，不修改原 journal。
- 回放中的 divergence 作为结构化结果返回，不以异常静默吞掉。

## 7. 验收标准

1. 正常 run：完成后回放，逐 step 无 divergence，最终 State hash 一致。
2. 中断 run：在 journal 写入后、checkpoint 写入前注入崩溃，resume 后回放仍一致。
3. 篡改 journal 中某 step 的 tool 结果，回放报告第一个 divergence 的 step 与字段。
4. 删除某 step 记录，回放报错而非重新调用外部服务（I4）。
5. 同一 journal 连续回放三次，结论完全相同（I3）。
6. 续跑 run：resume 段与父段衔接，回放跨越边界通过。
7. 既有测试全部通过，checkpoint v4 读写行为不变。

验证方式：deterministic fake model 与 fake tool 的 fixture，加上已有 `tests/` 的回归；不依赖真实 Brave/Jina/模型服务。

## 8. 实施切分

按 CLAUDE.md 的分工，核心语义由用户实现，协作者补齐外围与测试。

| 步骤 | 内容 | 负责 | 验证 |
|---|---|---|---|
| S1 | 冻结 journal 记录字段与不变量（I1–I6），写入 spec 定稿 | 用户确认，协作者起草 | 文档评审 |
| S2 | journal 的 append/read 原子操作（写入、末尾不完整行丢弃、fsync） | 协作者 | 单元测试：崩溃截断、损坏行 |
| S3 | step 记录结构与比对逻辑（哪些字段进入 hash，divergence 结构） | 用户 | 单元测试：比对纯函数 |
| S4 | loop 中接入 journal 写入，保持 checkpoint boundary 顺序（第 6 节） | 用户 | 集成测试：注入崩溃 |
| S5 | 回放驱动：用 journal 作为 Replay Source 驱动 loop，禁止外部调用（I4） | 用户 | 验收 1、3、4、5 |
| S6 | fake fixture、故障注入脚本、回归 | 协作者 | 验收 2、6、7 |
| S7 | 同步更新 implementation memory 与 `docs/interview/03`、`09` 的代码落点 | 协作者 | 文档与代码核对 |

## 9. 风险

- R1：ID/时间注入若遗漏一处，回放会误报 divergence。缓解：比对前先做非确定性字段白名单检查，并用 fake 对全部路径做覆盖。
- R2：journal 与 checkpoint 的一致性最易出错。缓解：S4 专门做崩溃注入测试。
- R3：并发 tool 完成顺序若未按记录提交，回放不稳定。缓解：在 S3 决定提交顺序规则并写入 I1 的补充条款。
- R4：范围蔓延到 observability。缓解：journal 只服务回放与恢复正确性，不提供查询接口。

## 10. 已确认决策与进度

> 注：用户后续委托由协作者完成 S3–S5，下方交接清单保留为设计记录。

已确认：
1. D1 = B：独立 append-only journal，checkpoint 保持 v4。
2. 回放范围包含 resume 续跑段（验收 6）。
3. S1–S7 分工接受：S3、S4、S5 由用户实现。

进度：
- S1 冻结：本文第 5、6 节的不变量与失败语义作为契约。
- S2 完成：`src/opinion_search/runtime/journal.py` 提供 `RuntimeJournal` 的 append（fsync）、read、truncate_after 与 torn tail 修复；I1 由 append 与 read 双向校验。测试见 `tests/unit/runtime/test_journal.py`（13 项通过）。全量测试 816 通过，2 项 live 测试按设计跳过。
- S2 不包含 step 记录语义，`step_index` 之外的 payload 结构留给 S3。

交接给用户（S3–S5）：
- S3：定义 step 记录字段与比对 hash 的字段集合，以及 divergence 结构。`RuntimeJournal` 只接受带整数 `step_index` 的 Mapping。
- S4：在 loop 的 checkpoint boundary 上接入 journal。注意第 6 节的写入顺序：journal 完成记录先于 checkpoint；resume 时用 `truncate_after` 对齐。
- S5：回放驱动，禁止外部调用（I4），缺失记录报错。

## 11. 实施结果与验收对应

- S3：`runtime/replay_record.py`（记录结构、指纹、divergence）。
- S4：`runtime/recording.py`（model 包装、journal 前置于 checkpoint、in-flight 对齐）。原方案的验收 2 在"跨进程 resume"场景下需要 in-flight 文件才能满足，因此实际实现增加了该侧文件。
- S5：`runtime/replay.py`（只替换 model 与 executor，缺失记录报错）。
- 验收对应：1 → `test_recorded_run_replays_to_match`；2 → `test_crash_between_journal_and_checkpoint_resumes_consistently`；3 → `test_context_hash_tamper_reports_first_divergence`；4 → `test_missing_recorded_call_is_an_error_not_a_live_call`；5 → `test_replay_is_repeatable`；6 → 同一 resume 测试（resume 段与父段衔接并回放一致）；7 → 全量 822 passed。
- 额外验证：跨 `PYTHONHASHSEED` 的录制与回放，journal 字节级一致。
- 已知限制：ruff 未安装，未运行 lint；仅覆盖离线 fake 装配，未在 live 录制上验证。
