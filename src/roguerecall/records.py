from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"


class RecordValidationError(ValueError):
    """Raised when a Run Record cannot be trusted."""


class UnsupportedRecordVersion(RecordValidationError):
    """Raised when a reader cannot interpret a Run Record major version."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def write_artifact(
    record_path: Path, category: str, content: bytes, extension: str
) -> dict[str, Any]:
    digest = sha256_bytes(content)
    relative_path = Path("artifacts") / category / f"{digest}.{extension}"
    destination = record_path / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "byte_length": len(content),
        "path": relative_path.as_posix(),
        "sha256": digest,
    }


def build_integrity(record_path: Path) -> dict[str, Any]:
    files = []
    for path in sorted(record_path.rglob("*")):
        if not path.is_file() or path.name == "integrity.json":
            continue
        content = path.read_bytes()
        logical_path = path.relative_to(record_path).as_posix()
        files.append(
            {
                "byte_length": len(content),
                "media_type": _media_type(path),
                "path": logical_path,
                "sha256": sha256_bytes(content),
            }
        )
    fingerprint = sha256_bytes(canonical_json(files))
    return {
        "algorithm": "sha256",
        "canonicalization": "RFC8785-compatible-json-v1",
        "files": files,
        "record_fingerprint": fingerprint,
    }


def write_integrity(record_path: Path) -> dict[str, Any]:
    integrity = build_integrity(record_path)
    write_json(record_path / "integrity.json", integrity)
    return integrity


def validate_record(record_path: Path, *, require_complete: bool = True) -> dict[str, Any]:
    if record_path.is_symlink() or not record_path.is_dir():
        raise RecordValidationError("Run Record path must be a real directory")
    run = _read_json(record_path / "run.json")
    _validate_schema_version(run.get("schema_version"))
    _validate_run_shape(run)
    if require_complete and run.get("lifecycle", {}).get("state") != "complete":
        raise RecordValidationError("Run Record is incomplete")
    integrity = _read_json(record_path / "integrity.json")
    actual = build_integrity(record_path)
    if integrity != actual:
        raise RecordValidationError("Run Record integrity validation failed")
    _validate_references(record_path, run)
    _validate_completion(record_path, run)
    _validate_summary(record_path, run)
    return run


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise RecordValidationError(f"Cannot read canonical JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise RecordValidationError(f"Canonical JSON must be an object: {path.name}")
    return value


def _validate_schema_version(version: Any) -> None:
    if not isinstance(version, str):
        raise RecordValidationError("Run Record has no schema version")
    try:
        major = int(version.split(".", 1)[0])
    except ValueError as error:
        raise RecordValidationError("Run Record schema version is invalid") from error
    if major != 1:
        raise UnsupportedRecordVersion(f"Unsupported Run Record schema version: {version}")


def _validate_run_shape(run: dict[str, Any]) -> None:
    required_objects = ("engine", "lifecycle", "summary", "target", "versions")
    for field in required_objects:
        if not isinstance(run.get(field), dict):
            raise RecordValidationError(f"Run Record field must be an object: {field}")
    case_sources = [field for field in ("case", "case_set") if isinstance(run.get(field), dict)]
    if len(case_sources) != 1:
        raise RecordValidationError("Run Record requires exactly one case or case_set object")
    if "case" in run and not isinstance(run.get("corpus"), dict):
        raise RecordValidationError("Run Record field must be an object: corpus")
    if "corpus" in run and not isinstance(run.get("corpus"), dict):
        raise RecordValidationError("Run Record field must be an object: corpus")
    if "case_set" in run and isinstance(run.get("corpus"), dict):
        from .releases import ReleaseValidationError, validate_release_resolution

        try:
            validate_release_resolution(run["corpus"])
        except ReleaseValidationError as error:
            raise RecordValidationError("Run Record corpus resolution is invalid") from error
    for field in ("observations", "plan"):
        if not isinstance(run.get(field), list):
            raise RecordValidationError(f"Run Record field must be a list: {field}")
        if not all(isinstance(item, dict) for item in run[field]):
            raise RecordValidationError(
                f"Run Record field must contain only objects: {field}"
            )
    for field in ("errors", "warnings"):
        if not isinstance(run.get(field), list):
            raise RecordValidationError(f"Run Record field must be a list: {field}")
    if not isinstance(run.get("record_counts"), dict):
        raise RecordValidationError("Run Record field must be an object: record_counts")
    if not isinstance(run.get("run_id"), str):
        raise RecordValidationError("Run Record has no run ID")


def _validate_references(record_path: Path, run: dict[str, Any]) -> None:
    case_source = _case_source(run)
    references = [case_source.get("path"), run.get("target", {}).get("path")]
    references.extend(item.get("path") for item in run.get("observations", []))
    for reference in references:
        if not isinstance(reference, str) or reference.startswith(("/", "../")):
            raise RecordValidationError("Run Record contains an invalid reference")
        resolved = (record_path / reference).resolve()
        if record_path.resolve() not in resolved.parents or not resolved.is_file():
            raise RecordValidationError(f"Run Record reference does not resolve: {reference}")


def _validate_completion(record_path: Path, run: dict[str, Any]) -> None:
    plan_keys = [_observation_key(item) for item in run["plan"]]
    observation_keys = [_observation_key(item) for item in run["observations"]]
    if len(plan_keys) != len(set(plan_keys)) or len(observation_keys) != len(
        set(observation_keys)
    ):
        raise RecordValidationError("Run Record contains duplicate planned observations")
    counts = run["record_counts"]
    if counts.get("planned") != len(plan_keys) or counts.get("observations") != len(
        observation_keys
    ):
        raise RecordValidationError("Run Record counts do not match its indexes")
    if run["lifecycle"].get("state") != "complete":
        return
    if observation_keys != plan_keys:
        raise RecordValidationError(
            "Completed Run Record does not contain every planned observation"
        )
    for item in run["observations"]:
        observation = _read_json(record_path / item["path"])
        if observation.get("terminal_status") not in {
            "graded",
            "grader_error",
            "target_error",
        }:
            raise RecordValidationError(
                "Completed Run Record contains a non-terminal observation"
            )
        _validate_observation(record_path, run, observation)


def _observation_key(item: dict[str, Any]) -> tuple[str, str]:
    case_id = item.get("case_id")
    target_system_id = item.get("target_system_id")
    if not isinstance(case_id, str) or not isinstance(target_system_id, str):
        raise RecordValidationError(
            "Planned observation identities must contain string IDs"
        )
    return case_id, target_system_id


def _validate_observation(
    record_path: Path, run: dict[str, Any], observation: dict[str, Any]
) -> None:
    timestamps = observation.get("timestamps")
    if not isinstance(timestamps, dict) or not all(
        isinstance(timestamps.get(field), str)
        for field in ("finished_at", "started_at")
    ):
        raise RecordValidationError("Observation timestamps are missing or invalid")
    if not isinstance(observation.get("attempts"), list):
        raise RecordValidationError("Observation attempts must be a list")
    case_source = _case_source(run)
    observed_fingerprint = observation.get("case_snapshot_fingerprint")
    if "case_set" in run:
        observed_fingerprint = observation.get("case_set_fingerprint")
    if observed_fingerprint != case_source.get("fingerprint"):
        raise RecordValidationError("Observation case fingerprint does not match")
    if observation.get("target_system_manifest_fingerprint") != run["target"].get(
        "fingerprint"
    ):
        raise RecordValidationError("Observation target fingerprint does not match")

    if observation["terminal_status"] == "graded":
        selected_response = observation.get("selected_response")
        if not isinstance(selected_response, dict) or not isinstance(
            selected_response.get("text"), str
        ):
            raise RecordValidationError("Graded observation has no selected response")
        grade = observation.get("grade")
        if not isinstance(grade, dict) or not isinstance(grade.get("text_leak"), bool):
            raise RecordValidationError("Graded observation has no valid grade")

    artifacts = observation.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RecordValidationError("Observation artifact inventory is missing")
    for name in ("normalized_evidence", "request", "response"):
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict):
            raise RecordValidationError(f"Observation artifact is missing: {name}")
        _validate_artifact_reference(record_path, artifact)


def _validate_artifact_reference(
    record_path: Path, artifact: dict[str, Any]
) -> None:
    relative_path = artifact.get("path")
    if not isinstance(relative_path, str) or relative_path.startswith(("/", "../")):
        raise RecordValidationError("Observation contains an invalid artifact reference")
    resolved = (record_path / relative_path).resolve()
    if record_path.resolve() not in resolved.parents or not resolved.is_file():
        raise RecordValidationError(
            f"Observation artifact does not resolve: {relative_path}"
        )
    content = resolved.read_bytes()
    if artifact.get("byte_length") != len(content) or artifact.get(
        "sha256"
    ) != sha256_bytes(content):
        raise RecordValidationError(
            f"Observation artifact metadata does not match: {relative_path}"
        )


def _case_source(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("case")
    if not isinstance(value, dict):
        value = run.get("case_set")
    if not isinstance(value, dict):
        raise RecordValidationError("Run Record has no case identity")
    return value


def _validate_summary(record_path: Path, run: dict[str, Any]) -> None:
    observations = [_read_json(record_path / item["path"]) for item in run["observations"]]
    graded = [item for item in observations if item.get("terminal_status") == "graded"]
    leaked = [item for item in graded if item.get("grade", {}).get("text_leak") is True]
    expected = {
        "formula_version": "1.0.0",
        "graded": len(graded),
        "grading_coverage": {"denominator": len(run["plan"]), "numerator": len(graded)},
        "leak_rate": {"denominator": len(graded), "numerator": len(leaked)},
        "planned": len(run["plan"]),
        "text_leaks": len(leaked),
    }
    if run.get("summary") != expected:
        raise RecordValidationError("Run Record summary is not reproducible")


def _media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"
