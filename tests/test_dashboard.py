from __future__ import annotations

import csv
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import pytest

from roguerecall.dashboard import create_server
from roguerecall.engine import run_synthetic
from roguerecall.records import write_integrity, write_json


@contextmanager
def running_dashboard(runs_root: Path) -> Iterator[str]:
    server = create_server(runs_root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def get(url: str) -> tuple[int, str, bytes]:
    response = urllib.request.urlopen(url, timeout=15)
    return (
        response.status,
        response.headers.get_content_type(),
        response.read(),
    )


def test_loopback_dashboard_displays_a_validated_completed_run_record(
    tmp_path: Path,
) -> None:
    record_path = run_synthetic(tmp_path)
    with running_dashboard(tmp_path) as base_url:
        status, _, body = get(f"{base_url}/")
        page = body.decode("utf-8")
        assert status == 200
        assert "RogueRecall Evaluation Run" in page
        assert record_path.name in page
        assert "Text Leak" in page
        assert "Grading Coverage</dt><dd>1/1" in page
        assert "Leak rate</dt><dd>1/1" in page
        assert "Errors</dt><dd>0" in page
        assert "Refusals</dt><dd>0" in page
        assert "Truncations</dt><dd>0" in page
        assert "Warnings</dt><dd>0" in page
        assert "Source Identification</dt><dd>0" in page
        assert f'href="/runs/{record_path.name}"' in page

        _, _, evidence = get(f"{base_url}/runs/{record_path.name}")
        evidence_page = evidence.decode("utf-8")
        assert "Evidence ledger" in evidence_page
        assert 'type="search"' in evidence_page
        assert "Continuation" in evidence_page
        assert "synthetic-deterministic-v1" in evidence_page
        assert "book-contiguous-20-v1" in evidence_page
        assert f'/runs/{record_path.name}/files/artifacts/responses/' in evidence_page
        assert f'/runs/{record_path.name}/files/artifacts/evidence/' in evidence_page
        assert 'id="grading-evidence-' in evidence_page

        request = urllib.request.Request(
            f"{base_url}/", data=b"start=true", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 405


def test_evidence_ledger_filters_and_opens_exact_artifacts(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    run = json.loads((record_path / "run.json").read_text(encoding="utf-8"))
    observation = json.loads(
        (record_path / run["observations"][0]["path"]).read_text(encoding="utf-8")
    )
    response_path = observation["artifacts"]["response"]["path"]

    with running_dashboard(tmp_path) as base_url:
        _, _, filtered = get(
            f"{base_url}/runs/{record_path.name}?q=does-not-exist&outcome=text_leak"
        )
        assert "No evidence matches the current filters." in filtered.decode("utf-8")

        status, content_type, artifact = get(
            f"{base_url}/runs/{record_path.name}/files/{response_path}"
        )
        assert status == 200
        assert content_type == "text/plain"
        assert artifact == (record_path / response_path).read_bytes()


def test_comparison_gates_deltas_on_compatibility(tmp_path: Path) -> None:
    left = run_synthetic(tmp_path)
    right = run_synthetic(tmp_path)

    with running_dashboard(tmp_path) as base_url:
        _, _, compatible = get(
            f"{base_url}/compare?left={left.name}&right={right.name}"
        )
        page = compatible.decode("utf-8")
        assert "Compatible Comparison" in page
        assert "Target System qualifiers" in page
        assert "Case-paired transitions" in page
        assert "Coverage change: +0.0 percentage points" in page
        assert "Text Leak → Text Leak" in page
        assert "winner" not in page.lower()

    run_path = right / "run.json"
    changed = json.loads(run_path.read_text(encoding="utf-8"))
    changed["versions"]["grader"] = "99.0.0"
    write_json(run_path, changed)
    write_integrity(right)

    with running_dashboard(tmp_path) as base_url:
        _, _, incompatible = get(
            f"{base_url}/compare?left={left.name}&right={right.name}"
        )
        page = incompatible.decode("utf-8")
        assert "Incompatible Run Records" in page
        assert "No calculated delta or merged denominator" in page
        assert "Coverage change:" not in page
        assert "Case-paired transitions" not in page


def test_incomplete_records_require_diagnostic_opt_in(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path, inject_failure="operator-interrupted")

    with running_dashboard(tmp_path) as base_url:
        _, _, ordinary = get(f"{base_url}/")
        ordinary_page = ordinary.decode("utf-8")
        assert record_path.name not in ordinary_page

        _, _, diagnostic = get(f"{base_url}/?include_incomplete=1")
        diagnostic_page = diagnostic.decode("utf-8")
        assert record_path.name in diagnostic_page
        assert "Diagnostic opt-in active" in diagnostic_page
        assert "Ordinary aggregate rates are intentionally unavailable" in diagnostic_page
        assert "Leak rate: 0/0" not in diagnostic_page


def test_export_package_has_stable_safe_traceable_tables(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    run = json.loads((record_path / "run.json").read_text(encoding="utf-8"))
    observation_path = record_path / run["observations"][0]["path"]
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["error"] = {
        "code": "diagnostic_note",
        "message": "=HYPERLINK(\"https://example.invalid\")",
    }
    write_json(observation_path, observation)
    write_integrity(record_path)

    with running_dashboard(tmp_path) as base_url:
        status, content_type, package = get(
            f"{base_url}/runs/{record_path.name}/export.zip"
        )
    assert status == 200
    assert content_type == "application/zip"

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert archive.namelist() == ["results.csv", "attempts.csv", "export-metadata.json"]
        results = list(
            csv.DictReader(io.StringIO(archive.read("results.csv").decode("utf-8")))
        )
        attempts_header = archive.read("attempts.csv").decode("utf-8").splitlines()[0]
        metadata = json.loads(archive.read("export-metadata.json"))

    assert "selected_response" not in results[0]
    assert results[0]["error_message"].startswith("'=HYPERLINK")
    assert results[0]["text_leak"] == "true"
    assert results[0]["error_code"] == "diagnostic_note"
    assert "attempt_number" in attempts_header
    assert metadata["source"]["record_fingerprint"] == json.loads(
        (record_path / "integrity.json").read_text(encoding="utf-8")
    )["record_fingerprint"]
    assert metadata["target_system_evidence"]["configuration_fingerprint"]
    assert metadata["target_system_evidence"]["versions"]["grader"]
    assert metadata["null_rule"] == "Unavailable values are empty CSV fields."
    assert metadata["spreadsheet_formula_sanitization"].startswith("Text beginning")


def test_dashboard_markup_encodes_wcag_2_2_aa_behaviors(tmp_path: Path) -> None:
    record_path = run_synthetic(tmp_path)
    with running_dashboard(tmp_path) as base_url:
        _, _, body = get(f"{base_url}/runs/{record_path.name}")
    page = body.decode("utf-8")

    assert 'class="skip-link" href="#main"' in page
    assert '<main id="main"' in page
    assert '<caption>' in page
    assert '<label for="evidence-search">' in page
    assert ':focus-visible' in page
    assert '@media (max-width: 40rem)' in page
    assert '@media (prefers-reduced-motion: reduce)' in page
    assert 'data-outcome="text-leak">Text Leak' in page


def test_dashboard_rejects_non_loopback_bind_address(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_server(tmp_path, host="0.0.0.0", port=0)
