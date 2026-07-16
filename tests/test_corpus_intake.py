from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from roguerecall import ReleaseValidationError, validate_corpus_candidate
from roguerecall.cli import main
from roguerecall.records import canonical_json

from test_releases import _cases, _composition, _release_case


def _era(case: dict[str, Any]) -> str | None:
    if case["classification"]["domain"] == "code":
        return None
    year = int(case["source_work"]["publication_date"][:4])
    return "pre_1950" if year < 1950 else "1950_1999" if year < 2000 else "2000_onward"


def _pool_entry(case: dict[str, Any], category: str) -> dict[str, Any]:
    modifiers = case["classification"]["prompt_modifiers"]
    criteria = {
        "domain": case["classification"]["domain"],
        "attack_vector": case["classification"]["attack_vector"],
        "era": _era(case),
        "category": category,
        "source_language": case["grading"]["source_language"],
        "prompt_modifier": modifiers[0] if modifiers else None,
    }
    slot_definition = {**criteria, "quota": 1}
    return {
        "case": deepcopy(case),
        "category": category,
        "category_evidence": {
            "explanation": "The cited source assigns this primary category or genre.",
            "reference": f"category-evidence-{case['identity']['case_id']}",
        },
        "creator_role_evidence": (
            {}
            if case["classification"]["domain"] == "code"
            else {
                creator: {
                    "is_primary": index == 0,
                    "reference": f"creator-role-{case['identity']['case_id']}-{index}",
                }
                for index, creator in enumerate(case["source_work"]["creators"])
            }
        ),
        "selection_slot": {
            **slot_definition,
            "slot_id": (
                f"slot-{hashlib.sha256(canonical_json(criteria)).hexdigest()}"
            ),
        },
    }


def candidate_record() -> dict[str, Any]:
    cases = sorted(_cases(), key=lambda case: case["identity"]["case_id"])
    composition = _composition(cases)
    candidate_pool = [
        _pool_entry(case, composition[case["identity"]["case_id"]])
        for case in cases
    ]
    alternative = _release_case(
        "book", "constrained_reconstruction", 50, 13, "1.0.0", None
    )
    alternative["classification"]["prompt_modifiers"] = deepcopy(
        candidate_pool[0]["case"]["classification"]["prompt_modifiers"]
    )
    candidate_pool.append(
        _pool_entry(alternative, candidate_pool[0]["category"])
    )
    pool_cases = [entry["case"] for entry in candidate_pool]
    attestations = {
        case["identity"]["case_id"]: {
            "contributor": case["review"]["author"],
            "dco_signed_off": True,
            "reference": f"attestation-{index:02d}",
            "rights_attestation": True,
        }
        for index, case in enumerate(pool_cases)
    }
    independent_reviews = {
        case["identity"]["case_id"]: {
            "checklist_passed": True,
            "reference": f"independent-review-{index:02d}",
            "reviewer": case["review"]["reviewer"],
        }
        for index, case in enumerate(pool_cases)
    }
    return {
        "schema_version": "1.0.0",
        "release_version": "1.0.0",
        "cases": cases,
        "composition": composition,
        "selection": {
            "algorithm": "sha256-seed-case-id-v1",
            "seed": "rogue-recall-v1-candidate-seed",
            "frozen_at": "2026-07-16T12:00:00Z",
            "target_system_feedback_used": False,
            "candidate_pool": candidate_pool,
            "exclusions": [],
        },
        "attestations": attestations,
        "independent_reviews": independent_reviews,
        "approvals": [
            {
                "identity": "Release Curator",
                "role": "release_curator",
                "reference": "curator-approval-1",
            },
            {
                "identity": "Rights Reviewer",
                "role": "rights_reviewer",
                "reference": "rights-approval-1",
            },
        ],
        "curator_confirmation": {
            "composition": True,
            "concentration": True,
            "contamination": True,
            "gradeability": True,
            "lifecycle": True,
            "warnings_reviewed": True,
            "warnings": [],
        },
    }


def test_candidate_validation_records_a_deterministic_pre_execution_freeze() -> None:
    candidate = candidate_record()

    validated = validate_corpus_candidate(candidate)

    assert validated["selection"]["seed"] == "rogue-recall-v1-candidate-seed"
    assert validated["selection"]["target_system_feedback_used"] is False
    assert [case["identity"]["case_id"] for case in validated["cases"]] == sorted(
        candidate["composition"]
    )


def test_code_cross_prompt_check_does_not_lex_natural_language_prompts() -> None:
    candidate = candidate_record()
    book = next(
        case for case in candidate["cases"]
        if case["classification"]["domain"] == "book"
    )
    case_id = book["identity"]["case_id"]
    prefix = "Natural-language punctuation: isn’t C code — @@@. "
    book["prompt"]["text"] = prefix + book["prompt"]["text"]
    book.pop("computed", None)
    pool_case = next(
        entry["case"] for entry in candidate["selection"]["candidate_pool"]
        if entry["case"]["identity"]["case_id"] == case_id
    )
    pool_case["prompt"]["text"] = prefix + pool_case["prompt"]["text"]
    pool_case.pop("computed", None)

    validate_corpus_candidate(candidate)


def test_candidate_validation_rejects_target_feedback_and_unattested_cases() -> None:
    candidate = candidate_record()
    candidate["selection"]["target_system_feedback_used"] = True

    with pytest.raises(ReleaseValidationError, match="Target System feedback"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    candidate["attestations"].pop(next(iter(candidate["attestations"])))

    with pytest.raises(ReleaseValidationError, match="attestations"):
        validate_corpus_candidate(candidate)


def test_candidate_validation_reproduces_seeded_slot_selection() -> None:
    candidate = candidate_record()
    candidate["selection"]["seed"] = "1"

    with pytest.raises(ReleaseValidationError, match="deterministic selection"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    selected_case_id = candidate["cases"][0]["identity"]["case_id"]
    candidate["selection"]["exclusions"].append(
        {
            "case_id": selected_case_id,
            "evidence_reference": "exploratory-run-1",
            "reasons": ["exploratory_target_testing"],
        }
    )

    with pytest.raises(ReleaseValidationError, match="eligible and excluded"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    candidate["selection"]["candidate_pool"][-1]["selection_slot"]["slot_id"] = (
        "slot-caller-chosen"
    )

    with pytest.raises(ReleaseValidationError, match="Selection Slot criteria"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    candidate["selection"]["candidate_pool"][-1]["selection_slot"]["quota"] = 2

    with pytest.raises(ReleaseValidationError, match="Selection Slot criteria conflict"):
        validate_corpus_candidate(candidate)


def test_candidate_validation_requires_review_and_category_evidence() -> None:
    candidate = candidate_record()
    case_id = candidate["cases"][0]["identity"]["case_id"]
    candidate["independent_reviews"].pop(case_id)

    with pytest.raises(ReleaseValidationError, match="independent reviews"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    candidate["selection"]["candidate_pool"][0]["category_evidence"]["reference"] = ""

    with pytest.raises(ReleaseValidationError, match="category evidence"):
        validate_corpus_candidate(candidate)


def test_selected_cases_and_categories_are_bound_to_the_eligible_pool() -> None:
    candidate = candidate_record()
    candidate["selection"]["candidate_pool"][0]["case"]["source_work"][
        "work_title"
    ] = "Different Work Title"

    with pytest.raises(ReleaseValidationError, match="differs from its eligible pool"):
        validate_corpus_candidate(candidate)

    candidate = candidate_record()
    original_slot_id = candidate["selection"]["candidate_pool"][0]["selection_slot"][
        "slot_id"
    ]
    for entry in candidate["selection"]["candidate_pool"]:
        if entry["selection_slot"]["slot_id"] == original_slot_id:
            entry["category"] = "fiction:different-source-category"
            entry["selection_slot"]["category"] = "fiction:different-source-category"
            criteria = {
                key: value
                for key, value in entry["selection_slot"].items()
                if key not in {"quota", "slot_id"}
            }
            entry["selection_slot"]["slot_id"] = (
                f"slot-{hashlib.sha256(canonical_json(criteria)).hexdigest()}"
            )

    with pytest.raises(ReleaseValidationError, match="category differs from its Selection Slot"):
        validate_corpus_candidate(candidate)


def test_candidate_validation_uses_named_primary_creators_for_concentration() -> None:
    candidate = candidate_record()
    book_ids = [
        case["identity"]["case_id"]
        for case in candidate["cases"]
        if case["classification"]["domain"] == "book"
    ][:3]
    for case in candidate["cases"]:
        if case["identity"]["case_id"] in book_ids:
            case["source_work"]["creators"].append("Shared Editor")
            case.pop("computed", None)
    for entry in candidate["selection"]["candidate_pool"]:
        case = entry["case"]
        if case["identity"]["case_id"] in book_ids:
            case["source_work"]["creators"].append("Shared Editor")
            case.pop("computed", None)
            entry["creator_role_evidence"]["Shared Editor"] = {
                "is_primary": False,
                "reference": "shared-editor-role-evidence",
            }

    validate_corpus_candidate(candidate)

    candidate = candidate_record()
    candidate["selection"]["candidate_pool"][0]["creator_role_evidence"].popitem()

    with pytest.raises(ReleaseValidationError, match="classify every Source Work credit"):
        validate_corpus_candidate(candidate)


def test_candidate_validation_rejects_unresolved_or_rejected_warnings() -> None:
    candidate = candidate_record()
    candidate["curator_confirmation"]["warnings"] = [
        {
            "code": "category-source-unclear",
            "disposition": "rejected_candidate",
            "rationale": "The candidate must be removed before validation.",
        }
    ]

    with pytest.raises(ReleaseValidationError, match="resolved before validation"):
        validate_corpus_candidate(candidate)


def test_candidate_validation_cli_reports_valid_and_invalid_records(
    tmp_path: Any, capsys: Any
) -> None:
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate_record()), encoding="utf-8")

    assert main(["validate-corpus-candidate", str(path)]) == 0
    assert capsys.readouterr().out == f"valid: {path}\n"

    candidate = candidate_record()
    candidate["curator_confirmation"]["warnings_reviewed"] = False
    path.write_text(json.dumps(candidate), encoding="utf-8")

    assert main(["validate-corpus-candidate", str(path)]) == 1
    assert "invalid: release curator must affirm every corpus gate" in capsys.readouterr().out

    path.write_text("not json", encoding="utf-8")

    assert main(["validate-corpus-candidate", str(path)]) == 1
    assert capsys.readouterr().out.startswith("invalid: cannot read candidate JSON:")
