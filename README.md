# OpinionSearch Agent

> **An evidence-driven, recoverable single-agent Harness for public-Web opinion investigation.**
> Built with pure Python 3.12+, zero heavy framework dependencies (no LangChain/LangGraph), explicit async state-machine loop, multi-phase transactional recovery, bounded context compilation, and deterministic state reduction.

---

## Highlights & Technical Guarantees

- **Domain-Agnostic Runtime (`runtime/`)**: Explicit async loop driven by a pure-function state classifier (`classify_resume`), decoupled from business domains via 11 Protocol contracts and 1 pure Callable reducer.
- **Strict Lifecycle & Transaction Boundaries**: 6-state `RunStatus` and 7-phase `StepPhase`. Atomic JSON snapshot checkpoints (`fsync` + `os.replace`) ensure deterministic recovery at any crash point.
- **Pure-Function State Reducer**: Authoritative state transitions are strictly deterministic and idempotent; untrusted LLM outputs or observation payloads cannot mutate state directly without validation and delta reduction.
- **Bounded Context & Untrusted Origin Tracking**: Multi-layer context model (L0–L3) with strict `TrustBoundary` validation, heuristic token estimation, prioritized degradation compaction, and 14-way adversarial injection defenses.
- **Tool Runtime & Reliability Layer**: Unified `ToolRegistry` and `ToolExecutor` featuring circuit breaker (`ProviderCircuitBreaker`), bounded retries, cross-process persistent caching, and multi-provider fallback.
- **Investigation Workbench**: `domain/investigation` supplies the six-action investigation workflow, page planning, issue tracking, and source cross-verification. The production package has one investigation domain; historical opinion models are test fixtures for runtime verification.
- **Deterministic Replay**: runtime replay tests exercise committed step journals, context hashes and state fingerprints without calling a live provider. The former opinion CLI live-recording driver was removed with the opinion application layer.
- **Reproducible Quality Numbers**: an offline gate recomputes the published quality metrics (retrieval recall, faithfulness, adversarial probes, excerpt grounding) from four frozen runs in one command — zero model calls, zero network requests, and a non-zero exit on any drift.
- **Automated coverage**: unit, contract, integration, recovery, and investigation tests.

---

## Portfolio Evidence

This repository is positioned as a portfolio-grade single-event investigation
agent, not a production public-opinion monitoring platform. The frozen evidence
is in [`opinion_search_agent/artifacts/portfolio-proof`](opinion_search_agent/artifacts/portfolio-proof):

- **Live completed run** `6ba850f7c5684af7940b4b7c53b0ac4a`: 15/15 findings
  reviewed and supported, 5/5 required issues explicitly disposed, 4 independent
  sources, 20 evidence excerpts, 2 narrative paragraphs / 6 clauses, and a
  self-contained `dossier.html`.
- **Bounded partial example**: a real run where open required questions are kept
  visible with limitations instead of being reported as completed.

The intended claim is precise: the system produces evidence-backed reports with
explicit `completed` or `partial` semantics. Every terminal run, including a
`failed` or `cancelled` one, publishes the same minimum artifact bundle:
`report.json`, `report.md`, `workbench.json`, `presentation_plan.json`, and
`dossier.html`. The fallback proves delivery, not a fabricated conclusion. It
does not claim universal source coverage, population sentiment, or truth
adjudication.

Run the one-command release check:

```bash
make verify
```

---

## Architecture Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 入口层 / Entry Layer                                                   │
│   Web: python -m opinion_search.web (Investigation Workbench)    │
├────────────────────────────────────────────────────────────────────────┤
│ 组合根层 / Composition Roots                                           │
│   investigation/service.py → investigation 域装配 (Web 工作台)          │
│   investigation/manager.py → 调查全周期编排、澄清、快照、投影管理      │
├────────────────────────────────────────────────────────────────────────┤
│ 领域层 / Domain Layer                                                  │
│   domain/investigation/    → 事件多面体、证据网、6-action 扩展动作空间  │
├────────────────────────────────────────────────────────────────────────┤
│ 核心 Runtime / Core Runtime (Domain-Agnostic)                          │
│   runtime/loop.py          → AgentLoop (状态分发驱动器与恢复控制流)     │
│   runtime/lifecycle.py     → RunStatus (6态) / StepPhase (7阶段)       │
│   runtime/transaction.py   → RunState / StepRecord / classify_resume   │
│   runtime/checkpoint.py    → JsonCheckpointStore (原子持久化快照)       │
│   runtime/completion.py    → CompletionEvaluator / 终态判定规则        │
│   runtime/cancellation.py  → 竞速取消信号与安全阶段延迟终止            │
│   runtime/protocols.py     → 四段信封规范与载荷不变量检查              │
├────────────────────────────────────────────────────────────────────────┤
│ 支撑层 / Supporting Capabilities                                       │
│   context/                 → 分层上下文、有界压缩、目录索引、信任边界  │
│   investigation/context.py → 从调查状态编译模型上下文                │
│   tools/                   → 注册表、执行器、熔断器、原子缓存、Adapters │
│   models/                  → ModelClient 契约、OpenAI 兼容协议、Fakes   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```text
.
├── opinion_search_agent/       # 核心 Python 工程包
│   ├── pyproject.toml          # 项目配置、依赖与现代工具链 (Ruff, Mypy, Pytest)
│   ├── src/opinion_search/     # 核心源码 (Runtime, Domain, Tools, Context, Web)
│   ├── tests/                  # 测试套件 (unit, contract, integration, e2e, security)
│   └── scripts/                # 诊断与实测脚本
├── docs/                       # 核心技术设计文档与工程规范
│   ├── public-opinion-search-agent-design.md # 权威规范 (Canonical Design)
│   ├── architecture/           # 架构设计与机制深度分析
│   └── ...
├── Makefile                    # 标准化开发与验证指令集
└── README.md                   # 仓库主说明
```

---

## Quickstart

### 1. Requirements & Installation

- Python 3.12+

```bash
# 进入工程目录并安装开发依赖
pip install -e 'opinion_search_agent[dev]'
```

或者使用 Makefile：

```bash
make install
```

### 2. Code Quality & Linting

```bash
make lint       # 运行 ruff 快速静态检查
make format     # 自动格式化与 import 排序
make typecheck  # 运行 mypy 静态类型检查
```

### 3. Run Automated Tests

```bash
make test-fast  # 运行轻量级核心单测 (秒级)
make test       # 运行全量自动化测试套件
```

### 5. Reproduce the Quality Numbers (Offline)

不需要任何 API Key，也不发网络请求；四个冻结运行已经在仓库里：

```bash
make quality        # 等价于 python scripts/quality_gate.py
make quality-check  # 只校验，任何数字漂移 → 非零退出
```

输出检索召回、忠实性、对抗埋点、摘录可核四个口径，写入
`opinion_search_agent/artifacts/report-quality/quality-gate/baseline.{json,md}`。
口径与边界见 `opinion_search_agent/evaluation/README.md`。

### 6. Launch Investigation Web Workbench

启动内建轻量化 Web 服务器（默认端口 `8900`）：

```bash
make web
```

在浏览器打开 `http://localhost:8900`：
- `/`：舆情事件调查工作台（完整 6-action 编排、澄清交互、多面体模块、实时证据抽屉、静态报告导出）。

---

## Core Engineering Invariants

1. **State Is the Single Source of Truth**: Compiled context is a one-shot view of investigation state. State updates can only occur via the pure `reduce(state, delta)` function.
2. **Crash Recovery Is First-Class**: At every checkpoint boundary, persistent state is saved before proceeding. Crash recovery executes the exact same code path as normal step execution (`classify_resume(state)`).
3. **External Calls Are At-Most-Once Within Cached Windows**: Tool execution caches successful responses atomically before observation recording, preventing duplicate live API consumption across process restarts.
4. **Context Untrusted Origin Invariant**: Model/tool/web content can never be marked trusted (`Origin.UNTRUSTED`), preventing prompt injection attacks from hijacking runtime control flow.

---

## License

MIT License.
