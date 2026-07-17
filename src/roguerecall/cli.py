from __future__ import annotations

import argparse
import json
import os
import webbrowser
from pathlib import Path
from typing import Sequence

from .benchmark import format_benchmark_summary, run_benchmark
from .dashboard import create_server
from .engine import run_synthetic, run_targets
from .records import RecordValidationError, validate_record
from .releases import (
    ReleaseValidationError,
    TrustStore,
    validate_corpus_candidate,
    verify_release,
)
from .installation import InstallationPaths, discover_paths, purge, run_doctor
from .qualification import QualificationValidationError, validate_qualification_report


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
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="execute a Benchmark Batch and write its Benchmark Summary",
    )
    benchmark_parser.add_argument("--runs-root", type=Path, required=True)
    benchmark_parser.add_argument("--manifest", type=Path, required=True)
    benchmark_parser.add_argument("--case-set", type=Path, required=True)
    benchmark_parser.add_argument("--results", type=Path)
    validate_parser = subparsers.add_parser(
        "validate", help="independently validate a Run Record"
    )
    validate_parser.add_argument("record", type=Path)
    candidate_parser = subparsers.add_parser(
        "validate-corpus-candidate",
        help="validate a frozen Corpus Candidate Record before assembly",
    )
    candidate_parser.add_argument("candidate", type=Path)
    qualification_parser = subparsers.add_parser(
        "validate-qualification",
        help="validate a V1 qualification report and its evidence artifacts",
    )
    qualification_parser.add_argument("report", type=Path)
    release_parser = subparsers.add_parser(
        "verify-release",
        help="verify a signed Benchmark Corpus Release without network access",
    )
    release_parser.add_argument("release", type=Path)
    release_parser.add_argument("--trust-key", type=Path, required=True)
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="serve validated results read-only over loopback"
    )
    dashboard_parser.add_argument("--runs-root", type=Path, required=True)
    dashboard_parser.add_argument("--port", type=int, default=7411)
    dashboard_parser.add_argument("--no-open", action="store_true")
    paths_parser = subparsers.add_parser("paths", help="show OS-native RogueRecall paths")
    _add_operator_path_arguments(paths_parser)
    doctor_parser = subparsers.add_parser("doctor", help="run offline installation diagnostics")
    _add_operator_path_arguments(doctor_parser)
    purge_parser = subparsers.add_parser("purge", help="remove local state safely")
    _add_operator_path_arguments(purge_parser, json_output=False)
    purge_parser.add_argument("--dry-run", action="store_true")
    purge_parser.add_argument("--all", action="store_true", help="also remove Run Records")
    purge_parser.add_argument("--confirm", action="store_true")
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
    if args.command == "benchmark":
        try:
            manifest = _read_json_object(args.manifest)
            case_set = _read_json_object(args.case_set)
            results_path, summary = run_benchmark(
                args.runs_root,
                manifest,
                case_set,
                results_path=args.results,
            )
        except (OSError, ValueError) as error:
            print(f"invalid benchmark input: {error}")
            return 2
        print(format_benchmark_summary(summary))
        print(f"Benchmark Summary: {results_path}")
        return 0 if summary["complete"] else 1
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
    if args.command == "validate-qualification":
        try:
            validate_qualification_report(args.report)
        except QualificationValidationError as error:
            print(f"invalid: {error}")
            return 1
        print(f"valid: {args.report}")
        return 0
    if args.command == "verify-release":
        try:
            public_identity = _read_json_object(args.trust_key)
            manifest = verify_release(
                args.release,
                TrustStore.from_identities([public_identity]),
            )
        except (OSError, ValueError, ReleaseValidationError) as error:
            print(json.dumps({"error": str(error), "valid": False}, sort_keys=True))
            return 1
        print(
            json.dumps(
                {
                    "release_digest": manifest["release_digest"],
                    "signer_key_id": manifest["signer_key_id"],
                    "valid": True,
                    "version": manifest["version"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "dashboard":
        server = create_server(args.runs_root, port=args.port)
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Read-only dashboard: {url}", flush=True)
        if not args.no_open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    if args.command == "paths":
        paths = _operator_paths(args.home)
        print(json.dumps(paths.serializable(), sort_keys=True) if args.json else _format_paths(paths))
        return 0
    if args.command == "doctor":
        report = run_doctor(_operator_paths(args.home))
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            for check in report["checks"]:
                print(f"{'ok' if check['ok'] else 'FAIL'} {check['id']}: {check['detail']}")
        return 0 if report["ok"] else 1
    if args.command == "purge":
        if args.all and not args.dry_run and not args.confirm:
            print("Complete removal requires --confirm; use --dry-run to inspect first")
            return 2
        paths = _operator_paths(args.home)
        actions = purge(paths, include_runs=args.all, dry_run=True)
        for action in actions:
            print(f"{action['action']}: {action['path']}")
        if not args.dry_run:
            purge(paths, include_runs=args.all, dry_run=False)
        return 0
    parser.error("unknown command")
    return 2


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _add_operator_path_arguments(parser: argparse.ArgumentParser, *, json_output: bool = True) -> None:
    parser.add_argument("--home", type=Path, help="override ROGUERECALL_HOME for this command")
    if json_output:
        parser.add_argument("--json", action="store_true")


def _operator_paths(home: Path | None) -> InstallationPaths:
    environ = dict(os.environ)
    if home is not None:
        environ["ROGUERECALL_HOME"] = str(home)
    return discover_paths(environ)


def _format_paths(paths: InstallationPaths) -> str:
    return "\n".join(f"{key}: {value}" for key, value in paths.serializable().items())


if __name__ == "__main__":
    raise SystemExit(main())
