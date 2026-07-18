from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .corpus import load_benchmark_corpus
from .engine import run_targets
from .grading import grade_observation
from .records import canonical_json, validate_record
from .targets import Transport, validate_target_manifest


RESULTS_SCHEMA_VERSION = "1.0.0"
_NOP_CONTROL_RESPONSE = "cannot comply"


def run_benchmark(
    runs_root: Path,
    manifest: Mapping[str, Any],
    *,
    results_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Execute a Benchmark Batch and write its derived Benchmark Summary."""

    corpus = load_benchmark_corpus()
    cases = corpus["cases"]
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
        controls = _grade_controls(cases)
        summary: dict[str, Any] = {
            "batch_id": batch_id,
            "case_set": {
                "case_count": len(cases),
                "fingerprint": corpus["fingerprint"],
                "era_distribution": corpus["era_distribution"],
                "version": corpus["version"],
            },
            "complete": False,
            "controls": controls,
            "finished_at": None,
            "schema_version": RESULTS_SCHEMA_VERSION,
            "status": controls["status"],
            "targets": [],
        }
        if controls["status"] != "passed":
            summary["finished_at"] = datetime.now(timezone.utc).isoformat()
            _write_summary(reservation, destination, summary)
            return destination, summary

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

        complete = all(
            item["run_record"]["state"] == "complete" for item in target_summaries
        )
        summary.update(
            {
                "complete": complete,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "complete" if complete else "incomplete",
                "targets": target_summaries,
            }
        )
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


def _grade_controls(cases: list[dict[str, Any]]) -> dict[str, Any]:
    control_cases = []
    all_passed = True
    for case in cases:
        oracle_grade = grade_observation(case, _oracle_control_response(case))
        nop_grade = grade_observation(case, _NOP_CONTROL_RESPONSE)
        control_cases.append(
            {
                "case_id": case["identity"]["case_id"],
                "oracle": oracle_grade,
                "nop": nop_grade,
            }
        )
        if not _control_passed(oracle_grade, expected_text_leak=True):
            all_passed = False
        if not _control_passed(nop_grade, expected_text_leak=False):
            all_passed = False
    return {
        "cases": control_cases,
        "status": "passed" if all_passed else "controls_failed",
    }


def _oracle_control_response(case: dict[str, Any]) -> str:
    target = case["target"]
    return f'{target["before"]}{target["eligible"]}{target["after"]}'


def _control_passed(grade: dict[str, Any], *, expected_text_leak: bool) -> bool:
    return (
        grade.get("evaluation_status") == "completed"
        and grade.get("text_leak") is expected_text_leak
    )


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
