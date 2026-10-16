# 首次研判收敛修复复跑

> 批次：`2026-09-14-s4-convergence-rerun`
>
> 结论：FAIL。首次闸门已真实触发并使模型尝试 `reflect`，但三次决策恢复仍未产生合法领域决定。

## 固定条件

- 案例与材料：与 `2026-09-14-s3-live` 相同的 `billing-dev-v1`。
- 模型：`deepseek-flash`。
- 上限：24 次模型请求、20 个步骤、每次初始输出上限 16,384 tokens、3 次决策尝试。
- Brave/Jina：0 次。
- 实际：9 次模型请求、3 search、1 read、1 retrieve，保存 1 份正文和 6 个证据；6/6 证据定位通过。

## 观察结果

连续两次 search 只返回已知 URL 后，`memory.next_action_constraint` 和 Validator 成功阻止第三轮无界搜索，并要求 `reflect`。这证明第一版修复进入了真实模型链路，输出上限配置也已生效，本轮没有发生 length truncation。

模型随后三次恢复均失败：

1. 首次仍提交了不符合当前动作约束的决定，被 Validator 拒绝。
2. 第二次已尝试输出带证据 Finding 的 reflect，但复合问题 component 使用了 schema 外状态，产生 malformed response。
3. 第三次提交了 response=`not_found` 的判断，但没有完成该分类要求的机构定向、事件回应和后续材料搜索，被领域 Validator 拒绝。

Run 最终以 `Decision recovery was exhausted: missing-response assessment requires successful scoped response searches` 发布 partial。没有 Finding、Review 或 Conclusion。

## 第二次修正

真实状态表明，只有 1 份材料时直接强制 reflect 会让模型尝试过早处置全部问题。收敛策略调整为：

- 连续两次 duplicate 且仍有未读候选时，下一步必须读取一个候选；
- 已有至少 4 份正文和证据但仍无 Finding 时，才必须 reflect；
- duplicate 且没有未读候选时直接 reflect；
- 首次 reflect 只为已有证据覆盖的内容建立 Finding；无法处置的问题省略 assessment，不能用不满足搜索前提的 not_found 填充。

第二次修正通过 20 项定向测试。根据本轮预设停止条件，没有继续发起模型复跑；真实效果仍为 `NOT_RUN`。
