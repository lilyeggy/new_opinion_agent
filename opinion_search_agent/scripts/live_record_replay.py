"""Record a live OpinionSearch run as a decision journal, then replay it.

Usage (from opinion_search_agent/, with the live environment loaded):
    set -a; . ./.env; set +a
    PYTHONPATH=src .venv/bin/python scripts/live_record_replay.py record \
        --run-dir artifacts/<name> --question "..." [--report]
    PYTHONPATH=src .venv/bin/python scripts/live_record_replay.py replay \
        --run-dir artifacts/<name>

record writes run.json (checkpoint), run.journal (committed-step records),
and initial_state.json (the exact starting state, including the task-frame
anchor date). With --report it also writes report.md and outcome.json through
the same RunBundleWriter the served entry point uses, so a journaled run can be
read without a separate export step. replay drives the real loop from those files without calling a
model or a search provider.
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from opinion_search.app.config import LiveConfig
from opinion_search.app.contracts import SearchRequest
from opinion_search.app.run_bundle import RunBundleWriter
from opinion_search.app.service import (
    OpinionRunState,
    _build_loop,
    build_live_service,
    default_investigation_gaps,
)
from opinion_search.domain.opinion.brief import build_search_outcome
from opinion_search.domain.opinion.decisions import AgentDecision
from opinion_search.domain.opinion.framing import build_task_frame
from opinion_search.domain.opinion.processor import OpinionObservation
from opinion_search.domain.opinion.state import OpinionSearchState
from opinion_search.runtime.recording import DecisionRecorder
from opinion_search.runtime.replay import ReplayCodec, load_step_records, replay_records
from opinion_search.tools.adapters.brave_search import BraveSearchAdapter
from opinion_search.tools.adapters.jina_reader import JinaReaderAdapter
from opinion_search.tools.capabilities.web import reader_tool_definition, search_tool_definition
from opinion_search.tools.http import HttpxTransport
from opinion_search.tools.registry import ToolRegistry

INITIAL_STATE = "initial_state.json"
JOURNAL = "run.journal"
CHECKPOINT = "run.json"


def _initial_state(run_id: str, question: str, config: LiveConfig, language: str) -> OpinionRunState:
    # Mirrors OpinionSearchService.investigate; the anchor date is stored so replay never reads today's date.
    request = SearchRequest(question=question, language=language)
    return OpinionRunState(
        run_id=run_id,
        domain_state=OpinionSearchState(
            request=request,
            gaps=default_investigation_gaps(request),
            task_frame=build_task_frame(request, anchor_date=date.today()),
            current_focus=request.focus,
        ),
    )


def _registry() -> ToolRegistry:
    # Same registration order as build_live_service, so tool specs match the recorded context.
    # The adapters are never invoked during replay; the placeholder key is inert.
    transport = HttpxTransport()
    registry = ToolRegistry()
    registry.register(search_tool_definition(), BraveSearchAdapter(transport=transport, api_key="replay"))
    registry.register(
        reader_tool_definition(),
        JinaReaderAdapter(transport=transport, api_key=None),
    )
    return registry


def record(run_dir: Path, question: str, language: str, report: bool = False) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    config = LiveConfig.from_env()
    state = _initial_state(f"opinion-record-{date.today().isoformat()}", question, config, language)
    (run_dir / INITIAL_STATE).write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    recorder = DecisionRecorder(run_dir / JOURNAL)
    service = build_live_service(run_dir / CHECKPOINT, config, recorder=recorder)
    # The service's loop is the only entry point that takes an explicit initial state.
    result = asyncio.run(service._loop.run(state))  # noqa: SLF001
    payload = {
        "status": result.status.value,
        "stop_reason": result.stop_reason,
        "committed_steps": len(recorder.journal.read()),
    }
    if report:
        outcome = build_search_outcome(
            result.domain_state,
            status=result.status,
            stop_reason=result.stop_reason or "unknown",
        )
        writer = RunBundleWriter(run_dir / CHECKPOINT)
        written = asyncio.run(writer.write_report(outcome))
        payload["report"] = str(written)
        payload["outcome"] = str(writer.outcome_path)
        payload["remaining_gap_ids"] = list(outcome.remaining_gap_ids)
    print(json.dumps(payload, ensure_ascii=False))


def replay(run_dir: Path) -> None:
    config = LiveConfig.from_env()
    initial = OpinionRunState.model_validate(
        json.loads((run_dir / INITIAL_STATE).read_text(encoding="utf-8"))
    )
    records = load_step_records(run_dir / JOURNAL)
    codec = ReplayCodec(
        decision=TypeAdapter(AgentDecision),
        observation=TypeAdapter(OpinionObservation),
    )
    registry = _registry()

    def build(model: Any, executor: Any, store: Any):
        return _build_loop(
            model=model,
            registry=registry,
            checkpoint_path=run_dir / "unused-replay-checkpoint.json",
            max_steps=config.max_steps,
            max_decision_attempts=config.max_decision_attempts,
            max_context_tokens=config.max_context_tokens,
            output_headroom_tokens=config.output_headroom_tokens,
            tool_timeout_seconds=config.tool_timeout_seconds,
            execution_profile="replay",
            action_executor=executor,
            checkpoint_store=store,
        )

    report = asyncio.run(replay_records(records, initial_state=initial, codec=codec, build_loop=build))
    print(report.model_dump_json(indent=1))
    if report.status.value != "matched":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--run-dir", type=Path, required=True)
    rec.add_argument("--question", required=True)
    rec.add_argument("--language", default="zh")
    rec.add_argument(
        "--report",
        action="store_true",
        help="also write report.md and outcome.json beside the checkpoint",
    )
    rep = sub.add_parser("replay")
    rep.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "record":
        record(args.run_dir, args.question, args.language, report=args.report)
    else:
        replay(args.run_dir)


if __name__ == "__main__":
    main()
