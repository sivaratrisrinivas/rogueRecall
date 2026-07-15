from __future__ import annotations

import copy
import base64
import ipaddress
import json
import http.client
import os
import random
import re
import socket
import ssl
import time
import uuid
import platform
import threading
from collections.abc import Mapping
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from .records import canonical_json, sha256_bytes


TARGET_MANIFEST_VERSION = "1.0.0"
ADAPTER_VERSION = "1.0.0"
ADAPTER_IDS = {
    "anthropic-messages-v1",
    "openai-compatible-chat-v1",
    "openai-responses-v1",
}
OFFICIAL_ADAPTERS = {"anthropic-messages-v1", "openai-responses-v1"}

_TARGET_FIELDS = {
    "adapter_id",
    "adapter_version",
    "base_url",
    "ca_bundle",
    "capabilities",
    "credential",
    "execution",
    "generation",
    "local_artifact",
    "requested_model",
    "target_system_id",
}
_REQUIRED_TARGET_FIELDS = {
    "adapter_id",
    "adapter_version",
    "credential",
    "requested_model",
    "target_system_id",
}
_CREDENTIAL_FIELDS = {"environment_variable", "kind"}
_GENERATION_FIELDS = {"max_output_tokens", "temperature"}
_EXECUTION_FIELDS = {
    "attempt_timeout_seconds",
    "concurrency",
    "connect_timeout_seconds",
    "max_attempts",
}
_LOCAL_ARTIFACT_FIELDS = {
    "context_size",
    "launch_configuration_digest",
    "model_artifact_name",
    "model_digest",
    "quantization",
    "software_name",
    "software_version",
}
_TARGET_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class TargetManifestError(ValueError):
    """Raised when a Target System manifest is unsafe or ambiguous."""


class EngineExecutionError(RuntimeError):
    """Raised when the engine cannot preserve authoritative attempt evidence."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    connect_timeout_seconds: float
    attempt_timeout_seconds: float
    ca_bundle: str | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class TransportError(Exception):
    """A bounded transport failure safe to classify without persisting repr()."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:500]
        self.retryable = retryable


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


class UrllibTransport:
    """Standard-library transport with explicit deadlines and no redirects/retries."""

    def __init__(self, ca_bundle: str | None = None) -> None:
        self._ca_bundle = ca_bundle

    def send(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        deadline = started + request.attempt_timeout_seconds
        parsed = urlsplit(request.url)
        if parsed.hostname is None:
            raise TransportError("invalid_url", "HTTP URL has no host", retryable=False)
        connect_timeout = min(
            request.connect_timeout_seconds, request.attempt_timeout_seconds
        )
        if parsed.scheme == "https":
            context = ssl.create_default_context(cafile=self._ca_bundle)
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=connect_timeout, context=context
            )
        else:
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=connect_timeout
            )
        phase = "connect"
        try:
            connection.connect()
            phase = "attempt"
            _set_socket_deadline(connection, deadline)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            connection.request(
                request.method,
                path,
                body=request.body if request.body else None,
                headers=request.headers,
            )
            _set_socket_deadline(connection, deadline)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise TransportError(
                    "redirect_rejected", "provider redirect was rejected", retryable=False
                )
            chunks: list[bytes] = []
            while True:
                _set_socket_deadline(connection, deadline)
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=b"".join(chunks),
            )
        except (TimeoutError, socket.timeout):
            code = "connect_timeout" if phase == "connect" else "attempt_timeout"
            raise TransportError(code, "HTTP attempt timed out") from None
        except TransportError:
            raise
        except (http.client.HTTPException, ssl.SSLError, ConnectionError, OSError):
            raise TransportError("connection_failure", "HTTP transport failed") from None
        finally:
            connection.close()


def _set_socket_deadline(
    connection: http.client.HTTPConnection, deadline: float
) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    if connection.sock is None:
        raise TransportError("connection_failure", "HTTP socket is unavailable")
    connection.sock.settimeout(remaining)


def validate_target_manifest(
    manifest: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Validate and return a canonical, secret-redacted Target System manifest."""

    if not isinstance(manifest, Mapping):
        raise TargetManifestError("Target System manifest must be an object")
    _exact_fields(manifest, {"schema_version", "target_systems"}, "manifest")
    if manifest["schema_version"] != TARGET_MANIFEST_VERSION:
        raise TargetManifestError("unsupported Target System manifest version")
    raw_targets = manifest["target_systems"]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise TargetManifestError("target_systems must be a non-empty array")

    environment = os.environ if environ is None else environ
    targets = [_validate_target(item, environment) for item in raw_targets]
    target_ids = [target["target_system_id"] for target in targets]
    if len(target_ids) != len(set(target_ids)):
        raise TargetManifestError("target_system_id must be unique within the run")

    redacted: dict[str, Any] = {
        "schema_version": TARGET_MANIFEST_VERSION,
        "target_systems": targets,
    }
    redacted["fingerprint"] = sha256_bytes(canonical_json(redacted))
    return redacted


def execute_target_system(
    target: Mapping[str, Any],
    cases: Sequence[Mapping[str, str]],
    transport: Transport,
    *,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float], float] | None = None,
    persist_attempt: Callable[[dict[str, Any]], None] | None = None,
    stop_all: threading.Event | None = None,
) -> dict[str, Any]:
    """Preflight and execute corpus cases for one validated Target System.

    The returned observations are always in corpus order. ``transport`` is a
    deliberately small injection seam whose ``send(HttpRequest)`` method must
    disable redirects and automatic retries.
    """

    environment = os.environ if environ is None else environ
    random_delay = (lambda upper: random.uniform(0, upper)) if jitter is None else jitter
    target_copy = copy.deepcopy(dict(target))
    warnings = list(target_copy.get("warnings", []))
    preflight = _preflight(target_copy, transport, environment, warnings)
    if preflight["status"] != "passed":
        cause = preflight["error"]
        return {
            "observations": [
                _not_tested(case, position, cause)
                for position, case in enumerate(cases)
            ],
            "preflight": preflight,
            "target_system_id": target_copy["target_system_id"],
            "warnings": warnings,
        }

    observations: list[dict[str, Any]] = []
    shared_cause: dict[str, str] | None = None
    position = 0
    concurrency = target_copy["execution"]["concurrency"]
    while position < len(cases):
        if stop_all is not None and stop_all.is_set():
            raise EngineExecutionError("Evaluation Run stopped after persistence failure")
        if shared_cause is not None:
            observations.extend(
                _not_tested(cases[index], index, shared_cause)
                for index in range(position, len(cases))
            )
            break
        batch = list(enumerate(cases[position : position + concurrency], position))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for case_position, case in batch:
                queued_monotonic = time.monotonic_ns()
                futures.append(
                    pool.submit(
                    _execute_case,
                    target_copy,
                    case,
                    case_position,
                    transport,
                    environment,
                    list(warnings),
                    sleep,
                    random_delay,
                    persist_attempt,
                    queued_monotonic,
                    stop_all,
                )
                )
            batch_observations = [future.result() for future in futures]
        for observation in batch_observations:
            for warning in observation.get("warnings", []):
                _append_warning(warnings, warning)
            if shared_cause is None and observation.get("stop_target") is True:
                shared_cause = observation["error"]
            observation.pop("stop_target", None)
            observations.append(observation)
        position += len(batch)
    return {
        "observations": observations,
        "preflight": preflight,
        "target_system_id": target_copy["target_system_id"],
        "warnings": warnings,
    }


def execute_target_systems(
    manifest: Mapping[str, Any],
    cases: Sequence[Mapping[str, str]],
    transport_factory: Callable[[Mapping[str, Any]], Transport],
    *,
    environ: Mapping[str, str] | None = None,
    persist_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Execute all manifest targets independently and retain manifest order."""

    targets = manifest.get("target_systems")
    if not isinstance(targets, list) or not targets:
        raise TargetManifestError("validated manifest contains no Target Systems")
    stop_all = threading.Event()

    def persist_or_stop(attempt: dict[str, Any]) -> None:
        if stop_all.is_set():
            raise EngineExecutionError("Evaluation Run persistence is unavailable")
        if persist_attempt is None:
            return
        try:
            persist_attempt(attempt)
        except Exception:
            stop_all.set()
            raise

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [
            pool.submit(
                execute_target_system,
                target,
                cases,
                transport_factory(target),
                environ=environ,
                persist_attempt=persist_or_stop,
                stop_all=stop_all,
            )
            for target in targets
        ]
        return [future.result() for future in futures]


def _preflight(
    target: dict[str, Any],
    transport: Transport,
    environment: Mapping[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    started_at = _utc_now()
    evidence: list[dict[str, Any]] = []
    if target["adapter_id"] in ADAPTER_IDS:
        request = _request(target, "models", None, environment, str(uuid.uuid4()))
        response = _send_preflight(transport, request)
        evidence.append(
            _preflight_evidence(
                request, response, _credential_values(target, environment)
            )
        )
        if target["adapter_id"] == "openai-compatible-chat-v1" and response.status in {404, 405}:
            _append_warning(warnings, "model_listing_unavailable")
        elif not 200 <= response.status < 300:
            return _failed_preflight(started_at, evidence, "model listing failed")
        elif target["adapter_id"] == "openai-compatible-chat-v1":
            try:
                listing = json.loads(response.body)
                model_ids = [item.get("id") for item in listing["data"]]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return _failed_preflight(started_at, evidence, "invalid model listing")
            if target["requested_model"] not in model_ids:
                return _failed_preflight(started_at, evidence, "requested model is missing")
        else:
            try:
                model = json.loads(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _failed_preflight(started_at, evidence, "invalid model response")
            if not isinstance(model, dict) or model.get("id") != target["requested_model"]:
                return _failed_preflight(started_at, evidence, "requested model is missing")

    probe_request = _request(
        target,
        "completion",
        "Reply with exactly: OK",
        environment,
        str(uuid.uuid4()),
        max_output_tokens=8,
    )
    probe_response = _send_preflight(transport, probe_request)
    evidence.append(
        _preflight_evidence(
            probe_request,
            probe_response,
            _credential_values(target, environment),
        )
    )
    result = _classify_response(target, probe_response)
    if result["kind"] != "completed":
        return _failed_preflight(started_at, evidence, "response-shape probe failed")
    _response_warnings(target, result, warnings)
    return {
        "evidence": evidence,
        "finished_at": _utc_now(),
        "started_at": started_at,
        "status": "passed",
    }


def _execute_case(
    target: dict[str, Any],
    case: Mapping[str, str],
    position: int,
    transport: Transport,
    environment: Mapping[str, str],
    warnings: list[str],
    sleep: Callable[[float], None],
    jitter: Callable[[float], float],
    persist_attempt: Callable[[dict[str, Any]], None] | None,
    queued_monotonic: int,
    stop_all: threading.Event | None,
) -> dict[str, Any]:
    case_id, prompt = _case_identity(case)
    queue_milliseconds = (time.monotonic_ns() - queued_monotonic) / 1_000_000
    logical_request_id = str(uuid.uuid4())
    attempts: list[dict[str, Any]] = []
    started_at = _utc_now()
    max_attempts = target["execution"]["max_attempts"]
    for attempt_number in range(1, max_attempts + 1):
        if stop_all is not None and stop_all.is_set():
            raise EngineExecutionError("Evaluation Run stopped after persistence failure")
        attempt_id = str(uuid.uuid4())
        request = _request(target, "completion", prompt, environment, attempt_id)
        attempt_started = _utc_now()
        monotonic_started = time.monotonic_ns()
        transport_error: TransportError | None = None
        try:
            response = transport.send(request)
            result = _classify_response(target, response)
        except TransportError as error:
            transport_error = error
            response = None
            result = {
                "error": {"code": "target_request_error", "message": error.message},
                "kind": "retryable_error" if error.retryable else "protocol_error",
            }

        retryable = result["kind"] == "retryable_error"
        will_retry = retryable and attempt_number < max_attempts
        delay, source = _retry_delay(response, attempt_number, jitter) if will_retry else (0.0, None)
        credential_values = _credential_values(target, environment)
        result = _redact_secrets(result, credential_values)
        if result["kind"] == "completed":
            _response_warnings(target, result, warnings)
        attempt = _attempt_evidence(
            target,
            case_id,
            position,
            logical_request_id,
            attempt_id,
            attempt_number,
            request,
            response,
            result,
            attempt_started,
            monotonic_started,
            will_retry,
            delay,
            source,
            transport_error,
            credential_values,
            queue_milliseconds if attempt_number == 1 else 0.0,
            warnings,
        )
        attempt = _redact_secrets(attempt, credential_values)
        attempts.append(attempt)
        if result["kind"] == "completed":
            _persist(attempt, persist_attempt)
            return {
                "attempts": attempts,
                "case_id": case_id,
                "logical_request_id": logical_request_id,
                "planned_position": position,
                "response_condition": result.get("condition"),
                "selected_response": {
                    "adapter_version": ADAPTER_VERSION,
                    "attempt_id": attempt_id,
                    "text": result["text"],
                },
                "target_system_id": target["target_system_id"],
                "terminal_status": "completed",
                "timestamps": {"finished_at": _utc_now(), "started_at": started_at},
                "warnings": list(warnings),
            }
        if not will_retry:
            _persist(attempt, persist_attempt)
            terminal_error = result["error"]
            if retryable:
                terminal_error = {
                    "code": "target_request_error",
                    "message": "transient failure exhausted the configured attempts",
                }
            deterministic = response is not None and response.status in {400, 401, 403, 404}
            return {
                "attempts": attempts,
                "case_id": case_id,
                "error": terminal_error,
                "logical_request_id": logical_request_id,
                "planned_position": position,
                "stop_target": deterministic,
                "target_system_id": target["target_system_id"],
                "terminal_status": "target_error",
                "timestamps": {"finished_at": _utc_now(), "started_at": started_at},
                "warnings": list(warnings),
            }
        wait_started = time.monotonic_ns()
        sleep(delay)
        actual_wait = (time.monotonic_ns() - wait_started) / 1_000_000_000
        attempt["retry"]["actual_wait_seconds"] = delay if sleep is not time.sleep else actual_wait
        _persist(attempt, persist_attempt)
    raise AssertionError("attempt loop must return a terminal observation")


def _request(
    target: dict[str, Any],
    operation: str,
    prompt: str | None,
    environment: Mapping[str, str],
    attempt_id: str,
    *,
    max_output_tokens: int | None = None,
) -> HttpRequest:
    adapter_id = target["adapter_id"]
    token_cap = target["generation"]["max_output_tokens"] if max_output_tokens is None else max_output_tokens
    headers = {"accept": "application/json", "content-type": "application/json"}
    credential = target["credential"]
    if credential["kind"] == "bearer":
        secret = environment.get(credential["environment_variable"])
        if not secret:
            raise TargetManifestError("credential disappeared after manifest validation")
        if adapter_id == "anthropic-messages-v1":
            headers["x-api-key"] = secret
        else:
            headers["authorization"] = f"Bearer {secret}"
    if operation == "models":
        if adapter_id == "openai-compatible-chat-v1":
            url = f"{target['base_url']}/v1/models"
        elif adapter_id == "openai-responses-v1":
            url = f"https://api.openai.com/v1/models/{quote(target['requested_model'], safe='')}"
        else:
            url = f"https://api.anthropic.com/v1/models/{quote(target['requested_model'], safe='')}"
            headers["anthropic-version"] = "2023-06-01"
        method = "GET"
        body = b""
    elif adapter_id == "openai-compatible-chat-v1":
        url = f"{target['base_url']}/v1/chat/completions"
        method = "POST"
        body_value: dict[str, Any] = {
            "max_tokens": token_cap,
            "messages": [{"content": prompt, "role": "user"}],
            "model": target["requested_model"],
            "n": 1,
            "stream": False,
        }
        _add_temperature(target, body_value)
        body = canonical_json(body_value)
    elif adapter_id == "openai-responses-v1":
        url = "https://api.openai.com/v1/responses"
        method = "POST"
        headers["x-client-request-id"] = attempt_id
        body_value = {
            "input": [{"content": prompt, "role": "user"}],
            "max_output_tokens": token_cap,
            "model": target["requested_model"],
            "store": False,
            "stream": False,
            "tools": [],
        }
        _add_temperature(target, body_value)
        body = canonical_json(body_value)
    else:
        url = "https://api.anthropic.com/v1/messages"
        method = "POST"
        headers["anthropic-version"] = "2023-06-01"
        body_value = {
            "max_tokens": token_cap,
            "messages": [{"content": prompt, "role": "user"}],
            "model": target["requested_model"],
            "stream": False,
        }
        _add_temperature(target, body_value)
        body = canonical_json(body_value)
    return HttpRequest(
        method=method,
        url=url,
        headers=headers,
        body=body,
        connect_timeout_seconds=float(target["execution"]["connect_timeout_seconds"]),
        attempt_timeout_seconds=float(target["execution"]["attempt_timeout_seconds"]),
        ca_bundle=None,
    )


def _classify_response(target: dict[str, Any], response: HttpResponse) -> dict[str, Any]:
    if not 200 <= response.status < 300:
        retryable = response.status in {408, 429, 500, 502, 503, 504, 529}
        return {
            "error": {
                "code": "target_request_error" if retryable else "target_protocol_error",
                "message": f"provider returned HTTP {response.status}",
            },
            "kind": "retryable_error" if retryable else "protocol_error",
        }
    try:
        raw = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _protocol_error("successful response was not valid JSON")
    if not isinstance(raw, dict):
        return _protocol_error("successful response body was not an object")
    adapter_id = target["adapter_id"]
    condition: str | None
    try:
        if adapter_id == "openai-compatible-chat-v1":
            choices = raw["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                return _protocol_error("chat response must contain exactly one choice")
            choice = choices[0]
            message = choice["message"]
            content = message.get("content")
            refusal = message.get("refusal")
            if isinstance(refusal, str):
                text = refusal
                condition = "response_refusal"
            elif isinstance(content, str):
                text = content
                condition = "response_truncated" if choice.get("finish_reason") == "length" else None
            else:
                return _protocol_error("chat response contains no textual content")
            returned_model = raw.get("model")
            provider_id = raw.get("id")
            stop_reason = choice.get("finish_reason")
        elif adapter_id == "anthropic-messages-v1":
            blocks = raw["content"]
            if not isinstance(blocks, list):
                return _protocol_error("Anthropic content must be an array")
            anthropic_texts: list[str] = []
            for block in blocks:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    anthropic_texts.append(block["text"])
            if not anthropic_texts:
                return _protocol_error("Anthropic response contains no textual content")
            text = "".join(anthropic_texts)
            stop_reason = raw.get("stop_reason")
            condition = "response_truncated" if stop_reason == "max_tokens" else ("response_refusal" if stop_reason == "refusal" else None)
            returned_model = raw.get("model")
            provider_id = raw.get("id")
        else:
            output = raw["output"]
            if not isinstance(output, list):
                return _protocol_error("OpenAI output must be an array")
            openai_texts: list[str] = []
            refusal_found = False
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
                    continue
                for block in item.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "output_text" and isinstance(block.get("text"), str):
                        openai_texts.append(block["text"])
                    elif isinstance(block, dict) and block.get("type") == "refusal" and isinstance(block.get("refusal"), str):
                        openai_texts.append(block["refusal"])
                        refusal_found = True
            if not openai_texts:
                return _protocol_error("OpenAI response contains no textual content")
            text = "".join(openai_texts)
            condition = "response_refusal" if refusal_found else ("response_truncated" if raw.get("status") == "incomplete" else None)
            returned_model = raw.get("model")
            provider_id = raw.get("id")
            stop_reason = raw.get("incomplete_details")
    except (KeyError, TypeError):
        return _protocol_error("successful response has an invalid shape")
    return {
        "condition": condition,
        "kind": "completed",
        "provider_response_id": provider_id,
        "server_request_id": _allowed_response_headers(response.headers).get(
            "x-request-id"
        )
        or _allowed_response_headers(response.headers).get("request-id"),
        "raw": raw,
        "returned_model": returned_model,
        "stop_reason": stop_reason,
        "text": text,
        "usage": raw.get("usage"),
    }


def _attempt_evidence(
    target: dict[str, Any],
    case_id: str,
    position: int,
    logical_request_id: str,
    attempt_id: str,
    attempt_number: int,
    request: HttpRequest,
    response: HttpResponse | None,
    result: dict[str, Any],
    started_at: str,
    monotonic_started: int,
    will_retry: bool,
    delay: float,
    retry_source: str | None,
    transport_error: TransportError | None,
    secrets: Sequence[str],
    queue_milliseconds: float,
    warnings: Sequence[str],
) -> dict[str, Any]:
    response_headers = {} if response is None else _allowed_response_headers(response.headers)
    evidence: dict[str, Any] = {
        "adapter_id": target["adapter_id"],
        "adapter_version": target["adapter_version"],
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "case_id": case_id,
        "finished_at": _utc_now(),
        "logical_request_id": logical_request_id,
        "monotonic_elapsed_milliseconds": (time.monotonic_ns() - monotonic_started) / 1_000_000,
        "planned_position": position,
        "queue_elapsed_milliseconds": queue_milliseconds,
        "request": {
            "body": json.loads(request.body) if request.body else None,
            "body_sha256": sha256_bytes(request.body),
            "body_utf8": request.body.decode("utf-8"),
            "headers": _redacted_request_headers(request.headers),
            "method": request.method,
            "url": request.url,
        },
        "response": {
            "body_base64": None
            if response is None
            else base64.b64encode(_redacted_bytes(response.body, secrets)).decode("ascii"),
            "body_sha256": None if response is None else sha256_bytes(response.body),
            "headers": response_headers,
            "http_status": None if response is None else response.status,
            "parsed_json": result.get("raw"),
            "provider_request_id": response_headers.get("x-request-id") or response_headers.get("request-id"),
            "provider_response_id": result.get("provider_response_id"),
            "returned_model": result.get("returned_model"),
            "stop_reason": result.get("stop_reason"),
            "text": result.get("text"),
            "usage": result.get("usage"),
        },
        "retry": {
            "actual_wait_seconds": delay if will_retry else 0,
            "delay_seconds": delay,
            "source": retry_source,
            "will_retry": will_retry,
        },
        "started_at": started_at,
        "target_system_id": target["target_system_id"],
        "timeouts": {
            "attempt_seconds": request.attempt_timeout_seconds,
            "connect_seconds": request.connect_timeout_seconds,
        },
        "versions": {
            "extraction_rule": f"{target['adapter_id']}-text-extraction-1.0.0",
            "http_library": "http.client",
            "operating_system": platform.system(),
            "python": platform.python_version(),
            "provider_sdk": "none",
            "roguerecall": "0.1.0",
        },
        "warnings": list(warnings),
    }
    if result.get("condition") is not None:
        evidence["response_condition"] = result["condition"]
    if result["kind"] != "completed":
        evidence["error"] = result["error"]
    if transport_error is not None:
        evidence["error"]["transport_code"] = transport_error.code
    return evidence


def _retry_delay(
    response: HttpResponse | None,
    attempt_number: int,
    jitter: Callable[[float], float],
) -> tuple[float, str]:
    if response is not None:
        value = _casefold_headers(response.headers).get("retry-after")
        if value is not None:
            try:
                delay = float(value)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    now = datetime.now(timezone.utc)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = max(0.0, (retry_at - now).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    delay = -1
            if 0 <= delay <= 3600:
                return delay, "retry_after"
    upper = min(30.0, float(2 ** (attempt_number - 1)))
    return max(0.0, min(upper, float(jitter(upper)))), "full_jitter"


def _response_warnings(
    target: dict[str, Any], result: dict[str, Any], warnings: list[str]
) -> None:
    if result.get("usage") is None:
        _append_warning(warnings, "usage_unavailable")
    if result.get("server_request_id") is None:
        _append_warning(warnings, "server_request_id_unavailable")
    returned_model = result.get("returned_model")
    if returned_model is None:
        _append_warning(warnings, "returned_model_unavailable")
    elif returned_model != target["requested_model"]:
        _append_warning(warnings, "returned_model_mismatch")


def _preflight_evidence(
    request: HttpRequest, response: HttpResponse, secrets: Sequence[str]
) -> dict[str, Any]:
    return {
        "request": {
            "body_utf8": request.body.decode("utf-8"),
            "body_sha256": sha256_bytes(request.body),
            "headers": _redacted_request_headers(request.headers),
            "method": request.method,
            "url": request.url,
        },
        "response": {
            "body_base64": base64.b64encode(
                _redacted_bytes(response.body, secrets)
            ).decode("ascii"),
            "body_sha256": sha256_bytes(response.body),
            "headers": _allowed_response_headers(response.headers),
            "http_status": response.status,
        },
    }


def _send_preflight(transport: Transport, request: HttpRequest) -> HttpResponse:
    try:
        return transport.send(request)
    except TransportError as error:
        return HttpResponse(599, {}, canonical_json({"transport_error": error.code}))


def _failed_preflight(
    started_at: str, evidence: list[dict[str, Any]], message: str
) -> dict[str, Any]:
    return {
        "error": {"code": "target_configuration_error", "message": message},
        "evidence": evidence,
        "finished_at": _utc_now(),
        "started_at": started_at,
        "status": "failed",
    }


def _not_tested(
    case: Mapping[str, str], position: int, cause: dict[str, str]
) -> dict[str, Any]:
    case_id, _ = _case_identity(case)
    return {
        "attempts": [],
        "case_id": case_id,
        "error": cause,
        "planned_position": position,
        "terminal_status": "not_tested",
    }


def _case_identity(case: Mapping[str, str]) -> tuple[str, str]:
    case_id = case.get("case_id")
    prompt = case.get("prompt")
    if not isinstance(case_id, str) or not case_id or not isinstance(prompt, str):
        raise TargetManifestError("execution cases require case_id and prompt text")
    return case_id, prompt


def _persist(
    attempt: dict[str, Any], callback: Callable[[dict[str, Any]], None] | None
) -> None:
    if callback is None:
        return
    try:
        callback(copy.deepcopy(attempt))
    except Exception as error:
        raise EngineExecutionError(
            f"attempt evidence could not be preserved after {type(error).__name__}"
        ) from None


def _protocol_error(message: str) -> dict[str, Any]:
    return {
        "error": {"code": "target_protocol_error", "message": message},
        "kind": "protocol_error",
    }


def _add_temperature(target: dict[str, Any], body: dict[str, Any]) -> None:
    if target["capabilities"]["temperature"]:
        body["temperature"] = target["generation"]["temperature"]


def _redacted_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    secret_names = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
    return {
        name.lower(): value
        for name, value in headers.items()
        if name.lower() not in secret_names
    }


def _allowed_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "anthropic-version",
        "content-type",
        "date",
        "openai-processing-ms",
        "request-id",
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-request-id",
    }
    return {name: value for name, value in _casefold_headers(headers).items() if name in allowed}


def _casefold_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _credential_values(
    target: Mapping[str, Any], environment: Mapping[str, str]
) -> tuple[str, ...]:
    environment_variable = target["credential"]["environment_variable"]
    if not isinstance(environment_variable, str):
        return ()
    value = environment.get(environment_variable)
    return () if not value else (value,)


def _redact_secrets(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secrets(item, secrets) for key, item in value.items()}
    return value


def _redacted_bytes(value: bytes, secrets: Sequence[str]) -> bytes:
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret.encode("utf-8"), b"[REDACTED]")
    return redacted


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_target(
    raw_target: object, environment: Mapping[str, str]
) -> dict[str, Any]:
    if not isinstance(raw_target, Mapping):
        raise TargetManifestError("each Target System must be an object")
    _allowed_fields(raw_target, _TARGET_FIELDS, _REQUIRED_TARGET_FIELDS, "Target System")
    target = copy.deepcopy(dict(raw_target))
    target.setdefault("base_url", None)
    target.setdefault("ca_bundle", None)
    target.setdefault("capabilities", {"temperature": True})
    target.setdefault("generation", {"max_output_tokens": 1024, "temperature": 0})
    target.setdefault(
        "execution",
        {
            "attempt_timeout_seconds": 90,
            "concurrency": 5,
            "connect_timeout_seconds": 10,
            "max_attempts": 3,
        },
    )
    target.setdefault("local_artifact", None)

    target_id = target["target_system_id"]
    if not isinstance(target_id, str) or not _TARGET_ID.fullmatch(target_id):
        raise TargetManifestError("target_system_id must be a stable lowercase ID")
    adapter_id = _enum(target, "adapter_id", ADAPTER_IDS)
    if target["adapter_version"] != ADAPTER_VERSION:
        raise TargetManifestError("unsupported adapter_version")
    _nonempty_text(target, "requested_model")

    base_url = target["base_url"]
    if adapter_id in OFFICIAL_ADAPTERS:
        if base_url is not None:
            raise TargetManifestError("official adapters reject a base_url override")
        if target["ca_bundle"] is not None or target["local_artifact"] is not None:
            raise TargetManifestError("official adapters reject local-only settings")
    else:
        target["base_url"] = _validate_local_url(base_url)
        _validate_local_artifact(target["local_artifact"])
        ca_bundle = target["ca_bundle"]
        if ca_bundle is not None and not isinstance(ca_bundle, str):
            raise TargetManifestError("ca_bundle must be a path string or null")
        if isinstance(ca_bundle, str):
            if not target["base_url"].startswith("https://"):
                raise TargetManifestError("ca_bundle is allowed only for local HTTPS")
            try:
                ca_content = Path(ca_bundle).read_bytes()
            except OSError as error:
                raise TargetManifestError("ca_bundle could not be read") from error
            target["ca_bundle"] = {"sha256": sha256_bytes(ca_content)}

    credential = _object(target, "credential", _CREDENTIAL_FIELDS)
    kind = _enum(credential, "kind", {"bearer", "none"})
    env_name = credential["environment_variable"]
    if kind == "none":
        if env_name is not None:
            raise TargetManifestError("credential environment variable must be null for none")
    elif not isinstance(env_name, str) or not env_name or not environment.get(env_name):
        raise TargetManifestError(f"credential environment variable is missing: {env_name}")
    if adapter_id in OFFICIAL_ADAPTERS and kind != "bearer":
        raise TargetManifestError("official adapters require a bearer credential")

    generation = _object(target, "generation", _GENERATION_FIELDS)
    _bounded_int(generation, "max_output_tokens", 1, 4096)
    temperature = generation["temperature"]
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise TargetManifestError("temperature must be a number")

    execution = _object(target, "execution", _EXECUTION_FIELDS)
    _bounded_int(execution, "concurrency", 1, 20)
    _positive_number(execution, "connect_timeout_seconds")
    _positive_number(execution, "attempt_timeout_seconds")
    _bounded_int(execution, "max_attempts", 1, 3)

    capabilities = target["capabilities"]
    if not isinstance(capabilities, Mapping) or set(capabilities) != {"temperature"}:
        raise TargetManifestError("capabilities must declare only temperature")
    if not isinstance(capabilities["temperature"], bool):
        raise TargetManifestError("temperature capability must be boolean")
    if adapter_id in OFFICIAL_ADAPTERS:
        catalog_temperature = _official_temperature_capability(
            adapter_id, target["requested_model"]
        )
        if "capabilities" in raw_target and capabilities["temperature"] != catalog_temperature:
            raise TargetManifestError(
                "official adapter capabilities come from the versioned catalog"
            )
        capabilities = {"temperature": catalog_temperature}

    warnings: list[str] = []
    if not capabilities["temperature"]:
        warnings.append("temperature_unsupported")
    if adapter_id in OFFICIAL_ADAPTERS and not _looks_pinned(target["requested_model"]):
        warnings.append("unpinned_model")
    if adapter_id == "openai-compatible-chat-v1":
        artifact = target["local_artifact"]
        if artifact is None or artifact["model_digest"] is None:
            warnings.append("unverifiable_model_artifact")
    target["capabilities"] = dict(capabilities)
    target["warnings"] = warnings
    return target


def _validate_local_url(value: object) -> str:
    if not isinstance(value, str):
        raise TargetManifestError("local adapter requires base_url")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise TargetManifestError("local base_url must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise TargetManifestError("local base_url must not contain user-info")
    if not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise TargetManifestError("local base_url must contain only an origin")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise TargetManifestError("plain HTTP is restricted to loopback hosts")
    try:
        port = parsed.port
    except ValueError as error:
        raise TargetManifestError("local base_url contains an invalid port") from error
    host = parsed.hostname
    assert host is not None
    canonical_host = f"[{host}]" if ":" in host else host.lower()
    netloc = canonical_host if port is None else f"{canonical_host}:{port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_local_artifact(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise TargetManifestError("local_artifact must be an object or null")
    _exact_fields(value, _LOCAL_ARTIFACT_FIELDS, "local_artifact")
    for field in (
        "software_name",
        "software_version",
        "model_artifact_name",
        "quantization",
    ):
        _nonempty_text(value, field)
    for field in ("model_digest", "launch_configuration_digest"):
        digest = value[field]
        if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise TargetManifestError(f"{field} must be a sha256 digest or null")
    _bounded_int(value, "context_size", 1, 10_000_000)


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    present = set(value)
    unknown = present - expected
    missing = expected - present
    if unknown:
        raise TargetManifestError(f"{label} contains unknown field: {sorted(unknown)[0]}")
    if missing:
        raise TargetManifestError(f"{label} is missing field: {sorted(missing)[0]}")


def _allowed_fields(
    value: Mapping[str, Any], allowed: set[str], required: set[str], label: str
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise TargetManifestError(f"{label} contains unknown field: {sorted(unknown)[0]}")
    if missing:
        raise TargetManifestError(f"{label} is missing field: {sorted(missing)[0]}")


def _object(
    container: Mapping[str, Any], field: str, expected: set[str]
) -> dict[str, Any]:
    value = container[field]
    if not isinstance(value, Mapping):
        raise TargetManifestError(f"{field} must be an object")
    _exact_fields(value, expected, field)
    return dict(value)


def _nonempty_text(container: Mapping[str, Any], field: str) -> str:
    value = container[field]
    if not isinstance(value, str) or not value.strip():
        raise TargetManifestError(f"{field} must be non-empty text")
    return value


def _enum(container: Mapping[str, Any], field: str, choices: set[str]) -> str:
    value = container[field]
    if not isinstance(value, str) or value not in choices:
        raise TargetManifestError(f"{field} contains an unsupported value")
    return value


def _bounded_int(
    container: Mapping[str, Any], field: str, minimum: int, maximum: int
) -> int:
    value = container[field]
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise TargetManifestError(f"{field} must be between {minimum} and {maximum}")
    return value


def _positive_number(container: Mapping[str, Any], field: str) -> float:
    value = container[field]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise TargetManifestError(f"{field} must be positive")
    return float(value)


def _looks_pinned(model: str) -> bool:
    return bool(re.search(r"(?:20\d{2}[-_]\d{2}[-_]\d{2}|\d{4})", model))


def _official_temperature_capability(adapter_id: str, model: str) -> bool:
    if adapter_id == "anthropic-messages-v1":
        return True
    return re.match(r"(?:o1|o3|o4|gpt-5)(?:-|$)", model) is None
