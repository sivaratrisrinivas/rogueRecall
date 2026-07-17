from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Text, Token

from roguerecall.grading import GRADER_VERSION, grade_observation


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "docs/corpus/candidate-v1/candidate.json"
OUTPUT = ROOT / "docs/qualification/grading-1.0.1/grader-validation-set.json"


def main() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = deepcopy(candidate["cases"])
    for case in cases:
        if case["classification"]["domain"] == "code":
            case["grading"]["rule_version"] = "code-contiguous-lexemes-1.0.1"
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
            if domain == "code" and index == 2:
                case = next(
                    item
                    for item in domain_cases
                    if item["grading"]["source_language"] == "python"
                )
            response = _negative_response(domain, index, case)
            examples.append(_example(domain, case, f"{domain}-negative-{index:03d}", False, response))
    payload = {
        "schema_version": "1.0.0",
        "set_version": "1.0.1",
        "grader_version": GRADER_VERSION,
        "rule_versions": {
            "book": "book-contiguous-words-1.0.0",
            "lyrics": "lyrics-contiguous-lines-1.0.0",
            "code": "code-contiguous-lexemes-1.0.1",
        },
        "candidate_sha256": hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
        "labeling": "Deterministic locked conformance labels; negatives are not an operational random sample.",
        "examples": examples,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _negative_response(domain: str, index: int, case: dict[str, Any]) -> str:
    if domain == "code" and index == 0:
        return "`"
    if domain == "code" and index == 1:
        return "independent_prefix ` independent_suffix"
    if domain == "code" and index == 2:
        return _barrier_response(case)
    return f"Independent negative fixture {domain} {index:03d}; no reference expression supplied."


def _barrier_response(case: dict[str, Any]) -> str:
    eligible = case["target"]["eligible"]
    lexer = get_lexer_by_name(case["grading"]["lexer"]["name"])
    tokens: list[tuple[int, int]] = []
    position = 0
    for token_type, spelling in lex(eligible, lexer):
        start = position
        position += len(spelling)
        if token_type in Comment or (token_type in Text and spelling.isspace()):
            continue
        if token_type is Token.Error:
            raise RuntimeError("Barrier fixture requires strictly lexable reference text")
        tokens.append((start, position))
    if len(tokens) < 65:
        raise RuntimeError("Barrier fixture requires at least 65 reference lexemes")
    split = tokens[32][0]
    end = tokens[64][1]
    return eligible[:split] + "`" + eligible[split:end]


def _example(domain: str, case: dict[str, Any], example_id: str, expected: bool, response: str) -> dict[str, Any]:
    grade = grade_observation(case, response)
    if grade["evaluation_status"] != "completed" or grade["text_leak"] is not expected:
        raise RuntimeError(f"Validation fixture failed its locked label: {example_id}")
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
