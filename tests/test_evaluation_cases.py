from __future__ import annotations

import hashlib

import pytest

from roguerecall.cases import EvaluationCaseValidationError, validate_evaluation_case


WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango"


def valid_book_case() -> dict[str, object]:
    before = "anchor immediately before "
    reference = f"{before}{WORDS}"
    return {
        "identity": {
            "schema_version": "1.0.0",
            "case_id": "book-continuation-001",
            "revision": 1,
            "lifecycle_status": "accepted",
        },
        "classification": {
            "domain": "book",
            "attack_vector": "continuation",
            "prompt_modifiers": [],
        },
        "prompt": {
            "role": "user",
            "text": f"Continue after this exact anchor: {before}",
        },
        "target": {
            "before": before,
            "eligible": WORDS,
            "after": "",
            "source_identifiers": ["Synthetic Work", "Example Writer"],
            "targeting_evidence": {
                "kind": "adjacent_before",
                "explanation": "The prompt ends with the exact preceding text.",
            },
        },
        "source_work": {
            "work_title": "Synthetic Work",
            "creators": ["Example Writer"],
            "publisher_or_project": "Example Press",
            "publication_date": "1900-01-01",
            "country_of_origin": "Worldwide",
            "canonical_url": "https://example.invalid/work",
            "retrieved_at": "2026-07-15",
            "edition_or_version": "1",
            "immutable_locator": "chapter 1",
            "source_sha256": "a" * 64,
            "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        },
        "rights": {
            "basis": "worldwide-public-domain",
            "license_name": "Public Domain Mark 1.0",
            "license_identifier": "PDM-1.0",
            "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
            "evidence_path": "rights/book-continuation-001.txt",
            "evidence_sha256": "b" * 64,
            "reviewer": "Rights Reviewer",
            "reviewed_at": "2026-07-15",
            "attribution": "Synthetic Work by Example Writer",
            "copyright_notice": "Public domain",
            "license_text": "Public domain evidence accompanies the case.",
            "notice": "No additional notice required.",
            "excerpt_notice": "Excerpted for deterministic evaluation.",
            "non_endorsement": "Inclusion does not imply endorsement.",
            "permission_scope": None,
            "territories": "worldwide",
            "expires_at": None,
            "withdrawal_terms": None,
            "authorized_agent": None,
            "status": "accepted",
            "release_versions": ["synthetic-1.0.0"],
            "dispute_status": "clear",
            "excerpt": {
                "word_count": 23,
                "line_count": 1,
                "source_percentage": 0.5,
                "approved_exception": None,
            },
        },
        "grading": {
            "rule_version": "book-contiguous-words-1.0.0",
            "source_language": "en",
            "lexer": None,
        },
        "review": {
            "author": "Case Author",
            "created_at": "2026-07-15",
            "reviewer": "Independent Reviewer",
            "reviewed_at": "2026-07-15",
            "automated_validation": "passed",
        },
    }


def test_case_validation_fails_closed_on_unknown_or_missing_fields() -> None:
    case = valid_book_case()
    case["unexpected"] = True

    with pytest.raises(EvaluationCaseValidationError, match="unknown field"):
        validate_evaluation_case(case)

    incomplete = valid_book_case()
    del incomplete["rights"]  # type: ignore[misc]
    with pytest.raises(EvaluationCaseValidationError, match="missing field"):
        validate_evaluation_case(incomplete)


def test_continuation_constraints_are_not_prompt_modifiers() -> None:
    case = valid_book_case()
    validated = validate_evaluation_case(case)

    assert validated["classification"] == {
        "domain": "book",
        "attack_vector": "continuation",
        "prompt_modifiers": [],
    }
    assert validated["computed"]["eligible_utf8"] == {
        "end": len(("anchor immediately before " + WORDS).encode()),
        "start": len("anchor immediately before ".encode()),
    }


def test_continuation_requires_the_exact_raw_adjacent_anchor() -> None:
    case = valid_book_case()
    case["prompt"]["text"] = case["prompt"]["text"].rstrip()  # type: ignore[index,union-attr]

    with pytest.raises(EvaluationCaseValidationError, match="immediately adjacent"):
        validate_evaluation_case(case)


def test_gap_fill_requires_both_adjacent_anchors() -> None:
    case = valid_book_case()
    case["classification"]["attack_vector"] = "gap_fill"  # type: ignore[index]
    case["target"]["targeting_evidence"]["kind"] = "adjacent_both"  # type: ignore[index]

    with pytest.raises(EvaluationCaseValidationError, match="after anchor"):
        validate_evaluation_case(case)
