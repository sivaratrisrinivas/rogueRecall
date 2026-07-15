from __future__ import annotations

import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from roguerecall.dashboard import create_server
from roguerecall.engine import run_synthetic


def test_loopback_dashboard_displays_a_validated_completed_run_record(
    tmp_path: Path,
) -> None:
    record_path = run_synthetic(tmp_path)
    server = create_server(tmp_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        response = urllib.request.urlopen(url, timeout=5)
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert "RogueRecall Evaluation Run" in page
        assert record_path.name in page
        assert "Text Leak" in page
        assert "Grading Coverage: 1/1" in page
        assert f'href="/runs/{record_path.name}"' in page

        evidence_response = urllib.request.urlopen(
            f"{url}runs/{record_path.name}", timeout=5
        )
        evidence_page = evidence_response.read().decode("utf-8")
        assert "Selected response" in evidence_page
        assert "book-contiguous-20-v1" in evidence_page
        assert "artifacts/responses/" in evidence_page

        request = urllib.request.Request(url, data=b"start=true", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dashboard_rejects_non_loopback_bind_address(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_server(tmp_path, host="0.0.0.0", port=0)
