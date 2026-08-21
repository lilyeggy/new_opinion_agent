from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from uuid import uuid4

from opinion_search.app.config import LiveConfig
from opinion_search.app.contracts import SearchRequest
from opinion_search.app.run_bundle import RunBundleError, RunBundleWriter
from opinion_search.app.service import (
    build_live_service,
    build_offline_service,
)
from opinion_search.domain.opinion.brief import SearchOutcome
from opinion_search.runtime.lifecycle import RunStatus
from opinion_search.runtime.checkpoint import CheckpointError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m opinion_search",
        description="Run or resume an OpinionSearch investigation.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("offline", "live"):
        command = subcommands.add_parser(name)
        command.add_argument("--question", required=True)
        command.add_argument("--topic")
        command.add_argument("--time-range")
        command.add_argument("--focus")
        command.add_argument("--language", default="zh")
        command.add_argument(
            "--include-domain",
            action="append",
            default=[],
            dest="include_domains",
        )
        command.add_argument(
            "--exclude-domain",
            action="append",
            default=[],
            dest="exclude_domains",
        )
        command.add_argument(
            "--checkpoint",
            type=Path,
            default=Path(".opinion_search/run.json"),
        )
        command.add_argument("--run-id", default=None)

    resume = subcommands.add_parser("resume")
    resume.add_argument("--mode", choices=("offline", "live"), required=True)
    resume.add_argument("--checkpoint", type=Path, required=True)
    return parser


async def _execute(arguments: argparse.Namespace) -> SearchOutcome:
    if arguments.command == "resume":
        service = (
            build_offline_service(arguments.checkpoint)
            if arguments.mode == "offline"
            else build_live_service(
                arguments.checkpoint,
                LiveConfig.from_env(),
            )
        )
        return await service.resume()

    service = (
        build_offline_service(arguments.checkpoint)
        if arguments.command == "offline"
        else build_live_service(
            arguments.checkpoint,
            LiveConfig.from_env(),
        )
    )
    request = SearchRequest(
        question=arguments.question,
        topic=arguments.topic,
        time_range=arguments.time_range,
        focus=arguments.focus,
        language=arguments.language,
        include_domains=tuple(arguments.include_domains),
        exclude_domains=tuple(arguments.exclude_domains),
    )
    return await service.investigate(
        request,
        run_id=arguments.run_id or f"opinion-{uuid4().hex}",
    )


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        outcome = asyncio.run(_execute(arguments))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except CheckpointError as exc:
        print(f"Checkpoint error: {exc}", file=sys.stderr)
        return 2

    try:
        report_path = asyncio.run(
            RunBundleWriter(arguments.checkpoint).write_report(outcome)
        )
    except RunBundleError as exc:
        print(f"Report error: {exc}", file=sys.stderr)
        return 2

    print(outcome.markdown)
    print(f"Report written to {report_path}", file=sys.stderr)
    return 1 if outcome.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
