from __future__ import annotations

import copy
import base64
import json
import threading
import time
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roguerecall.targets import (
    EngineExecutionError,
    HttpRequest,
    HttpResponse,
    TargetManifestError,
    TransportError,
    UrllibTransport,
    execute_target_system,
    validate_target_manifest,
)


def local_manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "target_systems": [
            {
                "target_system_id": "local-llama-3-1",
                "adapter_id": "openai-compatible-chat-v1",
                "adapter_version": "1.0.0",
                "requested_model": "llama-3.1-8b-instruct",
                "base_url": "http://127.0.0.1:8080",
                "credential": {
                    "kind": "bearer",
                    "environment_variable": "LOCAL_MODEL_TOKEN",
                },
            }
        ],
    }


def test_manifest_is_canonical_and_never_contains_credential_values() -> None:
    secret = "this-is-not-evidence"

    validated = validate_target_manifest(
        local_manifest(), environ={"LOCAL_MODEL_TOKEN": secret}
    )

    assert validated["target_systems"][0]["credential"] == {
        "environment_variable": "LOCAL_MODEL_TOKEN",
        "kind": "bearer",
    }
    assert secret not in repr(validated)
    assert validated["target_systems"][0]["warnings"] == []
    assert len(validated["fingerprint"]) == 64


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com:8080",
        "http://user:password@127.0.0.1:8080",
        "https://user@example.com",
        "ftp://127.0.0.1/model",
        "http://127.0.0.1:8080/path",
        "http://127.0.0.1:8080?query=yes",
    ],
)
def test_local_manifest_rejects_unsafe_or_noncanonical_urls(base_url: str) -> None:
    manifest = local_manifest()
    manifest["target_systems"][0]["base_url"] = base_url  # type: ignore[index]

    with pytest.raises(TargetManifestError):
        validate_target_manifest(manifest, environ={"LOCAL_MODEL_TOKEN": "secret"})


def test_official_adapters_reject_endpoint_overrides() -> None:
    manifest = local_manifest()
    target = manifest["target_systems"][0]  # type: ignore[index]
    target["adapter_id"] = "openai-responses-v1"  # type: ignore[index]
    target["base_url"] = "https://proxy.example.com"  # type: ignore[index]

    with pytest.raises(TargetManifestError, match="base_url"):
        validate_target_manifest(manifest, environ={"LOCAL_MODEL_TOKEN": "secret"})


def test_official_capabilities_come_from_the_adapter_catalog() -> None:
    manifest = local_manifest()
    target = manifest["target_systems"][0]  # type: ignore[index]
    target["adapter_id"] = "openai-responses-v1"  # type: ignore[index]
    target["requested_model"] = "gpt-5-2026-01-01"  # type: ignore[index]
    target["base_url"] = None  # type: ignore[index]
    target["capabilities"] = {"temperature": True}  # type: ignore[index]

    with pytest.raises(TargetManifestError, match="versioned catalog"):
        validate_target_manifest(manifest, environ={"LOCAL_MODEL_TOKEN": "secret"})

    del target["capabilities"]  # type: ignore[index]
    validated = validate_target_manifest(
        manifest, environ={"LOCAL_MODEL_TOKEN": "secret"}
    )["target_systems"][0]
    assert validated["capabilities"] == {"temperature": False}
    assert "temperature_unsupported" in validated["warnings"]


def test_manifest_fails_closed_on_unknown_fields_and_missing_credentials() -> None:
    unknown = local_manifest()
    unknown["target_systems"][0]["surprise"] = True  # type: ignore[index]
    with pytest.raises(TargetManifestError, match="fixed target contract"):
        validate_target_manifest(unknown, environ={"LOCAL_MODEL_TOKEN": "secret"})

    missing = copy.deepcopy(local_manifest())
    with pytest.raises(TargetManifestError, match="LOCAL_MODEL_TOKEN"):
        validate_target_manifest(missing, environ={})


def test_manifest_applies_fixed_local_contract_defaults() -> None:
    validated = validate_target_manifest(
        local_manifest(), environ={"LOCAL_MODEL_TOKEN": "secret"}
    )["target_systems"][0]

    assert validated["generation"] == {"max_output_tokens": 256, "temperature": 0}
    assert validated["execution"] == {
        "attempt_timeout_seconds": 90,
        "concurrency": 1,
        "connect_timeout_seconds": 10,
        "max_attempts": 2,
    }
    assert validated["capabilities"] == {"temperature": True}
    assert validated["ca_bundle"] is None
    assert validated["local_artifact"] is None


def test_local_contract_rejects_optional_fields_and_extra_settings() -> None:
    manifest = local_manifest()
    target = manifest["target_systems"][0]  # type: ignore[index]
    target["generation"] = {"max_output_tokens": 128, "temperature": 0}  # type: ignore[index]
    with pytest.raises(TargetManifestError, match="fixed target contract"):
        validate_target_manifest(manifest, environ={"LOCAL_MODEL_TOKEN": "secret"})


class ScriptedTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def response(status: int, body: object, **headers: str) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers={"content-type": "application/json", **headers},
        body=json.dumps(body).encode(),
    )


def validated_local_target() -> dict[str, Any]:
    manifest = validate_target_manifest(
        local_manifest(), environ={"LOCAL_MODEL_TOKEN": "secret"}
    )
    return manifest["target_systems"][0]


def local_success(text: str, *, finish_reason: str = "stop") -> HttpResponse:
    return response(
        200,
        {
            "id": "chatcmpl-1",
            "model": "llama-3.1-8b-instruct",
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": text},
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
        **{"x-request-id": "server-request-1"},
    )


class RunTransport:
    def send(self, request: HttpRequest) -> HttpResponse:
        if request.url.endswith("/v1/models"):
            return response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]})
        prompt = json.loads(request.body)["messages"][0]["content"]
        if prompt == "Reply with exactly: OK":
            return local_success("OK")
        return local_success("OK")


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


def official_target(adapter_id: str) -> dict[str, Any]:
    target = local_manifest()["target_systems"][0]  # type: ignore[index]
    target["target_system_id"] = adapter_id.replace("-v1", "")  # type: ignore[index]
    target["adapter_id"] = adapter_id  # type: ignore[index]
    target["requested_model"] = "provider-model-2026-01-01"  # type: ignore[index]
    target["base_url"] = None  # type: ignore[index]
    target["generation"] = {"max_output_tokens": 128, "temperature": 0}  # type: ignore[index]
    return validate_target_manifest(
        {"schema_version": "1.0.0", "target_systems": [target]},
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )["target_systems"][0]


@pytest.mark.parametrize(
    ("adapter_id", "endpoint", "provider_body", "token_field"),
    [
        (
            "openai-responses-v1",
            "https://api.openai.com/v1/responses",
            {
                "id": "resp-1",
                "model": "provider-model-2026-01-01",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "answer"}],
                    }
                ],
                "usage": {},
            },
            "max_output_tokens",
        ),
        (
            "anthropic-messages-v1",
            "https://api.anthropic.com/v1/messages",
            {
                "id": "msg-1",
                "model": "provider-model-2026-01-01",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "usage": {},
            },
            "max_tokens",
        ),
    ],
)
def test_official_adapters_preflight_the_model_and_keep_fixed_contracts(
    adapter_id: str, endpoint: str, provider_body: dict[str, Any], token_field: str
) -> None:
    transport = ScriptedTransport(
        [response(200, {"id": "provider-model-2026-01-01"}), response(200, provider_body), response(200, provider_body)]
    )

    report = execute_target_system(
        official_target(adapter_id),
        [{"case_id": "case-1", "prompt": "exact prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert transport.requests[0].url.endswith("/v1/models/provider-model-2026-01-01")
    assert transport.requests[1].url == endpoint
    body = json.loads(transport.requests[2].body)
    assert body[token_field] == 128
    assert body["messages" if adapter_id.startswith("anthropic") else "input"] == [
        {"content": "exact prompt", "role": "user"}
    ]
    assert report["observations"][0]["selected_response"]["text"] == "answer"


def test_local_adapter_preflights_and_uses_only_the_fixed_request_contract() -> None:
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            local_success("observed text"),
        ]
    )

    report = execute_target_system(
        validated_local_target(),
        [{"case_id": "case-1", "prompt": "published prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert [request.url for request in transport.requests] == [
        "http://127.0.0.1:8080/v1/models",
        "http://127.0.0.1:8080/v1/chat/completions",
        "http://127.0.0.1:8080/v1/chat/completions",
    ]
    corpus_body = json.loads(transport.requests[2].body)
    assert corpus_body == {
        "max_tokens": 256,
        "messages": [{"content": "published prompt", "role": "user"}],
        "model": "llama-3.1-8b-instruct",
        "n": 1,
        "stream": False,
        "temperature": 0,
    }
    assert report["preflight"]["status"] == "passed"
    assert report["observations"][0]["selected_response"]["text"] == "observed text"
    attempt = report["observations"][0]["attempts"][0]
    assert "authorization" not in attempt["request"]["headers"]
    assert "secret" not in repr(report)
    assert attempt["response"]["provider_request_id"] == "server-request-1"
    assert json.loads(attempt["request"]["body_utf8"]) == corpus_body
    assert json.loads(base64.b64decode(attempt["response"]["body_base64"]))[
        "choices"
    ][0]["message"]["content"] == "observed text"


def test_provider_echoed_credentials_are_redacted_from_all_evidence() -> None:
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            local_success("accidental secret echo"),
        ]
    )

    report = execute_target_system(
        validated_local_target(),
        [{"case_id": "case-1", "prompt": "prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert "secret" not in repr(report)
    assert report["observations"][0]["selected_response"]["text"] == (
        "accidental [REDACTED] echo"
    )


@pytest.mark.parametrize(
    ("provider_response", "condition", "expected_text"),
    [
        (local_success("ordinary answer"), None, "ordinary answer"),
        (
            response(
                200,
                {
                    "id": "chatcmpl-refusal",
                    "model": "llama-3.1-8b-instruct",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "refusal": "I cannot"},
                        }
                    ],
                    "usage": {},
                },
            ),
            "response_refusal",
            "I cannot",
        ),
        (local_success("partial", finish_reason="length"), "response_truncated", "partial"),
    ],
)
def test_protocol_valid_text_is_selected_with_response_conditions(
    provider_response: HttpResponse, condition: str | None, expected_text: str
) -> None:
    transport = ScriptedTransport(
        [response(404, {"error": "not found"}), local_success("OK"), provider_response]
    )

    report = execute_target_system(
        validated_local_target(),
        [{"case_id": "case-1", "prompt": "prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert "model_listing_unavailable" in report["warnings"]
    observation = report["observations"][0]
    assert observation["terminal_status"] == "completed"
    assert observation["response_condition"] == condition
    assert observation["selected_response"]["text"] == expected_text


def test_malformed_success_is_a_protocol_error_and_never_a_safe_outcome() -> None:
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            response(200, {"choices": []}),
        ]
    )

    report = execute_target_system(
        validated_local_target(),
        [{"case_id": "case-1", "prompt": "prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    observation = report["observations"][0]
    assert observation["terminal_status"] == "target_error"
    assert observation["error"]["code"] == "target_protocol_error"
    assert "selected_response" not in observation


def test_retry_policy_records_retry_after_and_exhausted_transient_failures() -> None:
    waits: list[float] = []
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            response(429, {"error": "busy"}, **{"retry-after": "2"}),
            response(503, {"error": "busy"}),
        ]
    )

    report = execute_target_system(
        validated_local_target(),
        [{"case_id": "case-1", "prompt": "prompt"}],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        sleep=waits.append,
        jitter=lambda upper: upper / 2,
    )

    observation = report["observations"][0]
    assert observation["terminal_status"] == "target_error"
    assert observation["error"]["code"] == "target_request_error"
    assert len(observation["attempts"]) == 2
    assert observation["attempts"][0]["retry"] == {
        "actual_wait_seconds": 2,
        "delay_seconds": 2,
        "source": "retry_after",
        "will_retry": True,
    }
    assert waits == [2]


def test_deterministic_target_error_stops_remaining_cases_in_corpus_order() -> None:
    target = validated_local_target()
    target["execution"]["concurrency"] = 1
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            response(401, {"error": "unauthorized"}),
        ]
    )

    report = execute_target_system(
        target,
        [
            {"case_id": "case-1", "prompt": "one"},
            {"case_id": "case-2", "prompt": "two"},
        ],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert [item["case_id"] for item in report["observations"]] == ["case-1", "case-2"]
    assert report["observations"][0]["terminal_status"] == "target_error"
    assert report["observations"][1]["terminal_status"] == "not_tested"


def test_persistence_failure_stops_execution_as_an_engine_error() -> None:
    transport = ScriptedTransport(
        [
            response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]}),
            local_success("OK"),
            local_success("answer"),
        ]
    )

    def fail_to_persist(_attempt: dict[str, Any]) -> None:
        raise OSError("disk contains sensitive path /secret")

    with pytest.raises(EngineExecutionError, match="attempt evidence"):
        execute_target_system(
            validated_local_target(),
            [{"case_id": "case-1", "prompt": "prompt"}],
            transport,
            environ={"LOCAL_MODEL_TOKEN": "secret"},
            persist_attempt=fail_to_persist,
        )


def test_builtin_transport_rejects_redirects() -> None:
    visited: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            visited.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/credential-destination")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("test sandbox does not permit loopback sockets")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        request = HttpRequest(
            method="GET",
            url=f"http://127.0.0.1:{server.server_port}/redirect",
            headers={},
            body=b"",
            connect_timeout_seconds=1,
            attempt_timeout_seconds=2,
        )
        with pytest.raises(TransportError, match="redirect"):
            UrllibTransport().send(request)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert visited == ["/redirect"]


def test_case_attempts_are_bounded_by_target_concurrency_and_return_in_corpus_order() -> None:
    class TrackingTransport:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()

        def send(self, request: HttpRequest) -> HttpResponse:
            if request.url.endswith("/v1/models"):
                return response(200, {"data": [{"id": "llama-3.1-8b-instruct"}]})
            prompt = json.loads(request.body)["messages"][0]["content"]
            if prompt == "Reply with exactly: OK":
                return local_success("OK")
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return local_success(prompt)

    transport = TrackingTransport()
    report = execute_target_system(
        validated_local_target(),
        [{"case_id": f"case-{number}", "prompt": str(number)} for number in range(4)],
        transport,
        environ={"LOCAL_MODEL_TOKEN": "secret"},
    )

    assert transport.maximum_active == 1
    assert [item["case_id"] for item in report["observations"]] == [
        "case-0",
        "case-1",
        "case-2",
        "case-3",
    ]
