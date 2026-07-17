from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .records import canonical_json, sha256_bytes


CORPUS_SCHEMA_VERSION = "1.0.0"
CORPUS_VERSION = "1.0.0"
CORPUS_RESOURCE = "data/benchmark_corpus.json"


class BenchmarkCorpusValidationError(ValueError):
    """Raised when the installed fixed Benchmark Corpus is invalid."""


def load_benchmark_corpus() -> dict[str, Any]:
    """Load and verify the Benchmark Corpus bundled with this installation."""

    resource = files("roguerecall").joinpath(CORPUS_RESOURCE)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
        raise BenchmarkCorpusValidationError(
            "installed Benchmark Corpus data is absent or unreadable"
        ) from error
    if not isinstance(value, Mapping):
        raise BenchmarkCorpusValidationError("Benchmark Corpus must be an object")
    expected_fingerprint = value.get("fingerprint")
    if not isinstance(expected_fingerprint, str):
        raise BenchmarkCorpusValidationError("Benchmark Corpus fingerprint is missing")
    authored = dict(value)
    authored.pop("fingerprint")
    return validate_benchmark_corpus(
        authored, expected_fingerprint=expected_fingerprint
    )


def validate_benchmark_corpus(
    corpus: Mapping[str, Any], *, expected_fingerprint: str | None = None
) -> dict[str, Any]:
    """Validate fixed membership and return canonical corpus identity and cases."""

    if not isinstance(corpus, Mapping) or set(corpus) != {
        "cases",
        "schema_version",
        "version",
    }:
        raise BenchmarkCorpusValidationError("Benchmark Corpus fields are invalid")
    if corpus.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise BenchmarkCorpusValidationError("unsupported Benchmark Corpus schema version")
    if corpus.get("version") != CORPUS_VERSION:
        raise BenchmarkCorpusValidationError("unsupported Benchmark Corpus version")
    raw_cases = corpus.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 50:
        raise BenchmarkCorpusValidationError(
            "Benchmark Corpus requires exactly 50 Evaluation Cases"
        )

    case_ids = []
    for case in raw_cases:
        if isinstance(case, Mapping):
            identity = case.get("identity")
            if isinstance(identity, Mapping):
                case_ids.append(identity.get("case_id"))
    if len(case_ids) == 50 and len(case_ids) != len(set(case_ids)):
        raise BenchmarkCorpusValidationError(
            "Benchmark Corpus cases require unique stable identity"
        )

    validated_cases = []
    try:
        for case in raw_cases:
            if not isinstance(case, Mapping):
                raise BenchmarkCorpusValidationError(
                    "Benchmark Corpus cases must be objects"
                )
            validated_cases.append(validate_evaluation_case(case))
    except EvaluationCaseValidationError as error:
        raise BenchmarkCorpusValidationError(str(error)) from error

    canonical = {
        "cases": raw_cases,
        "schema_version": corpus["schema_version"],
        "version": corpus["version"],
    }
    fingerprint_content = {
        "cases": validated_cases,
        "schema_version": CORPUS_SCHEMA_VERSION,
    }
    fingerprint = sha256_bytes(canonical_json(fingerprint_content))
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise BenchmarkCorpusValidationError(
            "Benchmark Corpus fingerprint does not match canonical content"
        )
    literary_eras = {
        case["identity"]["case_id"]: _publication_era(
            case["source_work"]["publication_date"]
        )
        for case in validated_cases
        if case["classification"]["domain"] in {"book", "lyrics"}
    }
    era_distribution = {
        era: sum(value == era for value in literary_eras.values())
        for era in ("pre-1950", "1950-1999", "2000-onward")
    }
    return {
        **canonical,
        "cases": copy.deepcopy(raw_cases),
        "era_distribution": era_distribution,
        "fingerprint": fingerprint,
        "literary_eras": literary_eras,
    }


def _publication_era(publication_date: str) -> str:
    year = int(publication_date[:4])
    if year < 1950:
        return "pre-1950"
    if year < 2000:
        return "1950-1999"
    return "2000-onward"
