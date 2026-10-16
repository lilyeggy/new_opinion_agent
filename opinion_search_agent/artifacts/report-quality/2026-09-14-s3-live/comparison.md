# `billing-dev-v1` 首次生产模型对照

> 批次：`2026-09-14-s3-live`
>
> 结论：FAIL。该批次证明当前生产 Agent 编排未能把已取得的证据转化为报告；基线模型也因输出上限没有形成可评分结果。它不支持“Agent 优于简单摘要”的结论。

## 固定条件

- 模型：`deepseek-flash`，OpenAI-compatible HTTPS 网关。
- 材料：`billing-dev-v1` 的 8 份冻结公开正文，manifest sha256 为 `18422d06c331fe9f0ea43e4735106c2ab41f3da373d1447ab1b3404f3a55c793`。
- Agent：生产 planner、Decision、Processor、Reducer、reviewer、completion 和 report 管线；Search/Reader 只返回冻结材料。
- Baseline：同一任务和同一组完整正文，一次结构化摘要；允许一次输出上限重试。
- Brave/Jina：0 次。批次模型请求上限 42 次，实际 42 次。

## Agent 组

| 项目 | 结果 |
|---|---:|
| 终态 | partial |
| 模型请求 | 40/40 |
| 已提交步骤 | 22 |
| Search / Read / Retrieve | 11 / 8 / 3 |
| 正文版本 | 8 |
| 证据片段 | 44 |
| Finding / Review / Conclusion | 0 / 0 / 0 |
| 必答问题仍 open | 6/6 |
| 必答子项仍 open | 17/17 |
| 证据原文定位 | 44/44 结构与文本匹配 |

Agent 取得了足以回答多个关键问题的正文和证据，例如 2024 年问题类型、2024 年企业披露的投诉与清退数字、2025 年再次调查认定和拟处罚安排。然而它一直选择继续搜索、读取或 retrieve，没有执行一次 `reflect`。冻结 Search 后续只能返回已知 URL，11 次搜索中只有首次增加候选，其余 10 次没有增加新材料。模型预算耗尽后，系统正确发布 partial，但报告核心回答为空。

这说明失败发生在“证据 → Finding”转换和 Loop 收敛，而不是材料缺失、Reader 失败、证据定位失败或前端展示。

## 单次摘要基线

基线输入约 18,661 prompt tokens。第一次输出上限为 4,096 tokens，发生 length truncation；客户端按策略以 8,192 tokens 重试。第二次响应记录 23,847 个 reasoning characters、8,192 completion tokens，但最终 content 仍为空，因此没有可解析 JSON，2 次请求预算全部消耗。

基线没有生成报告，不能进行语义质量评分。该失败同时暴露出模型输出预算配置虽然能够从 `.env` 解析，却没有传入生产模型客户端的问题。

## 本轮修复

1. 首次研判闸门：当已有至少 4 个正文版本和证据但没有 Finding，或连续两次搜索只返回已知 URL 时，下一步必须 `reflect`。
2. 同一闸门进入不可压缩的可信 Runtime context，并由 Validator 再校验；空 `reflect` 不能绕过。
3. `build_loop()` 改为使用 `LiveConfig.max_steps` 和 `max_decision_attempts`，不再硬编码 100/2。
4. `live_model()` 将 `model_max_output_tokens` 传入客户端，使实验配置真正生效。

这些修复已通过机制测试，但本批 42 次请求已经耗尽，因此尚未使用真实模型复跑。状态为 `IMPLEMENTED_NOT_MODEL_RERUN`。

## 未证明事项

- 没有证明修复后的 Agent 能生成高质量报告。
- 没有得到可评分的简单摘要，不能比较两组语义质量或成本收益。
- 没有执行真实 Brave/Jina 发现能力测试。
- 预标注仍为 `UNREVIEWED`，本批不能计入 V1 的 90%/95% 人工验收门槛。
