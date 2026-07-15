from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

import roguerecall.engine as engine_module
from roguerecall.engine import run_targets
from roguerecall.records import validate_record
from roguerecall.targets import HttpRequest, HttpResponse

from test_targets import local_manifest, local_success, response


class RunTransport:
    def send(self, request: HttpRequest) -> HttpResponse:
        if request.url.endswith("/v1/models"):
            return response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]})
        prompt = json.loads(request.body)["messages"][0]["content"]
        if prompt == "Reply with exactly: OK":
            return local_success("OK")
        case = json.loads(
            files("roguerecall").joinpath("data/synthetic_case.json").read_text()
        )
        return local_success(case["target"]["eligible"])


class TruncatingRunTransport(RunTransport):
    def send(self, request: HttpRequest) -> HttpResponse:
        result = super().send(request)
        if request.url.endswith("/v1/chat/completions"):
            prompt = json.loads(request.body)["messages"][0]["content"]
            if prompt != "Reply with exactly: OK":
                body = json.loads(result.body)
                body["choices"][0]["finish_reason"] = "length"
                return response(200, body)
        return result


def test_target_execution_is_graded_and_persisted_as_a_valid_run_record(
    tmp_path: Path,
) -> None:
    case = json.loads(
        files("roguerecall").joinpath("data/synthetic_case.json").read_text()
    )

    record_path = run_targets(
        tmp_path,
        local_manifest(),
        [case],
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    run = validate_record(record_path)
    observation = json.loads(
        (record_path / run["observations"][0]["path"]).read_text()
    )
    assert observation["terminal_status"] == "graded"
    assert observation["grade"]["text_leak"] is True
    assert len(observation["attempts"]) == 1
    assert len(list(record_path.glob("attempts/**/*.json"))) == 1
    assert observation["attempts"][0]["request"]["url"].endswith(
        "/v1/chat/completions"
    )
    assert b"secret" not in (record_path / "run.json").read_bytes()
    assert all(
        b"secret" not in path.read_bytes()
        for path in record_path.rglob("*")
        if path.is_file()
    )


def test_response_condition_is_preserved_in_the_run_record(tmp_path: Path) -> None:
    case = json.loads(
        files("roguerecall").joinpath("data/synthetic_case.json").read_text()
    )
    record_path = run_targets(
        tmp_path,
        local_manifest(),
        [case],
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: TruncatingRunTransport(),
    )

    run = validate_record(record_path)
    observation = json.loads(
        (record_path / run["observations"][0]["path"]).read_text()
    )
    assert observation["response_condition"] == "response_truncated"
    assert observation["attempts"][0]["response_condition"] == "response_truncated"


def test_attempt_persistence_failure_stops_the_production_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = json.loads(
        files("roguerecall").joinpath("data/synthetic_case.json").read_text()
    )
    real_write_json = engine_module.write_json

    def fail_attempt(path: Path, value: object) -> None:
        if "attempts" in path.parts:
            raise OSError("private disk path")
        real_write_json(path, value)

    monkeypatch.setattr(engine_module, "write_json", fail_attempt)
    with pytest.raises(engine_module.EngineExecutionError, match="attempt evidence"):
        run_targets(
            tmp_path,
            local_manifest(),
            [case],
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            transport_factory=lambda _target: RunTransport(),
        )
