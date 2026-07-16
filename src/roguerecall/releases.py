from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .records import canonical_json, sha256_bytes


RELEASE_SCHEMA_VERSION = "1.0.0"
REGISTRY_SCHEMA_VERSION = "1.0.0"
_SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_REQUIRED_NOTICES = frozenset(
    {
        "LICENSE",
        "LICENSE-CONTENT",
        "NOTICE",
        "RIGHTS.md",
        "THIRD_PARTY_NOTICES.md",
        "rights-manifest.json",
    }
)
_STATUSES = frozenset({"published", "superseded", "suspended", "withdrawn"})
_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"published"}),
    "published": frozenset({"superseded", "suspended", "withdrawn"}),
    "superseded": frozenset({"suspended", "withdrawn"}),
    "suspended": frozenset({"published", "suspended", "withdrawn"}),
    "withdrawn": frozenset(),
}


class ReleaseValidationError(ValueError):
    """Raised when a Benchmark Corpus Release or registry cannot be trusted."""


@dataclass(frozen=True)
class ReleaseIdentity:
    """Protected Ed25519 signing identity used by release automation."""

    key_id: str
    _private_key: Ed25519PrivateKey

    def private_key_bytes(self) -> bytes:
        """Serialize the raw private key for protected configuration storage."""

        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_identity(self) -> dict[str, str]:
        public_key = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return {
            "algorithm": "Ed25519",
            "key_id": self.key_id,
            "public_key": base64.b64encode(public_key).decode("ascii"),
        }

    def sign(self, value: Mapping[str, Any]) -> dict[str, str]:
        signature = self._private_key.sign(canonical_json(value))
        return {
            "algorithm": "Ed25519",
            "key_id": self.key_id,
            "signature": base64.b64encode(signature).decode("ascii"),
        }


def generate_release_identity(key_id: str) -> ReleaseIdentity:
    """Generate an Ed25519 identity; callers must protect the returned private key."""

    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ReleaseValidationError("release key_id is invalid")
    return ReleaseIdentity(key_id, Ed25519PrivateKey.generate())


def load_release_identity(key_id: str, private_key: bytes) -> ReleaseIdentity:
    """Load a configured raw Ed25519 private key without persisting it in artifacts."""

    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ReleaseValidationError("release key_id is invalid")
    try:
        loaded = Ed25519PrivateKey.from_private_bytes(private_key)
    except (TypeError, ValueError) as error:
        raise ReleaseValidationError("configured release private key is invalid") from error
    return ReleaseIdentity(key_id, loaded)


def validate_corpus_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a frozen 50-case Corpus Candidate Record before release assembly.

    The Corpus Candidate Record makes selection, contributor attestations,
    independent approvals, and curator decisions explicit. It does not sign or
    publish a Benchmark Corpus Release.
    """

    expected_fields = {
        "approvals",
        "attestations",
        "cases",
        "composition",
        "curator_confirmation",
        "independent_reviews",
        "release_version",
        "schema_version",
        "selection",
    }
    if not isinstance(candidate, Mapping) or set(candidate) != expected_fields:
        raise ReleaseValidationError("Corpus Candidate Record fields are invalid")
    if candidate.get("schema_version") != RELEASE_SCHEMA_VERSION:
        raise ReleaseValidationError("unsupported Corpus Candidate Record version")

    raw_cases = candidate.get("cases")
    if not isinstance(raw_cases, list):
        raise ReleaseValidationError("Corpus Candidate Record cases must be a list")
    cases = _validate_release_cases(raw_cases, candidate.get("release_version"))
    case_ids = [case["identity"]["case_id"] for case in cases]
    if case_ids != sorted(case_ids):
        raise ReleaseValidationError("Corpus Candidate Record cases require stable case_id order")

    composition = candidate.get("composition")
    if not isinstance(composition, Mapping):
        raise ReleaseValidationError("Corpus Candidate Record composition is invalid")
    selection, pool_cases = _validate_candidate_selection(
        candidate.get("selection"), set(case_ids), candidate.get("release_version")
    )
    pool_by_id = {
        entry["case"]["identity"]["case_id"]: entry
        for entry in selection["candidate_pool"]
    }
    selected_primary_creators = {
        case_id: pool_by_id[case_id]["primary_creators"] for case_id in case_ids
    }
    validated_composition = _validate_corpus_composition(
        cases, composition, selected_primary_creators
    )
    for case in cases:
        case_id = case["identity"]["case_id"]
        pool_entry = pool_by_id[case_id]
        if pool_entry["case"] != case:
            raise ReleaseValidationError(
                "selected Evaluation Case differs from its eligible pool record"
            )
        if pool_entry["category"] != validated_composition[case_id]:
            raise ReleaseValidationError(
                "selected case category differs from its Selection Slot evidence"
            )
    attestations = _validate_candidate_attestations(
        candidate.get("attestations"), pool_cases
    )
    independent_reviews = _validate_independent_reviews(
        candidate.get("independent_reviews"), pool_cases
    )
    approvals_value = candidate.get("approvals")
    if not isinstance(approvals_value, list):
        raise ReleaseValidationError("Corpus Candidate Record approvals must be a list")
    approvals = _validate_approvals(approvals_value, cases)
    curator_confirmation = _validate_curator_confirmation(
        candidate.get("curator_confirmation")
    )
    return {
        "approvals": approvals,
        "attestations": attestations,
        "cases": cases,
        "composition": validated_composition,
        "curator_confirmation": curator_confirmation,
        "independent_reviews": independent_reviews,
        "release_version": candidate["release_version"],
        "schema_version": RELEASE_SCHEMA_VERSION,
        "selection": selection,
    }


class TrustStore:
    """Offline trust keys plus append-only rotation and revocation records."""

    def __init__(self) -> None:
        self._keys: dict[str, Ed25519PublicKey] = {}
        self._revoked: set[str] = set()
        self._rotation_records: list[dict[str, Any]] = []
        self._revocation_records: list[dict[str, Any]] = []

    @property
    def rotation_records(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._rotation_records)

    @property
    def revocation_records(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._revocation_records)

    @classmethod
    def from_identities(cls, identities: Iterable[Mapping[str, Any]]) -> TrustStore:
        store = cls()
        for identity in identities:
            store._add_identity(identity)
        if not store._keys:
            raise ReleaseValidationError("trust store requires at least one public key")
        return store

    def is_trusted(self, key_id: str) -> bool:
        return key_id in self._keys and key_id not in self._revoked

    def verify(self, signature: Mapping[str, Any], value: Mapping[str, Any]) -> None:
        if signature.get("algorithm") != "Ed25519":
            raise ReleaseValidationError("unsupported signature algorithm")
        key_id = signature.get("key_id")
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise ReleaseValidationError("signature uses an untrusted release key")
        if key_id in self._revoked:
            raise ReleaseValidationError(f"release key is revoked: {key_id}")
        encoded = signature.get("signature")
        if not isinstance(encoded, str):
            raise ReleaseValidationError("signature value is missing")
        try:
            raw_signature = base64.b64decode(encoded, validate=True)
            self._keys[key_id].verify(raw_signature, canonical_json(value))
        except (ValueError, InvalidSignature) as error:
            raise ReleaseValidationError("signature verification failed") from error

    def apply_rotation(self, record: Mapping[str, Any]) -> None:
        body = _signed_record_body(record, "key_rotation", "signatures")
        old_key_id = body.get("old_key_id")
        new_identity = body.get("new_identity")
        signatures = record.get("signatures")
        if not isinstance(old_key_id, str) or not isinstance(new_identity, Mapping):
            raise ReleaseValidationError("key rotation record is incomplete")
        if not isinstance(signatures, list) or len(signatures) != 2:
            raise ReleaseValidationError("key rotation requires old and new signatures")
        by_key = {
            signature.get("key_id"): signature
            for signature in signatures
            if isinstance(signature, Mapping)
        }
        old_signature = by_key.get(old_key_id)
        new_key_id = new_identity.get("key_id")
        new_signature = by_key.get(new_key_id)
        if not isinstance(old_signature, Mapping) or not isinstance(new_signature, Mapping):
            raise ReleaseValidationError("key rotation signatures do not match its keys")
        self.verify(old_signature, body)
        candidate = TrustStore.from_identities([new_identity])
        candidate.verify(new_signature, body)
        self._add_identity(new_identity)
        self._rotation_records.append(copy.deepcopy(dict(record)))

    def apply_revocation(self, record: Mapping[str, Any]) -> None:
        body = _signed_record_body(record, "key_revocation", "signature")
        signature = record.get("signature")
        target_key_id = body.get("target_key_id")
        if not isinstance(signature, Mapping) or not isinstance(target_key_id, str):
            raise ReleaseValidationError("key revocation record is incomplete")
        self.verify(signature, body)
        if target_key_id not in self._keys:
            raise ReleaseValidationError("key revocation targets an unknown key")
        self._revoked.add(target_key_id)
        self._revocation_records.append(copy.deepcopy(dict(record)))

    def _add_identity(self, identity: Mapping[str, Any]) -> None:
        if set(identity) != {"algorithm", "key_id", "public_key"}:
            raise ReleaseValidationError("public trust identity has invalid fields")
        key_id = identity.get("key_id")
        if identity.get("algorithm") != "Ed25519" or not isinstance(
            key_id, str
        ) or not _KEY_ID.fullmatch(key_id):
            raise ReleaseValidationError("public trust identity is invalid")
        encoded = identity.get("public_key")
        try:
            raw = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
            key = Ed25519PublicKey.from_public_bytes(raw)
        except ValueError as error:
            raise ReleaseValidationError("public trust key is invalid") from error
        existing = self._keys.get(key_id)
        if existing is not None:
            existing_raw = existing.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            if existing_raw != raw:
                raise ReleaseValidationError("key_id cannot be reused for another key")
        self._keys[key_id] = key


def create_key_rotation(
    old_signer: ReleaseIdentity,
    new_signer: ReleaseIdentity,
    *,
    effective_at: datetime,
) -> dict[str, Any]:
    if old_signer.key_id == new_signer.key_id:
        raise ReleaseValidationError("key rotation requires a new key_id")
    body = {
        "effective_at": _timestamp(effective_at),
        "new_identity": new_signer.public_identity(),
        "old_key_id": old_signer.key_id,
        "record_type": "key_rotation",
        "schema_version": REGISTRY_SCHEMA_VERSION,
    }
    return {**body, "signatures": [old_signer.sign(body), new_signer.sign(body)]}


def create_key_revocation(
    *,
    target_key_id: str,
    authority_signer: ReleaseIdentity,
    effective_at: datetime,
    reason: str,
) -> dict[str, Any]:
    body = {
        "effective_at": _timestamp(effective_at),
        "reason": _required_text(reason, "key revocation reason"),
        "record_type": "key_revocation",
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "target_key_id": target_key_id,
    }
    return {**body, "signature": authority_signer.sign(body)}


def assemble_release(
    destination: Path,
    *,
    version: str,
    cases: Iterable[Mapping[str, Any]],
    composition: Mapping[str, str],
    artifacts: Mapping[str, bytes],
    notice_bundle: Mapping[str, bytes],
    approvals: Iterable[Mapping[str, Any]],
    contracts: Mapping[str, str],
    released_at: datetime,
    release_channel: str,
    signer: ReleaseIdentity,
    replaces: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Deterministically assemble and atomically publish a signed release directory."""

    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ReleaseValidationError("Benchmark Corpus version must be semantic")
    if destination.exists():
        raise ReleaseValidationError("published release destination is immutable")
    validated_cases = _validate_release_cases(list(cases), version)
    validated_composition = _validate_corpus_composition(validated_cases, composition)
    validated_approvals = _validate_approvals(list(approvals), validated_cases)
    notices = _validate_notice_bundle(notice_bundle)
    extra_artifacts = _validate_extra_artifacts(artifacts)
    validated_contracts = _validate_contracts(contracts)
    replacement = _validate_replacement(replaces, version)

    corpus = {"cases": validated_cases, "schema_version": RELEASE_SCHEMA_VERSION}
    files: dict[str, bytes] = {"corpus/cases.json": canonical_json(corpus) + b"\n"}
    files.update({f"notices/{name}": content for name, content in notices.items()})
    files.update(extra_artifacts)
    inventory = [_artifact_entry(path, content) for path, content in sorted(files.items())]
    notice_inventory = [item for item in inventory if item["path"].startswith("notices/")]
    case_entries = [
        {
            "case_id": case["identity"]["case_id"],
            "revision": case["identity"]["revision"],
            "sha256": sha256_bytes(canonical_json(case)),
        }
        for case in validated_cases
    ]
    manifest_body: dict[str, Any] = {
        "approvals": validated_approvals,
        "artifacts": inventory,
        "cases": case_entries,
        "contracts": validated_contracts,
        "composition": validated_composition,
        "release_channel": _required_text(release_channel, "release channel"),
        "release_notice_bundle": {
            "path": "notices",
            "sha256": sha256_bytes(canonical_json(notice_inventory)),
        },
        "released_at": _timestamp(released_at),
        "replaces": replacement,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "signer_key_id": signer.key_id,
        "version": version,
    }
    manifest = {
        **manifest_body,
        "release_digest": sha256_bytes(canonical_json(manifest_body)),
    }
    signature = signer.sign(manifest)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.partial-", dir=destination.parent
    ) as temporary:
        temporary_path = Path(temporary)
        for relative_path, content in files.items():
            path = temporary_path / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (temporary_path / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
        (temporary_path / "manifest.signature.json").write_bytes(
            canonical_json(signature) + b"\n"
        )
        temporary_path.rename(destination)
    return manifest


def assemble_and_publish_release(
    destination: Path,
    registry: CorpusRegistry,
    *,
    version: str,
    cases: Iterable[Mapping[str, Any]],
    composition: Mapping[str, str],
    artifacts: Mapping[str, bytes],
    notice_bundle: Mapping[str, bytes],
    approvals: Iterable[Mapping[str, Any]],
    contracts: Mapping[str, str],
    released_at: datetime,
    release_channel: str,
    signer: ReleaseIdentity,
    publication_reason: str,
    publication_authority: str,
    replaces: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish assets and initial registry state through one fail-closed operation."""

    if destination.exists():
        raise ReleaseValidationError("published release destination is immutable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.publication-", dir=destination.parent
    ) as temporary:
        staged_release = Path(temporary) / "release"
        manifest = assemble_release(
            staged_release,
            version=version,
            cases=cases,
            composition=composition,
            artifacts=artifacts,
            notice_bundle=notice_bundle,
            approvals=approvals,
            contracts=contracts,
            released_at=released_at,
            release_channel=release_channel,
            signer=signer,
            replaces=replaces,
        )
        status_record = registry.publish_release(
            staged_release,
            effective_at=released_at,
            reason=publication_reason,
            authority=publication_authority,
            signer=signer,
        )
        try:
            staged_release.rename(destination)
        except Exception:
            registry._rollback_initial_publication(status_record)
            raise
    return manifest, status_record


def _verify_release_bundle(
    release_path: Path, trust_store: TrustStore
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify a complete release using only its bundled artifacts and trust key."""

    if release_path.is_symlink() or not release_path.is_dir():
        raise ReleaseValidationError("Benchmark Corpus Release must be a real directory")
    manifest = _read_canonical_object(release_path / "manifest.json", "manifest")
    signature = _read_canonical_object(
        release_path / "manifest.signature.json", "manifest signature"
    )
    trust_store.verify(signature, manifest)
    if manifest.get("schema_version") != RELEASE_SCHEMA_VERSION:
        raise ReleaseValidationError("unsupported Corpus Release Manifest version")
    expected_signer = manifest.get("signer_key_id")
    if signature.get("key_id") != expected_signer:
        raise ReleaseValidationError("manifest signature key does not match signer identity")
    release_digest = manifest.get("release_digest")
    body = {key: value for key, value in manifest.items() if key != "release_digest"}
    if release_digest != sha256_bytes(canonical_json(body)):
        raise ReleaseValidationError("Corpus Release Manifest digest is invalid")
    inventory = manifest.get("artifacts")
    if not isinstance(inventory, list) or not inventory:
        raise ReleaseValidationError("Corpus Release Manifest has no artifacts")
    expected_paths: set[str] = set()
    for item in inventory:
        if not isinstance(item, Mapping):
            raise ReleaseValidationError("Corpus Release Manifest artifact is invalid")
        relative_path = _safe_relative_path(item.get("path"), "manifest artifact")
        expected_paths.add(relative_path)
        path = release_path / relative_path
        if not path.is_file() or path.is_symlink():
            raise ReleaseValidationError(f"missing artifact: {relative_path}")
        content = path.read_bytes()
        if item.get("byte_length") != len(content) or item.get("sha256") != sha256_bytes(
            content
        ):
            raise ReleaseValidationError(f"artifact hash or length mismatch: {relative_path}")
    actual_paths = {
        path.relative_to(release_path).as_posix()
        for path in release_path.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "manifest.signature.json"}
    }
    if actual_paths != expected_paths:
        raise ReleaseValidationError("release contains unmanifested or missing artifacts")
    corpus = _read_canonical_object(release_path / "corpus/cases.json", "corpus artifact")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != 50:
        raise ReleaseValidationError("Benchmark Corpus Release must contain exactly 50 cases")
    validated_cases = _validate_release_cases(cases, manifest.get("version"))
    composition = manifest.get("composition")
    if not isinstance(composition, Mapping) or composition != _validate_corpus_composition(
        validated_cases, composition
    ):
        raise ReleaseValidationError("Corpus Release Manifest composition is invalid")
    expected_cases = [
        {
            "case_id": case.get("identity", {}).get("case_id") if isinstance(case, Mapping) else None,
            "revision": case.get("identity", {}).get("revision") if isinstance(case, Mapping) else None,
            "sha256": sha256_bytes(canonical_json(case)),
        }
        for case in cases
    ]
    if manifest.get("cases") != expected_cases:
        raise ReleaseValidationError("manifest case revisions or hashes do not match corpus")
    raw_approvals = manifest.get("approvals")
    if not isinstance(raw_approvals, list) or not all(
        isinstance(approval, Mapping) for approval in raw_approvals
    ):
        raise ReleaseValidationError("Corpus Release Manifest approvals are invalid")
    checked_approvals = _validate_approvals(raw_approvals, validated_cases)
    if raw_approvals != checked_approvals:
        raise ReleaseValidationError("Corpus Release Manifest approvals are invalid")
    if not isinstance(manifest.get("contracts"), Mapping) or manifest.get(
        "contracts"
    ) != _validate_contracts(manifest["contracts"]):
        raise ReleaseValidationError("Corpus Release Manifest contracts are invalid")
    _required_text(manifest.get("release_channel"), "release channel")
    _parse_timestamp(manifest.get("released_at"), "release timestamp")
    _validate_replacement(manifest.get("replaces"), manifest["version"])
    notice_entries = [item for item in inventory if item.get("path", "").startswith("notices/")]
    if manifest.get("release_notice_bundle") != {
        "path": "notices",
        "sha256": sha256_bytes(canonical_json(notice_entries)),
    }:
        raise ReleaseValidationError("Release Notice Bundle digest is invalid")
    _validate_notice_bundle(
        {
            path.removeprefix("notices/"): (release_path / path).read_bytes()
            for path in expected_paths
            if path.startswith("notices/")
        }
    )
    return copy.deepcopy(manifest), validated_cases


def verify_release(release_path: Path, trust_store: TrustStore) -> dict[str, Any]:
    """Verify a complete release using only its artifacts and offline trust key."""

    manifest, _ = _verify_release_bundle(release_path, trust_store)
    return manifest


def load_verified_release_cases(
    release_path: Path,
    trust_store: TrustStore,
    *,
    expected_release_digest: str | None = None,
) -> list[dict[str, Any]]:
    """Load only Evaluation Cases whose complete signed release verifies offline."""

    manifest, validated = _verify_release_bundle(release_path, trust_store)
    if expected_release_digest is not None and manifest["release_digest"] != (
        expected_release_digest
    ):
        raise ReleaseValidationError("verified release changed before execution")
    return [
        {key: value for key, value in case.items() if key != "computed"}
        for case in validated
    ]


class CorpusRegistry:
    """In-memory builder for a signed, hash-chained append-only corpus registry."""

    def __init__(self, trust_store: TrustStore) -> None:
        self.trust_store = trust_store
        self._records: list[dict[str, Any]] = []

    @classmethod
    def from_snapshot(
        cls, snapshot: Mapping[str, Any], trust_store: TrustStore
    ) -> CorpusRegistry:
        registry = cls(trust_store)
        registry._records = _verify_registry_snapshot(snapshot, trust_store)
        return registry

    @property
    def records(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._records)

    def status(self, version: str, release_digest: str) -> str | None:
        return _current_status(self._records, version, release_digest)

    def publish_release(
        self,
        release_path: Path,
        *,
        effective_at: datetime,
        reason: str,
        authority: str,
        signer: ReleaseIdentity,
    ) -> dict[str, Any]:
        """Append initial publication only after assets and manifest agree offline."""

        manifest = verify_release(release_path, self.trust_store)
        return self.append_status(
            version=manifest["version"],
            release_digest=manifest["release_digest"],
            new_status="published",
            effective_at=effective_at,
            reason=reason,
            authority=authority,
            signer=signer,
            _verified_initial=True,
        )

    def _rollback_initial_publication(self, record: Mapping[str, Any]) -> None:
        if not self._records or self._records[-1] != record or record.get(
            "prior_status"
        ) is not None:
            raise ReleaseValidationError("cannot roll back unrelated registry state")
        self._records.pop()

    def append_status(
        self,
        *,
        version: str,
        release_digest: str,
        new_status: str,
        effective_at: datetime,
        reason: str,
        authority: str,
        signer: ReleaseIdentity,
        affected_case_ids: Iterable[str] = (),
        replacement_version: str | None = None,
        suspension_expires_at: datetime | None = None,
        _verified_initial: bool = False,
    ) -> dict[str, Any]:
        prior_status = self.status(version, release_digest)
        if prior_status is None and not _verified_initial:
            raise ReleaseValidationError(
                "initial publication requires verified release assets"
            )
        _validate_transition(prior_status, new_status)
        if self._records:
            previous_time = _parse_timestamp(
                self._records[-1].get("effective_at"), "status effective_at"
            )
            if effective_at.astimezone(timezone.utc) < previous_time:
                raise ReleaseValidationError("Corpus Status Records must be chronological")
        affected = sorted(set(affected_case_ids))
        if any(not isinstance(case_id, str) or not case_id for case_id in affected):
            raise ReleaseValidationError("affected case identities are invalid")
        if replacement_version is not None and not _SEMVER.fullmatch(replacement_version):
            raise ReleaseValidationError("replacement version is invalid")
        suspension_deadline = None
        if new_status == "suspended":
            if suspension_expires_at is None or suspension_expires_at <= effective_at:
                raise ReleaseValidationError("suspension requires a future review deadline")
            suspension_deadline = _timestamp(suspension_expires_at)
        elif suspension_expires_at is not None:
            raise ReleaseValidationError("only suspension records may have a review deadline")
        body: dict[str, Any] = {
            "affected_case_ids": affected,
            "authority": _required_text(authority, "status decision authority"),
            "effective_at": _timestamp(effective_at),
            "new_status": new_status,
            "previous_record_digest": (
                sha256_bytes(canonical_json(self._records[-1])) if self._records else None
            ),
            "prior_status": prior_status,
            "reason": _required_text(reason, "status reason"),
            "record_type": "corpus_status",
            "release_digest": _sha256_text(release_digest, "release digest"),
            "replacement_version": replacement_version,
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "sequence": len(self._records),
            "suspension_expires_at": suspension_deadline,
            "version": version,
        }
        signature = signer.sign(body)
        record: dict[str, Any] = {**body, "signature": signature}
        self.trust_store.verify(signature, body)
        self._records.append(record)
        return copy.deepcopy(record)

    def snapshot(self, generated_at: datetime) -> dict[str, Any]:
        body = {
            "generated_at": _timestamp(generated_at),
            "records": copy.deepcopy(self._records),
            "schema_version": REGISTRY_SCHEMA_VERSION,
        }
        return {**body, "identity": sha256_bytes(canonical_json(body))}


def resolve_release_for_run(
    release_path: Path,
    trust_store: TrustStore,
    *,
    registry_snapshot: Mapping[str, Any],
    checked_at: datetime,
    refresh_registry: Callable[[], Mapping[str, Any]] | None = None,
    max_snapshot_age: timedelta = timedelta(days=1),
    explicitly_pinned: bool = False,
    audit_override_reason: str | None = None,
) -> dict[str, Any]:
    """Verify registry state and return immutable metadata for a new Run Record."""

    manifest = verify_release(release_path, trust_store)
    if checked_at.tzinfo is None:
        raise ReleaseValidationError("registry check time must be timezone-aware")
    if max_snapshot_age < timedelta():
        raise ReleaseValidationError("maximum registry snapshot age cannot be negative")
    refreshed_online = refresh_registry is not None
    if refresh_registry is not None:
        try:
            snapshot = copy.deepcopy(dict(refresh_registry()))
        except Exception as error:
            raise ReleaseValidationError("online registry refresh failed") from error
    else:
        snapshot = copy.deepcopy(dict(registry_snapshot))
    records = _verify_registry_snapshot(snapshot, trust_store)
    status = _current_status(records, manifest["version"], manifest["release_digest"])
    if status is None:
        raise ReleaseValidationError("release is absent from the verified registry")
    generated_at = _parse_timestamp(snapshot.get("generated_at"), "registry generated_at")
    if generated_at > checked_at.astimezone(timezone.utc):
        raise ReleaseValidationError("registry snapshot cannot be from the future")
    age = max(timedelta(), checked_at.astimezone(timezone.utc) - generated_at)
    warnings: list[str] = []
    if not refreshed_online:
        warnings.append("Corpus registry status was not refreshed online")
    if age > max_snapshot_age:
        warnings.append("Verified Corpus registry snapshot is stale")

    override = None
    if status in {"suspended", "withdrawn"}:
        if audit_override_reason is None or not audit_override_reason.strip():
            raise ReleaseValidationError(f"{status} release is blocked for ordinary runs")
        override = {
            "permanent": True,
            "reason": audit_override_reason.strip(),
            "status": status,
        }
        warnings.append(f"Audit-only override uses a {status} Benchmark Corpus Release")
    elif status == "superseded":
        if not explicitly_pinned:
            raise ReleaseValidationError("superseded release requires an explicit version pin")
        warnings.append("Explicitly pinned Benchmark Corpus Release is superseded")

    return validate_release_resolution({
        "audit_override": override,
        "registry_snapshot": {
            "age_seconds": int(age.total_seconds()),
            "generated_at": snapshot["generated_at"],
            "identity": snapshot["identity"],
            "refreshed_online": refreshed_online,
        },
        "release": {
            "release_digest": manifest["release_digest"],
            "status": status,
            "version": manifest["version"],
        },
        "warnings": warnings,
    })


def validate_release_resolution(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on corpus admission metadata before it enters a Run Record."""

    if set(value) != {"audit_override", "registry_snapshot", "release", "warnings"}:
        raise ReleaseValidationError("release resolution fields are invalid")
    release = value.get("release")
    snapshot = value.get("registry_snapshot")
    warnings = value.get("warnings")
    if not isinstance(release, Mapping) or set(release) != {
        "release_digest", "status", "version"
    }:
        raise ReleaseValidationError("release resolution identity is invalid")
    _sha256_text(release.get("release_digest"), "release digest")
    status = release.get("status")
    if status not in _STATUSES:
        raise ReleaseValidationError("release resolution status is invalid")
    version = release.get("version")
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ReleaseValidationError("release resolution version is invalid")
    if not isinstance(snapshot, Mapping) or set(snapshot) != {
        "age_seconds", "generated_at", "identity", "refreshed_online"
    }:
        raise ReleaseValidationError("release resolution registry snapshot is invalid")
    age = snapshot.get("age_seconds")
    if not isinstance(age, int) or isinstance(age, bool) or age < 0:
        raise ReleaseValidationError("registry snapshot age is invalid")
    _parse_timestamp(snapshot.get("generated_at"), "registry generated_at")
    _sha256_text(snapshot.get("identity"), "registry snapshot identity")
    if not isinstance(snapshot.get("refreshed_online"), bool):
        raise ReleaseValidationError("registry refresh marker is invalid")
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ReleaseValidationError("release resolution warnings are invalid")
    override = value.get("audit_override")
    if override is not None:
        if not isinstance(override, Mapping) or set(override) != {
            "permanent", "reason", "status"
        }:
            raise ReleaseValidationError("audit-only override is invalid")
        if override.get("permanent") is not True or override.get("status") != status:
            raise ReleaseValidationError("audit-only override marker is invalid")
        _required_text(override.get("reason"), "audit-only override reason")
        if status not in {"suspended", "withdrawn"}:
            raise ReleaseValidationError("audit-only override is not allowed for release status")
    elif status in {"suspended", "withdrawn"}:
        raise ReleaseValidationError("non-current release requires an audit-only override")
    return copy.deepcopy(dict(value))


def _verify_registry_snapshot(
    snapshot: Mapping[str, Any], trust_store: TrustStore
) -> list[dict[str, Any]]:
    if snapshot.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ReleaseValidationError("unsupported corpus registry version")
    records = snapshot.get("records")
    if not isinstance(records, list):
        raise ReleaseValidationError("corpus registry records must be a list")
    body = {key: value for key, value in snapshot.items() if key != "identity"}
    if set(body) != {"generated_at", "records", "schema_version"} or snapshot.get(
        "identity"
    ) != sha256_bytes(canonical_json(body)):
        raise ReleaseValidationError("corpus registry snapshot identity is invalid")
    _parse_timestamp(snapshot.get("generated_at"), "registry generated_at")
    statuses: dict[tuple[str, str], str] = {}
    previous_digest = None
    validated: list[dict[str, Any]] = []
    for sequence, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise ReleaseValidationError("Corpus Status Record must be an object")
        record = copy.deepcopy(dict(raw_record))
        body = _signed_record_body(record, "corpus_status", "signature")
        expected_fields = {
            "affected_case_ids", "authority", "effective_at", "new_status",
            "previous_record_digest", "prior_status", "reason", "record_type",
            "release_digest", "replacement_version", "schema_version", "sequence",
            "suspension_expires_at", "version",
        }
        if set(body) != expected_fields:
            raise ReleaseValidationError("Corpus Status Record fields are invalid")
        signature = record.get("signature")
        if not isinstance(signature, Mapping):
            raise ReleaseValidationError("Corpus Status Record has no signature")
        trust_store.verify(signature, body)
        if body.get("sequence") != sequence or body.get("previous_record_digest") != previous_digest:
            raise ReleaseValidationError("corpus registry append-only chain is invalid")
        version = body.get("version")
        digest = body.get("release_digest")
        if not isinstance(version, str) or not _SEMVER.fullmatch(version):
            raise ReleaseValidationError("Corpus Status Record release identity is invalid")
        checked_digest = _sha256_text(digest, "Corpus Status Record release digest")
        effective_at = _parse_timestamp(body.get("effective_at"), "status effective_at")
        if validated:
            prior_time = _parse_timestamp(validated[-1]["effective_at"], "status effective_at")
            if effective_at < prior_time:
                raise ReleaseValidationError("Corpus Status Records must be chronological")
        _required_text(body.get("reason"), "status reason")
        _required_text(body.get("authority"), "status decision authority")
        affected = body.get("affected_case_ids")
        if not isinstance(affected, list) or affected != sorted(set(affected)) or any(
            not isinstance(case_id, str) or not case_id for case_id in affected
        ):
            raise ReleaseValidationError("Corpus Status Record affected cases are invalid")
        replacement = body.get("replacement_version")
        if replacement is not None and (
            not isinstance(replacement, str) or not _SEMVER.fullmatch(replacement)
        ):
            raise ReleaseValidationError("Corpus Status Record replacement is invalid")
        key = (version, checked_digest)
        prior = statuses.get(key)
        if body.get("prior_status") != prior:
            raise ReleaseValidationError("Corpus Status Record prior status is invalid")
        new_status = body.get("new_status")
        if not isinstance(new_status, str):
            raise ReleaseValidationError("Corpus Status Record status is invalid")
        _validate_transition(prior, new_status)
        suspension_deadline = body.get("suspension_expires_at")
        if new_status == "suspended":
            deadline = _parse_timestamp(suspension_deadline, "suspension review deadline")
            if deadline <= effective_at:
                raise ReleaseValidationError("suspension review deadline must be in the future")
        elif suspension_deadline is not None:
            raise ReleaseValidationError("non-suspension record has a review deadline")
        statuses[key] = new_status
        previous_digest = sha256_bytes(canonical_json(record))
        validated.append(record)
    generated_at = _parse_timestamp(snapshot.get("generated_at"), "registry generated_at")
    if validated and generated_at < _parse_timestamp(
        validated[-1]["effective_at"], "status effective_at"
    ):
        raise ReleaseValidationError("registry snapshot predates its latest status record")
    return validated


def _validate_release_cases(
    cases: list[Mapping[str, Any]], version: Any
) -> list[dict[str, Any]]:
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ReleaseValidationError("Benchmark Corpus version must be semantic")
    if len(cases) != 50:
        raise ReleaseValidationError("Benchmark Corpus Release must contain exactly 50 cases")
    validated = []
    try:
        validated = [
            validate_evaluation_case(
                {key: value for key, value in case.items() if key != "computed"}
            )
            for case in cases
        ]
    except EvaluationCaseValidationError as error:
        raise ReleaseValidationError(f"Evaluation Case is not releaseable: {error}") from error
    if any(
        "computed" in case and dict(case) != checked
        for case, checked in zip(cases, validated, strict=True)
    ):
        raise ReleaseValidationError("Evaluation Case computed fields are not canonical")
    case_ids = [case["identity"]["case_id"] for case in validated]
    if len(set(case_ids)) != len(case_ids):
        raise ReleaseValidationError("Benchmark Corpus case identities must be unique")
    source_works = [
        (
            case["source_work"]["canonical_url"],
            case["source_work"]["edition_or_version"],
        )
        for case in validated
    ]
    if len(set(source_works)) != len(source_works):
        raise ReleaseValidationError("Benchmark Corpus requires 50 distinct Source Works")
    if any(version not in case["rights"]["release_versions"] for case in validated):
        raise ReleaseValidationError("case Rights Record does not name this release version")
    return validated


def _validate_corpus_composition(
    cases: Sequence[Mapping[str, Any]],
    categories: Mapping[str, str],
    primary_creators: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    case_ids = [case["identity"]["case_id"] for case in cases]
    if set(categories) != set(case_ids) or any(
        not isinstance(value, str) or not value.strip() for value in categories.values()
    ):
        raise ReleaseValidationError("composition categories must cover every Evaluation Case")
    normalized = {case_id: categories[case_id].strip() for case_id in sorted(case_ids)}

    expected_cells = {
        ("book", "continuation"): 4,
        ("book", "gap_fill"): 4,
        ("book", "located_quotation"): 5,
        ("book", "constrained_reconstruction"): 4,
        ("lyrics", "continuation"): 4,
        ("lyrics", "gap_fill"): 4,
        ("lyrics", "located_quotation"): 4,
        ("lyrics", "constrained_reconstruction"): 5,
        ("code", "continuation"): 4,
        ("code", "gap_fill"): 4,
        ("code", "located_quotation"): 4,
        ("code", "constrained_reconstruction"): 4,
    }
    cells = Counter(
        (case["classification"]["domain"], case["classification"]["attack_vector"])
        for case in cases
    )
    if cells != Counter(expected_cells):
        raise ReleaseValidationError("Benchmark Corpus domain and Attack Vector matrix is invalid")

    primary_sources = Counter(
        principal
        for case in cases
        for principal in (
            [case["source_work"]["publisher_or_project"]]
            if case["classification"]["domain"] == "code"
            else (
                primary_creators[case["identity"]["case_id"]]
                if primary_creators is not None
                else case["source_work"]["creators"]
            )
        )
    )
    if any(count > 2 for count in primary_sources.values()):
        raise ReleaseValidationError(
            "a primary creator or code repository owner exceeds the Source Work concentration limit"
        )

    for domain in ("book", "lyrics"):
        eras: Counter[str] = Counter()
        for case in cases:
            if case["classification"]["domain"] != domain:
                continue
            try:
                year = int(case["source_work"]["publication_date"][:4])
            except (TypeError, ValueError) as error:
                raise ReleaseValidationError("Source Work publication date is invalid") from error
            era = "pre_1950" if year < 1950 else "1950_1999" if year < 2000 else "2000_onward"
            eras[era] += 1
        if eras != Counter({"pre_1950": 5, "1950_1999": 6, "2000_onward": 6}):
            raise ReleaseValidationError(f"Benchmark Corpus {domain} era allocation is invalid")
        if any(
            case["grading"]["source_language"] != "en"
            for case in cases
            if case["classification"]["domain"] == domain
        ):
            raise ReleaseValidationError(f"Benchmark Corpus {domain} cases must be English")

    book_categories = Counter(
        normalized[case["identity"]["case_id"]]
        for case in cases
        if case["classification"]["domain"] == "book"
    )
    fiction = sum(count for name, count in book_categories.items() if name.startswith("fiction:"))
    nonfiction = sum(
        count for name, count in book_categories.items() if name.startswith("nonfiction:")
    )
    if fiction < 8 or nonfiction < 6 or fiction + nonfiction != 17 or any(
        count > 4 for count in book_categories.values()
    ):
        raise ReleaseValidationError("Benchmark Corpus book category allocation is invalid")

    lyric_genres = Counter(
        normalized[case["identity"]["case_id"]]
        for case in cases
        if case["classification"]["domain"] == "lyrics"
    )
    if len(lyric_genres) < 6 or any(count > 3 for count in lyric_genres.values()):
        raise ReleaseValidationError("Benchmark Corpus lyric genre allocation is invalid")

    code_languages = Counter(
        case["grading"]["source_language"]
        for case in cases
        if case["classification"]["domain"] == "code"
    )
    if code_languages != Counter({"python": 4, "javascript": 4, "java": 4, "c": 4}):
        raise ReleaseValidationError("Benchmark Corpus code language allocation is invalid")
    for language in code_languages:
        vectors = Counter(
            case["classification"]["attack_vector"]
            for case in cases
            if case["classification"]["domain"] == "code"
            and case["grading"]["source_language"] == language
        )
        if vectors != Counter({vector: 1 for vector in (
            "continuation", "gap_fill", "located_quotation", "constrained_reconstruction"
        )}):
            raise ReleaseValidationError("each code language must cover every Attack Vector")

    modifier_counts: Counter[str] = Counter()
    unmodified_cells: Counter[tuple[str, str]] = Counter()
    modifier_cases: dict[str, list[Mapping[str, Any]]] = {}
    unmodified = 0
    for case in cases:
        modifiers = case["classification"]["prompt_modifiers"]
        if not modifiers:
            unmodified += 1
            unmodified_cells[(
                case["classification"]["domain"],
                case["classification"]["attack_vector"],
            )] += 1
            continue
        modifier = modifiers[0]
        modifier_counts[modifier] += 1
        modifier_cases.setdefault(modifier, []).append(case)
    expected_modifiers = {
        "role_play", "claimed_authority", "benign_purpose", "urgency", "output_format"
    }
    if unmodified != 25 or modifier_counts != Counter({name: 5 for name in expected_modifiers}):
        raise ReleaseValidationError("Benchmark Corpus Prompt Modifier allocation is invalid")
    if set(unmodified_cells) != set(expected_cells) or (
        max(unmodified_cells.values()) - min(unmodified_cells.values()) > 1
    ):
        raise ReleaseValidationError("unmodified cases are not evenly distributed")
    for modifier, selected in modifier_cases.items():
        if {case["classification"]["domain"] for case in selected} != {"book", "lyrics", "code"}:
            raise ReleaseValidationError(f"Prompt Modifier lacks domain coverage: {modifier}")
        if {case["classification"]["attack_vector"] for case in selected} != {
            "continuation", "gap_fill", "located_quotation", "constrained_reconstruction"
        }:
            raise ReleaseValidationError(f"Prompt Modifier lacks Attack Vector coverage: {modifier}")

    eligible_hashes = [case["computed"]["eligible_sha256"] for case in cases]
    if len(set(eligible_hashes)) != len(eligible_hashes):
        raise ReleaseValidationError("Benchmark Corpus contains duplicate Eligible Reference Spans")
    from .grading import has_decisive_match

    combined_prompts = "\n\nRR_PROMPT_BOUNDARY\n\n".join(
        case["prompt"]["text"] for case in cases
    )
    for case in cases:
        lexer = case["grading"]["lexer"]
        lexer_name = lexer["name"] if isinstance(lexer, Mapping) else None
        if has_decisive_match(
            case["classification"]["domain"],
            case["target"]["eligible"],
            combined_prompts,
            lexer_name=lexer_name,
        ):
            raise ReleaseValidationError("Benchmark Corpus has cross-prompt decisive contamination")
    return normalized


def _validate_approvals(
    approvals: list[Mapping[str, Any]], cases: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    expected = {"release_curator", "rights_reviewer"}
    if len(approvals) != 2 or {item.get("role") for item in approvals} != expected:
        raise ReleaseValidationError("release requires curator and rights reviewer approvals")
    normalized = []
    for item in approvals:
        if set(item) != {"identity", "reference", "role"}:
            raise ReleaseValidationError("release approval fields are invalid")
        normalized.append(
            {
                "identity": _required_text(item.get("identity"), "approval identity"),
                "reference": _required_text(item.get("reference"), "approval reference"),
                "role": str(item["role"]),
            }
        )
    identities = {item["identity"] for item in normalized}
    if len(identities) != 2:
        raise ReleaseValidationError("release approvers must be different people")
    authors = {case["review"]["author"] for case in cases}
    if identities & authors:
        raise ReleaseValidationError("release approvers cannot author included cases")
    return sorted(normalized, key=lambda item: item["role"])


def _validate_candidate_selection(
    value: Any, selected_case_ids: set[str], release_version: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fields = {
        "algorithm",
        "candidate_pool",
        "exclusions",
        "frozen_at",
        "seed",
        "target_system_feedback_used",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseValidationError("Corpus Candidate Record selection fields are invalid")
    if value.get("algorithm") != "sha256-seed-case-id-v1":
        raise ReleaseValidationError("Benchmark Corpus selection algorithm is unsupported")
    seed = _required_text(value.get("seed"), "Benchmark Corpus selection seed")
    frozen_at = _timestamp(
        _parse_timestamp(value.get("frozen_at"), "candidate freeze timestamp")
    )
    if value.get("target_system_feedback_used") is not False:
        raise ReleaseValidationError(
            "Benchmark Corpus selection must not use Target System feedback"
        )
    raw_pool = value.get("candidate_pool")
    if not isinstance(raw_pool, list) or not raw_pool:
        raise ReleaseValidationError("Corpus Candidate Record pool must be non-empty")

    allowed_reasons = {
        "exploratory_target_testing",
        "grader_threshold_selection",
        "prompt_development",
        "rights_ineligible",
        "validation_failed",
        "withdrawn",
    }
    pool: list[dict[str, Any]] = []
    pool_cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    eligible_by_slot: dict[str, list[str]] = {}
    slot_definitions: dict[str, dict[str, Any]] = {}
    source_works: set[tuple[str, str]] = set()
    for item in raw_pool:
        if not isinstance(item, Mapping) or set(item) != {
            "case",
            "category",
            "category_evidence",
            "creator_role_evidence",
            "selection_slot",
        }:
            raise ReleaseValidationError("Corpus Candidate Record pool entry is invalid")
        case = _validate_pool_case(item.get("case"), release_version)
        case_id = case["identity"]["case_id"]
        if case_id in seen_ids:
            raise ReleaseValidationError("Corpus Candidate Record pool IDs must be unique")
        seen_ids.add(case_id)
        source_identity = (
            case["source_work"]["canonical_url"],
            case["source_work"]["edition_or_version"],
        )
        if source_identity in source_works:
            raise ReleaseValidationError("candidate pool Source Works must be distinct")
        source_works.add(source_identity)
        category = _required_text(item.get("category"), "candidate category")
        evidence = item.get("category_evidence")
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "explanation", "reference"
        }:
            raise ReleaseValidationError("candidate category evidence is invalid")
        category_evidence = {
            "explanation": _required_text(
                evidence.get("explanation"), "candidate category evidence explanation"
            ),
            "reference": _required_text(
                evidence.get("reference"), "candidate category evidence reference"
            ),
        }
        creator_role_evidence, normalized_primary_creators = (
            _validate_creator_role_evidence(item.get("creator_role_evidence"), case)
        )
        slot = _validate_selection_slot(item.get("selection_slot"), case, category)
        slot_id = slot["slot_id"]
        prior_slot = slot_definitions.get(slot_id)
        if prior_slot is not None and prior_slot != slot:
            raise ReleaseValidationError("Selection Slot criteria conflict")
        slot_definitions[slot_id] = slot
        eligible_by_slot.setdefault(slot_id, []).append(case_id)
        pool_cases.append(case)
        pool.append(
            {
                "case": case,
                "category": category,
                "category_evidence": category_evidence,
                "creator_role_evidence": creator_role_evidence,
                "primary_creators": normalized_primary_creators,
                "selection_slot": slot,
            }
        )

    exclusions = _validate_candidate_exclusions(value.get("exclusions"), allowed_reasons)
    excluded_ids = {item["case_id"] for item in exclusions}
    if seen_ids & excluded_ids:
        raise ReleaseValidationError("a candidate cannot be both eligible and excluded")
    if not selected_case_ids <= seen_ids:
        raise ReleaseValidationError("selected case is absent from the eligible candidate pool")
    if sum(slot["quota"] for slot in slot_definitions.values()) != 50 or any(
        len(eligible_by_slot[slot_id]) < slot["quota"]
        for slot_id, slot in slot_definitions.items()
    ):
        raise ReleaseValidationError(
            "Corpus Candidate Record slot quotas must allocate 50 eligible cases"
        )
    winners = {
        case_id
        for slot_id, case_ids in eligible_by_slot.items()
        for case_id in sorted(
            case_ids,
            key=lambda candidate_id: hashlib.sha256(
                f"{seed}\0{candidate_id}".encode("utf-8")
            ).hexdigest(),
        )[: slot_definitions[slot_id]["quota"]]
    }
    if winners != selected_case_ids:
        raise ReleaseValidationError("Benchmark Corpus deterministic selection is not reproducible")
    return {
        "algorithm": "sha256-seed-case-id-v1",
        "candidate_pool": sorted(
            pool, key=lambda item: item["case"]["identity"]["case_id"]
        ),
        "exclusions": exclusions,
        "frozen_at": frozen_at,
        "seed": seed,
        "target_system_feedback_used": False,
    }, pool_cases


def _validate_pool_case(value: Any, release_version: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseValidationError("eligible candidate case must be an object")
    try:
        validated = validate_evaluation_case(
            {key: item for key, item in value.items() if key != "computed"}
        )
    except EvaluationCaseValidationError as error:
        raise ReleaseValidationError(f"eligible candidate case is invalid: {error}") from error
    if "computed" in value and dict(value) != validated:
        raise ReleaseValidationError("eligible candidate computed fields are not canonical")
    if release_version not in validated["rights"]["release_versions"]:
        raise ReleaseValidationError("eligible candidate Rights Record omits release version")
    return validated


def _validate_creator_role_evidence(
    value: Any, case: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    creators = case["source_work"]["creators"]
    if case["classification"]["domain"] == "code":
        if value != {}:
            raise ReleaseValidationError("code candidates must not classify creator roles")
        return {}, []
    if not isinstance(value, Mapping) or set(value) != set(creators):
        raise ReleaseValidationError(
            "creator role evidence must classify every Source Work credit"
        )
    normalized: dict[str, dict[str, Any]] = {}
    primary_creators: list[str] = []
    for creator in creators:
        evidence = value[creator]
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "is_primary",
            "reference",
        } or not isinstance(evidence.get("is_primary"), bool):
            raise ReleaseValidationError("candidate creator role evidence is invalid")
        is_primary = evidence["is_primary"]
        normalized[creator] = {
            "is_primary": is_primary,
            "reference": _required_text(
                evidence.get("reference"), "creator role evidence reference"
            ),
        }
        if is_primary:
            primary_creators.append(creator)
    if not primary_creators:
        raise ReleaseValidationError("non-code candidates require a primary creator")
    return normalized, primary_creators


def _validate_selection_slot(
    value: Any, case: Mapping[str, Any], category: str
) -> dict[str, Any]:
    fields = {
        "attack_vector", "category", "domain", "era", "prompt_modifier",
        "quota", "slot_id", "source_language",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseValidationError("Selection Slot fields are invalid")
    classification = case["classification"]
    year = int(case["source_work"]["publication_date"][:4])
    expected_era = None if classification["domain"] == "code" else (
        "pre_1950" if year < 1950 else "1950_1999" if year < 2000 else "2000_onward"
    )
    modifiers = classification["prompt_modifiers"]
    expected_modifier = modifiers[0] if modifiers else None
    quota = value.get("quota")
    if isinstance(quota, bool) or not isinstance(quota, int) or quota < 1:
        raise ReleaseValidationError("Selection Slot quota is invalid")
    criteria = {
        "attack_vector": classification["attack_vector"],
        "category": category,
        "domain": classification["domain"],
        "era": expected_era,
        "prompt_modifier": expected_modifier,
        "source_language": case["grading"]["source_language"],
    }
    expected = {
        **criteria,
        "quota": quota,
        "slot_id": f"slot-{hashlib.sha256(canonical_json(criteria)).hexdigest()}",
    }
    if dict(value) != expected:
        raise ReleaseValidationError("Selection Slot criteria do not match the candidate")
    return expected


def _validate_candidate_exclusions(
    value: Any, allowed_reasons: set[str]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReleaseValidationError("candidate exclusions must be a list")
    normalized = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "case_id", "evidence_reference", "reasons"
        }:
            raise ReleaseValidationError("candidate exclusion entry is invalid")
        case_id = _required_text(item.get("case_id"), "excluded candidate case_id")
        reasons = item.get("reasons")
        if case_id in seen or not isinstance(reasons, list) or not reasons:
            raise ReleaseValidationError("candidate exclusion evidence is invalid")
        if len(reasons) != len(set(reasons)) or any(
            not isinstance(reason, str) or reason not in allowed_reasons for reason in reasons
        ):
            raise ReleaseValidationError("candidate exclusion reason is invalid")
        seen.add(case_id)
        normalized.append({
            "case_id": case_id,
            "evidence_reference": _required_text(
                item.get("evidence_reference"), "candidate exclusion evidence reference"
            ),
            "reasons": sorted(reasons),
        })
    return sorted(normalized, key=lambda item: item["case_id"])


def _validate_candidate_attestations(
    value: Any, cases: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    case_by_id = {case["identity"]["case_id"]: case for case in cases}
    if not isinstance(value, Mapping) or set(value) != set(case_by_id):
        raise ReleaseValidationError("Corpus Candidate Record attestations are incomplete")
    normalized: dict[str, dict[str, Any]] = {}
    for case_id, attestation in value.items():
        if not isinstance(attestation, Mapping) or set(attestation) != {
            "contributor", "dco_signed_off", "reference", "rights_attestation"
        }:
            raise ReleaseValidationError("Corpus Candidate Record attestation is invalid")
        contributor = _required_text(attestation.get("contributor"), "attestation contributor")
        if contributor != case_by_id[case_id]["review"]["author"]:
            raise ReleaseValidationError("attestation contributor must match the case contributor")
        if attestation.get("dco_signed_off") is not True or attestation.get(
            "rights_attestation"
        ) is not True:
            raise ReleaseValidationError("RogueRecall Contributor attestations must be affirmative")
        normalized[case_id] = {
            "contributor": contributor,
            "dco_signed_off": True,
            "reference": _required_text(attestation.get("reference"), "attestation reference"),
            "rights_attestation": True,
        }
    return {case_id: normalized[case_id] for case_id in sorted(normalized)}


def _validate_independent_reviews(
    value: Any, cases: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    case_by_id = {case["identity"]["case_id"]: case for case in cases}
    if not isinstance(value, Mapping) or set(value) != set(case_by_id):
        raise ReleaseValidationError("Corpus Candidate Record independent reviews are incomplete")
    normalized: dict[str, dict[str, Any]] = {}
    for case_id, review in value.items():
        if not isinstance(review, Mapping) or set(review) != {
            "checklist_passed", "reference", "reviewer"
        }:
            raise ReleaseValidationError("candidate independent review is invalid")
        reviewer = _required_text(review.get("reviewer"), "independent reviewer")
        case = case_by_id[case_id]
        if reviewer != case["review"]["reviewer"] or reviewer in {
            case["review"]["author"], *case["source_work"]["creators"]
        }:
            raise ReleaseValidationError("independent reviewer conflicts with the case")
        if review.get("checklist_passed") is not True:
            raise ReleaseValidationError("independent review checklist must pass")
        normalized[case_id] = {
            "checklist_passed": True,
            "reference": _required_text(
                review.get("reference"), "independent review reference"
            ),
            "reviewer": reviewer,
        }
    return {case_id: normalized[case_id] for case_id in sorted(normalized)}


def _validate_curator_confirmation(value: Any) -> dict[str, Any]:
    gates = {
        "composition",
        "concentration",
        "contamination",
        "gradeability",
        "lifecycle",
        "warnings_reviewed",
    }
    if not isinstance(value, Mapping) or set(value) != gates | {"warnings"}:
        raise ReleaseValidationError("release curator confirmation fields are invalid")
    if any(value.get(gate) is not True for gate in gates):
        raise ReleaseValidationError("release curator must affirm every corpus gate")
    warnings = value.get("warnings")
    if not isinstance(warnings, list):
        raise ReleaseValidationError("release curator warnings must be a list")
    normalized_warnings = []
    for warning in warnings:
        if not isinstance(warning, Mapping) or set(warning) != {
            "code", "disposition", "rationale"
        }:
            raise ReleaseValidationError("release curator warning decision is invalid")
        if warning.get("disposition") != "resolved":
            raise ReleaseValidationError(
                "release curator warnings must be resolved before validation"
            )
        normalized_warnings.append(
            {
                "code": _required_text(warning.get("code"), "warning code"),
                "disposition": warning["disposition"],
                "rationale": _required_text(warning.get("rationale"), "warning rationale"),
            }
        )
    return {
        **{gate: True for gate in sorted(gates)},
        "warnings": sorted(normalized_warnings, key=lambda item: item["code"]),
    }


def _validate_notice_bundle(notices: Mapping[str, bytes]) -> dict[str, bytes]:
    if set(notices) != _REQUIRED_NOTICES:
        raise ReleaseValidationError("Release Notice Bundle is incomplete")
    normalized: dict[str, bytes] = {}
    for name, content in notices.items():
        if not isinstance(content, bytes) or not content.strip():
            raise ReleaseValidationError(f"Release Notice Bundle file is empty: {name}")
        normalized[name] = content
    try:
        rights_manifest = json.loads(normalized["rights-manifest.json"])
    except json.JSONDecodeError as error:
        raise ReleaseValidationError("rights-manifest.json is invalid") from error
    if not isinstance(rights_manifest, dict):
        raise ReleaseValidationError("rights-manifest.json must be an object")
    disclosure = normalized["RIGHTS.md"].decode("utf-8", errors="replace").casefold()
    required_phrases = (
        "roguerecall material only",
        "third-party excerpts",
        "rights evidence",
        "target system responses",
        "no endorsement",
        "case-specific notices",
        "rights contact:",
    )
    if any(phrase not in disclosure for phrase in required_phrases):
        raise ReleaseValidationError("Release Notice Bundle disclosure is incomplete")
    contact = disclosure.split("rights contact:", 1)[1].strip().split()[0]
    if "@" not in contact or "example.invalid" in contact or "placeholder" in contact:
        raise ReleaseValidationError("Release Notice Bundle rights contact is invalid")
    return dict(sorted(normalized.items()))


def _validate_extra_artifacts(artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    normalized = {}
    for raw_path, content in artifacts.items():
        path = _safe_relative_path(raw_path, "release artifact")
        if path.startswith("corpus/") or path.startswith("notices/") or path in {
            "manifest.json",
            "manifest.signature.json",
        }:
            raise ReleaseValidationError(f"release artifact path is reserved: {path}")
        if not isinstance(content, bytes):
            raise ReleaseValidationError(f"release artifact must contain bytes: {path}")
        normalized[path] = content
    return normalized


def _validate_contracts(contracts: Mapping[str, str]) -> dict[str, str]:
    if set(contracts) != {"corpus_schema", "grading"}:
        raise ReleaseValidationError("release contract versions are incomplete")
    if any(not isinstance(value, str) or not value for value in contracts.values()):
        raise ReleaseValidationError("release contract version is invalid")
    return dict(sorted(contracts.items()))


def _validate_replacement(
    replaces: Mapping[str, str] | None, version: str
) -> dict[str, str] | None:
    if replaces is None:
        return None
    if set(replaces) != {"version", "release_digest"}:
        raise ReleaseValidationError("replacement identity is incomplete")
    prior_version = replaces.get("version")
    if prior_version == version:
        raise ReleaseValidationError("replacement must receive a new version")
    if not isinstance(prior_version, str) or not _SEMVER.fullmatch(prior_version):
        raise ReleaseValidationError("replacement predecessor version is invalid")
    return {
        "release_digest": _sha256_text(replaces.get("release_digest"), "release digest"),
        "version": prior_version,
    }


def _artifact_entry(path: str, content: bytes) -> dict[str, Any]:
    suffix = PurePosixPath(path).suffix.casefold()
    media_type = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }.get(suffix, "text/plain" if PurePosixPath(path).name in {
        "LICENSE", "LICENSE-CONTENT", "NOTICE"
    } else "application/octet-stream")
    return {
        "byte_length": len(content),
        "media_type": media_type,
        "path": path,
        "sha256": sha256_bytes(content),
    }


def _read_canonical_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseValidationError(f"cannot read {label}") from error
    if not isinstance(value, dict) or raw != canonical_json(value) + b"\n":
        raise ReleaseValidationError(f"{label} is not canonical JSON")
    return value


def _signed_record_body(
    record: Mapping[str, Any], record_type: str, signature_field: str
) -> dict[str, Any]:
    body = {key: value for key, value in record.items() if key != signature_field}
    if record.get("record_type") != record_type:
        raise ReleaseValidationError(f"expected {record_type} record")
    if record.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ReleaseValidationError("unsupported signed record version")
    return body


def _current_status(
    records: Iterable[Mapping[str, Any]], version: str, release_digest: str
) -> str | None:
    status = None
    for record in records:
        if record.get("version") == version and record.get("release_digest") == release_digest:
            candidate = record.get("new_status")
            status = candidate if isinstance(candidate, str) else status
    return status


def _validate_transition(prior: str | None, new: str) -> None:
    if new not in _STATUSES or new not in _TRANSITIONS.get(prior, frozenset()):
        raise ReleaseValidationError(f"invalid lifecycle transition: {prior} -> {new}")


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseValidationError(f"{label} path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ReleaseValidationError(f"{label} path is unsafe")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseValidationError(f"{label} must be non-empty text")
    return value.strip()


def _sha256_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ReleaseValidationError(f"{label} must be a SHA-256 digest")
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReleaseValidationError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReleaseValidationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReleaseValidationError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise ReleaseValidationError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)
