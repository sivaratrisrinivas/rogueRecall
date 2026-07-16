from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from roguerecall.grading import grade_observation


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "docs/corpus/candidate-v1/candidate.json"
OUTPUT = ROOT / "docs/qualification/v1/grader-validation-set.json"


def main() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = candidate["cases"]
    examples: list[dict[str, Any]] = []
    for domain in ("book", "lyrics", "code"):
        domain_cases = [case for case in cases if case["classification"]["domain"] == domain]
        vectors: dict[str, dict[str, Any]] = {}
        for case in domain_cases:
            vectors.setdefault(case["classification"]["attack_vector"], case)
        for vector in sorted(vectors):
            case = vectors[vector]
            response = case["target"]["eligible"]
            examples.append(_example(domain, case, f"{domain}-positive-{vector}", True, response))
        for index in range(299):
            case = domain_cases[index % len(domain_cases)]
            response = f"Independent negative fixture {domain} {index:03d}; no reference expression supplied."
            examples.append(_example(domain, case, f"{domain}-negative-{index:03d}", False, response))
    payload = {
        "schema_version": "1.0.0",
        "set_version": "1.0.0",
        "candidate_sha256": hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
        "labeling": "Deterministic locked conformance labels; negatives are not an operational random sample.",
        "examples": examples,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _example(domain: str, case: dict[str, Any], example_id: str, expected: bool, response: str) -> dict[str, Any]:
    grade = grade_observation(case, response)
    return {
        "example_id": example_id,
        "domain": domain,
        "case_id": case["identity"]["case_id"],
        "expected_text_leak": expected,
        "response": response,
        "actual_text_leak": grade["text_leak"],
        "evaluation_status": grade["evaluation_status"],
        "outcome_reason": grade["outcome_reason"],
    }


if __name__ == "__main__":
    main()
