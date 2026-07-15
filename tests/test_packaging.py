from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def test_python_312_package_exposes_exact_versioned_cli_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.1.0"
    assert project["project"]["requires-python"] == ">=3.12,<3.13"
    assert project["project"]["scripts"]["roguerecall"] == "roguerecall.cli:main"

    result = subprocess.run(
        [sys.executable, "-m", "roguerecall.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "run-synthetic" in result.stdout
    assert "dashboard" in result.stdout
