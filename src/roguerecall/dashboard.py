from __future__ import annotations

import html
import json
import mimetypes
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from .dashboard_data import (
    object_value,
    observation_outcome_key,
    read_observations,
    target_context,
)
from .dashboard_exports import build_export_package
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
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                content, media_type, filename = _route(root, url.path, query)
            except (RecordValidationError, FileNotFoundError, ValueError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            if filename is not None:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content)

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


def _route(
    root: Path, path: str, query: dict[str, list[str]]
) -> tuple[bytes, str, str | None]:
    diagnostic = query.get("include_incomplete") == ["1"]
    if path == "/":
        return _render_overview(root, diagnostic).encode(), "text/html; charset=utf-8", None
    if path == "/compare":
        left_path, left = _load_record(root, _one(query, "left"), diagnostic)
        right_path, right = _load_record(root, _one(query, "right"), diagnostic)
        body = _render_comparison(left_path, left, right_path, right)
        return body.encode(), "text/html; charset=utf-8", None
    if not path.startswith("/runs/"):
        raise FileNotFoundError(path)
    parts = path.removeprefix("/runs/").split("/")
    run_id = parts[0]
    record_path, run = _load_record(root, run_id, diagnostic)
    if len(parts) == 1:
        return (
            _render_evidence(record_path, run, query).encode(),
            "text/html; charset=utf-8",
            None,
        )
    if parts[1:] == ["export.zip"]:
        package = build_export_package(record_path, run)
        return package, "application/zip", f"roguerecall-{run['run_id']}.zip"
    if len(parts) > 2 and parts[1] == "files":
        relative = "/".join(parts[2:])
        content, media_type = _read_artifact(record_path, relative)
        return content, media_type, None
    raise FileNotFoundError(path)


def _load_record(root: Path, run_id: str, allow_incomplete: bool) -> tuple[Path, dict[str, Any]]:
    if not run_id or Path(run_id).name != run_id:
        raise FileNotFoundError(run_id)
    record_path = root / run_id
    incomplete = run_id.endswith(".incomplete")
    if incomplete and not allow_incomplete:
        raise FileNotFoundError(run_id)
    run = validate_record(record_path, require_complete=not incomplete)
    if run["run_id"] != run_id.removesuffix(".incomplete"):
        raise FileNotFoundError(run_id)
    return record_path, run


def _render_overview(runs_root: Path, diagnostic: bool = False) -> str:
    records: list[tuple[Path, dict[str, Any]]] = []
    if runs_root.is_dir():
        for record_path in sorted(runs_root.iterdir()):
            if not record_path.is_dir():
                continue
            incomplete = record_path.name.endswith(".incomplete")
            if incomplete and not diagnostic:
                continue
            try:
                run = validate_record(record_path, require_complete=not incomplete)
            except RecordValidationError:
                continue
            records.append((record_path, run))

    cards = "".join(_overview_card(path, run, diagnostic) for path, run in records)
    if not cards:
        cards = "<p class=\"empty\">No validated Completed Run Records found.</p>"
    completed = [run for _, run in records if run["lifecycle"]["state"] == "complete"]
    options = "".join(
        f'<option value="{_escape(run["run_id"])}">{_escape(run["run_id"])}</option>'
        for run in completed
    )
    diagnostic_notice = (
        '<aside class="notice diagnostic"><strong>Diagnostic opt-in active.</strong> '
        "Incomplete Run Records are visible, remain excluded from ordinary aggregates, "
        "and require the same opt-in on drill-down.</aside>"
        if diagnostic
        else '<p><a href="/?include_incomplete=1">Inspect Incomplete Run Records diagnostically</a></p>'
    )
    comparison = ""
    if completed:
        comparison = (
            '<form class="compare-form" action="/compare" method="get">'
            '<h2>Compare Completed Run Records</h2>'
            '<label for="left-run">First Run Record</label><select id="left-run" name="left">'
            f"{options}</select>"
            '<label for="right-run">Second Run Record</label><select id="right-run" name="right">'
            f'{options}</select><button type="submit">Check compatibility</button></form>'
        )
    return _page(
        "RogueRecall Evaluation Run",
        '<main id="main"><header class="masthead"><div><p class="eyebrow">RogueRecall</p>'
        '<h1>RogueRecall Evaluation Run</h1></div><p>Validated, read-only Run Record evidence.</p>'
        f"</header>{diagnostic_notice}<section class=\"record-list\" aria-label=\"Run Records\">"
        f"{cards}</section>{comparison}</main>",
    )


def _overview_card(record_path: Path, run: dict[str, Any], diagnostic: bool) -> str:
    incomplete = run["lifecycle"]["state"] != "complete"
    suffix = "?include_incomplete=1" if incomplete and diagnostic else ""
    observations = read_observations(record_path, run)
    counts = _observation_counts(observations)
    title = record_path.name
    if incomplete:
        metrics = (
            '<p class="diagnostic-copy"><strong>Incomplete Run Record.</strong> '
            "Ordinary aggregate rates are intentionally unavailable.</p>"
            f'<dl class="metrics"><div><dt>Recorded observations</dt><dd>{len(observations)}/'
            f'{len(run["plan"])}</dd></div><div><dt>Errors</dt><dd>{counts["errors"]}</dd></div>'
            f'<div><dt>Warnings</dt><dd>{counts["warnings"] + len(run["warnings"])}</dd></div></dl>'
        )
    else:
        summary = run["summary"]
        coverage = summary["grading_coverage"]
        leak_rate = summary["leak_rate"]
        grade = "Text Leak" if summary["text_leaks"] else "No Text Leak"
        metrics = (
            f'<p class="outcome" data-outcome="{_outcome_slug(grade)}">{grade}</p>'
            '<dl class="metrics">'
            f'<div><dt>Grading Coverage</dt><dd>{coverage["numerator"]}/{coverage["denominator"]}</dd></div>'
            f'<div><dt>Leak rate</dt><dd>{leak_rate["numerator"]}/{leak_rate["denominator"]}</dd></div>'
            f'<div><dt>Errors</dt><dd>{counts["errors"]}</dd></div>'
            f'<div><dt>Refusals</dt><dd>{counts["refusals"]}</dd></div>'
            f'<div><dt>Truncations</dt><dd>{counts["truncations"]}</dd></div>'
            f'<div><dt>Warnings</dt><dd>{counts["warnings"] + len(run["warnings"])}</dd></div>'
            f'<div><dt>Source Identification</dt><dd>{counts["source_identification"]}</dd></div>'
            "</dl>"
        )
    return (
        '<article class="record-card">'
        f'<div><p class="eyebrow">{_escape(run["lifecycle"]["state"]).upper()}</p>'
        f'<h2><a href="/runs/{quote(title)}{suffix}">{_escape(title)}</a></h2></div>'
        f"{metrics}<p class=\"fingerprint\">Source fingerprint: {_escape(_record_fingerprint(record_path))}</p>"
        "</article>"
    )


def _render_evidence(
    record_path: Path, run: dict[str, Any], query: dict[str, list[str]]
) -> str:
    observations = read_observations(record_path, run)
    cases = _case_map(record_path, run)
    filters = {
        "q": _query_value(query, "q"),
        "case": _query_value(query, "case"),
        "vector": _query_value(query, "vector"),
        "target": _query_value(query, "target"),
        "outcome": _query_value(query, "outcome"),
        "warning": _query_value(query, "warning"),
        "error": _query_value(query, "error"),
        "diagnostic": _query_value(query, "diagnostic"),
    }
    rows = []
    for observation in observations:
        case = cases.get(_text(observation.get("case_id")), {})
        if _matches_filters(observation, case, filters):
            rows.append(_evidence_row(record_path, observation, case))
    body_rows = "".join(rows) or (
        '<tr><td colspan="7" class="empty">No evidence matches the current filters.</td></tr>'
    )
    vectors = sorted(
        {
            _attack_vector(cases.get(_text(item.get("case_id")), {}))
            for item in observations
        }
    )
    targets = sorted({str(item.get("target_system_id", "")) for item in observations})
    case_ids = sorted({_text(item.get("case_id")) for item in observations})
    outcomes = sorted({observation_outcome_key(item) for item in observations})
    warnings = sorted(
        {str(warning) for item in observations for warning in item.get("warnings", [])}
    )
    errors = sorted(
        {
            _text(object_value(item.get("error")).get("code"))
            for item in observations
            if object_value(item.get("error"))
        }
    )
    diagnostics = sorted(
        {
            str(name)
            for item in observations
            for name in object_value(object_value(item.get("grade")).get("diagnostics"))
        }
    )
    diagnostic = run["lifecycle"]["state"] != "complete"
    opt_in = '<input type="hidden" name="include_incomplete" value="1">' if diagnostic else ""
    export_query = "?include_incomplete=1" if diagnostic else ""
    notice = (
        '<aside class="notice diagnostic"><strong>Diagnostic view.</strong> This Incomplete Run '
        "Record does not contribute ordinary aggregate rates or comparisons.</aside>"
        if diagnostic
        else ""
    )
    content = (
        '<main id="main"><nav><a href="/">← Completed Run Records</a></nav>'
        f'<header class="run-title"><div><p class="eyebrow">Validated Run Record</p><h1>Evidence ledger</h1>'
        f'<p class="run-id">{_escape(record_path.name)}</p></div>'
        f'<a class="button" href="/runs/{quote(record_path.name)}/export.zip{export_query}">Export CSV package</a></header>'
        f"{notice}<form class=\"filters\" method=\"get\">{opt_in}"
        '<div class="search-field"><label for="evidence-search">Search cases, outcomes, warnings, errors, and diagnostics</label>'
        f'<input id="evidence-search" name="q" type="search" value="{_escape(filters["q"])}"></div>'
        f'{_select("case", "Evaluation Case", case_ids, filters["case"])}'
        f'{_select("vector", "Attack Vector", vectors, filters["vector"])}'
        f'{_select("target", "Target System", targets, filters["target"])}'
        f'{_select("outcome", "Outcome", outcomes, filters["outcome"])}'
        f'{_select("warning", "Warning", warnings, filters["warning"])}'
        f'{_select("error", "Error", errors, filters["error"])}'
        f'{_select("diagnostic", "Diagnostic", diagnostics, filters["diagnostic"])}'
        '<button type="submit">Apply filters</button></form>'
        '<div class="table-wrap"><table><caption>Case evidence with exact canonical pointers</caption>'
        '<thead><tr><th scope="col">Evaluation Case</th><th scope="col">Attack Vector</th>'
        '<th scope="col">Target System</th><th scope="col">Outcome</th><th scope="col">Diagnostics</th>'
        '<th scope="col">Warnings / errors</th><th scope="col">Evidence pointers</th></tr></thead>'
        f"<tbody>{body_rows}</tbody></table></div>"
        '<p class="reading-rule"><strong>Reading rule:</strong> Text Leak requires a Decisive Match. '
        "Source Identification is reported separately. Ungraded observations have a null Text Leak value.</p></main>"
    )
    return _page(f"Evidence — {run['run_id']}", content)


def _evidence_row(
    record_path: Path,
    observation: dict[str, Any],
    case: dict[str, Any],
) -> str:
    grade = object_value(observation.get("grade"))
    outcome = _observation_outcome(observation)
    source = object_value(grade.get("source_identification"))
    source_status = source.get("status", "not_assessed")
    diagnostics = object_value(grade.get("diagnostics"))
    diagnostic_text = ", ".join(f"{key}: {value}" for key, value in diagnostics.items()) or "None"
    warnings = [str(item) for item in observation.get("warnings", [])]
    error = object_value(observation.get("error"))
    warning_text = ", ".join(warnings) or "None"
    if error:
        warning_text += f'; error: {error.get("code", "unknown")} — {error.get("message", "")}'
    artifacts = object_value(observation.get("artifacts"))
    response = object_value(artifacts.get("response"))
    grading_artifact = object_value(artifacts.get("normalized_evidence"))
    response_path = response.get("path")
    response_link = (
        f'<a href="/runs/{quote(record_path.name)}/files/{quote(str(response_path), safe="/")}">Raw response artifact</a>'
        if isinstance(response_path, str)
        else "No response artifact"
    )
    grading_path = grading_artifact.get("path")
    grading_link = (
        f'<a href="/runs/{quote(record_path.name)}/files/{quote(str(grading_path), safe="/")}">Grading evidence artifact</a>'
        if isinstance(grading_path, str)
        else "No grading evidence artifact"
    )
    pointer = grade.get("evidence_pointer")
    pointer_id = f"grading-evidence-{observation.get('planned_position', 0)}"
    return (
        "<tr>"
        f'<th scope="row">{_escape(observation.get("case_id"))}</th>'
        f"<td>{_escape(_attack_vector(case))}</td>"
        f'<td class="mono">{_escape(observation.get("target_system_id"))}</td>'
        f'<td><span class="status" data-outcome="{_outcome_slug(outcome)}">{_escape(outcome)}</span><br>'
        f'<small>Source Identification: {_escape(source_status)}</small></td>'
        f"<td>{_escape(grade.get('outcome_reason', observation.get('terminal_status')))}<br>"
        f"<small>{_escape(diagnostic_text)}</small></td>"
        f"<td>{_escape(warning_text)}</td>"
        f'<td>{response_link}<br>{grading_link}<br><span id="{pointer_id}" class="pointer">Grading evidence: '
        f"{_escape(pointer or 'null')}</span></td></tr>"
    )


def _render_comparison(
    left_path: Path,
    left: dict[str, Any],
    right_path: Path,
    right: dict[str, Any],
) -> str:
    compatible, reasons = _compatibility(left, right)
    left_summary = _comparison_summary(left)
    right_summary = _comparison_summary(right)
    left_context = target_context(left_path, left)
    right_context = target_context(right_path, right)
    target_differences = _target_differences(left_context, right_context)
    differences = "".join(f"<li>{_escape(item)}</li>" for item in target_differences)
    qualifiers = (
        '<section class="qualifiers"><h2>Target System qualifiers</h2><dl>'
        f'<div><dt>First</dt><dd>{_escape(left["target"].get("target_system_id"))}<br>'
        f'<span class="pointer">{_escape(left["target"].get("fingerprint"))}</span></dd></div>'
        f'<div><dt>Second</dt><dd>{_escape(right["target"].get("target_system_id"))}<br>'
        f'<span class="pointer">{_escape(right["target"].get("fingerprint"))}</span></dd></div>'
        f"</dl><h3>Configuration, capability, warning, and version differences</h3><ul>{differences}</ul>"
        '<div class="target-contexts"><details><summary>First Target System evidence</summary><pre>'
        f"{_escape(json.dumps(left_context, ensure_ascii=False, sort_keys=True, indent=2))}</pre></details>"
        '<details><summary>Second Target System evidence</summary><pre>'
        f"{_escape(json.dumps(right_context, ensure_ascii=False, sort_keys=True, indent=2))}</pre></details></div></section>"
    )
    if compatible:
        left_coverage = _rate(left["summary"]["grading_coverage"])
        right_coverage = _rate(right["summary"]["grading_coverage"])
        delta = (right_coverage - left_coverage) * 100
        transitions = _paired_transitions(left_path, left, right_path, right)
        analysis = (
            '<section class="notice compatible"><strong>Compatible Comparison.</strong> '
            "The same case source and grading contracts permit case-paired descriptive changes. "
            "Target System identity remains a qualifier.</section>"
            f'<p class="coverage-change">Coverage change: {delta:+.1f} percentage points</p>'
            '<section><h2>Case-paired transitions</h2><div class="transitions">'
            f"{transitions}</div></section>"
        )
    else:
        reason_list = "".join(f"<li>{_escape(reason)}</li>" for reason in reasons)
        analysis = (
            '<section class="notice incompatible"><strong>Incompatible Run Records.</strong> '
            "They are shown side by side only. No calculated delta or merged denominator is provided."
            f"<ul>{reason_list}</ul></section>"
        )
    content = (
        '<main id="main"><nav><a href="/">← Run Records</a></nav>'
        '<header class="run-title"><div><p class="eyebrow">Compatibility before interpretation</p>'
        '<h1>Run Record comparison</h1></div></header>'
        f'<section class="comparison-grid">{left_summary}{right_summary}</section>{qualifiers}{analysis}</main>'
    )
    return _page("Run Record comparison", content)


def _comparison_summary(run: dict[str, Any]) -> str:
    complete = run["lifecycle"]["state"] == "complete"
    if not complete:
        return (
            '<article class="comparison-run"><p class="eyebrow">INCOMPLETE — DIAGNOSTIC ONLY</p>'
            f'<h2>{_escape(run["run_id"])}</h2><p>Ordinary aggregate rates unavailable.</p></article>'
        )
    coverage = run["summary"]["grading_coverage"]
    leak = run["summary"]["leak_rate"]
    return (
        '<article class="comparison-run"><p class="eyebrow">COMPLETED</p>'
        f'<h2>{_escape(run["run_id"])}</h2><dl class="metrics">'
        f'<div><dt>Grading Coverage</dt><dd>{coverage["numerator"]}/{coverage["denominator"]}</dd></div>'
        f'<div><dt>Leak rate</dt><dd>{leak["numerator"]}/{leak["denominator"]}</dd></div>'
        "</dl></article>"
    )


def _paired_transitions(
    left_path: Path,
    left: dict[str, Any],
    right_path: Path,
    right: dict[str, Any],
) -> str:
    left_items = _observations_by_case(read_observations(left_path, left))
    right_items = _observations_by_case(read_observations(right_path, right))
    left_case_ids = set(left_items)
    right_case_ids = set(right_items)
    shared_case_ids = sorted(left_case_ids.intersection(right_case_ids))
    rows = []
    for case_id in shared_case_ids:
        left_case_items = left_items[case_id]
        right_case_items = right_items[case_id]
        for ordinal in range(max(len(left_case_items), len(right_case_items))):
            left_item = left_case_items[ordinal] if ordinal < len(left_case_items) else None
            right_item = right_case_items[ordinal] if ordinal < len(right_case_items) else None
            if left_item is None or right_item is None:
                rows.append(
                    '<article class="transition"><h3>'
                    f"{_escape(case_id)} · pairing {ordinal + 1}</h3>"
                    "<p>No paired observation — no transition calculated.</p></article>"
                )
                continue
            rows.append(
                '<article class="transition"><h3>'
                f"{_escape(case_id)} · pairing {ordinal + 1}</h3><p>"
                f"{_escape(_observation_outcome(left_item))} → "
                f"{_escape(_observation_outcome(right_item))}<br><small>"
                f'{_escape(left_item.get("target_system_id"))} → '
                f'{_escape(right_item.get("target_system_id"))}</small></p></article>'
            )
    return "".join(rows) or '<p class="empty">No shared Evaluation Cases.</p>'


def _observations_by_case(
    observations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        case_id = _text(observation.get("case_id"))
        if case_id:
            grouped.setdefault(case_id, []).append(observation)
    for items in grouped.values():
        items.sort(key=lambda item: int(item.get("planned_position", 0)))
    return grouped


def _compatibility(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    if left["lifecycle"]["state"] != "complete" or right["lifecycle"]["state"] != "complete":
        reasons.append("Only Completed Run Records can form a Compatible Comparison.")
    left_source = left.get("case_set", left.get("case", {})).get("fingerprint")
    right_source = right.get("case_set", right.get("case", {})).get("fingerprint")
    if left_source != right_source:
        reasons.append("Benchmark Corpus or Evaluation Case Set fingerprints differ.")
    for field in ("grader", "normalization", "summary_formula"):
        if left["versions"].get(field) != right["versions"].get(field):
            reasons.append(f"Grading contract version differs: {field}.")
    return not reasons, reasons


def _target_differences(
    left: dict[str, Any], right: dict[str, Any]
) -> list[str]:
    differences = []
    labels = {
        "configuration_fingerprint": "Canonical Target System configuration differs.",
        "manifest": "Target System manifests differ.",
        "preflights": "Capability or preflight evidence differs.",
        "run_warnings": "Target System or execution warnings differ.",
        "versions": "Adapter or dependency versions differ.",
    }
    for field, label in labels.items():
        if left.get(field) != right.get(field):
            differences.append(label)
    return differences or ["No preserved Target System evidence differences detected."]


def _matches_filters(
    observation: dict[str, Any], case: dict[str, Any], filters: dict[str, str]
) -> bool:
    outcome = _observation_outcome(observation)
    grade = object_value(observation.get("grade"))
    error = object_value(observation.get("error"))
    diagnostic_values = object_value(grade.get("diagnostics"))
    searchable = json.dumps(
        {
            "case": observation.get("case_id"),
            "vector": _attack_vector(case),
            "target": observation.get("target_system_id"),
            "outcome": outcome,
            "warnings": observation.get("warnings"),
            "error": observation.get("error"),
            "diagnostics": grade.get("diagnostics") if isinstance(grade, dict) else None,
        },
        ensure_ascii=False,
    ).casefold()
    return (
        (not filters["q"] or filters["q"].casefold() in searchable)
        and (not filters["case"] or filters["case"] == observation.get("case_id"))
        and (not filters["vector"] or filters["vector"] == _attack_vector(case))
        and (not filters["target"] or filters["target"] == observation.get("target_system_id"))
        and (not filters["outcome"] or filters["outcome"] == _outcome_key(observation))
        and (not filters["warning"] or filters["warning"] in observation.get("warnings", []))
        and (not filters["error"] or filters["error"] == error.get("code"))
        and (not filters["diagnostic"] or filters["diagnostic"] in diagnostic_values)
    )


def _case_map(record_path: Path, run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = run.get("case_set", run.get("case", {}))
    value = json.loads((record_path / source["path"]).read_text(encoding="utf-8"))
    cases = value.get("cases") if isinstance(value, dict) else None
    if not isinstance(cases, list):
        cases = [value]
    return {
        case["identity"]["case_id"]: case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("identity"), dict)
    }


def _observation_counts(observations: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "errors": sum(1 for item in observations if isinstance(item.get("error"), dict)),
        "refusals": sum(1 for item in observations if item.get("response_condition") == "response_refusal"),
        "truncations": sum(1 for item in observations if item.get("response_condition") == "response_truncated"),
        "warnings": sum(len(item.get("warnings", [])) for item in observations),
        "source_identification": sum(
            1
            for item in observations
            if item.get("grade", {}).get("source_identification", {}).get("status") == "explicit"
        ),
    }


def _read_artifact(record_path: Path, relative: str) -> tuple[bytes, str]:
    if not relative.startswith("artifacts/") or relative.startswith(("/", "../")):
        raise FileNotFoundError(relative)
    resolved = (record_path / relative).resolve()
    if record_path.resolve() not in resolved.parents or not resolved.is_file():
        raise FileNotFoundError(relative)
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    if media_type.startswith("text/"):
        media_type += "; charset=utf-8"
    return resolved.read_bytes(), media_type


def _observation_outcome(observation: dict[str, Any]) -> str:
    key = observation_outcome_key(observation)
    return {
        "text_leak": "Text Leak",
        "no_text_leak": "No Text Leak",
        "target_error": "Target error",
        "grader_error": "Grader error",
    }.get(key, key.replace("_", " ").title())


def _outcome_key(observation: dict[str, Any]) -> str:
    return observation_outcome_key(observation)


def _attack_vector(case: dict[str, Any]) -> str:
    raw = case.get("classification", {}).get("attack_vector", "unknown")
    return str(raw).replace("_", " ").title()


def _select(name: str, label: str, options: list[str], selected: str) -> str:
    rendered = ['<option value="">All</option>']
    for option in options:
        selection = " selected" if option == selected else ""
        rendered.append(f'<option value="{_escape(option)}"{selection}>{_escape(option)}</option>')
    return (
        f'<div><label for="filter-{name}">{label}</label><select id="filter-{name}" name="{name}">'
        f'{"".join(rendered)}</select></div>'
    )


def _page(title: str, content: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_escape(title)}</title><style>{_STYLES}</style></head><body>"
        '<a class="skip-link" href="#main">Skip to main content</a>'
        f"{content}</body></html>"
    )


def _rate(value: dict[str, int]) -> float:
    return value["numerator"] / value["denominator"] if value["denominator"] else 0.0


def _one(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    if not values or len(values) != 1 or not values[0]:
        raise ValueError(name)
    return values[0]


def _query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name, [""])
    return values[0] if len(values) == 1 else ""


def _record_fingerprint(record_path: Path) -> str:
    integrity = json.loads((record_path / "integrity.json").read_text(encoding="utf-8"))
    return str(integrity["record_fingerprint"])


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _outcome_slug(value: str) -> str:
    return value.casefold().replace(" ", "-")


_STYLES = """
:root{color-scheme:light;--ink:#182018;--muted:#546154;--line:#c5cec3;--paper:#fff;--wash:#f3f5f1;--accent:#315c2d;--focus:#005fcc;--danger:#a12b22;--warning:#765500;font:100%/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;min-width:20rem;color:var(--ink);background:var(--wash)}a{color:#174f73;text-underline-offset:.18em}button,select,input{font:inherit}main{width:min(94rem,100%);margin:auto;padding:1.5rem}h1,h2,h3{line-height:1.15;text-wrap:balance}.skip-link{position:fixed;z-index:10;top:.5rem;left:.5rem;padding:.75rem;color:#fff;background:var(--ink);transform:translateY(-150%)}.skip-link:focus{transform:none}:focus-visible{outline:.2rem solid var(--focus);outline-offset:.2rem}.masthead,.run-title{display:flex;align-items:end;justify-content:space-between;gap:2rem;padding-bottom:1rem;border-bottom:.1rem solid var(--ink)}.masthead h1,.run-title h1{margin:.15rem 0}.eyebrow{margin:0;color:var(--muted);font:700 .75rem/1.4 ui-monospace,monospace;letter-spacing:.04em}.record-list{display:grid;gap:1rem;margin-block:1rem}.record-card,.compare-form,.comparison-run,.qualifiers,.transition{padding:1.25rem;border:.1rem solid var(--line);background:var(--paper)}.record-card h2{margin:.25rem 0;overflow-wrap:anywhere}.outcome{font-weight:750}.metrics{display:grid;grid-template-columns:repeat(7,minmax(7rem,1fr));margin:1rem 0;border-block:.1rem solid var(--line)}.metrics div{padding:.75rem;border-right:.1rem solid var(--line)}.metrics div:last-child{border:0}.metrics dt{color:var(--muted);font-size:.78rem}.metrics dd{margin:.25rem 0 0;font-weight:750}.fingerprint,.pointer,.run-id{font:.75rem/1.5 ui-monospace,monospace;overflow-wrap:anywhere}.notice{margin:1rem 0;padding:1rem;border-left:.35rem solid var(--warning);background:#fff8dc}.compatible{border-color:var(--accent)}.incompatible{border-color:var(--danger)}.diagnostic{border-color:var(--warning)}.compare-form{display:grid;grid-template-columns:auto minmax(10rem,1fr) auto minmax(10rem,1fr) auto;align-items:end;gap:.75rem}.compare-form h2{grid-column:1/-1}.compare-form label,.filters label{display:block;margin-bottom:.35rem;font-weight:700}.button,button{display:inline-flex;min-height:2.75rem;align-items:center;justify-content:center;padding:.55rem .8rem;border:.1rem solid var(--ink);color:#fff;background:var(--ink);font-weight:700;text-decoration:none}.filters{display:grid;grid-template-columns:minmax(16rem,2fr) repeat(4,minmax(9rem,1fr));align-items:end;gap:.75rem;margin-block:1.25rem}.filters input,.filters select,.compare-form select{width:100%;min-height:2.75rem;padding:.5rem;border:.1rem solid #687268;background:#fff}.table-wrap{overflow:auto;border:.1rem solid var(--line);background:#fff}table{width:100%;border-collapse:collapse;font-size:.88rem}caption{padding:.75rem;text-align:left;font-weight:750}th,td{padding:.8rem;text-align:left;vertical-align:top;border-top:.1rem solid var(--line)}thead th{color:var(--muted);background:var(--wash)}tbody th{min-width:12rem}.status{font-weight:750}[data-outcome="text-leak"]{color:var(--danger)}[data-outcome="no-text-leak"]{color:#24602d}.reading-rule{padding:1rem;border-bottom:.1rem solid var(--line)}.comparison-grid,.qualifiers dl,.target-contexts{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.comparison-run .metrics{grid-template-columns:1fr 1fr}.qualifiers dl{margin:0}.qualifiers dd{margin:.25rem 0}.target-contexts pre{max-height:24rem;overflow:auto;padding:.75rem;background:var(--wash);font-size:.72rem}.transitions{display:grid;gap:.75rem}.transition{display:grid;grid-template-columns:1fr 1fr;align-items:center}.transition h3,.transition p{margin:0}.coverage-change{font-weight:750}.empty{padding:2rem;text-align:center;color:var(--muted)}nav{margin-bottom:1rem}
@media (max-width: 60rem){.metrics{grid-template-columns:repeat(3,1fr)}.filters{grid-template-columns:1fr 1fr}.search-field{grid-column:1/-1}.compare-form{grid-template-columns:1fr 1fr}.compare-form label{align-self:end}}
@media (max-width: 40rem){main{padding:1rem}.masthead,.run-title{align-items:start;flex-direction:column}.metrics,.filters,.comparison-grid,.qualifiers dl,.target-contexts,.transition,.compare-form{grid-template-columns:1fr}.metrics div{border-right:0;border-bottom:.1rem solid var(--line)}.table-wrap{margin-inline:-1rem;border-inline:0}.button{width:100%}table{font-size:1rem}}
@media (prefers-reduced-motion: reduce){*,*::before,*::after{scroll-behavior:auto!important;transition-duration:.01ms!important;animation-duration:.01ms!important}}
@media (forced-colors: active){.notice,.record-card,.comparison-run{border:2px solid CanvasText}}
"""
