from __future__ import annotations

import html
import json
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .records import RecordValidationError, validate_record


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_server(
    runs_root: Path, *, host: str = "127.0.0.1", port: int = 7411
) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("The dashboard may bind only to a loopback address")
    root = runs_root.resolve()

    class ReadOnlyRunRecordHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            request_path = urlsplit(self.path).path
            if request_path == "/":
                body = _render_overview(root).encode("utf-8")
            elif request_path.startswith("/runs/"):
                run_id = request_path.removeprefix("/runs/")
                if not run_id or "/" in run_id:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                record_path = root / run_id
                try:
                    run = validate_record(record_path)
                except RecordValidationError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if run["run_id"] != run_id:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body = _render_evidence(record_path, run).encode("utf-8")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Run Record view is read-only")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def log_message(self, format: str, *args: Any) -> None:
            return

    if host == "::1":
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        return IPv6ThreadingHTTPServer((host, port), ReadOnlyRunRecordHandler)
    return ThreadingHTTPServer((host, port), ReadOnlyRunRecordHandler)


def _render_overview(runs_root: Path) -> str:
    rows = []
    if runs_root.is_dir():
        for record_path in sorted(runs_root.iterdir()):
            if not record_path.is_dir() or record_path.name.endswith(".incomplete"):
                continue
            try:
                run = validate_record(record_path)
            except RecordValidationError:
                continue
            summary = run["summary"]
            grade = "Text Leak" if summary["text_leaks"] else "No Text Leak"
            coverage = summary["grading_coverage"]
            leak_rate = summary["leak_rate"]
            escaped_run_id = html.escape(run["run_id"])
            rows.append(
                "<article>"
                f'<h2><a href="/runs/{escaped_run_id}">{escaped_run_id}</a></h2>'
                f"<p><strong>{grade}</strong></p>"
                f"<p>Grading Coverage: {coverage['numerator']}/{coverage['denominator']}</p>"
                f"<p>Leak rate: {leak_rate['numerator']}/{leak_rate['denominator']}</p>"
                f"<p>Record fingerprint: {html.escape(_record_fingerprint(record_path))}</p>"
                "</article>"
            )
    content = "".join(rows) or "<p>No validated Completed Run Records found.</p>"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>RogueRecall Evaluation Run</title>"
        "<style>body{font:16px/1.5 system-ui;max-width:60rem;margin:3rem auto;padding:0 1rem}"
        "article{border-block-start:1px solid #777;padding-block:1rem}strong{font-size:1.15rem}</style>"
        "</head><body><main><h1>RogueRecall Evaluation Run</h1>"
        f"{content}</main></body></html>"
    )


def _render_evidence(record_path: Path, run: dict[str, Any]) -> str:
    observation_reference = run["observations"][0]
    observation = json.loads(
        (record_path / observation_reference["path"]).read_text(encoding="utf-8")
    )
    response = observation["selected_response"]
    grade = observation["grade"]
    response_artifact = observation["artifacts"]["response"]
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Evidence — {html.escape(run['run_id'])}</title></head><body><main>"
        '<p><a href="/">Back to Completed Run Records</a></p>'
        f"<h1>Evidence for {html.escape(run['run_id'])}</h1>"
        f"<p>Evaluation Case: {html.escape(observation['case_id'])}</p>"
        f"<h2>Selected response</h2><pre>{html.escape(response['text'])}</pre>"
        f"<p>Grade: {html.escape(grade['outcome_reason'])}; "
        f"Text Leak: {str(grade['text_leak']).lower()}</p>"
        f"<p>Raw response artifact: {html.escape(response_artifact['path'])}</p>"
        "</main></body></html>"
    )


def _record_fingerprint(record_path: Path) -> str:
    integrity = json.loads((record_path / "integrity.json").read_text(encoding="utf-8"))
    return str(integrity["record_fingerprint"])
