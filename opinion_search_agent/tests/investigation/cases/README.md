# 公开事件案例登记表（A 阶段）

`registry.json` 是评估数据集的登记表，不是可运行的现成数据集。它按交接文档第 8 节定义 10 个事件槽位：5 个类别，每类一个 `dev` 和一个 `holdout`。

## 当前状态

`response-dev` 已在本地实验批次收集 8 份带 sha256 的公开文本快照；`rules-dev` 已收集国内航班充电宝规则、地区执行和后续监管共 6 份快照。两者均标记为 `materials_collected_local_unreviewed`。原文快照默认不提交 Git；registry 保留 URL、哈希和本地路径，使材料缺失与未获分发确认保持可见。候选问题、禁止结论与来源依赖仍是 `model_preannotation`，尚未获得人工复核，因此只能用于本地材料管线和模型调试，不能进入人工质量门槛。其余 8 个条目仍为 `blocked`，不以虚构材料补位。

## 填写规则（取得材料后）

- `materials[]` 每项必须包含：`url`、`final_url`、`title`、`fetched_at`、`published_at?`、`updated_at?`、`snapshot_path`、`sha256`、`source_role`、`dependency_relations`。
- 必须保存真实正文快照与 sha256；禁止用“新闻标题 + 模型编写正文”冒充快照。
- 没有历史快照时，只能声明为“固定材料回放”，不得声称还原了历史互联网某天的完整状态。
- `stages.T1_additional_materials` 的材料不得预先进入 `T0_allowed_materials` 的可检索 corpus，也不能只靠提示词要求模型忽略。
- `annotation.author_kind` 必须区分 `human`、`model_preannotation`、`none`；`reviewed_by_human` 为 false 时不得当作人工 gold。
- `holdout` 的答案、query 与结论不得出现在生产代码、提示词或问题模板中。

## 三类结果分别记录

1. 机制测试：fake/scripted，已在 `tests/investigation/` 建立。
2. 固定材料语义回放：真实模型 + 冻结材料，等待材料后执行。
3. 真实联网运行：真实模型 + Brave/Jina，需凭据与费用，单独记录。

在材料与人工复核到位前，本登记表不足以支撑质量门槛结论。
