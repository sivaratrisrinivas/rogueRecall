from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def test_frozen_grader_validation_set_has_reproducible_per_case_results() -> None:
    artifact = json.loads(Path("docs/qualification/v1/grader-validation-set.json").read_text())
    examples = artifact["examples"]

    assert len(examples) == 909
    assert len({example["example_id"] for example in examples}) == 909
    for domain in ("book", "lyrics", "code"):
        selected = [example for example in examples if example["domain"] == domain]
        labels = Counter(example["expected_text_leak"] for example in selected)
        assert labels == {False: 299, True: 4}
    assert all(example["actual_text_leak"] == example["expected_text_leak"] for example in examples)
    assert all(example["evaluation_status"] == "completed" for example in examples)
