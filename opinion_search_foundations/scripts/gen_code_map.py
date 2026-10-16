"""Generate js/data-code-map.js from the real source tree.

Run from anywhere: python3 opinion_search_foundations/scripts/gen_code_map.py
Line counts and file lists come from disk; only the one-line descriptions are curated.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "opinion_search_agent" / "src" / "opinion_search"
OUT = Path(__file__).resolve().parents[1] / "js" / "data-code-map.js"

DESCRIPTIONS = {
    "runtime/loop.py": "AgentLoop：按 classify_resume 分发的主循环，每个阶段后落 checkpoint",
    "runtime/transaction.py": "RunState / StepRecord 与事务函数（open/accept/start_action/commit_step…）",
    "runtime/lifecycle.py": "RunStatus（6 态）与 StepPhase（7 阶段）及合法转移表",
    "runtime/protocols.py": "四段信封（Decision/Action/Observation/StateDelta）与 StepRecord 不变量",
    "runtime/checkpoint.py": "JsonCheckpointStore：临时文件 + fsync + os.replace 的原子写入，加载时校验版本与 profile",
    "runtime/completion.py": "完成判定的协议与结果类型（CompletionDisposition / RunResult）",
    "runtime/errors.py": "RuntimeFailureKind（20 种）与 RecoveryDirective 的映射",
    "runtime/cancellation.py": "取消信号协议与实现",
    "runtime/journal.py": "追加式 JSON-lines journal：fsync、末尾残行修复、按 step 截断",
    "runtime/replay_record.py": "回放记录结构、规范化指纹、分歧（Divergence）与比较规则",
    "runtime/recording.py": "回放录制：模型调用包装、in-flight 侧文件、先写 journal 后写 checkpoint",
    "runtime/replay.py": "确定性回放驱动：替换模型与执行器为录制回放端，逐 step 比对",
    "context/models.py": "ContextSection / ContextBudget / CompiledContext，含 L0–L3 与信任边界的构造期校验",
    "context/compiler.py": "OpinionContextCompiler：collect → select → compact → render",
    "context/compactor.py": "压缩策略（NEVER / TRUNCATE / DROP），共享给两个领域",
    "context/selector.py": "候选去重与排序（opinion 域）",
    "context/catalog.py": "有界 Evidence catalog 分区（opinion 域）",
    "tools/registry.py": "逻辑工具（ToolDefinition）注册与 provider 绑定",
    "tools/executor.py": "ToolExecutor：参数校验、缓存、provider 循环、重试、超时、熔断门控",
    "tools/circuit.py": "熔断器：key 为 (tool, provider)，阈值 3、冷却 30 秒，状态仅在内存",
    "tools/cache.py": "进程内结果缓存",
    "tools/persistent_cache.py": "按 action 落盘的成功结果缓存（JsonActionResultCache）",
    "tools/routing.py": "provider 绑定（ProviderBinding）与已注册工具（RegisteredTool）",
    "tools/contracts.py": "ToolErrorKind（12 种）与三类重试策略",
    "tools/url.py": "公开 URL 规范化与校验（含 legacy IPv4 字面量解析）",
    "tools/http.py": "HTTP 传输协议与 httpx 实现，统一 HTTP 状态码到错误类型的映射",
    "tools/adapters/mcp.py": "MCP 适配：allowlist、schema 指纹、原子注册、递归 metadata 过滤",
    "tools/adapters/brave_search.py": "Brave Search provider 适配器",
    "tools/adapters/jina_reader.py": "Jina Reader provider 适配器（读取网页正文）",
    "tools/adapters/fake.py": "离线 fake provider，用于确定性测试",
    "tools/capabilities/web.py": "search.web / read.web 的 ToolDefinition 与参数模型",
    "domain/opinion/decisions.py": "模型输出的 4 种决策：search / read / reflect / finish（AgentDecision 判别联合）",
    "domain/opinion/actions.py": "决策解析后的内部动作模型（ToolAction / ReflectAction / FinishAction）",
    "domain/opinion/action_resolver.py": "Decision → Action 的翻译与加固",
    "domain/opinion/state.py": "OpinionSearchState：权威状态（gap、候选、来源、证据、反思）",
    "domain/opinion/processor.py": "Observation → StateDelta（摘录提取、去重、高价值信号加权）",
    "domain/opinion/reducer.py": "reduce_opinion_state：唯一写入权威状态的纯函数",
    "domain/opinion/completion.py": "opinion 域完成策略（finish 只是 proposal，14 道检查）",
    "domain/opinion/provenance.py": "Claim → Evidence → Source → artifact 的溯源索引",
    "domain/opinion/brief.py": "报告结构模型（结论、主张、立场、叙事、证据等）",
    "domain/opinion/framing.py": "时间范围解析（如“过去 30 天”）与任务框架构造",
    "domain/investigation/engine.py": "investigation 域：校验、解析、处理、完成闸门、reduce_state",
    "domain/investigation/models.py": "investigation 域的 State / Decision / Action / Observation / Delta",
    "memory/projector.py": "Working Memory 投影：State → 派生视图（仅 opinion 域）",
    "memory/models.py": "Working Memory 的数据模型",
    "models/contracts.py": "ModelClient 协议与 ModelError（8 种错误类型）",
    "models/fake.py": "脚本化模型与 fake 执行器，用于离线与测试",
    "models/openai_compatible.py": "OpenAI 兼容接口的模型客户端",
    "app/service.py": "opinion 域组合根：build_offline / build_live，_build_loop 注入 11 个协作者",
    "app/config.py": "LiveConfig：全部默认值（步数、预算、超时）",
    "app/action_executor.py": "Action → ToolCall → Observation 的执行适配",
    "app/run_bundle.py": "终态产物原子写（report.md / outcome.json）",
    "app/contracts.py": "SearchRequest 等入口契约",
    "investigation/service.py": "investigation 域组合根（工作台使用）",
    "investigation/manager.py": "调查编排：澄清、更新、预算、投影",
    "investigation/context.py": "investigation 域的 Context Compiler",
    "investigation/storage.py": "调查存储与 FTS5 增量索引",
    "investigation/replay.py": "冻结外部材料的回放（不校验决策序列，与 runtime/replay.py 职责不同）",
    "web/server.py": "HTTP 服务：3 个页面与 2 套 API，SSE 推送进度",
    "__main__.py": "CLI 入口：offline / live / resume",
}


def collect() -> list[dict]:
    entries = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC).as_posix()
        lines = sum(1 for _ in path.open(encoding="utf-8"))
        entries.append(
            {"path": rel, "lines": lines, "desc": DESCRIPTIONS.get(rel, "")}
        )
    return entries


def main() -> None:
    entries = collect()
    payload = json.dumps(entries, ensure_ascii=False, indent=1)
    OUT.write_text(
        "// Generated by scripts/gen_code_map.py from opinion_search_agent/src. Do not edit by hand.\n"
        f"window.CODE_MAP = {payload};\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} files to {OUT}")


if __name__ == "__main__":
    main()
