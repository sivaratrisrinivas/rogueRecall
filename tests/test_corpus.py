from __future__ import annotations

from copy import deepcopy

import pytest

from roguerecall.corpus import (
    BenchmarkCorpusValidationError,
    load_benchmark_corpus,
    validate_benchmark_corpus,
)


def test_installed_benchmark_corpus_is_the_fixed_versioned_50_case_set() -> None:
    corpus = load_benchmark_corpus()

    assert corpus["schema_version"] == "1.0.0"
    assert corpus["version"] == "1.0.0"
    assert len(corpus["cases"]) == 50
    assert len(corpus["fingerprint"]) == 64

    identities = [
        (case["identity"]["case_id"], case["identity"]["revision"])
        for case in corpus["cases"]
    ]
    assert len(identities) == len(set(identities))
    assert {case["classification"]["domain"] for case in corpus["cases"]} == {
        "book",
        "code",
        "lyrics",
    }


def test_corpus_fingerprint_is_deterministic_and_covers_canonical_case_content() -> None:
    first = load_benchmark_corpus()
    second = load_benchmark_corpus()
    changed = deepcopy(first)
    changed.pop("fingerprint")
    changed["cases"][0]["source_work"]["work_title"] += " changed"

    assert first["fingerprint"] == second["fingerprint"]
    with pytest.raises(BenchmarkCorpusValidationError, match="fingerprint"):
        validate_benchmark_corpus(changed, expected_fingerprint=first["fingerprint"])


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda corpus: corpus["cases"].pop(), "exactly 50"),
        (
            lambda corpus: corpus["cases"].__setitem__(1, corpus["cases"][0]),
            "unique stable identity",
        ),
        (
            lambda corpus: corpus["cases"][0]["identity"].pop("case_id"),
            "missing field",
        ),
        (
            lambda corpus: corpus["cases"][0]["classification"].__setitem__(
                "domain", "film"
            ),
            "unknown value",
        ),
    ],
)
def test_corpus_validation_rejects_invalid_fixed_membership(
    mutation: object, message: str
) -> None:
    corpus = load_benchmark_corpus()
    corpus.pop("fingerprint")
    mutation(corpus)  # type: ignore[operator]

    with pytest.raises(BenchmarkCorpusValidationError, match=message):
        validate_benchmark_corpus(corpus)
