"""Run the frozen quality corpus and emit an auditable baseline.

The corpus (``evaluation/corpus.json``) names run directories that are already in
the tree. The annotation files next to it hold every human judgement, so the gate
itself stays mechanical: same files in, same numbers out, no network and no model
call.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from opinion_search.evaluation import metrics
from opinion_search.evaluation.bundle import RunBundle, load_bundle

SCHEMA = "opinion-search-quality-gate/1"
PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = PACKAGE_ROOT / "evaluation" / "corpus.json"
DEFAULT_OUTPUT = PACKAGE_ROOT / "artifacts" / "report-quality" / "quality-gate"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return done.stdout.strip()


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _fraction(hits: Any, total: Any) -> str:
    return f"{hits}/{total}"


def evaluate_case(case: dict[str, Any], root: Path) -> dict[str, Any]:
    bundle: RunBundle = load_bundle(case, root)
    specs: dict[str, Any] = {}
    for name, relative in (case.get("annotations") or {}).items():
        specs[name] = _load(root / relative) if relative else None
    return {
        "case_id": bundle.case_id,
        "domain": bundle.domain,
        "label": case.get("label", ""),
        "run_dir": case["run_dir"],
        "fingerprint": bundle.fingerprint,
        "counts": {
            "sources": len(bundle.sources),
            "evidence": len(bundle.evidence),
            "claims": len(bundle.claims),
            "candidates": len(bundle.candidates),
            "read": len(bundle.read),
        },
        "metrics": {
            "provenance_closure": metrics.provenance_closure(bundle),
            "excerpt_grounding": metrics.excerpt_grounding(bundle),
            "claim_grounding": metrics.claim_grounding(bundle),
            "source_diversity": metrics.source_diversity(bundle),
            "retrieval_recall": metrics.retrieval_recall(bundle, specs.get("retrieval_recall")),
            "faithfulness": metrics.faithfulness(bundle, specs.get("faithfulness")),
            "quote_support": metrics.quote_support(bundle),
            "adversarial": metrics.adversarial(bundle, specs.get("adversarial")),
        },
    }


def _headline(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {case["case_id"]: case for case in cases}
    adversarial = by_id.get("sanjiu-adversarial", {})
    opinion_cases = [case for case in cases if case["domain"] == "opinion"]
    grounding = [
        case["metrics"]["excerpt_grounding"] for case in cases
        if case["metrics"]["excerpt_grounding"]["checkable"]
    ]
    verified = sum(item["verified"] for item in grounding)
    checkable = sum(item["checkable"] for item in grounding)
    recall = by_id.get("sanjiu-s5b", {}).get("metrics", {}).get("retrieval_recall", {})
    faith = by_id.get("sanjiu-s5b", {}).get("metrics", {}).get("faithfulness", {})
    human = faith.get("human", {})
    system = faith.get("system", {})
    adv = adversarial.get("metrics", {}).get("adversarial", {})
    quotes = by_id.get("sanjiu-s5b", {}).get("metrics", {}).get("quote_support", {})
    return {
        "retrieval_recall": {
            "case_id": "sanjiu-s5b",
            "discovery": _fraction(recall.get("discovery_hits"), recall.get("total")),
            "read": _fraction(recall.get("read_hits"), recall.get("total")),
            "published_discovery": _fraction(recall.get("reported_discovery_hits"), recall.get("total")),
            "published_read": _fraction(recall.get("reported_read_hits"), recall.get("total")),
            "human_machine_agreement": (recall.get("agreement") or {}).get("rate"),
        },
        "faithfulness": {
            "case_id": "sanjiu-s5b",
            "human_fully_supported": _fraction(
                human.get("counts", {}).get("fully_supported", 0), human.get("total", 0)
            ),
            "human_rate": human.get("fully_supported_rate"),
            "fabricated": human.get("fabricated"),
            "system_supported": _fraction(
                system.get("verdicts", {}).get("supported", 0), system.get("reviewed", 0)
            ),
            "excerpt_grounding": _fraction(verified, checkable),
            "excerpt_grounding_rate": None if checkable == 0 else verified / checkable,
        },
        "adversarial_points": {
            "case_id": "sanjiu-adversarial",
            "passed": _fraction(adv.get("report_passed"), adv.get("report_total")),
            "rate": (
                None if not adv.get("report_total")
                else adv["report_passed"] / adv["report_total"]
            ),
            "mechanism": _fraction(adv.get("passed"), adv.get("total")),
        },
        "quote_support": {
            "case_id": "sanjiu-s5b",
            "quotes": quotes.get("quotes"),
            "in_excerpt": quotes.get("in_excerpt"),
            "recoverable": quotes.get("recoverable"),
            "absent_from_doc": quotes.get("absent_from_doc"),
            "doc_unavailable": quotes.get("doc_unavailable"),
            "coverage": quotes.get("coverage"),
            "repairable_coverage": quotes.get("repairable_coverage"),
        },
        "live_regression": {
            case["case_id"]: {
                "claims": case["counts"]["claims"],
                "ungrounded": case["metrics"]["claim_grounding"]["ungrounded"],
                "domains_read": case["metrics"]["source_diversity"]["read"]["domains"],
                "candidates": case["counts"]["candidates"],
                "fingerprint": case["fingerprint"],
            }
            for case in opinion_cases
        },
    }


def _markdown(payload: dict[str, Any]) -> str:
    headline = payload["headline"]
    code = payload["code"]
    recall = headline["retrieval_recall"]
    faith = headline["faithfulness"]
    adv = headline["adversarial_points"]
    q = headline["quote_support"]
    lines = [
        "# OpinionSearch 质量门禁基线",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 代码：`{code.get('head') or 'unknown'}`（worktree dirty: {code.get('dirty')}）",
        f"- 语料：`{payload['corpus']}`（{len(payload['cases'])} 个冻结运行）",
        "- 成本：0 次模型调用 / 0 次网络请求，纯离线重算",
        "- 复现命令：`python scripts/quality_gate.py`（校验：`--check`）",
        "",
        "## 三个数字",
        "",
        "| 指标 | 本次重算 | 历史记录 | 口径 |",
        "| --- | --- | --- | --- |",
        f"| 检索召回（发现层） | {recall['discovery']} | {recall['published_discovery']} | 10 项必中清单 × 运行候选池 |",
        f"| 检索召回（已读层） | {recall['read']} | {recall['published_read']} | 10 项必中清单 × 实际已读来源 |",
        f"| 忠实性（人工完全支持） | {faith['human_fully_supported']} | 10/14 | 冻结人工标注，逐条核对绑定摘录 |",
        f"| 忠实性（系统自评 supported） | {faith['system_supported']} | 6/14 | 运行内 review verdict |",
        f"| 摘录可核（引用落回快照） | {faith['excerpt_grounding']} | 100% | 摘录 vs 冻结快照字符区间 |",
        f"| 零虚构 | {faith['fabricated']} | 0 | 人工标注 fabricated 计数 |",
        f"| 对抗埋点（报告层） | {adv['passed']} | 2/3 | 更正采纳 / 反叙事引用 / 错误数字隔离 |",
        f"| 对抗埋点（机制层） | {adv['mechanism']} | 无历史值 | 新增：数字矛盾检测能否报出 10 倍放大 |",
        f"| 引语落在引用摘录内 | {_fraction(q['in_excerpt'], q['quotes'])} | 无历史值 | 带引语判断的引号片段 vs 其绑定摘录 |",
        f"| 引语可修复（原文有、摘录没摘） | {q['recoverable']} 条 | 无历史值 | 确定性回填的上限，不需模型 |",
        "",
        f"人机一致率（必中清单逐项）：{_ratio(recall['human_machine_agreement'])}",
        "",
        "## 逐案例",
        "",
        "| 案例 | 来源/证据/判断 | 已读域 | 候选 | 引用闭合 | 摘录可核 | 判断有据 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in payload["cases"]:
        counts = case["counts"]
        closure = case["metrics"]["provenance_closure"]
        grounding = case["metrics"]["excerpt_grounding"]
        claim = case["metrics"]["claim_grounding"]
        ground_cell = f"{grounding['verified']}/{grounding['checkable']}"
        if grounding["unverifiable"]:
            ground_cell += f" (+{grounding['unverifiable']} 无快照)"
        lines.append(
            f"| {case['case_id']} | {counts['sources']}/{counts['evidence']}/{counts['claims']} "
            f"| {case['metrics']['source_diversity']['read']['domains']} "
            f"| {counts['candidates']} | {_ratio(closure['closure_rate'])} "
            f"| {ground_cell} | {claim['grounded']}/{claim['total']} |"
        )
    lines += ["", "## 对抗埋点", ""]
    adv_case = next(
        (case["metrics"]["adversarial"] for case in payload["cases"] if case["case_id"] == adv["case_id"]),
        {},
    )
    for check in adv_case.get("checks", []):
        mark = "通过" if check["passed"] else "未通过"
        layer = "机制" if check.get("layer") == "mechanism" else "报告"
        note = f" ｜{check['note']}" if check.get("note") else ""
        lines.append(
            f"- [{mark}·{layer}] {check['question']} — {json.dumps(check['observed'], ensure_ascii=False)}{note}"
        )
    lines += ["", "## 人机分歧", ""]
    for case in payload["cases"]:
        recall_metric = case["metrics"]["retrieval_recall"]
        if not recall_metric.get("available"):
            continue
        for item in recall_metric["items"]:
            if item["published_discovery"] is not None and item["discovered"] != item["published_discovery"]:
                lines.append(
                    f"- {case['case_id']} 必中第 {item['item_id']} 项（{item['content']}）："
                    f"机械判定 discovered={item['discovered']}，历史记录={item['published_discovery']}"
                )
    lines += ["", "## 引语溯源", ""]
    lines.append(
        f"- {q['quotes']} 个引号片段：{q['in_excerpt']} 落在引用摘录内、{q['recoverable']} 在原文但未被摘、"
        f"{q['absent_from_doc']} 在冻结原文里找不到、{q['doc_unavailable']} 无快照可核"
    )
    lines.append(
        f"- 覆盖率 {_ratio(q['coverage'])}，确定性回填后可到 {_ratio(q['repairable_coverage'])}"
        " （回填只补证据，不改判断文本）"
    )
    for case in payload["cases"]:
        quote_metric = case["metrics"].get("quote_support") or {}
        for miss in quote_metric.get("misses", []):
            if miss["reason"] == "not_selected_into_excerpt" and case["case_id"] == q["case_id"]:
                lines.append(f"- 未摘但原文有：{miss['claim_id']} 「{miss['quote']}」")
    lines += ["", "## 已知边界", ""]
    for line in payload.get("boundaries", []):
        lines.append(f"- {line}")
    lines.append("")
    return "\n".join(lines)


def run_gate(
    corpus_path: Path = DEFAULT_CORPUS,
    root: Path = PACKAGE_ROOT,
    output_dir: Path = DEFAULT_OUTPUT,
    write: bool = True,
) -> dict[str, Any]:
    corpus = _load(corpus_path)
    cases = [evaluate_case(case, root) for case in corpus["cases"]]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": str(corpus_path.relative_to(root)) if corpus_path.is_relative_to(root) else str(corpus_path),
        "code": {
            "head": _git(root, "rev-parse", "--short", "HEAD"),
            "dirty": bool(_git(root, "status", "--porcelain")),
        },
        "boundaries": corpus.get("boundaries", []),
        "cases": cases,
        "headline": _headline(cases),
    }
    if write:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "baseline.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "baseline.md").write_text(_markdown(payload), encoding="utf-8")
    return payload


def comparable(payload: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(payload))
    clone.pop("generated_at", None)
    clone.pop("code", None)
    return clone


def _diff(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: list[str] = []
        for key in sorted(set(left) | set(right)):
            label = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_diff(left.get(key), right.get(key), label))
        return found
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{prefix}: list length {len(left)} vs {len(right)}"]
        found = []
        for index in range(len(left)):
            found.extend(_diff(left[index], right[index], f"{prefix}[{index}]"))
        return found
    if left != right:
        return [f"{prefix}: {left} vs {right}"]
    return []


def check_gate(
    corpus_path: Path = DEFAULT_CORPUS,
    root: Path = PACKAGE_ROOT,
    output_dir: Path = DEFAULT_OUTPUT,
) -> tuple[bool, list[str]]:
    baseline_path = output_dir / "baseline.json"
    if not baseline_path.is_file():
        return False, [f"missing baseline: {baseline_path}"]
    expected = _load(baseline_path)
    current = run_gate(corpus_path, root, output_dir, write=False)
    differences = _diff(comparable(expected), comparable(current))
    return not differences, differences
