"""Command-line entry point for the OpinionSearch web demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from opinion_search.web.server import OpinionSearchServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m opinion_search.web",
        description=(
            "Serve the OpinionSearch demo website and run investigations "
            "from the browser."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8900,
        help="port to bind (default: 8900)",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(".opinion_search_web"),
        help="directory holding one checkpoint sub-directory per run",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file merged into the environment for live mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    server = OpinionSearchServer(
        runs_root=arguments.runs_dir,
        env_file=arguments.env_file,
    )
    server.serve(host=arguments.host, port=arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())