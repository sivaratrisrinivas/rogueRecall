from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Encode JSON deterministically for fingerprints and request evidence."""

    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 digest of immutable byte content."""

    return hashlib.sha256(content).hexdigest()
