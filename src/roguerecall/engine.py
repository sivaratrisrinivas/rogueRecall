from __future__ import annotations

import json
import base64
import platform
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any

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


TARGET_ID = "synthetic-deterministic-v1"
TARGET_VERSION = "1.0.0"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: str
    started_monotonic: int
    plan: list[dict[str, Any]]
    case_path: str
    case_fingerprint: str
    observation_path: str
    target_path: str
    target_fingerprint: str


def run_synthetic(runs_root: Path, *, inject_failure: str | None = None) -> Path:
    started_monotonic = time.monotonic_ns()
    started_at = _utc_now()
    run_id = _uuid7()
    incomplete_path = runs_root / f"{run_id}.incomplete"
    complete_path = runs_root / run_id
    incomplete_path.mkdir(parents=True)
    case = _load_case()
    target = {
        "adapter_id": "synthetic-deterministic",
        "adapter_version": TARGET_VERSION,
        "authentication": "none",
        "credential_environment_variable": None,
        "deterministic": True,
        "target_system_id": TARGET_ID,
    }
    context = RunContext(
        run_id=run_id,
        started_at=started_at,
        started_monotonic=started_monotonic,
        plan=[
            {
                "case_id": case["identity"]["case_id"],
                "position": 0,
                "target_system_id": TARGET_ID,
            }
        ],
        case_path=f"cases/{case['identity']['case_id']}.json",
        case_fingerprint=sha256_bytes(canonical_json(case)),
        observation_path=(
            f"observations/{TARGET_ID}/{case['identity']['case_id']}.json"
        ),
        target_path=f"targets/{TARGET_ID}.json",
        target_fingerprint=sha256_bytes(canonical_json(target)),
    )
    observations: list[dict[str, Any]] = []
    try:
        write_json(incomplete_path / context.case_path, case)
        write_json(incomplete_path / context.target_path, target)
        if inject_failure == "operator-interrupted":
            raise KeyboardInterrupt
        observations.append(_execute_observation(incomplete_path, context, case))
        if inject_failure == "finalization-interrupted":
            raise KeyboardInterrupt
        return _finalize_completed_record(
            incomplete_path, complete_path, context, observations
        )
    except KeyboardInterrupt:
        progress = (
            "1/1 observations graded; finalization interrupted"
            if observations
            else "0/1 observations reached a terminal outcome"
        )
        return _preserve_incomplete_record(
            incomplete_path,
            context,
            case,
            target,
            observations=observations,
            cause={
                "code": "operator_interrupted",
                "message": "Synthetic interruption requested by the Benchmark Operator",
            },
            last_known_progress=progress,
        )
    except Exception as error:
        _preserve_incomplete_record(
            incomplete_path,
            context,
            case,
            target,
            observations=observations,
            cause={
                "code": "engine_error",
                "message": f"Synthetic Evaluation Run stopped after {type(error).__name__}",
            },
            last_known_progress=(
                "1/1 observations graded; finalization failed"
                if observations
                else "0/1 observations reached a terminal outcome"
            ),
        )
        raise


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
        release_resolution=None,
        environ=environ,
        transport_factory=transport_factory,
    )


def run_release(
    runs_root: Path,
    manifest: Mapping[str, Any],
    release_path: Path,
    trust_store: Any,
    *,
    registry_snapshot: Mapping[str, Any],
    checked_at: datetime,
    refresh_registry: Callable[[], Mapping[str, Any]] | None = None,
    max_snapshot_age: timedelta = timedelta(days=1),
    explicitly_pinned: bool = False,
    audit_override_reason: str | None = None,
    environ: Mapping[str, str] | None = None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None = None,
) -> Path:
    """Verify and execute the exact cases from one signed Benchmark Corpus Release."""

    from .releases import load_verified_release_cases, resolve_release_for_run

    resolution = resolve_release_for_run(
        release_path,
        trust_store,
        registry_snapshot=registry_snapshot,
        checked_at=checked_at,
        refresh_registry=refresh_registry,
        max_snapshot_age=max_snapshot_age,
        explicitly_pinned=explicitly_pinned,
        audit_override_reason=audit_override_reason,
    )
    cases = load_verified_release_cases(
        release_path,
        trust_store,
        expected_release_digest=resolution["release"]["release_digest"],
    )
    return _run_targets(
        runs_root,
        manifest,
        cases,
        release_resolution=resolution,
        environ=environ,
        transport_factory=transport_factory,
    )


def _run_targets(
    runs_root: Path,
    manifest: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    release_resolution: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None,
    transport_factory: Callable[[Mapping[str, Any]], Transport] | None,
) -> Path:

    validated_resolution = None
    if release_resolution is not None:
        from .releases import validate_release_resolution

        validated_resolution = validate_release_resolution(release_resolution)
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
        list(validated_resolution["warnings"]) if validated_resolution is not None else []
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
    if validated_resolution is not None:
        run["corpus"] = validated_resolution
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


def _finalize_completed_record(
    incomplete_path: Path,
    complete_path: Path,
    context: RunContext,
    observations: list[dict[str, Any]],
) -> Path:
    write_json(
        incomplete_path / "run.json",
        _run_index(
            context,
            state="complete",
            observations=observations,
            cause=None,
            last_known_progress="1/1 observations graded",
        ),
    )
    write_integrity(incomplete_path)
    validate_record(incomplete_path)
    incomplete_path.rename(complete_path)
    return complete_path


def _execute_observation(
    record_path: Path, context: RunContext, case: dict[str, Any]
) -> dict[str, Any]:
    request = case["prompt"]["text"].encode("utf-8")
    response_text = case["target"]["eligible"]
    response = response_text.encode("utf-8")
    request_artifact = write_artifact(record_path, "requests", request, "txt")
    response_artifact = write_artifact(record_path, "responses", response, "txt")
    grade = grade_observation(case, response_text)
    normalized_response = canonical_json(
        {
            "decisive_matches": grade["decisive_matches"],
            "diagnostics": grade["diagnostics"],
            "normalization": grade["versions"]["normalization"],
        }
    )
    normalized_artifact = write_artifact(
        record_path, "evidence", normalized_response, "txt"
    )
    observation_started = _utc_now()
    observation_finished = _utc_now()
    write_json(
        record_path / context.observation_path,
        {
            "artifacts": {
                "normalized_evidence": normalized_artifact,
                "request": request_artifact,
                "response": response_artifact,
            },
            "attempts": [],
            "case_id": case["identity"]["case_id"],
            "case_snapshot_fingerprint": context.case_fingerprint,
            "grade": grade,
            "planned_position": 0,
            "selected_response": {
                "adapter_version": TARGET_VERSION,
                "text": response_text,
            },
            "target_system_id": TARGET_ID,
            "target_system_manifest_fingerprint": context.target_fingerprint,
            "terminal_status": "graded",
            "timestamps": {"finished_at": observation_finished, "started_at": observation_started},
        },
    )
    return {
        "case_id": case["identity"]["case_id"],
        "path": context.observation_path,
        "target_system_id": TARGET_ID,
    }


def _preserve_incomplete_record(
    record_path: Path,
    context: RunContext,
    case: dict[str, Any],
    target: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    cause: dict[str, str],
    last_known_progress: str,
) -> Path:
    write_json(record_path / context.case_path, case)
    write_json(record_path / context.target_path, target)
    write_json(
        record_path / "run.json",
        _run_index(
            context,
            state="incomplete",
            observations=observations,
            cause=cause,
            last_known_progress=last_known_progress,
        ),
    )
    write_integrity(record_path)
    validate_record(record_path, require_complete=False)
    return record_path


def _load_case() -> dict[str, Any]:
    data = files("roguerecall").joinpath("data/synthetic_case.json").read_text(encoding="utf-8")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Bundled Evaluation Case must be an object")
    return validate_evaluation_case(value)


def _run_index(
    context: RunContext,
    *,
    state: str,
    observations: list[dict[str, Any]],
    cause: dict[str, str] | None,
    last_known_progress: str,
) -> dict[str, Any]:
    graded = len(observations)
    text_leaks = len(observations)
    return {
        "case": {
            "case_id": context.plan[0]["case_id"],
            "fingerprint": context.case_fingerprint,
            "path": context.case_path,
        },
        "corpus": {
            "corpus_id": "synthetic",
            "snapshot_fingerprint": context.case_fingerprint,
            "version": "1.0.0",
        },
        "engine": {
            "architecture": platform.machine(),
            "operating_system": platform.system(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "roguerecall_version": __version__,
            "source_revision": "unknown",
        },
        "errors": [],
        "lifecycle": {
            "cause": cause,
            "elapsed_milliseconds": (time.monotonic_ns() - context.started_monotonic)
            // 1_000_000,
            "finished_at": _utc_now(),
            "last_known_progress": last_known_progress,
            "started_at": context.started_at,
            "state": state,
        },
        "observations": observations,
        "plan": context.plan,
        "record_counts": {
            "observations": len(observations),
            "planned": len(context.plan),
        },
        "run_id": context.run_id,
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "formula_version": "1.0.0",
            "graded": graded,
            "grading_coverage": {
                "denominator": len(context.plan),
                "numerator": graded,
            },
            "leak_rate": {"denominator": graded, "numerator": text_leaks},
            "planned": len(context.plan),
            "text_leaks": text_leaks,
        },
        "target": {
            "fingerprint": context.target_fingerprint,
            "path": context.target_path,
            "target_system_id": TARGET_ID,
        },
        "versions": {
            "adapter_contract": TARGET_VERSION,
            "dependencies": {
                "PyNaCl": "1.6.2",
                "Pygments": "2.20.0",
                "regex": "2024.11.6",
            },
            "grader": GRADER_VERSION,
            "lexer": "not-applicable-synthetic-v1",
            "normalization": "unicode-nfc-full-casefold-uax29-1.0.0",
            "summary_formula": "1.0.0",
        },
        "warnings": [],
    }


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
