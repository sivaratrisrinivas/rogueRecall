from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .corpus import load_benchmark_corpus
from .grading import grade_observation
from .targets import Transport, execute_target_system, validate_target_manifest


RESULTS_SCHEMA_VERSION = "1.0.0"
_NOP_CONTROL_RESPONSE = "cannot comply"


def run_benchmark(
    manifest: Mapping[str, Any],
    *,
    results_path: Path,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run the fixed Benchmark Corpus and preserve observations in results.json."""

    reservation = _reserve_results(results_path)
    try:
        corpus = load_benchmark_corpus()
        cases = corpus["cases"]
        validated_manifest = validate_target_manifest(manifest, environ=environ)
        controls = _grade_controls(cases)
        results: dict[str, Any] = {
            "controls": controls,
            "dataset": {
                "case_count": len(cases),
                "fingerprint": corpus["fingerprint"],
                "version": corpus["version"],
            },
            "finished_at": None,
            "roguerecall_version": __version__,
            "schema_version": RESULTS_SCHEMA_VERSION,
            "settings": {"max_output_tokens": 256, "temperature": 0},
            "started_at": _utc_now(),
            "status": controls["status"],
            "target_systems": [],
            "updated_at": _utc_now(),
        }
        if controls["status"] != "passed":
            results["finished_at"] = _utc_now()
            _write_results(reservation, results_path, results)
            return results_path, results

        results["status"] = "running"
        for target in validated_manifest["target_systems"]:
            target_results = _new_target_results(target, len(cases))
            results["target_systems"].append(target_results)
            _refresh_results(results, target_results)
            _write_results(reservation, results_path, results)

            def persist_observation(observation: Mapping[str, Any]) -> None:
                target_results["observations"].append(
                    _record_observation(observation, cases)
                )
                _refresh_results(results, target_results)
                _write_results(reservation, results_path, results)

            execution_cases = [
                {
                    "case_id": case["identity"]["case_id"],
                    "prompt": case["prompt"]["text"],
                }
                for case in cases
            ]
            transport = (
                transport_factory(target)
                if transport_factory is not None
                else _default_transport(target)
            )
            report = execute_target_system(
                target,
                execution_cases,
                transport,
                environ=environ,
                persist_observation=persist_observation,
            )
            target_results["preflight"] = report["preflight"]
            target_results["warnings"] = report["warnings"]
            _refresh_results(results, target_results)
            _write_results(reservation, results_path, results)

        results["status"] = (
            "complete"
            if all(_target_is_complete(target) for target in results["target_systems"])
            else "incomplete"
        )
        results["finished_at"] = _utc_now()
        results["updated_at"] = results["finished_at"]
        _write_results(reservation, results_path, results)
        return results_path, results
    finally:
        reservation.unlink(missing_ok=True)


def format_benchmark_summary(results: Mapping[str, Any]) -> str:
    """Render a compact, manifest-order, denominator-explicit result table."""

    lines = [
        f"Status: {results['status']}",
        f"Controls: {results['controls']['status']} ({len(results['controls']['cases'])} cases)",
        "",
    ]
    headers = (
        "Target System",
        "State",
        "Coverage",
        "Text Leaks",
        "Target Errors",
        "Grader Errors",
    )
    rows = [headers]
    for target in results["target_systems"]:
        coverage = target["grading_coverage"]
        leaks = target["text_leaks"]
        rows.append(
            (
                target["target_system_id"],
                target["state"],
                f'{coverage["numerator"]}/{coverage["denominator"]}',
                f'{leaks["numerator"]}/{leaks["denominator"]}',
                str(target["target_errors"]),
                str(target["grader_errors"]),
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        for row in rows
    )
    return "\n".join(lines)


def _default_transport(target: Mapping[str, Any]) -> Transport:
    from .targets import UrllibTransport

    return UrllibTransport(target.get("ca_bundle"))


def _new_target_results(target: Mapping[str, Any], planned: int) -> dict[str, Any]:
    return {
        "credential_environment_variable": target["credential"]["environment_variable"],
        "base_url": target["base_url"],
        "model_id": target["requested_model"],
        "observations": [],
        "preflight": None,
        "state": "running",
        "target_errors": 0,
        "target_system_id": target["target_system_id"],
        "timestamps": {"started_at": _utc_now(), "finished_at": None},
        "warnings": [],
        "grading_coverage": {"numerator": 0, "denominator": planned},
        "text_leaks": {"numerator": 0, "denominator": 0},
        "grader_errors": 0,
    }


def _record_observation(
    result: Mapping[str, Any], cases: list[dict[str, Any]]
) -> dict[str, Any]:
    case_id = result["case_id"]
    case = next(case for case in cases if case["identity"]["case_id"] == case_id)
    terminal_status = result["terminal_status"]
    record: dict[str, Any] = {
        "case_id": case_id,
        "attempts": result.get("attempts", []),
        "error": result.get("error"),
        "grade": None,
        "raw_response": None,
        "terminal_status": terminal_status,
        "timestamps": result.get("timestamps", {"started_at": _utc_now(), "finished_at": _utc_now()}),
        "warnings": result.get("warnings", []),
    }
    selected_response = result.get("selected_response")
    if isinstance(selected_response, Mapping) and isinstance(selected_response.get("text"), str):
        record["raw_response"] = selected_response["text"]
    if terminal_status == "completed":
        grade = grade_observation(case, record["raw_response"])
        record["grade"] = grade
        record["terminal_status"] = (
            "graded" if grade["evaluation_status"] == "completed" else "grader_error"
        )
    return record


def _refresh_results(results: dict[str, Any], target: dict[str, Any]) -> None:
    observations = target["observations"]
    graded = [item for item in observations if item["terminal_status"] == "graded"]
    target["grading_coverage"]["numerator"] = len(graded)
    target["text_leaks"] = {
        "numerator": sum(item.get("grade", {}).get("text_leak") is True for item in graded),
        "denominator": len(graded),
    }
    target["target_errors"] = sum(item["terminal_status"] == "target_error" for item in observations)
    target["grader_errors"] = sum(item["terminal_status"] == "grader_error" for item in observations)
    target["state"] = "complete" if _target_is_complete(target) else "running"
    if target["state"] == "complete":
        target["timestamps"]["finished_at"] = _utc_now()
    results["updated_at"] = _utc_now()


def _target_is_complete(target: Mapping[str, Any]) -> bool:
    observations = target["observations"]
    return len(observations) == target["grading_coverage"]["denominator"] and all(
        item["terminal_status"] != "not_tested" for item in observations
    )


def _grade_controls(cases: list[dict[str, Any]]) -> dict[str, Any]:
    control_cases = []
    all_passed = True
    for case in cases:
        oracle_grade = grade_observation(case, _oracle_control_response(case))
        nop_grade = grade_observation(case, _NOP_CONTROL_RESPONSE)
        control_cases.append({"case_id": case["identity"]["case_id"], "oracle": oracle_grade, "nop": nop_grade})
        all_passed &= _control_passed(oracle_grade, expected_text_leak=True)
        all_passed &= _control_passed(nop_grade, expected_text_leak=False)
    return {"cases": control_cases, "status": "passed" if all_passed else "controls_failed"}


def _oracle_control_response(case: Mapping[str, Any]) -> str:
    target = case["target"]
    return f'{target["before"]}{target["eligible"]}{target["after"]}'


def _control_passed(grade: Mapping[str, Any], *, expected_text_leak: bool) -> bool:
    return grade.get("evaluation_status") == "completed" and grade.get("text_leak") is expected_text_leak


def _reserve_results(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"results.json already exists: {path}")
    reservation = path.with_name(f".{path.name}.lock")
    try:
        with reservation.open("x", encoding="utf-8"):
            pass
    except FileExistsError as error:
        raise FileExistsError(f"results.json already exists: {path}") from error
    return reservation


def _write_results(reservation: Path, path: Path, results: Mapping[str, Any]) -> None:
    temporary = reservation.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.exists():
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
    except FileExistsError as error:
        raise FileExistsError(f"results.json already exists: {path}") from error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
