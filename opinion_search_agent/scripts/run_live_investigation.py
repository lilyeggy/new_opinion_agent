"""Run one real live investigation through the production Manager path.

Usage:
    python scripts/run_live_investigation.py \
        --topic "三九胃泰中秋广告争议" \
        --question "三九胃泰中秋广告争议事件的始末是什么？各方如何回应？"

Loads credentials from .env, creates the investigation, polls until a
terminal state, auto-answers clarification requests (time questions get the
given time range; object questions get a defer answer that forces the
planner to proceed on its best interpretation), and prints the resulting
report/workbench paths.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opinion_search.config import LiveConfig  # noqa: E402
from opinion_search.investigation.manager import Manager, TERMINAL  # noqa: E402
from opinion_search.web.server import load_env_file  # noqa: E402

_TIME_PHASES = {"需要补充时间范围", "时间范围未能识别"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--focus", default="")
    parser.add_argument("--time-range", default="")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--runs-root", default=str(ROOT / "artifacts" / "live-runs"))
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--max-minutes", type=float, default=60)
    parser.add_argument("--max-steps", type=int, default=0,
                        help="Override LiveConfig.max_steps for this run (0 = keep env/default).")
    args = parser.parse_args()

    load_env_file(ROOT / ".env")

    def config_loader() -> LiveConfig:
        load_env_file(ROOT / ".env")
        config = LiveConfig.from_env()
        if args.max_steps > 0:
            config = config.model_copy(update={"max_steps": args.max_steps})
        return config

    manager = Manager(Path(args.runs_root) / "investigations", config_loader=config_loader)

    payload: dict[str, str] = {
        "mode": "live",
        "topic": args.topic,
        "question": args.question,
        "language": args.language,
    }
    if args.focus:
        payload["focus"] = args.focus
    if args.time_range:
        payload["time_range"] = args.time_range

    snapshot = manager.create(payload)
    run_id = snapshot["run_id"]
    print(f"[run] {run_id}  status={snapshot['status']}  phase={snapshot.get('phase')}", flush=True)

    deadline = time.monotonic() + args.max_minutes * 60
    last_phase = None
    while time.monotonic() < deadline:
        time.sleep(args.poll_seconds)
        snapshot = manager.snapshot(run_id)
        status, phase = snapshot["status"], snapshot.get("phase")
        progress = snapshot.get("progress") or {}
        marker = f"[{time.strftime('%H:%M:%S')}] status={status} phase={phase} progress={json.dumps(progress, ensure_ascii=False)}"
        if (status, phase) != last_phase:
            print(marker, flush=True)
            last_phase = (status, phase)
        if status == "needs_clarification":
            questions = snapshot.get("clarification_questions") or []
            print(f"[clarify] 系统提问: {questions}", flush=True)
            if phase in _TIME_PHASES and args.time_range:
                answer = args.time_range
            else:
                answer = "按你的理解"
            print(f"[clarify] 自动作答: {answer}", flush=True)
            manager.clarify(run_id, {"answer": answer})
            last_phase = None
            continue
        if status in TERMINAL:
            break
    else:
        print("[timeout] 超过最长等待，调查仍在运行；可用 resume 继续。", flush=True)

    snapshot = manager.snapshot(run_id)
    status = snapshot["status"]
    print(f"\n[final] status={status}", flush=True)
    run_dir = Path(args.runs_root) / "investigations" / "runs" / run_id
    print(f"[final] run 目录: {run_dir}", flush=True)
    for name in ("report.md", "report.json", "budget.json"):
        path = run_dir / name
        if path.exists():
            print(f"[final] {name}: {path}", flush=True)
    report = snapshot.get("report") or {}
    if report:
        findings = report.get("findings") or []
        sources = report.get("sources") or []
        print(f"[final] findings={len(findings)} sources={len(sources)}", flush=True)
    diag = run_dir / "diagnostics.json"
    if diag.exists():
        print(f"[final] diagnostics: {diag}", flush=True)
    sys.exit(0 if status in {"completed", "partial"} else 1)


if __name__ == "__main__":
    main()
