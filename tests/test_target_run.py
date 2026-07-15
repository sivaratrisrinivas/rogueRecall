from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

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
    assert observation["attempts"][0]["request"]["url"].endswith(
        "/v1/chat/completions"
    )
    assert b"secret" not in (record_path / "run.json").read_bytes()
    assert all(
        b"secret" not in path.read_bytes()
        for path in record_path.rglob("*")
        if path.is_file()
    )
