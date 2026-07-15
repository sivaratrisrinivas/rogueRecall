from __future__ import annotations

import json
from pathlib import Path

import pytest

from roguerecall.engine import run_synthetic
from roguerecall.records import (
    RecordValidationError,
    UnsupportedRecordVersion,
    validate_record,
    write_integrity,
    write_json,
)


def test_integrity_validation_rejects_modified_evidence(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    run = validate_record(record_path)
    observation_path = record_path / run["observations"][0]["path"]
    observation_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RecordValidationError, match="integrity"):
        validate_record(record_path)


def test_run_record_excludes_environment_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "rr-secret-value-that-must-never-be-evidence"
    monkeypatch.setenv("ROGUERECALL_SYNTHETIC_TOKEN", secret)
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    record_path = run_synthetic(tmp_path)

    for canonical_file in record_path.rglob("*"):
        if canonical_file.is_file():
            assert secret.encode("utf-8") not in canonical_file.read_bytes()


def test_reader_rejects_unsupported_record_major_version(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    run_path = record_path / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["schema_version"] = "2.0.0"
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(UnsupportedRecordVersion, match="2.0.0"):
        validate_record(record_path)


def test_completed_run_record_requires_every_planned_observation(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    run_path = record_path / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["observations"] = []
    run["record_counts"]["observations"] = 0
    run["summary"] = {
        "formula_version": "1.0.0",
        "graded": 0,
        "grading_coverage": {"denominator": 1, "numerator": 0},
        "leak_rate": {"denominator": 0, "numerator": 0},
        "planned": 1,
        "text_leaks": 0,
    }
    write_json(run_path, run)
    write_integrity(record_path)

    with pytest.raises(RecordValidationError, match="planned observation"):
        validate_record(record_path)


def test_completed_run_record_requires_selected_response_evidence(
    tmp_path: Path,
) -> None:
    record_path = run_synthetic(tmp_path)
    run = json.loads((record_path / "run.json").read_text(encoding="utf-8"))
    observation_path = record_path / run["observations"][0]["path"]
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    del observation["selected_response"]
    write_json(observation_path, observation)
    write_integrity(record_path)

    with pytest.raises(RecordValidationError, match="selected response"):
        validate_record(record_path)
