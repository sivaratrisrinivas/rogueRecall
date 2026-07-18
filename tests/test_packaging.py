from __future__ import annotations

import json
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
    assert "benchmark" in result.stdout
    assert "run-synthetic" not in result.stdout
    assert "dashboard" not in result.stdout
    assert "doctor" not in result.stdout
    assert "paths" not in result.stdout
    assert "purge" not in result.stdout

    version = subprocess.run(
        [sys.executable, "-m", "roguerecall.cli", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0
    assert version.stdout.strip() == "roguerecall 0.1.0"


def test_source_tree_contains_complete_cli_runtime() -> None:
    names = {
        path.relative_to(Path("src")).as_posix()
        for path in Path("src/roguerecall").rglob("*")
        if path.is_file()
    }

    for required in (
        "roguerecall/cli.py",
        "roguerecall/benchmark.py",
        "roguerecall/engine.py",
        "roguerecall/grading.py",
        "roguerecall/data/benchmark_corpus.json",
    ):
        assert required in names

    for removed in (
        "roguerecall/dashboard.py",
        "roguerecall/dashboard_exports.py",
        "roguerecall/dashboard_data.py",
        "roguerecall/installation.py",
        "roguerecall/data/default_corpus.json",
        "roguerecall/data/synthetic_case.json",
    ):
        assert removed not in names

    corpus = json.loads(Path("src/roguerecall/data/benchmark_corpus.json").read_text())
    assert corpus["version"] == "1.0.0"
    assert len(corpus["cases"]) == 50
    assert len(corpus["fingerprint"]) == 64
