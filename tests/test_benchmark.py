from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from roguerecall.benchmark import format_benchmark_summary, run_benchmark
from roguerecall.cli import main

from test_targets import ScriptedTransport, local_manifest, local_success, response
from test_targets import RunTransport


def test_mvp_benchmark_interface_does_not_accept_an_arbitrary_case_set() -> None:
    assert "case_set" not in inspect.signature(run_benchmark).parameters

    with pytest.raises(SystemExit) as error:
        main(["benchmark", "--help"])
    assert error.value.code == 0

    with pytest.raises(SystemExit) as error:
        main(["--version"])
    assert error.value.code == 0


def test_benchmark_batch_writes_one_completed_run_and_summary(tmp_path: Path) -> None:
    results_path, summary = run_benchmark(
        tmp_path,
        local_manifest(),
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    assert results_path.parent.parent == tmp_path / "benchmarks"
    assert json.loads(results_path.read_text()) == summary
    assert summary["schema_version"] == "1.0.0"
    assert summary["case_set"]["case_count"] == 50
    assert summary["case_set"]["version"] == "1.0.0"
    assert sum(summary["case_set"]["era_distribution"].values()) == 34
    assert len(summary["targets"]) == 1
    target = summary["targets"][0]
    assert target["target_system_id"] == "local-llama-3-1"
    assert target["run_record"]["state"] == "complete"
    assert target["planned"] == 50
    assert target["grading_coverage"] == {"numerator": 50, "denominator": 50}
    assert target["text_leaks"] == {"numerator": 0, "denominator": 50}
    assert target["target_errors"] == 0
    assert target["grader_errors"] == 0
    assert target["not_tested"] == 0
    assert summary["complete"] is True
    assert target["run_record"]["path_base"] == "runs_root"
    record_path = tmp_path / target["run_record"]["path"]
    assert record_path.is_dir()
    run = json.loads((record_path / "run.json").read_text())
    assert run["case_set"]["fingerprint"] == summary["case_set"]["fingerprint"]


def test_benchmark_batch_preserves_manifest_order_in_separate_run_records(
    tmp_path: Path,
) -> None:
    manifest = local_manifest()
    second = deepcopy(manifest["target_systems"][0])  # type: ignore[index]
    second["target_system_id"] = "local-llama-second"
    manifest["target_systems"].append(second)  # type: ignore[union-attr]

    _, summary = run_benchmark(
        tmp_path,
        manifest,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    assert [item["target_system_id"] for item in summary["targets"]] == [
        "local-llama-3-1",
        "local-llama-second",
    ]
    paths = [
        tmp_path / item["run_record"]["path"] for item in summary["targets"]
    ]
    assert len(set(paths)) == 2
    for path in paths:
        run = json.loads((path / "run.json").read_text())
        assert len({item["target_system_id"] for item in run["plan"]}) == 1


def test_benchmark_batch_continues_after_an_incomplete_target(tmp_path: Path) -> None:
    manifest = local_manifest()
    first = manifest["target_systems"][0]  # type: ignore[index]
    first["execution"]["concurrency"] = 1
    second = deepcopy(first)
    second["target_system_id"] = "local-llama-second"
    manifest["target_systems"].append(second)  # type: ignore[union-attr]

    def transport_factory(target: dict[str, object]) -> object:
        if target["target_system_id"] == "local-llama-3-1":
            return ScriptedTransport(
                [
                    response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
                    local_success("OK"),
                    response(401, {"error": "unauthorized"}),
                ]
            )
        return RunTransport()

    _, summary = run_benchmark(
        tmp_path,
        manifest,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=transport_factory,  # type: ignore[arg-type]
    )

    assert [item["run_record"]["state"] for item in summary["targets"]] == [
        "incomplete",
        "complete",
    ]
    assert summary["targets"][0]["target_errors"] == 1
    assert summary["targets"][0]["not_tested"] == 49
    assert summary["targets"][1]["grading_coverage"] == {
        "numerator": 50,
        "denominator": 50,
    }
    assert summary["complete"] is False


def test_benchmark_summary_is_non_ranked_and_denominator_explicit(
    tmp_path: Path,
) -> None:
    manifest = local_manifest()
    second = deepcopy(manifest["target_systems"][0])  # type: ignore[index]
    second["target_system_id"] = "local-llama-second"
    manifest["target_systems"].append(second)  # type: ignore[union-attr]
    _, summary = run_benchmark(
        tmp_path,
        manifest,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    rendered = format_benchmark_summary(summary)

    assert rendered.index("local-llama-3-1") < rendered.index("local-llama-second")
    assert "Coverage" in rendered
    assert "Text Leaks" in rendered
    assert rendered.count("50/50") == 2
    assert all("0/50" in line for line in rendered.splitlines()[1:])
    assert "winner" not in rendered.casefold()
    assert "rank" not in rendered.casefold()


def test_benchmark_never_overwrites_an_existing_summary(tmp_path: Path) -> None:
    results_path = tmp_path / "existing" / "results.json"
    results_path.parent.mkdir()
    results_path.write_text("original\n")

    with pytest.raises(FileExistsError, match="already exists"):
        run_benchmark(
            tmp_path / "runs",
            local_manifest(),
            results_path=results_path,
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            transport_factory=lambda _target: RunTransport(),
        )

    assert results_path.read_text() == "original\n"
    assert not (tmp_path / "runs").exists()


def test_benchmark_reserves_results_before_target_execution(tmp_path: Path) -> None:
    unusable_parent = tmp_path / "not-a-directory"
    unusable_parent.write_text("occupied\n")
    transports_created = 0

    def transport_factory(_target: dict[str, object]) -> RunTransport:
        nonlocal transports_created
        transports_created += 1
        return RunTransport()

    with pytest.raises(OSError):
        run_benchmark(
            tmp_path / "runs",
            local_manifest(),
            results_path=unusable_parent / "results.json",
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            transport_factory=transport_factory,  # type: ignore[arg-type]
        )

    assert transports_created == 0
    assert not (tmp_path / "runs").exists()


def test_benchmark_cli_rejects_an_arbitrary_case_set_option(
    tmp_path: Path, capsys: object
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(local_manifest()))

    with pytest.raises(SystemExit) as error:
        main(
            [
                "benchmark",
                "--runs-root",
                str(tmp_path / "runs"),
                "--manifest",
                str(manifest_path),
                "--case-set",
                str(tmp_path / "candidate.json"),
            ]
        )

    assert error.value.code == 2
    assert "unrecognized arguments: --case-set" in capsys.readouterr().err  # type: ignore[attr-defined]
    assert not (tmp_path / "runs").exists()
