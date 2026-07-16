from __future__ import annotations

import json
import base64
import hashlib
import os
import platform as platform_module
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from importlib.resources import files
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .dashboard import create_server
from .engine import run_synthetic
from .records import sha256_bytes, validate_record


DEFAULT_CORPUS_MANIFEST_SHA256 = "d54a07789c5d285ac452cd877f44cdbf685efc67fbfc6e3f6456d91c1a6778ef"


@dataclass(frozen=True)
class InstallationPaths:
    data: Path
    config: Path
    cache: Path
    runs: Path

    def serializable(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def discover_paths(
    environ: Mapping[str, str] | None = None, *, platform: str | None = None
) -> InstallationPaths:
    env = os.environ if environ is None else environ
    system = (platform or sys.platform).lower()
    home = Path(env.get("HOME", str(Path.home())))
    override = env.get("ROGUERECALL_HOME")
    if override:
        root = Path(override).expanduser()
        data, config, cache = root / "data", root / "config", root / "cache"
    elif system.startswith("win"):
        data = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")) / "RogueRecall"
        config = Path(env.get("APPDATA", home / "AppData" / "Roaming")) / "RogueRecall"
        cache = data / "Cache"
    elif system == "darwin":
        library = home / "Library"
        data = library / "Application Support" / "RogueRecall"
        config = data / "config"
        cache = library / "Caches" / "RogueRecall"
    else:
        data = Path(env.get("XDG_DATA_HOME", home / ".local" / "share")) / "roguerecall"
        config = Path(env.get("XDG_CONFIG_HOME", home / ".config")) / "roguerecall"
        cache = Path(env.get("XDG_CACHE_HOME", home / ".cache")) / "roguerecall"
    return InstallationPaths(data=data, config=config, cache=cache, runs=data / "runs")


def run_doctor(paths: InstallationPaths) -> dict[str, Any]:
    checks: list[dict[str, object]] = []

    def check(identifier: str, action: Callable[[], object]) -> None:
        try:
            detail = action()
            checks.append({"id": identifier, "ok": True, "detail": str(detail)})
        except Exception as error:
            checks.append({"id": identifier, "ok": False, "detail": str(error)})

    check("runtime_support", lambda: _runtime_detail())
    check("package_integrity", _package_integrity)
    check("corpus_integrity", _corpus_integrity)
    check("paths_writable", lambda: _paths_writable(paths))
    check("dashboard_startup", lambda: _dashboard_startup(paths.runs))
    check("grading_fixture", _grading_fixture)
    check("run_record_round_trip", _record_round_trip)
    return {"ok": all(item["ok"] for item in checks), "offline": True, "checks": checks}


def purge(paths: InstallationPaths, *, include_runs: bool, dry_run: bool) -> list[dict[str, str]]:
    targets = [paths.cache, paths.config]
    targets.extend([paths.data] if include_runs else [child for child in _children(paths.data) if child != paths.runs])
    actions = [
        {"action": "remove", "path": str(path)} for path in targets if path.exists()
    ]
    if not include_runs:
        actions.append({"action": "preserve", "path": str(paths.runs)})
    if not dry_run:
        for item in actions:
            if item["action"] == "remove":
                path = Path(item["path"])
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    return actions


def _children(path: Path) -> list[Path]:
    return list(path.iterdir()) if path.is_dir() else []


def _runtime_detail() -> str:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Python 3.12 required; found {platform_module.python_version()}")
    return platform_module.python_version()


def _package_integrity() -> str:
    package = files("roguerecall")
    required = ("cli.py", "engine.py", "grading.py", "dashboard.py")
    missing = [name for name in required if not package.joinpath(name).is_file()]
    if missing:
        raise RuntimeError(f"missing packaged modules: {', '.join(missing)}")
    try:
        package_files = distribution("roguerecall").files or []
    except PackageNotFoundError:
        package_files = []
    verified = 0
    for item in package_files:
        if not str(item).startswith("roguerecall/") or item.hash is None:
            continue
        content = Path(item.locate()).read_bytes()
        actual = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        if item.hash.mode != "sha256" or actual != item.hash.value:
            raise RuntimeError(f"installed package integrity failed: {item}")
        verified += 1
    return f"roguerecall {__version__}; {verified or len(required)} files verified"


def _corpus_integrity() -> str:
    resource = files("roguerecall").joinpath("data/default_corpus.json")
    payload = resource.read_bytes()
    if sha256_bytes(payload) != DEFAULT_CORPUS_MANIFEST_SHA256:
        raise RuntimeError("bundled default corpus manifest integrity failed")
    corpus = json.loads(payload)
    for case in corpus["cases"]:
        case_payload = files("roguerecall").joinpath(f"data/{case['resource']}").read_bytes()
        if sha256_bytes(case_payload) != case["sha256"]:
            raise RuntimeError("bundled default corpus Evaluation Case integrity failed")
    return f"{corpus['corpus_id']}@{corpus['version']}"


def _paths_writable(paths: InstallationPaths) -> str:
    for path in (paths.data, paths.config, paths.cache):
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor-write-probe"
        probe.write_bytes(b"ok")
        probe.unlink()
    return "data, config, and cache paths are writable"


def _dashboard_startup(runs_root: Path) -> str:
    server = create_server(runs_root, port=0)
    try:
        return f"127.0.0.1:{server.server_port}"
    finally:
        server.server_close()


def _grading_fixture() -> str:
    with tempfile.TemporaryDirectory() as directory:
        record = run_synthetic(Path(directory))
        run = validate_record(record)
        if run["summary"]["graded"] != 1:
            raise RuntimeError("bundled grading fixture did not produce one grade")
    return "bundled synthetic fixture graded"


def _record_round_trip() -> str:
    with tempfile.TemporaryDirectory() as directory:
        record = run_synthetic(Path(directory))
        run = validate_record(record)
        machine_json = json.dumps(run, sort_keys=True)
        if json.loads(machine_json) != run:
            raise RuntimeError("Run Record machine JSON round-trip failed")
    return "temporary Run Record and machine JSON validated"
