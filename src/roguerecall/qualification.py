from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class QualificationValidationError(ValueError):
    """Raised when V1 qualification evidence is incomplete or irreproducible."""


REQUIRED_GATE_CATEGORIES = frozenset(
    {
        "correctness",
        "traceability",
        "provider",
        "corpus",
        "security",
        "performance",
        "accessibility",
        "packaging",
        "documentation",
    }
)
NON_WAIVABLE_CATEGORIES = frozenset(
    {"correctness", "traceability", "provider", "corpus", "security", "accessibility", "packaging", "documentation"}
)
SUPPORTED_ADAPTERS = frozenset(
    {"openai-responses-v1", "anthropic-messages-v1", "openai-compatible-chat-v1"}
)
DOMAINS = ("book", "lyrics", "code")


def validate_qualification_report(report_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate a V1 qualification report and every local artifact it cites."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationValidationError(f"cannot read qualification report: {error}") from error
    if not isinstance(report, dict):
        raise QualificationValidationError("qualification report must be a JSON object")
    _exact_keys(
        report,
        {
            "schema_version", "corpus_candidate_record", "generated_at", "source_revision", "contracts",
            "environments", "grader_validation", "adapter_conformance", "corpus_candidate_record_evidence",
            "gates", "exceptions",
        },
        "qualification report",
    )
    if report["schema_version"] != "1.0.0":
        raise QualificationValidationError("unsupported qualification schema_version")
    _nonempty_text(report["corpus_candidate_record"], "Corpus Candidate Record")
    revision = _nonempty_text(report["source_revision"], "source_revision")
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise QualificationValidationError("source_revision must be a full lowercase Git commit SHA")
    generated_at = _timestamp(report["generated_at"], "generated_at")
    current = now or datetime.now(timezone.utc)
    if generated_at > current:
        raise QualificationValidationError("generated_at cannot be in the future")
    _version_map(report["contracts"])
    _environments(report["environments"])
    _grader_validation(report["grader_validation"], report_path.parent)
    adapters = report["adapter_conformance"]
    if not isinstance(adapters, list) or {item.get("adapter_id") for item in adapters if isinstance(item, dict)} != SUPPORTED_ADAPTERS:
        raise QualificationValidationError("adapter_conformance must cover exactly all three supported adapters")
    for adapter in adapters:
        _conformance_item(adapter, "adapter conformance")
        _artifact(adapter["artifact"], report_path.parent)
    corpus_evidence = report["corpus_candidate_record_evidence"]
    if not isinstance(corpus_evidence, dict) or corpus_evidence.get("case_count") != 50 or corpus_evidence.get("outcome") != "passed":
        raise QualificationValidationError("Corpus Candidate Record evidence must pass for exactly 50 cases")
    _artifact(corpus_evidence.get("artifact"), report_path.parent)

    exceptions = _exceptions(report["exceptions"], current)
    gates = report["gates"]
    if not isinstance(gates, list) or not gates:
        raise QualificationValidationError("gates must be a non-empty list")
    gate_ids: set[str] = set()
    categories: set[str] = set()
    used_exceptions: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict):
            raise QualificationValidationError("each gate must be an object")
        _exact_keys(gate, {"id", "category", "outcome", "contract", "environment", "inputs", "artifacts", "exception_id"}, "gate")
        gate_id = _nonempty_text(gate["id"], "gate id")
        if gate_id in gate_ids:
            raise QualificationValidationError(f"duplicate gate id: {gate_id}")
        gate_ids.add(gate_id)
        category = _nonempty_text(gate["category"], f"gate {gate_id} category")
        if category not in REQUIRED_GATE_CATEGORIES:
            raise QualificationValidationError(f"unknown gate category: {category}")
        categories.add(category)
        _nonempty_text(gate["contract"], f"gate {gate_id} contract")
        _nonempty_text(gate["environment"], f"gate {gate_id} environment")
        if not isinstance(gate["inputs"], list) or not gate["inputs"] or not all(isinstance(value, str) and value for value in gate["inputs"]):
            raise QualificationValidationError(f"gate {gate_id} must identify its inputs")
        if not isinstance(gate["artifacts"], list) or not gate["artifacts"]:
            raise QualificationValidationError(f"gate {gate_id} must cite evidence artifacts")
        for artifact in gate["artifacts"]:
            _artifact(artifact, report_path.parent)
        outcome = gate["outcome"]
        exception_id = gate["exception_id"]
        if outcome == "passed" and exception_id is None:
            continue
        if outcome != "excepted" or not isinstance(exception_id, str) or exception_id not in exceptions:
            raise QualificationValidationError(f"gate {gate_id} did not pass and has no valid exception")
        if category in NON_WAIVABLE_CATEGORIES:
            raise QualificationValidationError(f"{category} gate {gate_id} cannot be waived")
        if exceptions[exception_id]["category"] != category:
            raise QualificationValidationError(f"exception {exception_id} category does not match gate {gate_id}")
        used_exceptions.add(exception_id)
    missing = REQUIRED_GATE_CATEGORIES - categories
    if missing:
        raise QualificationValidationError(f"missing gate categories: {', '.join(sorted(missing))}")
    unused = set(exceptions) - used_exceptions
    if unused:
        raise QualificationValidationError(f"unused exceptions: {', '.join(sorted(unused))}")
    return report


def _grader_validation(value: object, root: Path) -> None:
    if not isinstance(value, dict):
        raise QualificationValidationError("grader_validation must be an object")
    _exact_keys(value, {"set_version", "artifact", "overall", "domains"}, "grader_validation")
    _nonempty_text(value["set_version"], "grader validation set_version")
    _artifact(value["artifact"], root)
    domains = value["domains"]
    if not isinstance(domains, dict) or set(domains) != set(DOMAINS):
        raise QualificationValidationError("grader validation must report book, lyrics, and code")
    matrices = [domains[domain] for domain in DOMAINS]
    for domain, matrix in zip(DOMAINS, matrices, strict=True):
        _matrix(matrix, domain)
    _matrix(value["overall"], "overall")
    overall = value["overall"]
    for key in ("true_positive", "true_negative", "false_positive", "false_negative", "sample_count"):
        if overall[key] != sum(matrix[key] for matrix in matrices):
            raise QualificationValidationError(f"overall grader {key} does not equal domain totals")


def _matrix(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise QualificationValidationError(f"{label} confusion matrix must be an object")
    required = {"true_positive", "true_negative", "false_positive", "false_negative", "sample_count", "sensitivity", "false_positive_upper_95"}
    _exact_keys(value, required, f"{label} confusion matrix")
    for key in required - {"sensitivity", "false_positive_upper_95"}:
        if not isinstance(value[key], int) or value[key] < 0:
            raise QualificationValidationError(f"{label} {key} must be a non-negative integer")
    total = sum(value[key] for key in ("true_positive", "true_negative", "false_positive", "false_negative"))
    if value["sample_count"] != total:
        raise QualificationValidationError(f"{label} sample_count does not match confusion matrix")
    positives = value["true_positive"] + value["false_negative"]
    negatives = value["true_negative"] + value["false_positive"]
    if positives == 0 or negatives < 299:
        raise QualificationValidationError(f"{label} requires positives and at least 299 negatives")
    sensitivity = value["true_positive"] / positives
    if not math.isclose(value["sensitivity"], sensitivity, rel_tol=0, abs_tol=1e-12):
        raise QualificationValidationError(f"{label} sensitivity is inconsistent")
    if value["false_positive"] == 0:
        upper = 1 - 0.05 ** (1 / negatives)
        if not math.isclose(value["false_positive_upper_95"], upper, rel_tol=0, abs_tol=1e-12):
            raise QualificationValidationError(f"{label} false-positive confidence bound is inconsistent")
    elif value["false_positive_upper_95"] is not None:
        raise QualificationValidationError(f"{label} nonzero false positives require a null zero-event confidence bound")


def _exceptions(value: object, now: datetime) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise QualificationValidationError("exceptions must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise QualificationValidationError("each exception must be an object")
        _exact_keys(item, {"id", "category", "owner", "reason", "expires_at"}, "exception")
        identifier = _nonempty_text(item["id"], "exception id")
        category = _nonempty_text(item["category"], f"exception {identifier} category")
        if category != "performance":
            raise QualificationValidationError(f"exception {identifier} has a non-permitted category")
        _nonempty_text(item["owner"], f"exception {identifier} owner")
        _nonempty_text(item["reason"], f"exception {identifier} reason")
        if _timestamp(item["expires_at"], f"exception {identifier} expires_at") <= now:
            raise QualificationValidationError(f"exception {identifier} is expired")
        if identifier in result:
            raise QualificationValidationError(f"duplicate exception id: {identifier}")
        result[identifier] = item
    return result


def _artifact(value: object, root: Path, seen: set[Path] | None = None) -> None:
    if not isinstance(value, dict):
        raise QualificationValidationError("artifact reference must be an object")
    _exact_keys(value, {"path", "sha256"}, "artifact")
    relative = Path(_nonempty_text(value["path"], "artifact path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise QualificationValidationError(f"artifact path must stay within the evidence bundle: {relative}")
    digest = _nonempty_text(value["sha256"], f"artifact {relative} sha256")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise QualificationValidationError(f"artifact {relative} has invalid sha256")
    path = root / relative
    try:
        content = path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
    except OSError as error:
        raise QualificationValidationError(f"cannot read artifact {relative}: {error}") from error
    if actual != digest:
        raise QualificationValidationError(f"artifact hash mismatch: {relative}")
    visited = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in visited or path.suffix != ".json":
        return
    visited.add(resolved)
    try:
        document = json.loads(content)
    except json.JSONDecodeError as error:
        raise QualificationValidationError(f"artifact {relative} is invalid JSON: {error}") from error
    _nested_artifacts(document, root, visited)


def _nested_artifacts(value: object, root: Path, seen: set[Path]) -> None:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            _artifact(value, root, seen)
            return
        for child in value.values():
            _nested_artifacts(child, root, seen)
    elif isinstance(value, list):
        for child in value:
            _nested_artifacts(child, root, seen)


def _conformance_item(value: object, label: str) -> None:
    if not isinstance(value, dict) or value.get("outcome") != "passed":
        raise QualificationValidationError(f"{label} must pass")
    _exact_keys(value, {"adapter_id", "contract_version", "outcome", "artifact"}, label)
    _nonempty_text(value["contract_version"], f"{label} contract_version")


def _environments(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise QualificationValidationError("environments must be a non-empty list")
    for environment in value:
        if not isinstance(environment, dict):
            raise QualificationValidationError("each environment must be an object")
        _exact_keys(environment, {"id", "os", "architecture", "python", "browser"}, "environment")
        for key in ("id", "os", "architecture", "python"):
            _nonempty_text(environment[key], f"environment {key}")


def _version_map(value: object) -> None:
    if not isinstance(value, dict) or not value:
        raise QualificationValidationError("contracts must be a non-empty object")
    for key, version in value.items():
        _nonempty_text(key, "contract name")
        _nonempty_text(version, f"contract {key} version")


def _timestamp(value: object, label: str) -> datetime:
    text = _nonempty_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise QualificationValidationError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise QualificationValidationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualificationValidationError(f"{label} must be non-empty text")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise QualificationValidationError(f"{label} fields must be exactly: {', '.join(sorted(expected))}")
