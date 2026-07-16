from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from roguerecall.qualification import QualificationValidationError, validate_qualification_report


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _artifact(root: Path, name: str, content: bytes = b"passed\n") -> dict[str, str]:
    path = root / name
    path.write_bytes(content)
    return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}


def _matrix(true_positive: int, true_negative: int) -> dict[str, int | float | None]:
    return {
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": 0,
        "false_negative": 0,
        "sample_count": true_positive + true_negative,
        "sensitivity": 1.0,
        "false_positive_upper_95": 1 - 0.05 ** (1 / true_negative),
    }


def _report(tmp_path: Path) -> Path:
    evidence = _artifact(tmp_path, "evidence.txt")
    domains = {domain: _matrix(4, 299) for domain in ("book", "lyrics", "code")}
    overall = _matrix(12, 897)
    categories = (
        "correctness", "traceability", "provider", "corpus", "security",
        "performance", "accessibility", "packaging", "documentation",
    )
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "corpus_candidate_record": "RogueRecall V1 Corpus Candidate Record",
        "generated_at": "2026-07-16T10:00:00Z",
        "source_revision": "0" * 40,
        "contracts": {"grading": "1.0.0", "run_record": "1.0.0"},
        "environments": [{"id": "linux-x64", "os": "Linux", "architecture": "x86-64", "python": "3.12", "browser": "Firefox"}],
        "grader_validation": {"set_version": "1.0.0", "artifact": evidence, "overall": overall, "domains": domains},
        "adapter_conformance": [
            {"adapter_id": adapter, "contract_version": "1.0.0", "outcome": "passed", "artifact": evidence}
            for adapter in ("openai-responses-v1", "anthropic-messages-v1", "openai-compatible-chat-v1")
        ],
        "corpus_candidate_record_evidence": {"case_count": 50, "outcome": "passed", "artifact": evidence},
        "gates": [
            {"id": f"{category}-gate", "category": category, "outcome": "passed", "contract": "1.0.0", "environment": "linux-x64", "inputs": ["candidate"], "artifacts": [evidence], "exception_id": None}
            for category in categories
        ],
        "exceptions": [],
    }
    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_complete_reproducible_v1_qualification_evidence_passes(tmp_path: Path) -> None:
    report_path = _report(tmp_path)

    report = validate_qualification_report(report_path, now=NOW)

    assert report["grader_validation"]["overall"]["sample_count"] == 909
    assert {gate["category"] for gate in report["gates"]} == {
        "correctness", "traceability", "provider", "corpus", "security",
        "performance", "accessibility", "packaging", "documentation",
    }


@pytest.mark.parametrize("category", ["correctness", "traceability", "provider", "corpus", "security", "accessibility", "packaging", "documentation"])
def test_non_waivable_gate_failures_are_rejected(tmp_path: Path, category: str) -> None:
    report_path = _report(tmp_path)
    report = json.loads(report_path.read_text())
    report["exceptions"] = [{"id": "waiver", "category": "performance", "owner": "owner", "reason": "reason", "expires_at": "2026-08-01T00:00:00Z"}]
    gate = next(gate for gate in report["gates"] if gate["category"] == category)
    gate.update({"outcome": "excepted", "exception_id": "waiver"})
    report_path.write_text(json.dumps(report))

    with pytest.raises(QualificationValidationError):
        validate_qualification_report(report_path, now=NOW)


def test_expired_or_unowned_exceptions_and_tampered_artifacts_are_rejected(tmp_path: Path) -> None:
    report_path = _report(tmp_path)
    report = json.loads(report_path.read_text())
    report["exceptions"] = [{"id": "perf", "category": "performance", "owner": "Benchmark Operator", "reason": "provider quota", "expires_at": "2026-07-01T00:00:00Z"}]
    gate = next(gate for gate in report["gates"] if gate["category"] == "performance")
    gate.update({"outcome": "excepted", "exception_id": "perf"})
    report_path.write_text(json.dumps(report))
    with pytest.raises(QualificationValidationError, match="expired"):
        validate_qualification_report(report_path, now=NOW)

    report_path = _report(tmp_path)
    (tmp_path / "evidence.txt").write_text("tampered")
    with pytest.raises(QualificationValidationError, match="hash mismatch"):
        validate_qualification_report(report_path, now=NOW)


def test_grader_metrics_must_be_complete_and_mathematically_consistent(tmp_path: Path) -> None:
    report_path = _report(tmp_path)
    report = json.loads(report_path.read_text())
    report["grader_validation"]["domains"]["book"]["sensitivity"] = 0.0
    report_path.write_text(json.dumps(report))

    with pytest.raises(QualificationValidationError, match="sensitivity"):
        validate_qualification_report(report_path, now=NOW)
