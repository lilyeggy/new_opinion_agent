# OpinionSearch Agent — 收口一页纸（2026-10-17）

> 读者：面试官，以及三个月后想不起自己做过什么的自己。
>
> 一句话：一个自己写 Runtime 的单 agent Harness，把「公开网络舆情调查」跑成
> **可回放、可复算**的过程，而不是一次性的 prompt 拼装。

## 1. 它解决了什么

对公开网络做舆情调查，有三件事在普通 agent 里没法保证：同一输入不能复现、
中断后状态不可信、报告里的结论说不清来自哪一段原文。这个项目把这三件事当成
一等公民：每一步要么完整提交要么整体丢弃，每一步的外部输出都进 journal，
每条判断都绑定可回溯的摘录区间。

规模：`src/` 24,467 行 / 95 文件，`tests/` 19,790 行 / 91 文件，
**828 passed, 2 skipped**。

## 2. 三个数字（可复现，不是一次性统计）

```bash
make quality-check    # 0 次模型调用 / 0 次网络请求
# quality gate: baseline reproduced exactly
```

| 指标 | 数值 | 口径 |
| --- | --- | --- |
| 检索召回 | **6/10**（已读层） | 10 项人工标注「必须找到」的内容 × 实际已读来源 |
| 忠实性 | **10/14** 完全支持，**0** 无中生有 | 14 条判断逐条核对「绑定摘录是否真的支持它」 |
| 对抗埋点 | **2/3** | 7 篇真实正文 + 3 篇手写埋点，sha256 冻结 |
| 摘录可核 | **110/110** | 摘录落回冻结快照的字符区间 |

三个数字都能被第三方用一条命令重算；口径、标注和边界在
`opinion_search_agent/evaluation/README.md`。

两个必须主动讲的细节：

- 发现层的机械判定是 7/10，人工是 6/10。唯一分歧（大河网「河声」评论）我
  **照实打印在基线里**，而不是把规则调到「刚好等于 6」。人机一致率 9/10。
- 对抗 2/3 丢掉的那一分是「反方稿被读、被摘了 5 条证据，但没有一条判断引用
  它」。被放大 10 倍的数字没进判断层，但以原始摘录留在报告附录里——通过的原因
  是「这轮没轮到综合」，不是「有数字校验收拦截」。这句写在 `baseline.md` 里。

## 3. 六层架构

| 层 | 负责 | 位置 |
| --- | --- | --- |
| Runtime | 生命周期、7 阶段事务、checkpoint/resume、journal/replay | `src/opinion_search/runtime/` |
| Context | L0–L3 有界上下文编译、token 预算、信任边界、注入防御 | `src/opinion_search/context/` |
| Tools | registry、熔断、有界重试、跨进程缓存、多 provider 回退 | `src/opinion_search/tools/` |
| Domain | opinion（4 动作）/ investigation（6 动作）、纯函数 reducer | `src/opinion_search/domain/` |
| Report | 报告契约、投影、校验、渲染 | `report_contract/`、`presentation_skill/` |
| App | 服务层、SSE、workbench、CLI | `app/`、`web/`、`__main__.py` |

关键不变量：状态只能通过纯 `reduce(state, delta)` 变更；模型与网页内容永远是
`Origin.UNTRUSTED`；每个 checkpoint 边界都 `fsync` + `os.replace`。

## 4. 三个取舍（面试主动讲）

**① 为什么只有一个搜索引擎。** 因为我量化过瓶颈在哪：s5-b 那轮 61 个候选里
40 个（66%）来自 `news.qq.com` 一个聚合站，原发媒体站全部零覆盖，17 次读取里
6 次失败也全在 qq.com。接第二个引擎是明确的下一步，但我把它排在「把已有链路的
正确性做扎实」之后——半成品的双引擎不如一个说清边界的单引擎。

**② 为什么是单 agent。** planner/research/analyst/reviewer 的多角色流水线我做过，
评估后归档到 `archive/harness-pipeline/`：它重复了生产路径已有的能力，而且绕开了
Runtime 的可靠性机制（事务、回放、上下文预算）。多角色没有带来新的可验证性。

**③ 为什么自己写 Runtime。** 6 状态 × 7 阶段事务、at-most-once 外部调用、确定性
回放、上下文预算强制降级——这些保障现成框架给不了。代价是 2,552 行 runtime 要自己
维护，收益是「同一输入必然同一输出」这句话可以被验证，而不只是被声称。

## 5. 已知限制（都带数字）

1. 单引擎 + 聚合站偏向：候选域 66% 集中在一个门户，原发站零覆盖。
2. 摘录召回是单点瓶颈：4 条 partial 全部是「引语在原文但摘录没摘到」，不是编造。
3. 数字护栏只验出处不验可信度：真实的 316.03 亿与埋点的 3160.3 亿可以静默并存。
4. 模型不会把长期无证据的问题显式从 `open` 转 `not_found`——completion gate
   因此拒了 `finish` 18 次，最后诚实收在 `partial`。

## 6. 下一步（按投入产出比，均未做）

1. **结构化 QueryPlan + 第二引擎**——唯一能直接抬「检索召回」的改动，成本最高。
2. **数字矛盾检测**——把对抗埋点从「结果层侥幸」变成「机制层拦截」，中等成本。
3. **对抗埋点扩成多案例回归**——成本最低，防止改代码后悄悄退化。

## 7. 五分钟复现

```bash
make install        # 依赖（Python 3.12+）
make test-fast      # 秒级单测
make quality-check  # 三个数字（离线，无需 Key）
make demo           # 确定性离线全链路
make web            # 本地工作台 http://localhost:8900
```

Live 模式需要 `.env`（见 `.env.example`）：一个 OpenAI 兼容模型 + Brave 搜索 Key，
可选 Jina 读取 Key。
