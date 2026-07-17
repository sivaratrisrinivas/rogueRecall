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

    raw_identities = []
    for case in raw_cases:
        if isinstance(case, Mapping):
            identity = case.get("identity")
            if isinstance(identity, Mapping):
                raw_identities.append(
                    (identity.get("case_id"), identity.get("revision"))
                )
    if len(raw_identities) == 50 and len(raw_identities) != len(set(raw_identities)):
        raise BenchmarkCorpusValidationError(
            "Benchmark Corpus cases require unique stable identity"
        )

    try:
        for case in raw_cases:
            if not isinstance(case, Mapping):
                raise BenchmarkCorpusValidationError(
                    "Benchmark Corpus cases must be objects"
                )
            validate_evaluation_case(case)
    except EvaluationCaseValidationError as error:
        raise BenchmarkCorpusValidationError(str(error)) from error

    canonical = {
        "cases": raw_cases,
        "schema_version": corpus["schema_version"],
        "version": corpus["version"],
    }
    fingerprint = sha256_bytes(canonical_json(canonical))
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise BenchmarkCorpusValidationError(
            "Benchmark Corpus fingerprint does not match canonical content"
        )
    return {**canonical, "cases": copy.deepcopy(raw_cases), "fingerprint": fingerprint}
