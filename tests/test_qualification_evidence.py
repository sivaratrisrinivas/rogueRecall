from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from roguerecall.grading import grade_observation


def test_frozen_grader_validation_set_has_reproducible_per_case_results() -> None:
    root = Path("docs/qualification/grading-1.0.1")
    artifact_path = root / "grader-validation-set.json"
    artifact = json.loads(artifact_path.read_text())
    summary = json.loads((root / "grader-validation.json").read_text())
    examples = artifact["examples"]

    assert summary["set_version"] == artifact["set_version"]
    assert summary["grader_version"] == artifact["grader_version"]
    assert summary["rule_versions"] == artifact["rule_versions"]
    assert summary["per_example_artifact"]["sha256"] == hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()
    assert artifact["set_version"] == "1.0.1"
    assert artifact["grader_version"] == "1.0.1"
    assert artifact["rule_versions"]["code"] == "code-contiguous-lexemes-1.0.1"
    assert len(examples) == 909
    assert len({example["example_id"] for example in examples}) == 909
    for domain in ("book", "lyrics", "code"):
        selected = [example for example in examples if example["domain"] == domain]
        labels = Counter(example["expected_text_leak"] for example in selected)
        assert labels == {False: 299, True: 4}
    assert all(example["actual_text_leak"] == example["expected_text_leak"] for example in examples)
    assert all(example["evaluation_status"] == "completed" for example in examples)
    code_errors = {
        example["example_id"]: example
        for example in examples
        if example["example_id"]
        in {"code-negative-000", "code-negative-001", "code-negative-002"}
    }
    assert set(code_errors) == {
        "code-negative-000",
        "code-negative-001",
        "code-negative-002",
    }
    assert all(example["actual_text_leak"] is False for example in code_errors.values())

    candidate = json.loads(
        Path("docs/corpus/candidate-v1/candidate.json").read_text()
    )
    cases = {
        case["identity"]["case_id"]: case for case in candidate["cases"]
    }
    barrier = code_errors["code-negative-002"]
    case = deepcopy(cases[barrier["case_id"]])
    case["grading"]["rule_version"] = "code-contiguous-lexemes-1.0.1"
    response = barrier["response"]
    assert grade_observation(case, response)["text_leak"] is False
    assert grade_observation(case, response.replace("`", ""))["text_leak"] is True
