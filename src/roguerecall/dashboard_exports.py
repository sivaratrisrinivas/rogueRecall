from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .dashboard_data import (
    object_value,
    observation_outcome_key,
    read_observations,
    target_context,
)


RESULT_FIELDS = (
    "run_id",
    "case_id",
    "target_system_id",
    "terminal_status",
    "outcome",
    "text_leak",
    "source_identification",
    "response_condition",
    "warning_codes",
    "error_code",
    "error_message",
    "response_artifact_path",
    "response_artifact_sha256",
    "grading_evidence_pointer",
)
ATTEMPT_FIELDS = (
    "run_id",
    "case_id",
    "target_system_id",
    "attempt_number",
    "attempt_id",
    "adapter_id",
    "adapter_version",
    "started_at",
    "finished_at",
    "http_status",
    "returned_model",
    "provider_response_id",
    "response_condition",
    "error_code",
    "request_body_sha256",
    "response_body_sha256",
)


def build_export_package(record_path: Path, run: dict[str, Any]) -> bytes:
    """Build a deterministic, traceable export without copying protected response text."""

    observations = read_observations(record_path, run)
    results = [_result_row(run, observation) for observation in observations]
    attempts = [
        _attempt_row(run, observation, attempt)
        for observation in observations
        for attempt in observation.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    integrity = json.loads((record_path / "integrity.json").read_text(encoding="utf-8"))
    metadata = {
        "export_schema_version": "1.0.0",
        "null_rule": "Unavailable values are empty CSV fields.",
        "spreadsheet_formula_sanitization": (
            "Text beginning with =, +, -, @, tab, or carriage return is prefixed "
            "with an apostrophe."
        ),
        "source": {
            "record_fingerprint": integrity["record_fingerprint"],
            "run_id": run["run_id"],
            "run_record_schema_version": run["schema_version"],
        },
        "target_system_evidence": target_context(record_path, run),
        "tables": {
            "attempts.csv": list(ATTEMPT_FIELDS),
            "results.csv": list(RESULT_FIELDS),
        },
    }
    members = (
        ("results.csv", _csv_bytes(RESULT_FIELDS, results)),
        ("attempts.csv", _csv_bytes(ATTEMPT_FIELDS, attempts)),
        (
            "export-metadata.json",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            ),
        ),
    )
    destination = io.BytesIO()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return destination.getvalue()


def _result_row(run: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    grade = object_value(observation.get("grade"))
    source = object_value(grade.get("source_identification"))
    source_status = source.get("status")
    error = object_value(observation.get("error"))
    response = object_value(object_value(observation.get("artifacts")).get("response"))
    leak = grade.get("text_leak")
    return {
        "run_id": run["run_id"],
        "case_id": observation.get("case_id"),
        "target_system_id": observation.get("target_system_id"),
        "terminal_status": observation.get("terminal_status"),
        "outcome": observation_outcome_key(observation),
        "text_leak": "true" if leak is True else "false" if leak is False else None,
        "source_identification": source_status,
        "response_condition": observation.get("response_condition"),
        "warning_codes": "|".join(observation.get("warnings", [])),
        "error_code": error.get("code"),
        "error_message": error.get("message"),
        "response_artifact_path": response.get("path"),
        "response_artifact_sha256": response.get("sha256"),
        "grading_evidence_pointer": grade.get("evidence_pointer"),
    }


def _attempt_row(
    run: dict[str, Any], observation: dict[str, Any], attempt: dict[str, Any]
) -> dict[str, Any]:
    response = object_value(attempt.get("response"))
    request = object_value(attempt.get("request"))
    error = object_value(attempt.get("error"))
    return {
        "run_id": run["run_id"],
        "case_id": observation.get("case_id"),
        "target_system_id": observation.get("target_system_id"),
        "attempt_number": attempt.get("attempt_number"),
        "attempt_id": attempt.get("attempt_id"),
        "adapter_id": attempt.get("adapter_id"),
        "adapter_version": attempt.get("adapter_version"),
        "started_at": attempt.get("started_at"),
        "finished_at": attempt.get("finished_at"),
        "http_status": response.get("http_status"),
        "returned_model": response.get("returned_model"),
        "provider_response_id": response.get("provider_response_id"),
        "response_condition": attempt.get("response_condition"),
        "error_code": error.get("code"),
        "request_body_sha256": request.get("body_sha256"),
        "response_body_sha256": response.get("body_sha256"),
    }


def _csv_bytes(fields: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _safe_cell(row.get(field)) for field in fields})
    return output.getvalue().encode("utf-8")


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value
