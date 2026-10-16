"""CLI: recompute or verify the frozen report-quality baseline (offline)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from opinion_search.evaluation.gate import (
    DEFAULT_CORPUS,
    DEFAULT_OUTPUT,
    PACKAGE_ROOT,
    check_gate,
    run_gate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute the frozen report-quality baseline (offline, no model call)."
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the committed baseline instead of rewriting it",
    )
    args = parser.parse_args(argv)

    if args.check:
        ok, differences = check_gate(args.corpus, PACKAGE_ROOT, args.out)
        if ok:
            print("quality gate: baseline reproduced exactly")
            return 0
        print("quality gate: baseline drift detected")
        for line in differences:
            print(f"  - {line}")
        return 1

    payload = run_gate(args.corpus, PACKAGE_ROOT, args.out)
    headline = payload["headline"]
    recall = headline["retrieval_recall"]
    faith = headline["faithfulness"]
    adv = headline["adversarial_points"]
    print(f"quality gate: {len(payload['cases'])} cases -> {args.out}")
    print(f"  retrieval recall : discovery {recall['discovery']} / read {recall['read']}")
    print(f"  faithfulness     : human {faith['human_fully_supported']} / system {faith['system_supported']}")
    print(f"  adversarial      : {adv['passed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
