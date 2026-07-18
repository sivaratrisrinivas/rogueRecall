from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .benchmark import format_benchmark_summary, run_benchmark


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roguerecall")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="execute a Benchmark Batch and write its Benchmark Summary",
    )
    benchmark_parser.add_argument("--runs-root", type=Path, required=True)
    benchmark_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_parser.add_argument("--results", type=Path)
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        try:
            manifest = _read_json_object(args.manifest)
            results_path, summary = run_benchmark(
                args.runs_root,
                manifest,
                results_path=args.results,
            )
        except (OSError, ValueError) as error:
            print(f"invalid benchmark input: {error}")
            return 2
        print(format_benchmark_summary(summary))
        print(f"Benchmark Summary: {results_path}")
        return 0 if summary["complete"] else 1
    parser.error("unknown command")
    return 2


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
