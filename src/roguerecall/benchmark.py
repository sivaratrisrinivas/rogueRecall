from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import validate_evaluation_case
from .engine import run_targets
from .records import canonical_json, sha256_bytes, validate_record
from .targets import Transport, validate_target_manifest


RESULTS_SCHEMA_VERSION = "1.0.0"


def run_benchmark(
    runs_root: Path,
    manifest: Mapping[str, Any],
    case_set: Mapping[str, Any],
    *,
    results_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Execute a Benchmark Batch and write its derived Benchmark Summary."""

    cases, validated_cases = _validate_case_set(case_set)
    validate_target_manifest(manifest, environ=environ)
    targets = manifest["target_systems"]
    if not isinstance(targets, list):
        raise ValueError("target_systems must be a list")

    batch_id = str(uuid.uuid4())
    destination = results_path or (
        runs_root / "benchmarks" / batch_id / "results.json"
    )
    reservation = _reserve_summary(destination)
    try:
        target_summaries = []
        for target in targets:
            single_manifest = {
                "schema_version": manifest["schema_version"],
                "target_systems": [target],
            }
            record_path = run_targets(
                runs_root,
                single_manifest,
                cases,
                environ=environ,
                transport_factory=transport_factory,
            )
            target_summaries.append(_summarize_record(record_path, runs_root))

        normalized_case_set = {
            "cases": validated_cases,
            "schema_version": "1.0.0",
        }
        summary = {
            "batch_id": batch_id,
            "case_set": {
                "case_count": len(cases),
                "fingerprint": sha256_bytes(canonical_json(normalized_case_set)),
            },
            "complete": all(
                item["run_record"]["state"] == "complete"
                for item in target_summaries
            ),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": RESULTS_SCHEMA_VERSION,
            "targets": target_summaries,
        }
        _write_summary(reservation, destination, summary)
        return destination, summary
    finally:
        reservation.unlink(missing_ok=True)


def format_benchmark_summary(summary: Mapping[str, Any]) -> str:
    """Render a non-ranked Benchmark Summary in manifest order."""

    headers = (
        "Target System",
        "State",
        "Coverage",
        "Text Leaks",
        "Target Errors",
        "Grader Errors",
        "Not Tested",
        "Run Record",
    )
    rows = [headers]
    for target in summary["targets"]:
        coverage = target["grading_coverage"]
        leaks = target["text_leaks"]
        rows.append(
            (
                target["target_system_id"],
                target["run_record"]["state"],
                f'{coverage["numerator"]}/{coverage["denominator"]}',
                f'{leaks["numerator"]}/{leaks["denominator"]}',
                str(target["target_errors"]),
                str(target["grader_errors"]),
                str(target["not_tested"]),
                f'runs_root/{target["run_record"]["path"]}',
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    return "\n".join(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        for row in rows
    )


def _validate_case_set(
    case_set: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    if set(case_set) != {"cases", "schema_version"}:
        raise ValueError(
            "Evaluation Case Set requires exactly schema_version and cases"
        )
    if case_set["schema_version"] != "1.0.0":
        raise ValueError("unsupported Evaluation Case Set schema version")
    raw_cases = case_set["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Evaluation Case Set requires at least one case")
    authored_cases = []
    validated_cases = []
    for case in raw_cases:
        if not isinstance(case, Mapping):
            raise ValueError("Evaluation Case Set cases must be objects")
        authored_cases.append(case)
        validated_cases.append(validate_evaluation_case(case))
    return authored_cases, validated_cases


def _summarize_record(record_path: Path, runs_root: Path) -> dict[str, Any]:
    complete = not record_path.name.endswith(".incomplete")
    run = validate_record(record_path, require_complete=complete)
    observations = [
        json.loads((record_path / item["path"]).read_text(encoding="utf-8"))
        for item in run["observations"]
    ]
    integrity = json.loads(
        (record_path / "integrity.json").read_text(encoding="utf-8")
    )
    return {
        "grader_errors": sum(
            item.get("terminal_status") == "grader_error" for item in observations
        ),
        "grading_coverage": run["summary"]["grading_coverage"],
        "planned": run["summary"]["planned"],
        "not_tested": sum(
            item.get("terminal_status") == "not_tested" for item in observations
        ),
        "run_record": {
            "fingerprint": integrity["record_fingerprint"],
            "path": record_path.resolve().relative_to(runs_root.resolve()).as_posix(),
            "path_base": "runs_root",
            "state": run["lifecycle"]["state"],
        },
        "target_errors": sum(
            item.get("terminal_status") == "target_error" for item in observations
        ),
        "target_system_id": run["plan"][0]["target_system_id"],
        "text_leaks": run["summary"]["leak_rate"],
    }


def _reserve_summary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Benchmark Summary already exists: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.touch(exist_ok=False)
    return temporary


def _write_summary(
    temporary: Path, path: Path, summary: Mapping[str, Any]
) -> None:
    with temporary.open("wb") as handle:
        handle.write(canonical_json(summary) + b"\n")
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise FileExistsError(f"Benchmark Summary already exists: {path}") from error
