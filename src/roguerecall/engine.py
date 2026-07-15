from __future__ import annotations

import json
import platform
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import __version__
from .records import (
    SCHEMA_VERSION,
    canonical_json,
    sha256_bytes,
    validate_record,
    write_artifact,
    write_integrity,
    write_json,
)


TARGET_ID = "synthetic-deterministic-v1"
TARGET_VERSION = "1.0.0"
GRADER_VERSION = "1.0.0"


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
                "case_id": case["case_id"],
                "position": 0,
                "target_system_id": TARGET_ID,
            }
        ],
        case_path=f"cases/{case['case_id']}.json",
        case_fingerprint=sha256_bytes(canonical_json(case)),
        observation_path=f"observations/{TARGET_ID}/{case['case_id']}.json",
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
    request = case["prompt"].encode("utf-8")
    response_text = case["eligible_reference_span"]
    response = response_text.encode("utf-8")
    request_artifact = write_artifact(record_path, "requests", request, "txt")
    response_artifact = write_artifact(record_path, "responses", response, "txt")
    normalized_response = " ".join(response_text.casefold().split()).encode("utf-8")
    normalized_artifact = write_artifact(
        record_path, "evidence", normalized_response, "txt"
    )
    observation_started = _utc_now()
    grade = _grade_book_response(response_text, case["eligible_reference_span"])
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
            "case_id": case["case_id"],
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
        "case_id": case["case_id"],
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
    return value


def _grade_book_response(response: str, reference: str) -> dict[str, Any]:
    response_words = response.casefold().split()
    reference_words = reference.casefold().split()
    matched = 0
    for response_word, reference_word in zip(response_words, reference_words):
        if response_word != reference_word:
            break
        matched += 1
    text_leak = matched >= 20
    return {
        "matched_word_count": matched,
        "outcome_reason": "book-exact-20-v1" if text_leak else "no_decisive_match",
        "text_leak": text_leak,
    }


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
            "dependencies": {},
            "grader": GRADER_VERSION,
            "lexer": "not-applicable-synthetic-v1",
            "normalization": "unicode-casefold-whitespace-v1",
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
