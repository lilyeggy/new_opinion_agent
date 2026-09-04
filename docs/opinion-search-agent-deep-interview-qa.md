# OpinionSearch Agent 深度面试问题集

> 这不是知识点清单，而是一组能够支撑连续追问的核心问题。  
> 建议每题先掌握 60 秒主回答，再理解后面的机制、取舍、失败窗口和代码证据。  
> 文档只陈述当前实现；明确标注为“演进方向”的内容不能当作已完成成果。

## 问题一：为什么你没有使用 LangGraph，而是自己实现 Agent Harness？这是不是重复造轮子？

### 核心回答

是否使用 LangGraph，取决于 Agent Runtime 是项目的实现手段，还是项目本身要研究和交付的能力。如果目标是快速搭建一个业务 Agent，我会优先考虑成熟框架；但这个项目要解决的核心问题正是：一次长程 Agent 运行如何可靠地完成模型决策、工具执行、状态提交、崩溃恢复和上下文重建。

LangGraph 可以提供图节点、状态快照、条件边和持久化接口，但这些抽象会替开发者决定一部分执行语义。本项目希望明确拥有这些语义，因此实现了显式 async loop、Run/Step 双生命周期、step transaction、pure Reducer、checkpoint/resume 和 Completion Control。

所以这不是在声称“自研框架全面优于 LangGraph”，而是在一个刻意收窄的 workload 中，把框架通常隐藏的机制展开并验证。

### 我们具体拥有了哪些框架内部语义

一次 step 不是简单的“调用模型、调用工具、追加消息”，而是明确经历：

```text
opened
-> deciding
-> decision_accepted
-> action_running
-> observation_ready
-> reducing
-> committed
```

每个 phase 都有严格的 payload 不变量。例如 `ACTION_RUNNING` 必须已有 Decision 和 Action，但不能提前有 Observation；`OBSERVATION_READY` 必须三者都存在。checkpoint 如果出现 phase 与 payload 不一致，会在加载时直接失败，而不是由框架或业务代码猜测应该从哪里继续。

Runtime 还显式定义了：

- 决策失败是在同一个 step 内增加 attempt，还是终止 run；
- 外部动作开始前必须保存哪个 checkpoint；
- 工具已经返回、State 尚未提交时怎样恢复；
- step committed 后、完成判断前崩溃怎样处理；
- 重复 delta 为什么只能形成一次状态效果；
- resume 时如何拒绝 schema 或执行组合不兼容的 checkpoint。

这些正是本项目的核心产出。如果直接交给图框架，项目很容易退化为“会使用节点和条件边”，而不是“理解并实现 Agent Runtime 的可靠执行”。

### 与 LangGraph 的真实差异

| 维度 | LangGraph 一类通用框架 | 当前项目 |
|---|---|---|
| 目标 | 支持多种图拓扑和 Agent workload | 只服务一个 OpinionSearch 单 Agent workload |
| 控制流 | 节点、边、interrupt 和框架调度 | 显式 `classify_resume` + async loop |
| 状态约束 | 通用 graph state 与 reducer 机制 | phase-payload、action correlation、domain invariants 全部显式建模 |
| 恢复 | 由 checkpointer 与图执行语义共同决定 | 每个持久 phase 都有明确恢复动作和调用次数断言 |
| 上下文 | 通常由应用自行组织 | L0-L3 Context Compiler 是一等模块 |
| 代价 | 学习框架语义和生态依赖 | 自己承担 Runtime 正确性与维护成本 |

我们的优势是边界窄、机制透明、可针对恢复语义做强约束；LangGraph 的优势是成熟生态、图组合、HITL、已有持久化实现和更快的业务交付。脱离场景声称任何一方“更好”都不专业。

### 面试官可能继续追问

**追问：既然最终还是一个 while loop，自研价值在哪里？**

普通 while loop 只有控制流，没有事务语义。这里每轮都从可持久化状态通过纯 `classify_resume` 决定下一动作；每个副作用前后都有 checkpoint boundary；commit 同时更新 Domain State、step history、action ledger、cursor 和 continuation marker。真正的价值不在 `while`，而在围绕它建立的协议、不变量和恢复证明。

**追问：以后能迁移到 LangGraph 吗？**

可以复用领域 State、Decision schema、Tool Protocol、Observation processor、pure Reducer 和 CompletionPolicy；需要重新映射的是 step transaction、checkpoint phase 和 continuation 语义。迁移前必须验证 LangGraph saver/interrupt 对三个崩溃窗口的行为与当前承诺一致，而不是只把函数包装成 nodes。

**追问：什么时候你会直接选 LangGraph？**

当 Runtime 不是核心竞争力、需求更关心多节点业务编排和快速上线、框架的 checkpoint/HITL 语义已经满足一致性要求时，我会选框架。自研只有在你确实需要拥有这些语义时才值得。

### 代码与验证证据

- `runtime/lifecycle.py`
- `runtime/protocols.py`
- `runtime/transaction.py`
- `runtime/loop.py`
- `tests/e2e/test_recovery_matrix.py`

---

## 问题二：为什么要把 Decision、Action、Observation 和 StateDelta 分成四个对象？模型和工具为什么都不能直接修改 State？

### 核心回答

因为它们代表四个不同的事实阶段，也属于四个不同的责任主体：

```text
Model proposes Decision
Runtime validates and resolves Action
Environment returns Observation
Domain processor proposes StateDelta
Reducer commits new State
```

Decision 是意图，不是命令；Action 是已经通过结构和 state-aware 校验的执行承诺；Observation 只说明外部世界发生了什么；StateDelta 表示领域层希望改变哪些状态。只有 Reducer 能把 accepted delta 写入权威 State。

如果把这些对象合并，模型可能绕过校验产生副作用，工具返回可能绕过领域规则直接成为事实，Runtime 也无法判断崩溃发生在“动作未执行”“结果已获得”还是“状态已提交”。

### 为什么 Decision 不是 ToolCall

当前模型有四种领域决策：`search/read/reflect/finish`。

- `search/read` 需要外部能力，经过 ActionResolver 后成为内部 ToolCall；
- `reflect` 是基于现有 Evidence 提交 Claim、Position、Narrative 和 GapAssessment 的内部 action；
- `finish` 是向 CompletionPolicy 提出的终止建议。

如果 Decision 就是 ToolCall，那么 reflect 和 finish 要么被伪装成假工具，要么会绕开统一生命周期。更重要的是，Decision 中的 `target_gap_id`、`purpose` 和 `focus` 是领域意图，ToolCall 只关心稳定 tool name 与 validated arguments。分开之后，模型不需要知道 Brave、Jina 或 MCP provider 的存在。

### 为什么 ToolResult 不是 Observation

ToolResult 只描述工具执行结果：tool name、payload、artifact refs、attempts。ObservationEnvelope 还要携带 run_id、step_id、attempt、action_id，并且内部 action 也需要生成 Observation。因此 ToolResult 是某类环境结果，Observation 是 Runtime 可以恢复和关联的统一事实。

这个差异在失败时尤其重要：ToolError 可以成为一个合法 Observation，让下一轮 Agent 知道搜索超时或页面不可读；它并不自动意味着 run failed，也不能直接改写 Gap。

### 为什么 Observation 之后还要有 StateDelta

同一个 SearchResults，可以根据领域规则产生不同 delta：

- URL 需要先正规化；
- include/exclude domain filter 必须执行；
- 重复 Candidate 需要合并而不是新增；
- snippet 只能成为 CandidateSource，不能成为 Evidence。

同一个 ReadResult 也不能整体塞进 State：正文应写 artifact，只有经过过滤、去重和 focus 排序的有限 excerpt 成为 Evidence。Observation processor 承担的就是“环境结果如何翻译成合法领域变化”。

### Envelope 解决了什么

Decision payload 本身不知道属于哪个 run 和 step。Envelope 统一携带：

- `run_id`
- `step_id`
- `attempt`
- 对 Action/Observation/Delta 还包括 `action_id`

StepRecord 会验证这些 correlation 完全一致。这样一个旧 Observation 不可能被误提交给新的 attempt，一个 provider 返回也不能替换 action identity。

### 这套设计怎样抑制幻觉

它不能消除模型语义判断错误，但能限制错误的权限：

- 模型可以提出不存在的 Evidence ID，但 state-aware validator 会拒绝；
- 模型可以说某 Gap 已解决，但缺少相应 Claim/Position/Narrative 时无法提交；
- 网页可以包含恶意指令，但它只能作为 untrusted Observation 内容；
- 模型可以提前 finish，但 Completion Gate 可以拒绝；
- 模型不能直接生成新的权威 State 快照覆盖已有证据。

这是“限制模型写权限”，而不是“相信模型更聪明”。

### 面试官可能继续追问

**追问：StateDelta 还是模型间接生成的，真的安全吗？**

Delta 由确定性 processor 根据已经验证的 Decision 和 Observation 构造。Reflect 中确实包含模型提出的语义对象，但 validator 先检查所有引用和领域前置条件，Reducer 再检查全局不变量。模型影响内容，代码控制可写范围和引用完整性。

**追问：为什么不让 Reducer同时做校验和 I/O？**

Reducer 必须能对序列化输入独立重放。加入 HTTP、文件写入或模型调用后，同一 delta 可能产生不同结果，也会在恢复时重复副作用。因此 I/O 在 ActionExecutor，翻译在 processor，纯状态合并在 Reducer。

### 代码与验证证据

- `runtime/protocols.py`
- `domain/opinion/action_resolver.py`
- `app/action_executor.py`
- `domain/opinion/processor.py`
- `domain/opinion/reducer.py`
- `tests/unit/runtime/test_protocols.py`
- `tests/unit/domain/opinion/test_processor.py`
- `tests/unit/domain/opinion/test_reducer.py`

---

## 问题三：工具已经执行成功，但 Agent 在提交 State 前崩溃了，你如何恢复？能保证 exactly-once 吗？

### 核心回答

不能笼统承诺外部请求 exactly-once。项目把问题拆成“外部动作是否重复”和“状态效果是否重复”两层：

- 通过稳定 action_id 和持久化成功结果缓存，尽可能复用已完成的工具结果；
- 通过 committed action ledger 和幂等 commit，保证同一个 delta 不会重复改变 Domain State；
- 因此当前准确承诺是 effectively-once state effect，而不是外部服务 exactly-once。

### 三个关键崩溃窗口

#### 窗口 A：已经保存 ACTION_RUNNING，但还没有保存 Observation

Runtime 知道准备执行哪个 action，却不知道 provider 是否已经响应。resume 保持原 action_id，ToolExecutor 先查询 `JsonActionResultCache`：

- 如果 provider 成功结果已缓存，新进程直接复用，fresh adapter 调用次数为 0；
- 如果缓存 miss，当前 search/read 是只读工具，可以再次执行同一 action；
- 如果缓存损坏，不能当 miss，而要抛 typed read error，因为无法判断动作是否已发生。

持久化缓存缩小了重复请求窗口，但在“provider 已收到请求、结果尚未写缓存”时仍可能重发。这正是不能声称 exactly-once 的原因。

#### 窗口 B：Observation 已保存，但 State 尚未提交

checkpoint 已有完整 ObservationEnvelope。resume 直接进入 `REDUCE_OBSERVATION`，重新构造 delta 并提交，绝不再次调用工具。Reducer 必须确定、无 I/O，才能安全重放。

#### 窗口 C：State 已提交，但调用方还没有得到成功结果

`commit_step` 同时写入新 State、committed step、committed action_id、next_step_index，并设置 `continuation_pending=True`。恢复后先评估 continuation，不再次执行工具或 Reducer。

`continuation_pending` 专门封住“commit 已完成，完成判断尚未完成”的窗口，否则恢复可能错误打开下一 step，或者重放上一 step。

### 为什么 action_id 是核心

逻辑身份关系是：

```text
step_id   = {run_id}:step:{step_index}
action_id = {step_id}:attempt:{attempt}:action
```

模型修复 Decision 会增加 attempt，因此产生新的 action identity；Executor 内的 timeout retry 和 provider fallback 仍是同一个业务动作，因此 action_id 不变，只有 `ToolInvocation.attempt` 增加。

action_id 同时贯穿：

- ActionRequest 与 ObservationEnvelope correlation；
- ToolResult cache key；
- committed action ledger；
- StateDelta replay；
- recovery matrix 的调用次数验证。

### checkpoint 自身如何可靠

checkpoint 外层保存 schema version、execution profile 和完整 RunState。写入流程是：

```text
temporary file
-> deterministic JSON
-> flush
-> fsync
-> os.replace
```

这样不会在进程中断时留下半个正式 JSON。schema version 防止新代码误读旧状态；execution profile 防止用另一套模型/工具 composition 恢复同一 run，同时不保存密钥和 provider 配置。

### 为什么这仍然不是分布式 exactly-once

真正的外部 exactly-once 通常需要 provider 接受幂等键、共享事务存储、outbox/inbox 或协调协议。当前结果缓存只有单机文件原子性和进程内锁；两个进程同时恢复同一未缓存 action，仍可能都调用 provider。

生产化时至少需要：

- run ownership 或 lease；
- action record 的 compare-and-set；
- provider 支持时传递 action_id 作为 idempotency key；
- 对有副作用工具定义补偿或人工确认策略。

### 面试官可能继续追问

**追问：为什么缓存损坏不直接重新执行？**

因为 miss 表示“从未记录成功”，损坏表示“可能记录过成功但证据丢失”。二者风险不同。把损坏降级为 miss 会把不确定性隐藏成安全重试。

**追问：取消发生在 Observation 已落盘之后怎么办？**

在 reduction 阶段延迟取消，先把已观测结果 commit，再终止 run；否则恢复后同一 Observation 的命运取决于取消时序。取消只中止本地协程，不承诺远端回滚。

### 代码与验证证据

- `runtime/transaction.py`
- `runtime/checkpoint.py`
- `runtime/cancellation.py`
- `tools/persistent_cache.py`
- `tests/e2e/test_action_running_recovery.py`
- `tests/e2e/test_recovery_matrix.py`
- `tests/integration/test_checkpoint_resume.py`

---

## 问题四：你的 Tool Runtime 如何区分 retry、fallback 和 Agent 再规划？为什么这些策略不能交给模型？

### 核心回答

三者发生在不同层次：

- retry：同一个 provider 对同一个 action 的瞬时错误恢复；
- fallback：同一个 capability 对同一个 action 切换 provider；
- Agent 再规划：执行层已经给出最终 ToolError 后，模型改变 query、candidate 或调查方向。

retry 和 fallback 是确定性执行策略，由 ToolExecutor 统一拥有；模型只负责领域策略。如果让模型处理底层重试，每次 retry 都可能变成新 step、新 action_id，既污染调查历史，也无法统一控制退避、限流和熔断。

### Tool Runtime 的执行顺序

```text
resolve registered tool
-> validate arguments
-> result cache lookup
-> iterate ordered providers
   -> circuit gate
   -> bounded local retries
   -> timeout/error normalization
   -> success cache or fallback decision
-> stable ToolResult / ToolError
```

Registry 只负责稳定 ToolDefinition 与有序 ProviderBinding。Executor 负责校验、缓存、timeout、retry、backoff、circuit、fallback 和安全错误。Adapter 每次只做一次供应商协议翻译，不自行实现第二套 retry。

### 为什么同一个工具可以绑定多个 provider

模型应该看到 `search.web` 或 `read.web` 这样的能力，而不是 Brave、Jina 或某个 MCP server。Registry 允许同一完全相等的 ToolDefinition 绑定多个 provider；definition 不一致时拒绝追加，避免“模型看到同一 schema，实际 provider 接受不同参数”。provider_id 与 adapter 从不进入 model specs。

### typed error 如何决定策略

当前同 provider 有界重试主要针对：

- timeout；
- rate_limited；
- server_error。

invalid_arguments、unknown_tool、cancelled 立即停止。authentication、permission、not_found、unreadable_content、content_too_large、unknown_provider_error 等不在同 provider 盲目重试，但可以按照固定 fallback 表尝试另一个 provider。

指数退避受最大值限制，并尊重 provider 的 retry-after。`ToolInvocation.attempt` 是跨 provider 的全局物理调用次数，action_id 始终不变。

### Circuit Breaker 为什么按 tool/provider 隔离

如果只按 provider 熔断，某个工具接口故障会让该 provider 的其他能力一起不可用；如果只按 tool 熔断，一个 provider 的故障会遮蔽另一个健康 provider。因此 key 是 `(tool_name, provider_id)`。

只有 timeout、rate-limit、server 和 unknown provider error 会毒化 circuit；authentication/permission 是配置问题，不应通过 cooldown 假装自愈。half-open 只允许单 probe，成功关闭，毒化失败重新打开，非毒化失败也必须释放 probe。

### 错误为什么必须使用 safe message

原始异常可能包含 endpoint、response body、command、header 甚至 credential。如果直接把异常文本反馈给模型，就把 provider 边界变成数据泄漏路径。Adapter 只能抛带固定 safe_message 的 ToolAdapterError；未知异常统一变成不含 `repr` 的 `unknown_provider_error`。

### 一个具体安全取舍：不自动跟随 redirect

Brave 使用自定义 credential header。跨域 redirect 时，不能假设 HTTP client 会剥离所有非标准鉴权头，因此通用 transport 设置 `follow_redirects=False`，3xx 交给 adapter 正规化。这牺牲了自动跳转便利，换来 credential 不被意外带到第二域名。

### 面试官可能继续追问

**追问：fallback 后还是同一个 action 吗？**

是。业务意图和参数没变，只是执行 provider 改变，所以 action_id 恒定，attempts 累加。只有模型收到最终失败后生成新的 Decision，才进入新的 Agent attempt 或 step。

**追问：为什么只缓存成功结果？**

临时失败若缓存，会让恢复永久复用旧 timeout/rate-limit；成功结果才用于 at-most-once 复用。cache identity conflict 是程序错误，不能转成普通 ToolError。

**追问：circuit 重启后怎么办？**

当前 circuit 是内存级保护，重启重置。这是单 Runtime 的明确边界；多 worker 生产环境需要共享 provider health 或 Tool Gateway。

### 代码与验证证据

- `tools/contracts.py`
- `tools/registry.py`
- `tools/routing.py`
- `tools/executor.py`
- `tools/circuit.py`
- `tools/http.py`
- `tests/unit/tools/test_executor.py`
- `tests/e2e/test_tool_fallback.py`

---

## 问题五：MCP 只是接个协议，为什么你的项目在 MCP 边界做了 allowlist、schema pin 和递归元数据过滤？

### 核心回答

MCP 解决的是工具发现和调用的互操作性，不自动解决授权、契约稳定和内容信任。远端 server 能控制工具列表、schema、description、annotations 和返回 content；如果把这些直接暴露给模型或 Runtime，就相当于让外部服务动态扩大 Agent 权限并向上下文注入控制信息。

因此项目坚持“内部 Tool Protocol 先成立，MCP 只是 adapter”，并在 discovery、registration、transport 和 result projection 四个位置收紧边界。

### Discovery 的完整安全流程

```text
paginate all tools
-> detect cursor cycles
-> reject duplicate remote names
-> require explicit allowlist match
-> verify canonical input/output schema hashes
-> check local Registry conflicts
-> atomically register all bindings
```

任何一步失败，Registry 保持不变。这样不会出现三个工具中前两个已注册、第三个 schema 不匹配的半更新状态。

本地工具名使用 `mcp.<server_id>.<remote_name>` namespace，防止不同 server 的同名工具冲突。模型看到的 description 只来自 app config，不使用 remote prose；remote annotations 没有策略权威。

### schema pin 的意义

允许某个工具名不代表允许它随意改变参数或输出结构。canonical schema hash 对排序稳定的 JSON schema 做 SHA-256；server schema 变化时必须由应用显式更新 pin。错误只暴露 remote name 和 expected/actual hash，不把整个未知 schema 放进日志或模型上下文。

### 为什么需要递归元数据过滤

最初只剥顶层 `_meta/meta/annotations` 存在 laundering 路径：远端可以把 metadata 放在 EmbeddedResource.resource 或更深的 content block 中，经过外层包装后进入普通 payload。

第二版若先对整个对象 `model_dump(mode="json")` 再删除 metadata，又有一个异常路径：攻击者在本来应该丢弃的 metadata 内放不可序列化对象，序列化会在过滤前失败，Pydantic 异常穿透 adapter。

最终策略是：

1. 根据 BaseModel 字段名和 alias 判断 metadata；
2. 在序列化之前跳过这些字段；
3. 对 Mapping、sequence 和嵌套模型递归投影；
4. 检测当前递归路径中的循环引用；
5. 最后验证整个公开投影是 JsonValue；
6. 所有失败归一为固定安全 ToolAdapterError。

这体现了“先过滤、后验证”，而不是在不可信对象上先执行复杂序列化。

### output schema 为什么 fail closed

如果应用 pin 了 output schema，但 server 只返回非结构化 content，项目不会降级成“尽量解析文本”，而是直接失败。否则 schema pin 只约束了一个实际上没有被使用的字段，契约形同虚设。

### Transport 层还有哪些边界

- stdio 的 environment 是显式 allowlist，不继承整个进程环境；
-生产 HTTP 必须是正规化后的公开 HTTPS；
- loopback HTTP 只允许显式 development opt-in；
- 每次 SDK 操作开闭 client context，不支持 stateful session 复用；
- transport/SDK 异常被归一化，不泄漏 command、headers、payload 或异常 repr。

### 面试官可能继续追问

**追问：MCP 已经通过 HTTPS 了，为什么还不可信？**

HTTPS 证明传输加密和服务器身份，不证明返回内容拥有系统指令权限。信任按内容生产者划分，不按传输是否加密划分。

**追问：为什么不直接动态注册 server 返回的所有工具？**

discovery 是能力发现，不是授权。动态全注册会让 server 通过新增工具扩大 Agent attack surface，也会让模型上下文和行为在应用未变更时漂移。

### 代码与验证证据

- `tools/adapters/mcp.py`
- `tools/adapters/mcp_sdk.py`
- `tests/contract/test_mcp_adapter.py`
- `tests/contract/test_mcp_sdk_transport.py`
- `tests/e2e/test_real_mcp_tool.py`

---

## 问题六：为什么你把 Context 做成 Compiler，而不是直接维护聊天历史？压缩以后还能找回原始证据吗？

### 核心回答

长程 Agent 的上下文不是聊天记录，而是一个受模型窗口、任务相关性、信任边界和恢复要求共同约束的临时执行环境。简单 `messages.append()` 会导致历史线性增长、重复内容堆积、重要规则被挤出、外部文本与控制指令混杂，并且 resume 后依赖进程内消息对象。

本项目每轮都从 committed State 重新投影 Working Memory，再经过确定性的 Context Compiler 生成一次性输入：

```text
collect
-> select
-> deduplicate
-> compact
-> render
-> measure
-> overflow fallback
```

压缩只影响这一轮模型看见什么，不删除 Full State 和 Artifact，所以仍能沿 provenance 找回原始内容。

### 五类对象为什么必须分开

| 对象 | 职责 | 是否权威 | 是否持久化 |
|---|---|---:|---:|
| Full Domain State | 完整领域事实与关系 | 是 | 是 |
| Working Memory | State 的紧凑认知投影 | 否 | 否，可重建 |
| Artifact | 完整网页正文和大型对象 | 原始材料 | 是 |
| Recent Interaction | 最近步骤的高保真窗口 | 否 | 来源在 StepRecord |
| Compiled Context | 单次模型调用输入 | 否 | 否 |

Working Memory 不能覆盖 State，也不能通过摘要创造新事实。它被删除后重新投影必须得到相等结果。

### L0-L3 如何分层

- L0：不可变 instruction、action 协议和不信任外部内容规则；
- L1：SearchRequest、TaskFrame、decision schema、tool specs；
- L2：Gap coverage、Evidence、Claim、Position、Narrative、候选和失败方向；
- L3：近期 Decision、Observation、错误和 completion rejection。

L0/L1 是 required、trusted、不可压缩的 floor；L2/L3 根据 current gap、priority、recency 和预算选择。输入预算先减 output headroom，防止上下文占满窗口后模型没有空间输出结构化 Decision。

### 选择和压缩怎样保持确定性

selector 使用稳定排序键，dedup key 包含 trust、origin、layer 和 normalized content，不会把不同来源或权限的相同文本合并。Compactor 先截断允许截断的旧 untrusted L3，再删除低优先级 optional section；required floor 放不下时抛 `RequiredContextOverflow` 并 partial stop，而不是截断系统规则或最终字符串尾部。

CompiledContext 保存最终内容 SHA-256 和每个 section measure。相同 State、配置和 estimator 应生成相同 render/hash，resume 不依赖隐藏消息历史。

### 640 条 Evidence 为什么不会全部进入 prompt

模型 Reflect 时需要准确复制 opaque Evidence ID，所以关键目录必须保留；但全量 required catalog 会无限增长。当前 catalog 分为：

- 当前 required evidence，最多 64；
- history chunks，每块 64，属于 optional；
- coverage 每个 Gap 最多采样 16 个 ID，同时保留 evidence_count 和 source_count。

选择优先使用 semantic relation：当前 Gap 的 semantic evidence、contested evidence、其他 semantic evidence、unlinked evidence，再到仅为当前 Gap 获取的 evidence。这样“为某 Gap 搜到”不会压过“实际支持该 Gap”。

### 压缩后如何溯源

Evidence 保存 source_id、excerpt 和 locator，Source 保存 artifact_ref；ProvenanceIndex 保存 Evidence 与 semantic Gap、Claim、Position、Narrative 的关系。即使某段正文没有进入当前 Context：

```text
Claim/Narrative
-> Evidence ID
-> Source ID
-> artifact_ref
-> original normalized content + locator
```

因此 Compaction 是可逆的“本轮视图选择”，不是删除事实。目前缺少让模型主动 re-read artifact 局部内容的专用 action，这是下一步可补的能力；但人工审计和报告溯源已经存在。

### Prompt injection 边界

每个 ContextSection 同时有 origin 和 trust：model/tool/provider 永远不能 trusted，即使内容已经 commit、checkpoint 或 resume。priority 与 trust 正交：外部证据可以非常重要，但没有指令权限。

混合内容会拆分，例如 ToolError 的 kind/attempt/action_id 属于 runtime/trusted control，provider message 属于 provider/untrusted prose。Renderer 还会转义外部正文伪造的 `[CONTEXT_SECTION ...]` 标记。

### 面试官可能继续追问

**追问：token estimator 准吗？**

当前是启发式估算，可注入测试 estimator，不保证与 DeepSeek tokenizer 逐 token 一致。生产化应使用模型 tokenizer，并保留 provider length error 兜底。项目证明的是选择和降级机制有界，不是某个估算公式绝对精确。

**追问：为什么不用向量数据库？**

当前是单 run、数百 Evidence，首先需要确定性引用和恢复，不是百万文档召回。向量库会引入 embedding 版本、召回不确定性和第二事实源风险；当 artifact 规模超过结构索引能力时，可以把向量检索作为派生索引加入，但不能取代 State。

### 代码与验证证据

- `context/models.py`
- `context/compiler.py`
- `context/selector.py`
- `context/compactor.py`
- `context/catalog.py`
- `memory/projector.py`
- `domain/opinion/provenance.py`
- `tests/integration/test_context_long_trajectory.py`
- `tests/security/test_context_injection_matrix.py`

---

## 问题七：普通 Search Agent 是寻找答案，你的舆情 Search Agent 搜索的到底是什么？如何避免结果只是散乱材料？

### 核心回答

舆情调查通常没有唯一正确答案。系统真正要建立的是一张 evidence-linked opinion map：发生了什么、哪些主体公开表达了什么、主要叙事如何组织事实、有哪些反叙事或争议、哪些结论仍然缺证据。

因此当前领域状态不只保存 SearchResult，而是保存：

```text
CandidateSource
-> Source
-> Evidence
-> Claim
-> StakeholderPosition
-> Narrative
-> GapAssessment
-> FinalSynthesis
```

四个固定 Investigation Gap——事实基线、主体立场、主导叙事、反叙事——保证 Agent 不会找到几篇支持同一观点的页面就直接结束。

### 为什么 Candidate、Source、Evidence 必须分开

Search snippet 是搜索供应商截断和重写的导航信息，所以只能生成 CandidateSource。页面成功 read 并正规化后才产生 Source；从正文中选出的可定位 excerpt 才是 Evidence。

完整正文以内容寻址 artifact 保存。进入 State 前过滤推广、登录注册、导航密集、图片/标记为主和低信息 block，重复内容去重，再按当前 read focus 做确定性排序；每个 Source 默认最多提交三条 Evidence。这样 State 不会变成网页 dump，但 Evidence 仍可通过 locator 回到未破坏的 artifact。

### acquisition 和 semantic provenance 是舆情闭环的关键

一个页面可能是为了寻找 counter narrative 而读，但正文只提供事实；也可能为事实基线而读，却包含某个 stakeholder 的立场。

因此：

- `target_gap_id`、`discovered_for_gap_ids`、`acquired_for_gap_id` 只记录为什么获取；
- Evidence 对哪个 Gap、Claim、Position 或 Narrative 有语义作用，必须由 Reflect 显式提交；
- validator 检查引用的 Evidence ID 真实存在；
- Reducer 才把 semantic relation 写入 State。

这避免了最常见的错误：把“搜索过某个方向”当成“这个方向已经被证据覆盖”。

### Gap 如何被关闭

模型负责提出语义判断，但没有最终写权。resolved Gap 除了 Evidence，还必须存在维度对应的 semantic record：

- factual baseline：与该 Gap Evidence 相交的 fact Claim；
- stakeholder：StakeholderPosition；
- dominant narrative：dominant 或 emerging Narrative；
- counter narrative：counter Narrative。

模型若只说“我认为已经解决”，没有相应对象和真实 Evidence ID，会被 state-aware validator 拒绝，并在下一轮 Context 中收到安全、结构化的修复反馈。

### 如何避免散乱报告

早期系统虽然有 Evidence 和 Gap，却容易把审计明细直接当最终报告，导致用户看到很多离散点。当前通过两层收口：

1. accepted finish 必须提交 `FinalSynthesis`，先给 evidence-linked 结论和 limitations；
2. 从 committed State 构建 typed `SearchReportView`，按结论、Claim、主体立场、Narrative、Gap coverage、Evidence appendix 和 Source 分层，再确定性渲染 Markdown。

因此报告不再从 trace 临时拼接，也不让前端反向解析 Markdown 恢复关系。

### 当前搜索策略的诚实评价

当前已经形成可靠执行闭环：

```text
gap
-> search
-> candidate
-> read
-> evidence
-> reflect semantic coverage
-> completion feedback
-> next action
```

但它仍然是固定四 Gap 驱动，搜索质量层没有完全成熟。它缺少动态主题/意图拆解、holder-target-aspect 结构、对比查询模板、information gain 和 saturation。因此当前可以说“有舆情语义约束的 Search Agent”，不能说“已经完成最优舆情搜索策略”。

### 演进方向：真正的 coverage-driven opinion search

下一阶段可以增加：

- `OpinionAnalysisFrame`：subject、event、time、stakeholder、aspect、risk question；
- `SearchIntent`：事实确认、主体立场、争议、反证、时间变化、来源追溯；
- `OpinionSignal`：holder、target、aspect、stance/sentiment、time、evidence；
- `CoverageMap`：统计不同主体、议题、立场、时间和来源的覆盖；
- contrastive query：主动搜索支持/反对、官方/媒体/专家、早期/后续修正；
- information gain 与 saturation：按新增语义信号而不是页面数量决定下一步和停止。

这些是明确设计方向，目前没有实现，面试中应作为“下一步如何深化”的回答。

### 面试官可能继续追问

**追问：Gap 的语义判断是不是仍然依赖模型？**

是，模型负责判断 excerpt 的语义含义；确定性代码负责引用存在性、对象类型、时间范围、Gap 状态转换和 Completion Gate。系统不是消灭模型推理，而是限制模型推理能直接改变的范围。

**追问：为什么不只做 sentiment analysis？**

sentiment 只能表达表面极性，不能回答谁针对什么对象、在哪个 aspect、依据什么证据持什么立场，也无法表达事实争议和叙事框架。舆情分析需要 holder-target-aspect-stance-evidence 关系，正负面只是其中一个 signal。

### 代码与验证证据

- `domain/opinion/state.py`
- `domain/opinion/decisions.py`
- `domain/opinion/processor.py`
- `domain/opinion/reducer.py`
- `domain/opinion/completion.py`
- `domain/opinion/brief.py`
- `tests/unit/domain/opinion/`

---

## 问题八：模型为什么不能自己决定结束？你的 Completion Gate 如何避免“有材料但没有结论”和“单方证据过早结束”？

### 核心回答

模型的 finish 只是 proposal，因为模型会受上下文长度、最近材料、生成偏好和推理预算影响，不能同时充当研究者和验收者。Runtime 将 FinishDecision 交给 Domain CompletionPolicy，得到四类结果：

- accept_complete；
- reject_and_continue；
- accept_partial；
- safety_stop。

只有 accepted finish 才把模型 answer candidate 转成 `FinalSynthesis` 提交 State；rejected finish 不产生任何状态变化。

### Completion 不只是“每个 Gap 都 resolved”

当前完整完成至少要求：

1. Finish 提议的 resolved/unresolved Gap 集合与 committed State 一致；
2. 没有 open Gap；
3. 存在 Source 和 Evidence；
4. factual baseline 有 evidence-linked fact Claim；
5. stakeholder dimension 有 evidence-linked Position；
6. dominant dimension 有 dominant/emerging Narrative；
7. counter dimension 有 counter Narrative；
8. semantic coverage 至少来自两个 distinct Source records；
9. contested Claim 的正反证据跨至少两个 Source；
10. 有界时间任务中，resolved Evidence 的页面发布时间已知且在窗口内。

source_kind 不参与权限或真实性判断，因为它只是模型生成的分析标签。当前“两个 Source”也是 URL-level record 多样性，不等于 publisher independence。

### reject、partial 和 failed 的语义区别

如果还有 open Gap，finish 被 reject，Agent 获得 completion rejection 后继续调查。若所有 Gap 已关闭但有 blocked、来源不足、缺少语义对象或时间证据无效，则可以 accept_partial：系统已有可交付成果，但不满足 complete 质量标准。

failed 表示无法形成可靠运行结果，例如 reducer invariant、checkpoint corruption 或从未成功提交且修复耗尽。partial 保留已 committed 成果，不是把失败换个名字。

### FinalSynthesis 为什么必须提交到 State

如果最终结论只存在于最后一次模型响应或 trace：

- checkpoint resume 后未必能重建同一结论；
- Web server 重启只能看到 Evidence 明细；
- report 需要重新调用模型或解析历史消息；
- 无法校验最终总结引用的 Evidence 是否 committed。

FinalSynthesis 保存 summary、Evidence IDs 和 limitation Gap IDs。它只在 finish 被接受后进入权威 State，使最终结论可 checkpoint、可恢复、可审计。

### 时间范围为什么既在 Reflect 又在 Completion 校验

Reflect validator 提前阻止未知或窗口外 Evidence 关闭 Gap，给模型修复机会；CompletionPolicy 再对 committed State 做最终防线，避免旧 checkpoint、边界 bug 或组合变化绕过前置校验。这不是无意义重复，而是 input validation 与 terminal invariant 的双层防御。

TaskFrame 在 run 创建时冻结 anchor date，resume 不会按第二天重新解释“过去一周”。Reader 只有在 provider 提供可解析发布时间时才标 `reported`，不允许模型从正文猜日期。

### 面试官可能继续追问

**追问：CompletionPolicy 会不会过于僵硬？**

固定四维适合当前 Milestone 的可测试基线，但确实不适合所有舆情任务。下一步应由 OpinionAnalysisFrame 动态生成 required coverage，再让通用 completion engine 检查 CoverageMap；Runtime 的 completion protocol 无需改变。

**追问：模型仍然编写 FinalSynthesis，如何防止它写入无证据内容？**

当前至少校验引用 ID 必须来自 committed State，报告的结构化章节也从 State 投影；但 summary 文本的逐句 entailment 仍主要依赖模型。这是后续可增加 claim-level citation coverage 或 verifier 的位置，当前不能声称完全解决生成幻觉。

### 代码与验证证据

- `runtime/completion.py`
- `domain/opinion/completion.py`
- `domain/opinion/state.py`
- `domain/opinion/brief.py`
- `tests/unit/domain/opinion/test_completion_policy.py`
- `tests/unit/domain/opinion/test_brief.py`

---

## 问题九：你如何证明这个系统不是“代码很多但没有真正跑通过”？哪些测试真正证明了设计，而不是堆数量？

### 核心回答

当前验证数字是非 Web `561 passed, 2 skipped`，Web E2E `11 passed`，合计 `572 passed, 2 skipped`。但面试中我不会只报测试数量，而会说明每组测试对应哪个系统不变量和失败窗口。

### 最关键的五类证据

#### 1. Recovery Matrix：证明恢复控制流

测试直接构造每种持久状态：created、无 active step、deciding、decision accepted、action running、observation ready、reducing、committed+continuation、terminal。

每行不只断言“最终完成”，还断言 model、resolver、adapter、processor 和 reducer 的调用次数，以及 step_id、attempt、action_id 和 revision。例如 Observation 已保存时 adapter 调用必须为 0；否则系统虽然结果正确，却可能重复外部请求。

#### 2. ACTION_RUNNING 跨进程缓存恢复

测试先让旧 Executor 调用 provider 并把成功结果写 cache，但不把 Observation 写入 state，模拟精确崩溃窗口；随后用全新的 registry、adapter、executor、cache 和 loop resume。断言 fresh adapter 调用 0、原 action_id 不变、state revision 只增加一次。

#### 3. 100-step / 640-Evidence 长轨迹

构造 100 个 committed steps、80 个 Source/Candidate、640 条 Evidence、contested Claim、Position、Narrative 和恶意 section marker。固定 80K budget 下 10/50/100 步都能编译，required catalog 不超过 64，coverage sample 不超过 16，两次编译 hash 相同，JSON resume 后 rendered/plan/hash 相同。

这证明 Context 的有界性、确定性和无进程内隐藏状态，不只是“prompt 没报错”。

#### 4. 14 路 Prompt Injection Matrix

覆盖 search snippet、reader excerpt、MCP structured/unstructured content、模型 query/focus/reflection、gap rationale、Decision prose、ToolError message、validation error、completion rejection、checkpoint resume 和伪造 section marker。

统一断言：哨兵内容只能位于 untrusted section，L0/L1 不受污染，trusted control 不包含 provider/model prose，resume 不提升 trust。

#### 5. Contract 与真实边界 E2E

Fake/Brave/Jina/MCP adapter 共享内部 contract；真实本地 stdio MCP 经过 discovery、allowlist、schema pin、Registry、Executor、adapter、SDK transport 到 ToolResult；Web E2E 覆盖启动 run、SSE、snapshot、取消、历史恢复和报告。两个默认 skip 是需要真实 provider key 的 live-gated smoke，不是静默跳过核心测试。

### 三个能体现工程深度的故障故事

#### 空 Decision

现象是模型调用成功但 structured Decision 为空。通过独立连通性请求、checkpoint 稳定复现和安全响应 metadata，定位到 reasoning token 消耗了硬 completion 上限，`finish_reason=length`。修复不是无脑重试，而是取消请求体硬 token 限制并增加 contract assertion。

#### Evidence ID 别名

模型把 opaque hash ID 改写为顺序别名。系统没有模糊匹配，而是保留严格 validator，同时增加 bounded required ID catalog、L0 复制规则和 known-ID repair feedback。这证明严格契约要配合可恢复上下文。

#### MCP metadata laundering

从顶层 metadata 剥离，逐步发现嵌套洗白和“过滤前序列化”异常路径，最终改成递归、先过滤后验证并测试循环引用。这个故事比“我们做了输入校验”更能证明真正处理过边界。

### 测试数字的诚实表达

仓库仍在演进，所以简历适合写“570+ 自动化测试”，面试现场可补充当前精确数字和日期。测试环境禁止 bind loopback 时，Web tests 会因 PermissionError 失败；在允许本机回环 socket 的环境单独运行是 11 passed。这属于测试环境权限，不应伪装成代码失败或忽略不报。

### 面试官可能继续追问

**追问：为什么没有 benchmark 分数？**

项目聚焦 Harness/Tool/Context 两层，当前测试验证软件正确性，不建设 Eval Infra。对于最终搜索质量，确实还需要独立 scenario dataset、citation correctness、coverage 和 report quality 指标；它是后续领域深化的一部分，当前不拿单元测试数量冒充效果评测。

**追问：测试都是自己写的，会不会只验证自己的假设？**

风险存在，所以关键测试从故障模型出发：构造撕裂 phase、损坏 cache、跨进程 fresh components、恶意 MCP payload、注入矩阵和长轨迹，而不是只复现实现路径。真实 provider smoke 和 stdio MCP E2E再验证 adapter 假设，但仍需要未来的真实舆情数据集验证领域效果。

### 代码与验证证据

- `tests/unit/`
- `tests/contract/`
- `tests/integration/`
- `tests/security/`
- `tests/e2e/`
- `docs/opinion-search-agent-implementation-memory.md`

---

## 问题十：这个项目如果作为三个月实习项目，目前够不够？最大的不足是什么？你会如何继续深化但不把方向做散？

### 核心回答

作为 Agent Infra 方向的校招或实习项目，当前已经能支撑深入面试，因为它不是调用模型和搜索 API 的薄封装，而是具备显式 Runtime、恢复语义、Tool/MCP 边界、Context/Memory、领域状态和系统化故障测试。

但如果声称是完整三个月业务成果，当前最明显的问题是“基础设施深度强于舆情搜索质量”：系统已经能可靠运行，却仍主要依赖固定四 Gap 和模型语义推理，动态意图拆解、观点信号抽取、coverage-driven 查询和效果评测不够成熟。

继续深化时不应该再横向加入多 Agent、向量库、sandbox 或分布式队列，而应沿两条已经确定的主线向下做深。

### 第一条主线：把 Harness 的正确性推到更接近生产

当前单机恢复语义已经清晰，下一层不是马上建设 Control Plane，而是先补最直接的可靠性缺口：

1. 为 run 增加单执行者 ownership/lease，解决两个进程同时恢复；
2. 将 checkpoint/action result 抽象替换为支持 CAS 的持久后端，同时保留当前 schema 与 phase 语义；
3. 对副作用工具引入 idempotency capability metadata，明确哪些 action 可安全重试；
4. 增加 artifact re-read/retrieval action，使 Context 压缩后 Agent 能主动取回局部原文；
5. 自动生成 recovery/capability manifest，避免文档和测试数字漂移。

这些仍属于 Harness/Tool/Context，不需要把项目扩张成平台。

### 第二条主线：把舆情搜索从固定 Gap 推向语义覆盖闭环

最值得做的不是接更多搜索 API，而是让每次搜索行动有明确的舆情信息目标：

```text
User task
-> OpinionAnalysisFrame
-> missing Coverage cell
-> SearchIntent
-> contrastive query
-> Source/Evidence
-> OpinionSignal
-> CoverageMap update
-> information gain / saturation
-> synthesis
```

具体深化顺序应该是：

1. 定义 OpinionAnalysisFrame，把主题、事件、时间、stakeholder、aspect 和风险问题冻结为任务结构；
2. 定义有限 SearchIntent taxonomy，而不是让 query 只带自由文本 purpose；
3. 从 Evidence 提取 holder-target-aspect-stance-time-source 结构化 OpinionSignal；
4. 建 CoverageMap，能回答哪些主体/议题/立场/时段缺失；
5. 增加 contrastive search 和 source-family diversification；
6. 用 marginal information gain 与 saturation 作为下一步和停止信号；
7. 建小规模真实舆情 scenario，评估 citation correctness、coverage completeness、stance consistency 和 synthesis coherence。

这条主线会直接改善用户已经观察到的“结果散乱”，同时继续用现有 Runtime 验证长程执行。

### 为什么不优先做多 Agent

多 Agent 可以并行调查不同维度，但它不会自动解决语义覆盖和报告质量；反而增加任务分配、状态合并、冲突、并发 checkpoint 和失败传播。如果单 Agent 不知道要覆盖哪些 holder/aspect，把它复制成四个 Agent 只会并行地产生更多散乱材料。

正确顺序是先把单 Agent 的 OpinionAnalysisFrame、Signal 和 CoverageMap 做清，再判断哪些独立 SearchIntent 值得并行成 subagent。

### 为什么不优先接更多 provider

当前 Brave/Jina/Fake/MCP 已经证明 Tool Protocol 可替换，更多 adapter 的边际价值主要是供应商覆盖，不会提升 Agent 核心机制。除非真实运行证明 Brave 在某类来源覆盖不足，否则应优先改搜索策略、语义抽取和 synthesis，而不是堆 API logo。

### 简历与面试的正确表述

可以强调：

- 实现显式单 Agent Runtime 和 step transaction，覆盖三个崩溃窗口与跨进程结果复用；
- 构建统一 Tool/MCP Runtime，集中管理 retry/fallback/circuit/cache 与不可信输入；
- 构建 L0-L3 Context Compiler 和 State-derived Working Memory，通过长轨迹与注入矩阵验证；
- 用 evidence-linked 的舆情领域状态和 Completion Gate 跑通真实公开 Web 调查。

不应声称：

- 支持分布式多租户执行；
- 已实现完整舆情意图识别和全网观点覆盖；
- 有严格外部 exactly-once；
- source diversity 已做到媒体所有权独立；
- 单元测试等同于搜索质量 benchmark。

### 面试官可能继续追问

**追问：只能选一个下一步，你选什么？**

我会先实现 OpinionAnalysisFrame + SearchIntent + CoverageMap 的最小纵向闭环。原因是当前 Runtime 已经足以承载复杂迭代，而最影响最终价值的是 Agent 不知道“下一次搜索为了补哪一类舆情语义覆盖”。先解决决策质量，再考虑并行和平台化。

**追问：这个方向还是 Agent Infra 吗？**

是。OpinionAnalysisFrame 和 CoverageMap 属于 Domain Policy，但它们会反过来验证 Context selection、Working Memory 投影、Completion Control 和长程 Loop 是否真的支持复杂 workload。项目并不是只做领域 NLP，而是用更真实的领域控制信号检验前两层 Infra。

### 当前验证基线

- 非 Web：`561 passed, 2 skipped`
- Web E2E：`11 passed`
- 合计：`572 passed, 2 skipped`
- 100 steps / 640 Evidence 长轨迹
- 14 路 prompt injection matrix
- 三崩溃窗口 recovery matrix
- Fake、Brave、Jina、MCP 和 OpenAI-compatible 模型边界

---

## 最后的使用方法

不要逐字背诵全文。每一道题只背下面四句话的骨架：

1. **我解决的具体问题是什么。**
2. **我把责任拆给了哪些对象，为什么不能合并。**
3. **最危险的失败窗口是什么，我如何验证。**
4. **当前承诺到哪里，下一步是什么。**

如果能围绕这四句话持续回答追问，这 10 道题已经足以覆盖本项目绝大多数高质量 Agent Infra 面试。

