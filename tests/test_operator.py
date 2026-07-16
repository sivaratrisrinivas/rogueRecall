from __future__ import annotations

import json
from pathlib import Path

from roguerecall.cli import main
from roguerecall.installation import discover_paths


def test_home_override_controls_all_operator_paths(tmp_path: Path) -> None:
    paths = discover_paths({"ROGUERECALL_HOME": str(tmp_path / "home")}, platform="linux")

    assert paths.data == tmp_path / "home" / "data"
    assert paths.config == tmp_path / "home" / "config"
    assert paths.cache == tmp_path / "home" / "cache"
    assert paths.runs == tmp_path / "home" / "data" / "runs"


def test_paths_command_is_machine_readable(tmp_path: Path, capsys: object) -> None:
    assert main(["paths", "--json", "--home", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["runs"] == str(tmp_path / "data" / "runs")
    assert set(payload) == {"cache", "config", "data", "runs"}


def test_doctor_runs_offline_and_reports_machine_readable_checks(
    tmp_path: Path, capsys: object
) -> None:
    assert main(["doctor", "--json", "--home", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert {check["id"] for check in payload["checks"]} == {
        "corpus_integrity",
        "dashboard_startup",
        "grading_fixture",
        "package_integrity",
        "paths_writable",
        "run_record_round_trip",
        "runtime_support",
    }


def test_purge_preserves_run_records_and_complete_removal_needs_confirmation(
    tmp_path: Path, capsys: object
) -> None:
    (tmp_path / "data" / "runs" / "evidence").mkdir(parents=True)
    (tmp_path / "data" / "state.json").write_text("state", encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "cache.bin").write_text("cache", encoding="utf-8")

    assert main(["purge", "--home", str(tmp_path), "--dry-run"]) == 0
    assert "preserve" in capsys.readouterr().out
    assert (tmp_path / "data" / "state.json").exists()

    assert main(["purge", "--home", str(tmp_path), "--all"]) == 2
    assert "--confirm" in capsys.readouterr().out
    assert main(["purge", "--home", str(tmp_path), "--all", "--confirm"]) == 0
    assert not (tmp_path / "data" / "runs").exists()
