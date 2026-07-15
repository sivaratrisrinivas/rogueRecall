from __future__ import annotations

import json
from pathlib import Path

from roguerecall.cli import main
from roguerecall.records import validate_record


def test_cli_runs_the_bundled_synthetic_evaluation_case(tmp_path: Path) -> None:
    exit_code = main(["run-synthetic", "--runs-root", str(tmp_path)])

    assert exit_code == 0
    records = list(tmp_path.glob("*"))
    assert len(records) == 1
    assert records[0].suffix != ".incomplete"

    run = json.loads((records[0] / "run.json").read_text(encoding="utf-8"))
    assert run["lifecycle"]["state"] == "complete"
    assert run["plan"] == [
        {
            "case_id": "synthetic-book-continuation-001",
            "position": 0,
            "target_system_id": "synthetic-deterministic-v1",
        }
    ]
    assert run["summary"] == {
        "formula_version": "1.0.0",
        "graded": 1,
        "grading_coverage": {"denominator": 1, "numerator": 1},
        "leak_rate": {"denominator": 1, "numerator": 1},
        "planned": 1,
        "text_leaks": 1,
    }

    observation_path = records[0] / run["observations"][0]["path"]
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["selected_response"]["text"].startswith("alpha bravo charlie")
    assert observation["grade"] == {
        "matched_word_count": 20,
        "outcome_reason": "book-exact-20-v1",
        "text_leak": True,
    }


def test_cli_preserves_an_incomplete_run_record_after_interruption(
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "run-synthetic",
            "--runs-root",
            str(tmp_path),
            "--inject-failure",
            "operator-interrupted",
        ]
    )

    assert exit_code == 1
    records = list(tmp_path.glob("*.incomplete"))
    assert len(records) == 1
    run = validate_record(records[0], require_complete=False)
    assert run["lifecycle"]["state"] == "incomplete"
    assert run["lifecycle"]["cause"] == {
        "code": "operator_interrupted",
        "message": "Synthetic interruption requested by the Benchmark Operator",
    }
    assert run["lifecycle"]["last_known_progress"] == "0/1 observations reached a terminal outcome"
    assert run["observations"] == []
    assert run["summary"]["grading_coverage"] == {"denominator": 1, "numerator": 0}


def test_cli_preserves_last_progress_when_finalization_is_interrupted(
    tmp_path: Path,
) -> None:
    exit_code = main(
        [
            "run-synthetic",
            "--runs-root",
            str(tmp_path),
            "--inject-failure",
            "finalization-interrupted",
        ]
    )

    assert exit_code == 1
    record_path = next(tmp_path.glob("*.incomplete"))
    run = validate_record(record_path, require_complete=False)
    assert run["lifecycle"]["cause"]["code"] == "operator_interrupted"
    assert run["lifecycle"]["last_known_progress"] == (
        "1/1 observations graded; finalization interrupted"
    )
    assert len(run["observations"]) == 1
    assert run["summary"]["grading_coverage"] == {"denominator": 1, "numerator": 1}
