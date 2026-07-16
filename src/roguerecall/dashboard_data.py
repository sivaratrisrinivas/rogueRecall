from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def object_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def read_observations(record_path: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        json.loads((record_path / item["path"]).read_text(encoding="utf-8"))
        for item in run["observations"]
    ]


def observation_outcome_key(observation: dict[str, Any]) -> str:
    grade = object_value(observation.get("grade"))
    if grade.get("text_leak") is True:
        return "text_leak"
    if grade.get("text_leak") is False:
        return "no_text_leak"
    return str(observation.get("terminal_status", "unknown"))


def target_context(record_path: Path, run: dict[str, Any]) -> dict[str, Any]:
    target_record = json.loads(
        (record_path / run["target"]["path"]).read_text(encoding="utf-8")
    )
    manifest = object_value(target_record.get("manifest"))
    if not manifest:
        manifest = target_record
    preflights = target_record.get("preflights", [])
    return {
        "configuration_fingerprint": run["target"].get("fingerprint"),
        "manifest": manifest,
        "preflights": preflights if isinstance(preflights, list) else [],
        "run_warnings": run.get("warnings", []),
        "versions": run.get("versions", {}),
    }
