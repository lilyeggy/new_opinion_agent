# OpinionSearch 与 DeepResearch Bench：题目匹配和适配审查

> 2026-10-29；只读分析。没有启动 Agent、调用模型、搜索网页、运行评分器或产生成绩。题目适配结论由助手根据用户授权判断，不代表官方分类；产品仍面向广义舆情事件，不承诺覆盖所有主题。

## 1. 结论

DeepResearch Bench I 可作为公开的通用研究能力补充评测，但不适合作为现阶段唯一的舆情事件验收集。检查原始 100 个问题后，未发现清晰地围绕某个舆情事件还原经过和各方回应的直接匹配题；以下几个可以作为相关但不等价的探针。这个结论是对本版题目的审阅判断，而非宣称所有近似任务都不可用。

建议：先以 ID 42 和 ID 87 作为**适配试点候选**，可补 ID 17；按原始问题、原 benchmark 分数和原评审协议分别记录。此 2–3 题是方便检查接入的探索性样本，不是代表性抽样或官方总体成绩；仅运行和复核后才能判断系统表现。最终事件专项覆盖须另查更贴近的公开数据或补少量针对性案例；目前没有选定具体数据集。

## 2. 复核证据及版本

- 官方 [DeepResearch Bench I 仓库](https://github.com/Ayanami0730/deep_research_bench)；审查时 `main` 指向 `f2735b5c3636759c22f9e936c0232de8bf545b67`。固定版本的[题目数据](https://github.com/Ayanami0730/deep_research_bench/blob/f2735b5c3636759c22f9e936c0232de8bf545b67/data/prompt_data/query.jsonl)，原始文件 SHA-256 `62b197a264a027fd4e2e795ff322a82dd6d566f5e350596ccc7572539ec987d1`。
- 直接读取全部 JSONL：100 条，中文 50、英文 50，字段为 `id`、`topic`、`language`、`prompt`。查看所有题目的摘要并逐字复核 ID 17、42、77、81、87、90；这是人工相关性判断，不是经过双人标注的标准分类。
- 固定版本的 [评分项](https://github.com/Ayanami0730/deep_research_bench/blob/f2735b5c3636759c22f9e936c0232de8bf545b67/data/criteria_data/criteria.jsonl)和[参考报告](https://github.com/Ayanami0730/deep_research_bench/blob/f2735b5c3636759c22f9e936c0232de8bf545b67/data/test_data/cleaned_data/reference.jsonl)均可读，各有 100 条；前者字段包括 `id`、`prompt`、`dimension_weight`、`criterions`，后者包括 `id`、`prompt`、`article`。
- 未下载并保存 benchmark 数据，未核实第三方网页内容权利和全部资源可访问性。代码仓库 Apache-2.0 不自动赋予第三方网页内容使用权；正式使用前核查数据和内容许可。

## 3. 题目适配判断

原题完整内容见固定版本题目链接，以下仅概述。

| ID | 题目主题 | 判断 | 合理用途与不匹配 |
|---|---|---|---|
| 42（中文） | 围绕 2025 年教育规划中的学生体育活动要求，调研实际情况、影响因素及政策措施 | **最接近的探针之一** | 有具体公共政策背景与现状材料，可探索证据检索和政策分析；题目还要求政策制定建议，非具体舆情事件的观点/回应复盘，不能当作事件案例 |
| 87（英文） | AI 时尚设计工具与创意同质化、版权争议 | **争议分析探针** | 有争议主题，适合检查不同观点及引用；不是指定单个事件，还要求解决方案，英文输出及知识范围可能超出当前产品设计 |
| 17（中文） | 低代码/无代码的效率与维护成本，涉及开发者和业务视角 | **多视角探针** | 可考察冲突观点与证据归属；是行业分析且含趋势预测，不是一个舆情事件 |
| 90（英文） | 辅助驾驶事故中的责任分配及法律政策 | **暂不优先** | 有事故和各方责任，但要求专业法律、案例与政策建议；评测失败不能简单归因于舆情能力 |
| 81（英文） | 当代政治社会视角下历史叙事、纪念和记忆 | **不作为首批** | 多视角，但属于学术史论，不是事件调查 |
| 77（英文） | 个体认知需求与错误信息接受之间的关系 | **不作为首批** | 可测通用证据研究，但不是单一事件或舆情报告 |

不能根据一项入选或没入选就宣称系统适合/不适合某语言或某事件类别。筛选子集须提前记录标准、ID、未选择原因，且不可称其为官方全量成绩。

## 4. 实际输入输出与现有产品路径

### 输入

- 正式输入使用 `InvestigationRequest`，继承 `SearchRequest`，支持 `question`、可选 `topic`、`language` 等；`Manager.create` 在 live 模式校验配置并启动生产调查。对原始 ID 17、42、77、81、87、90 做了**纯模型字段校验**：各题按原 `prompt` 输入、`language` 按其语言字段输入均可构造。这只证明请求结构接受，未证明规划或研究能成功。[models.py](/Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/domain/investigation/models.py:28)
- 现有 `scripts/run_live_investigation.py` 要求 `--topic` 和 `--question`，默认 `zh`，遇澄清会自动回答“按你的理解”或给时间范围。它可作为参考，但直接用于 benchmark 会添加 topic、隐式改变澄清行为，且英文题可能被指定中文；不能视为无偏的澄清评测。[run_live_investigation.py](/Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/scripts/run_live_investigation.py)
- 实验驱动应保留原始 prompt、id、语言，不静默重写；若系统要求追问，记录问题及状态。是否配置固定用户回答或标记交互未完成应预先规定并分开统计；不能因脚本方便自动掩盖澄清。

### 输出与评分

- 官方 README 规定原始结果为 JSONL，关键字段 `id`、`prompt`、`article`；原样保留题目字符串。[官方 README](https://github.com/Ayanami0730/deep_research_bench/blob/f2735b5c3636759c22f9e936c0232de8bf545b67/README.md)
- 该版本 [RACE 实现](https://github.com/Ayanami0730/deep_research_bench/blob/f2735b5c3636759c22f9e936c0232de8bf545b67/deepresearch_bench_race.py) 按 `prompt` 匹配目标、参考与标准；比较目标与参考报告的加权得分，最终使用 target/(target+reference)，不是直接的绝对合格率。清洗和评审需要模型调用；版本及参考应固定。
- 项目 Markdown 正文使用 `[evidence-id]`，来源与 URL 在后部证据列表。是否被官方 FACT 正确解析为“陈述 → URL”尚未验证；需要在不改变语义的前提下设计映射、检查缺失和歧义。不能只因 URL 在文末就宣称引用评测兼容。原始 `report.md`、结构化 report、状态及转换后的文章都要保留，禁止将未支持的引用补成已支持。
- `completed`/`partial`/`failed`/`cancelled`、等待澄清、超时和无报告应分别记录；partial 报告的成绩不应被当作完整任务成功率。错误、未评分或未覆盖案例不能悄悄剔除，只报有分的幸存样本。打分异常和转换失败均为可见失败。

## 5. 固定材料与联网的限制

现有 [investigation/replay.py](/Users/mac/Desktop/resume_proj/agent_code/opinion_search_agent/src/opinion_search/investigation/replay.py:90) 支持冻结材料并对快照校验，但每次搜索返回该 case 全部材料，其结果不模拟真实搜索引擎排名，也不直接匹配 BrowseComp-Plus 的固定大语料检索设置；它只能在相应条件下用于阅读和报告分析。`mode=live` 并不等于完全离线，模型仍可调用外部服务。公开 benchmark 的联网原任务也不能假装等价于该 replay 实验。

## 6. 拟定最小验证步骤（提案，未执行）

1. 在独立临时目录保留版本号、原始题目和运行配置；明确 42/87 为试点、17 可选，原问题不改写。
2. 先建立一个只读评测适配方案并审查：输入透传、原文输出及引用映射、等待用户、停止/超时和结果统计；验证不改变产品用户路径。实施前明确授权与经费。
3. 首次试点应预先限制请求次数/时间/花费并记录逐项成本，区分调查模型、搜索/阅读和评审模型；未知费用显示未知，不因拿到 API 响应就认定质量通过。
4. 运行完整生产链路，逐题留存原始产物、状态、模型、来源、日志和题目；报告缺失与 partial 单独说明。用户需要介入时按预先制定的规则处理，不静默伪造答案。
5. 评估官方 scorer 是否可准确消费转换后的文章及 URL；先做本地格式/映射检查，再决定是否产生费用调用评审。RACE 与 FACT 分别报告；实际可用性与费用未验证。
6. 人工检查少量判断-引用，记录评审模型与人工分歧。样本太少只作适配与错误分析，不得推断舆情任务整体成功率或真实业务价值。
7. 结果作为决策材料：需要进一步扩大公开题集、另外寻找事件基准，或只为尚缺失的澄清/观点归属等补充案例。重大架构与评测门槛继续由用户参与确定。

## 7. 目前已知但不能当作实验证据的事项

- 本次没有实际报告、官方得分、延迟/费用或 benchmark 对比；字段校验仅证明 Pydantic 接受原 prompt。
- 产品当前对六种动作、公开网页和报告有既有设计，但该 benchmark 有趋势预测、决策建议、英语和多领域研究任务；失败可能反映能力不足，也可能反映产品范围不匹配，需结合任务具体要求判断。
- 用户原项目与真实公司合作已结束；通用 benchmark 成绩和自行标注结果均不证明真实营销业务收益。
