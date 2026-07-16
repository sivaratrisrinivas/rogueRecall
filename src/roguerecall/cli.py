from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .dashboard import create_server
from .engine import run_synthetic, run_targets
from .records import RecordValidationError, validate_record
from .releases import ReleaseValidationError, validate_corpus_candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roguerecall")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run-synthetic", help="run the bundled synthetic Evaluation Case"
    )
    run_parser.add_argument("--runs-root", type=Path, required=True)
    run_parser.add_argument(
        "--inject-failure",
        choices=("finalization-interrupted", "operator-interrupted"),
        help="preserve an Incomplete Run Record after planning (test support)",
    )
    targets_parser = subparsers.add_parser(
        "run", help="run Evaluation Cases against declared Target Systems"
    )
    targets_parser.add_argument("--runs-root", type=Path, required=True)
    targets_parser.add_argument("--manifest", type=Path, required=True)
    targets_parser.add_argument("--case", type=Path, action="append", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="independently validate a Run Record"
    )
    validate_parser.add_argument("record", type=Path)
    candidate_parser = subparsers.add_parser(
        "validate-corpus-candidate",
        help="validate a frozen Corpus Candidate Record before assembly",
    )
    candidate_parser.add_argument("candidate", type=Path)
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="serve validated results read-only over loopback"
    )
    dashboard_parser.add_argument("--runs-root", type=Path, required=True)
    dashboard_parser.add_argument("--port", type=int, default=7411)
    args = parser.parse_args(argv)

    if args.command == "run-synthetic":
        record_path = run_synthetic(args.runs_root, inject_failure=args.inject_failure)
        print(record_path)
        return 1 if record_path.name.endswith(".incomplete") else 0
    if args.command == "run":
        manifest = _read_json_object(args.manifest)
        cases = [_read_json_object(path) for path in args.case]
        record_path = run_targets(args.runs_root, manifest, cases)
        print(record_path)
        return 1 if record_path.name.endswith(".incomplete") else 0
    if args.command == "validate":
        try:
            validate_record(
                args.record,
                require_complete=not args.record.name.endswith(".incomplete"),
            )
        except RecordValidationError as error:
            print(f"invalid: {error}")
            return 1
        print(f"valid: {args.record}")
        return 0
    if args.command == "validate-corpus-candidate":
        try:
            validate_corpus_candidate(_read_json_object(args.candidate))
        except ReleaseValidationError as error:
            print(f"invalid: {error}")
            return 1
        except (OSError, ValueError) as error:
            print(f"invalid: cannot read candidate JSON: {error}")
            return 1
        print(f"valid: {args.candidate}")
        return 0
    if args.command == "dashboard":
        server = create_server(args.runs_root, port=args.port)
        print(f"Read-only dashboard: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    parser.error("unknown command")
    return 2


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
