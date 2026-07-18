from __future__ import annotations

import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from roguerecall.benchmark import format_benchmark_summary, run_benchmark
from roguerecall.cli import main

from test_targets import RunTransport, local_manifest, response


def test_benchmark_writes_one_complete_auditable_results_document(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"

    destination, results = run_benchmark(
        local_manifest(),
        results_path=results_path,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    assert destination == results_path
    assert json.loads(results_path.read_text()) == results
    assert results["status"] == "complete"
    assert results["roguerecall_version"] == "0.1.0"
    assert results["dataset"] == {"case_count": 50, "fingerprint": results["dataset"]["fingerprint"], "version": "1.0.0"}
    assert results["settings"] == {"max_output_tokens": 256, "temperature": 0}
    assert results["controls"]["status"] == "passed"
    assert len(results["controls"]["cases"]) == 50
    assert len(results["target_systems"]) == 1
    target = results["target_systems"][0]
    assert target["target_system_id"] == "local-llama-3-1"
    assert target["grading_coverage"] == {"numerator": 50, "denominator": 50}
    assert target["text_leaks"] == {"numerator": 0, "denominator": 50}
    observation = target["observations"][0]
    assert observation["raw_response"] == "OK"
    assert observation["grade"]["text_leak"] is False
    assert observation["grade"]["decisive_matches"] == []
    assert observation["timestamps"]["started_at"]
    assert observation["timestamps"]["finished_at"]


def test_benchmark_never_overwrites_or_contacts_a_target_for_existing_output(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "results.json"
    results_path.write_text("original\n")
    transports_created = 0

    def transport_factory(_target: object) -> RunTransport:
        nonlocal transports_created
        transports_created += 1
        return RunTransport()

    with pytest.raises(FileExistsError, match="already exists"):
        run_benchmark(
            local_manifest(),
            results_path=results_path,
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            transport_factory=transport_factory,
        )

    assert results_path.read_text() == "original\n"
    assert transports_created == 0


def test_interruption_preserves_completed_observations_in_running_json(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"

    class InterruptingTransport(RunTransport):
        def __init__(self) -> None:
            self.completions = 0

        def send(self, request: object) -> object:
            url = request.url  # type: ignore[attr-defined]
            if url.endswith("/v1/chat/completions"):
                self.completions += 1
                if self.completions == 3:
                    raise KeyboardInterrupt
            return super().send(request)  # type: ignore[arg-type]

    with pytest.raises(KeyboardInterrupt):
        run_benchmark(
            local_manifest(),
            results_path=results_path,
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            transport_factory=lambda _target: InterruptingTransport(),
        )

    persisted = json.loads(results_path.read_text())
    assert persisted["status"] == "running"
    assert persisted["finished_at"] is None
    observations = persisted["target_systems"][0]["observations"]
    assert len(observations) == 1
    assert observations[0]["raw_response"] == "OK"


def test_each_observation_checkpoint_is_valid_json(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"

    class InspectingTransport(RunTransport):
        def __init__(self) -> None:
            self.completions = 0

        def send(self, request: object) -> object:
            if request.url.endswith("/v1/chat/completions"):  # type: ignore[attr-defined]
                self.completions += 1
                if self.completions > 2:
                    checkpoint = json.loads(results_path.read_text())
                    assert checkpoint["status"] == "running"
                    assert len(checkpoint["target_systems"][0]["observations"]) == self.completions - 2
            return super().send(request)  # type: ignore[arg-type]

    _, results = run_benchmark(
        local_manifest(),
        results_path=results_path,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: InspectingTransport(),
    )

    assert results["status"] == "complete"


def test_controls_failure_is_persisted_without_provider_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def broken_grade(case: object, response: object) -> dict[str, object]:
        del case
        return {"evaluation_status": "completed", "text_leak": False}

    def transport_factory(_target: object) -> RunTransport:
        nonlocal calls
        calls += 1
        return RunTransport()

    monkeypatch.setattr("roguerecall.benchmark.grade_observation", broken_grade)
    results_path, results = run_benchmark(
        local_manifest(),
        results_path=tmp_path / "results.json",
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=transport_factory,
    )

    assert json.loads(results_path.read_text()) == results
    assert results["status"] == "controls_failed"
    assert results["target_systems"] == []
    assert calls == 0


def test_cli_has_only_manifest_and_results_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert "runs_root" not in inspect.signature(run_benchmark).parameters
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(local_manifest()))

    exit_code = main(["benchmark", "--manifest", str(manifest_path), "--results", str(tmp_path / "results.json")])

    assert exit_code == 2
    assert "invalid benchmark input" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(["benchmark", "--help"])
    assert error.value.code == 0


def test_summary_is_denominator_explicit_and_non_ranked(tmp_path: Path) -> None:
    _, results = run_benchmark(
        local_manifest(),
        results_path=tmp_path / "results.json",
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    rendered = format_benchmark_summary(results)
    assert "Coverage" in rendered
    assert "Text Leaks" in rendered
    assert "50/50" in rendered
    assert "winner" not in rendered.casefold()
    assert "rank" not in rendered.casefold()


def test_benchmark_compares_targets_in_manifest_order_with_identical_inputs(
    tmp_path: Path,
) -> None:
    manifest = local_manifest()
    second_target = deepcopy(manifest["target_systems"][0])  # type: ignore[index]
    second_target["target_system_id"] = "local-mistral-7b"
    second_target["requested_model"] = "mistral-7b-instruct"
    manifest["target_systems"].append(second_target)  # type: ignore[index]

    class RecordingTransport(RunTransport):
        def __init__(self, model_id: str, case_events: list[str]) -> None:
            self.model_id = model_id
            self.case_events = case_events
            self.case_prompts: list[str] = []
            self.case_messages: list[object] = []

        def send(self, request: object) -> object:
            url = request.url  # type: ignore[attr-defined]
            if url.endswith("/v1/models"):
                return response(200, {"data": [{"id": self.model_id}]})
            body = json.loads(request.body)  # type: ignore[attr-defined]
            assert body["model"] == self.model_id
            assert body["temperature"] == 0
            assert body["max_tokens"] == 256
            prompt = body["messages"][0]["content"]
            if prompt != "Reply with exactly: OK":
                self.case_prompts.append(prompt)
                self.case_messages.append(body["messages"])
                self.case_events.append(self.model_id)
            return super().send(request)  # type: ignore[arg-type]

    transports: list[RecordingTransport] = []
    case_events: list[str] = []

    def transport_factory(target: object) -> RecordingTransport:
        transport = RecordingTransport(target["requested_model"], case_events)  # type: ignore[index]
        transports.append(transport)
        return transport

    _, results = run_benchmark(
        manifest,
        results_path=tmp_path / "results.json",
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=transport_factory,
    )

    assert [target["target_system_id"] for target in results["target_systems"]] == [
        "local-llama-3-1",
        "local-mistral-7b",
    ]
    assert all(
        target["grading_coverage"] == {"numerator": 50, "denominator": 50}
        and target["text_leaks"] == {"numerator": 0, "denominator": 50}
        and target["target_errors"] == 0
        and target["grader_errors"] == 0
        for target in results["target_systems"]
    )
    assert len(transports) == 2
    assert len(transports[0].case_prompts) == 50
    assert transports[0].case_prompts == transports[1].case_prompts
    assert transports[0].case_messages == transports[1].case_messages
    assert case_events == ["llama-3.1-8b-instruct"] * 50 + ["mistral-7b-instruct"] * 50

    rendered = format_benchmark_summary(results)
    assert all(
        heading in rendered
        for heading in ("Target System", "State", "Coverage", "Text Leaks", "Target Errors", "Grader Errors")
    )
    assert rendered.index("local-llama-3-1") < rendered.index("local-mistral-7b")
    serialized = (tmp_path / "results.json").read_text().casefold()
    assert all(
        f'"{field}"' not in serialized
        for field in ("winner", "ranking", "score", "composite_score")
    )
