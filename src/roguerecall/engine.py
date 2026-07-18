from __future__ import annotations

import json
import base64
import platform
import secrets
import time
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from datetime import datetime, timezone

from . import __version__
from .cases import validate_evaluation_case
from .grading import GRADER_VERSION, grade_observation
from .records import (
    SCHEMA_VERSION,
    canonical_json,
    sha256_bytes,
    validate_record,
    write_artifact,
    write_integrity,
    write_json,
)
from .targets import (
    EngineExecutionError,
    Transport,
    UrllibTransport,
    execute_target_systems,
    validate_target_manifest,
)


def run_targets(
    runs_root: Path,
    manifest: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None = None,
) -> Path:
    """Run a non-release Evaluation Case Set against declared Target Systems."""

    return _run_targets(
        runs_root,
        manifest,
        cases,
        environ=environ,
        transport_factory=transport_factory,
    )


def _run_targets(
    runs_root: Path,
    manifest: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    environ: Mapping[str, str] | None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None,
) -> Path:
    started_monotonic = time.monotonic_ns()
    started_at = _utc_now()
    run_id = _uuid7()
    record_path = runs_root / f"{run_id}.incomplete"
    complete_path = runs_root / run_id
    record_path.mkdir(parents=True)
    ca_bundles = _ca_bundle_paths(manifest)
    validated_manifest = validate_target_manifest(manifest, environ=environ)
    validated_cases = [validate_evaluation_case(case) for case in cases]
    if not validated_cases:
        raise ValueError("an Evaluation Run requires at least one Evaluation Case")
    case_set = {"cases": validated_cases, "schema_version": "1.0.0"}
    case_fingerprint = sha256_bytes(canonical_json(case_set))
    target_fingerprint = validated_manifest["fingerprint"]
    case_path = "cases/corpus.json"
    target_path = "targets/manifest.json"
    write_json(record_path / case_path, case_set)
    write_json(record_path / target_path, validated_manifest)

    execution_cases = [
        {
            "case_id": case["identity"]["case_id"],
            "prompt": case["prompt"]["text"],
        }
        for case in validated_cases
    ]
    if transport_factory is None:
        factory: Callable[[Mapping[str, Any]], Transport] = lambda target: (
            UrllibTransport(ca_bundles.get(target["target_system_id"]))
        )
    else:
        factory = transport_factory
    reports = execute_target_systems(
        validated_manifest,
        execution_cases,
        factory,
        environ=environ,
        persist_attempt=lambda attempt: _persist_attempt_record(record_path, attempt),
    )
    write_json(
        record_path / target_path,
        {
            "manifest": validated_manifest,
            "preflights": [
                {
                    "preflight": report["preflight"],
                    "target_system_id": report["target_system_id"],
                    "warnings": report["warnings"],
                }
                for report in reports
            ],
        },
    )
    cases_by_id = {case["identity"]["case_id"]: case for case in validated_cases}
    observations: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    warnings: list[str] = (
        []
    )
    contains_not_tested = False
    for report in reports:
        for warning in report["warnings"]:
            if warning not in warnings:
                warnings.append(warning)
        target_id = report["target_system_id"]
        for result in report["observations"]:
            case_id = result["case_id"]
            plan_position = len(plan)
            plan.append(
                {
                    "case_id": case_id,
                    "position": plan_position,
                    "target_system_id": target_id,
                }
            )
            result["planned_position"] = plan_position
            if result["terminal_status"] == "not_tested":
                contains_not_tested = True
            observation = _persist_target_observation(
                record_path,
                result,
                cases_by_id[case_id],
                case_fingerprint,
                target_fingerprint,
            )
            observation_path = f"observations/{target_id}/{case_id}.json"
            write_json(record_path / observation_path, observation)
            observations.append(
                {
                    "case_id": case_id,
                    "path": observation_path,
                    "target_system_id": target_id,
                }
            )
            if isinstance(result.get("error"), dict):
                errors.append(result["error"])

    lifecycle_state = "incomplete" if contains_not_tested else "complete"
    graded_count = sum(
        1
        for item in observations
        if _read_observation_status(record_path / item["path"]) == "graded"
    )
    text_leaks = sum(
        1
        for item in observations
        if _read_observation_leak(record_path / item["path"])
    )
    run = {
        "case_set": {
            "fingerprint": case_fingerprint,
            "path": case_path,
        },
        "engine": {
            "architecture": platform.machine(),
            "operating_system": platform.system(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "roguerecall_version": __version__,
            "source_revision": "unknown",
        },
        "errors": errors,
        "lifecycle": {
            "cause": errors[0] if contains_not_tested and errors else None,
            "elapsed_milliseconds": (time.monotonic_ns() - started_monotonic) // 1_000_000,
            "finished_at": _utc_now(),
            "last_known_progress": f"{len(observations)}/{len(plan)} observations recorded",
            "started_at": started_at,
            "state": lifecycle_state,
        },
        "observations": observations,
        "plan": plan,
        "record_counts": {"observations": len(observations), "planned": len(plan)},
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "formula_version": "1.0.0",
            "graded": graded_count,
            "grading_coverage": {"denominator": len(plan), "numerator": graded_count},
            "leak_rate": {"denominator": graded_count, "numerator": text_leaks},
            "planned": len(plan),
            "text_leaks": text_leaks,
        },
        "target": {
            "fingerprint": target_fingerprint,
            "path": target_path,
            "target_system_id": "declared-target-systems",
        },
        "versions": {
            "adapter_contract": "1.0.0",
            "dependencies": {
                "PyNaCl": "1.6.2",
                "Pygments": "2.20.0",
                "regex": "2024.11.6",
            },
            "grader": GRADER_VERSION,
            "lexer": "Pygments-2.20.0",
            "normalization": "unicode-nfc-full-casefold-uax29-1.0.0",
            "summary_formula": "1.0.0",
        },
        "warnings": warnings,
    }
    write_json(record_path / "run.json", run)
    write_integrity(record_path)
    validate_record(record_path, require_complete=not contains_not_tested)
    if contains_not_tested:
        return record_path
    record_path.rename(complete_path)
    return complete_path


def _persist_target_observation(
    record_path: Path,
    result: dict[str, Any],
    case: dict[str, Any],
    case_fingerprint: str,
    target_fingerprint: str,
) -> dict[str, Any]:
    attempts = result.get("attempts", [])
    final_attempt = attempts[-1] if attempts else None
    request_content = (
        case["prompt"]["text"].encode("utf-8")
        if final_attempt is None
        else final_attempt["request"]["body_utf8"].encode("utf-8")
    )
    response_content = b""
    if final_attempt is not None and final_attempt["response"]["body_base64"] is not None:
        response_content = base64.b64decode(final_attempt["response"]["body_base64"])
    terminal_status = result["terminal_status"]
    grade: dict[str, Any] | None = None
    selected_response = result.get("selected_response")
    if terminal_status == "completed":
        if not isinstance(selected_response, dict) or not isinstance(
            selected_response.get("text"), str
        ):
            raise EngineExecutionError("completed response has no gradeable text")
        grade = grade_observation(case, selected_response["text"])
        terminal_status = "graded" if grade["evaluation_status"] == "completed" else "grader_error"
    normalized = canonical_json(
        {
            "decisive_matches": [] if grade is None else grade["decisive_matches"],
            "diagnostics": [] if grade is None else grade["diagnostics"],
            "normalization": "unicode-nfc-full-casefold-uax29-1.0.0",
        }
    )
    artifacts = {
        "normalized_evidence": write_artifact(record_path, "evidence", normalized, "json"),
        "request": write_artifact(record_path, "requests", request_content, "json"),
        "response": write_artifact(record_path, "responses", response_content, "json"),
    }
    observation = {
        "artifacts": artifacts,
        "attempts": attempts,
        "case_id": result["case_id"],
        "case_set_fingerprint": case_fingerprint,
        "planned_position": result["planned_position"],
        "target_system_id": result.get("target_system_id"),
        "target_system_manifest_fingerprint": target_fingerprint,
        "terminal_status": terminal_status,
        "timestamps": result.get("timestamps", {"finished_at": _utc_now(), "started_at": _utc_now()}),
        "warnings": result.get("warnings", []),
    }
    if selected_response is not None:
        observation["selected_response"] = selected_response
    if grade is not None:
        observation["grade"] = grade
    if "error" in result:
        observation["error"] = result["error"]
    if result.get("response_condition") is not None:
        observation["response_condition"] = result["response_condition"]
    return observation


def _persist_attempt_record(record_path: Path, attempt: dict[str, Any]) -> None:
    relative_path = (
        Path("attempts")
        / attempt["target_system_id"]
        / attempt["case_id"]
        / f"{attempt['attempt_number']:02d}-{attempt['attempt_id']}.json"
    )
    write_json(record_path / relative_path, attempt)


def _read_observation_status(path: Path) -> str | None:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value.get("terminal_status") if isinstance(value, dict) else None


def _read_observation_leak(path: Path) -> bool:
    value = json.loads(path.read_text(encoding="utf-8"))
    return isinstance(value, dict) and value.get("grade", {}).get("text_leak") is True


def _ca_bundle_paths(manifest: Mapping[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    targets = manifest.get("target_systems")
    if not isinstance(targets, list):
        return paths
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        target_id = target.get("target_system_id")
        ca_bundle = target.get("ca_bundle")
        if isinstance(target_id, str) and isinstance(ca_bundle, str):
            paths[target_id] = ca_bundle
    return paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uuid7() -> str:
    timestamp_ms = int(time.time() * 1000)
    random_bits = secrets.randbits(74)
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    hexadecimal = f"{value:032x}"
    return "-".join(
        (
            hexadecimal[:8],
            hexadecimal[8:12],
            hexadecimal[12:16],
            hexadecimal[16:20],
            hexadecimal[20:],
        )
    )
