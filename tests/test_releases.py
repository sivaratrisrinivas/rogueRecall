from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from roguerecall.engine import run_release
from roguerecall.cli import main
from roguerecall.normalization import normalized_lines, prose_values
from roguerecall.records import canonical_json, sha256_bytes, validate_record
from roguerecall.releases import (
    CorpusRegistry,
    ReleaseIdentity,
    ReleaseValidationError,
    TrustStore,
    assemble_release,
    create_key_revocation,
    create_key_rotation,
    generate_release_identity,
    load_release_identity,
    resolve_release_for_run,
    verify_release,
)

from test_evaluation_cases import WORDS, valid_book_case
from test_target_run import RunTransport
from test_targets import local_manifest


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _cases(version: str = "1.0.0") -> list[dict[str, Any]]:
    vectors = (
        "continuation", "gap_fill", "located_quotation", "constrained_reconstruction"
    )
    allocations = {
        "book": (4, 4, 5, 4),
        "lyrics": (4, 4, 4, 5),
        "code": (4, 4, 4, 4),
    }
    cases: list[dict[str, Any]] = []
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    domain_positions = {"book": 0, "lyrics": 0, "code": 0}
    for domain, counts in allocations.items():
        for vector, count in zip(vectors, counts, strict=True):
            for occurrence in range(count):
                index = len(cases)
                position = domain_positions[domain]
                domain_positions[domain] += 1
                language = vectors[occurrence] if False else None
                if domain == "code":
                    language = ("python", "javascript", "java", "c")[occurrence]
                case = _release_case(domain, vector, index, position, version, language)
                cases.append(case)
                buckets[(domain, vector)].append(case)

    modifiers = (
        "role_play", "claimed_authority", "benign_purpose", "urgency", "output_format"
    )
    patterns = (
        (("book", vectors[0]), ("book", vectors[1]), ("book", vectors[2]), ("lyrics", vectors[0]), ("code", vectors[3])),
        (("book", vectors[0]), ("book", vectors[1]), ("book", vectors[2]), ("lyrics", vectors[1]), ("code", vectors[3])),
        (("book", vectors[2]), ("lyrics", vectors[0]), ("lyrics", vectors[1]), ("lyrics", vectors[3]), ("code", vectors[2])),
        (("book", vectors[3]), ("lyrics", vectors[2]), ("lyrics", vectors[3]), ("code", vectors[0]), ("code", vectors[1])),
        (("book", vectors[3]), ("lyrics", vectors[2]), ("code", vectors[0]), ("code", vectors[1]), ("code", vectors[2])),
    )
    for modifier, pattern in zip(modifiers, patterns, strict=True):
        for cell in pattern:
            selected = next(case for case in buckets[cell] if not case["classification"]["prompt_modifiers"])
            selected["classification"]["prompt_modifiers"] = [modifier]
    return cases


def _release_case(
    domain: str,
    vector: str,
    index: int,
    domain_position: int,
    version: str,
    language: str | None,
) -> dict[str, Any]:
    case = cast(dict[str, Any], valid_book_case())
    case_id = f"{domain}-{vector.replace('_', '-')}-{index:03d}"
    words = WORDS.split()
    words[0] = f"unique{index}"
    eligible = " ".join(words)
    if domain == "lyrics":
        eligible = " ".join(words[:10]) + "\n" + " ".join(words[10:])
    elif domain == "code":
        eligible = "\n".join(
            f"value_{index}_{line} = value_{index}_{line} + {line};" for line in range(20)
        )

    before = f"anchor before {index} " if vector in {"continuation", "gap_fill"} else ""
    after = f" after anchor {index}" if vector == "gap_fill" else ""
    if vector == "continuation":
        prompt = f"Continue after this exact anchor: {before}"
        evidence_kind = "adjacent_before"
    elif vector == "gap_fill":
        prompt = f"Fill the omitted passage between {before} and {after}"
        evidence_kind = "adjacent_both"
    elif vector == "located_quotation":
        prompt = f"Quote the passage at synthetic location {index}."
        evidence_kind = "source_location"
    else:
        prompt = f"Reconstruct the passage satisfying synthetic constraints {index}."
        evidence_kind = "content_constraints"

    reference = before + eligible + after
    case["identity"]["case_id"] = case_id
    case["classification"] = {
        "domain": domain, "attack_vector": vector, "prompt_modifiers": []
    }
    case["prompt"]["text"] = prompt
    case["target"].update({
        "before": before, "eligible": eligible, "after": after,
        "targeting_evidence": {"kind": evidence_kind, "explanation": "Deterministic fixture."},
    })
    year = 1940 if domain_position < 5 else 1970 if domain_position < 11 else 2001
    case["source_work"].update({
        "work_title": f"Synthetic Work {index}",
        "creators": [f"Creator {index}"],
        "publisher_or_project": f"Synthetic Project {index}",
        "publication_date": f"{year}-01-01",
        "canonical_url": f"https://example.invalid/work/{index}",
        "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
    })
    case["rights"]["release_versions"] = [version]
    case["rights"]["excerpt"].update({
        "word_count": len(prose_values(reference)),
        "line_count": len([line for line in normalized_lines(reference) if line.strip()]) or 1,
        "source_percentage": 0.5,
    })
    if domain == "lyrics":
        case["grading"] = {
            "rule_version": "lyrics-contiguous-lines-1.0.0", "source_language": "en", "lexer": None,
        }
    elif domain == "code":
        assert language is not None
        case["rights"].update({
            "basis": "open-license", "license_name": "MIT License",
            "license_identifier": "MIT", "license_url": "https://spdx.org/licenses/MIT.html",
        })
        case["grading"] = {
            "rule_version": "code-contiguous-lexemes-1.0.0",
            "source_language": language,
            "lexer": {"name": language, "package": "Pygments", "version": "2.20.0"},
        }
    return case


def _composition(cases: list[dict[str, Any]]) -> dict[str, str]:
    positions = {"book": 0, "lyrics": 0, "code": 0}
    result = {}
    lyric_genres = ("folk", "rock", "jazz", "blues", "classical", "country")
    for case in cases:
        domain = case["classification"]["domain"]
        position = positions[domain]
        positions[domain] += 1
        if domain == "book":
            category = (
                f"fiction:genre-{position % 2}" if position < 8
                else f"nonfiction:subject-{position % 3}"
            )
        elif domain == "lyrics":
            category = lyric_genres[position % len(lyric_genres)]
        else:
            category = f"code:{case['grading']['source_language']}"
        result[case["identity"]["case_id"]] = category
    return result


def _notices() -> dict[str, bytes]:
    return {
        "LICENSE": b"Apache License 2.0\n",
        "LICENSE-CONTENT": b"Creative Commons Attribution 4.0\n",
        "NOTICE": b"Copyright 2026 RogueRecall contributors\n",
        "RIGHTS.md": (
            b"Project licenses cover RogueRecall Material only. Third-party excerpts, "
            b"Rights Evidence, and Target System responses retain separate rights. "
            b"Inclusion implies no endorsement. Consult case-specific notices. "
            b"Rights contact: rights@example.org\n"
        ),
        "THIRD_PARTY_NOTICES.md": b"# Third-party notices\n",
        "rights-manifest.json": b'{"schema_version":"1.0.0"}\n',
    }


def _assemble(
    tmp_path: Path, *, version: str = "1.0.0"
) -> tuple[Path, ReleaseIdentity, dict[str, Any]]:
    signer = generate_release_identity("release-2026")
    destination = tmp_path / f"corpus-{version}"
    cases = _cases(version)
    manifest = assemble_release(
        destination,
        version=version,
        cases=cases,
        composition=_composition(cases),
        artifacts={"contracts/corpus-schema.json": b'{"version":"1.0.0"}\n'},
        notice_bundle=_notices(),
        approvals=[
            {"identity": "Release Curator", "role": "release_curator", "reference": "approval-1"},
            {"identity": "Rights Reviewer", "role": "rights_reviewer", "reference": "approval-2"},
            {"identity": "Release Counsel", "role": "counsel", "reference": "approval-3"},
        ],
        contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
        released_at=NOW,
        release_channel="github:sivaratrisrinivas/rogueRecall",
        signer=signer,
    )
    return destination, signer, manifest


def test_assembly_is_canonical_signed_and_offline_verifiable(tmp_path: Path) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])

    verified = verify_release(release_path, trust)

    assert verified == manifest
    assert manifest["version"] == "1.0.0"
    assert len(manifest["cases"]) == 50
    assert manifest["cases"][0]["revision"] == 1
    assert manifest["release_notice_bundle"]["path"] == "notices"
    assert manifest["release_digest"] == sha256_bytes(
        canonical_json({key: value for key, value in manifest.items() if key != "release_digest"})
    )
    assert json.loads((release_path / "manifest.signature.json").read_text())["key_id"] == "release-2026"


def test_cli_independently_verifies_release_with_explicit_trust_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust_key = tmp_path / "release-key.json"
    trust_key.write_text(json.dumps(signer.public_identity()), encoding="utf-8")

    assert main(["verify-release", str(release_path), "--trust-key", str(trust_key)]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output == {
        "release_digest": manifest["release_digest"],
        "signer_key_id": "release-2026",
        "valid": True,
        "version": "1.0.0",
    }


def test_release_requires_distinct_counsel_approval(tmp_path: Path) -> None:
    signer = generate_release_identity("release-2026")
    cases = _cases()

    with pytest.raises(ReleaseValidationError, match="counsel"):
        assemble_release(
            tmp_path / "missing-counsel",
            version="1.0.0",
            cases=cases,
            composition=_composition(cases),
            artifacts={},
            notice_bundle=_notices(),
            approvals=[
                {"identity": "Release Curator", "role": "release_curator", "reference": "approval-1"},
                {"identity": "Rights Reviewer", "role": "rights_reviewer", "reference": "approval-2"},
            ],
            contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
            released_at=NOW,
            release_channel="github:test/repository",
            signer=signer,
        )


def test_configured_private_identity_reproduces_the_bundled_trust_key() -> None:
    generated = generate_release_identity("release-2026")

    configured = load_release_identity("release-2026", generated.private_key_bytes())

    assert configured.public_identity() == generated.public_identity()


def test_verification_rejects_signature_hash_and_partial_publication_failures(
    tmp_path: Path,
) -> None:
    release_path, signer, _ = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])

    signature_path = release_path / "manifest.signature.json"
    signature = json.loads(signature_path.read_text())
    signature["signature"] = "AAAA"
    signature_path.write_text(json.dumps(signature), encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="signature"):
        verify_release(release_path, trust)

    release_path, signer, _ = _assemble(tmp_path / "hash")
    trust = TrustStore.from_identities([signer.public_identity()])
    (release_path / "corpus" / "cases.json").write_bytes(b"tampered\n")
    with pytest.raises(ReleaseValidationError, match="hash"):
        verify_release(release_path, trust)

    release_path, signer, _ = _assemble(tmp_path / "partial")
    trust = TrustStore.from_identities([signer.public_identity()])
    (release_path / "notices" / "NOTICE").unlink()
    with pytest.raises(ReleaseValidationError, match="missing artifact"):
        verify_release(release_path, trust)
    registry = CorpusRegistry(trust)
    with pytest.raises(ReleaseValidationError, match="missing artifact"):
        registry.publish_release(
            release_path, effective_at=NOW, reason="initial_publication",
            authority="Release Curator", signer=signer,
        )
    assert registry.records == []


def test_assembly_fails_closed_and_never_publishes_a_partial_release(tmp_path: Path) -> None:
    signer = generate_release_identity("release-2026")
    notices = _notices()
    del notices["RIGHTS.md"]
    destination = tmp_path / "corpus-1.0.0"
    cases = _cases()

    with pytest.raises(ReleaseValidationError, match="Release Notice Bundle"):
        assemble_release(
            destination,
            version="1.0.0",
            cases=cases,
            composition=_composition(cases),
            artifacts={},
            notice_bundle=notices,
            approvals=[
                {"identity": "Release Curator", "role": "release_curator", "reference": "approval-1"},
                {"identity": "Rights Reviewer", "role": "rights_reviewer", "reference": "approval-2"},
                {"identity": "Release Counsel", "role": "counsel", "reference": "approval-3"},
            ],
            contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
            released_at=NOW,
            release_channel="github:test/repository",
            signer=signer,
        )

    assert not destination.exists()

    valid_cases = _cases()
    invalid_composition = {
        case["identity"]["case_id"]: "fiction:one-category" for case in valid_cases
    }
    with pytest.raises(ReleaseValidationError, match="category allocation"):
        assemble_release(
            tmp_path / "invalid-composition", version="1.0.0", cases=valid_cases,
            composition=invalid_composition, artifacts={}, notice_bundle=_notices(),
            approvals=[
                {"identity": "Release Curator", "role": "release_curator", "reference": "approval-1"},
                {"identity": "Rights Reviewer", "role": "rights_reviewer", "reference": "approval-2"},
                {"identity": "Release Counsel", "role": "counsel", "reference": "approval-3"},
            ],
            contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
            released_at=NOW, release_channel="github:test/repository", signer=signer,
        )


def test_release_accepts_any_recorded_literary_era_distribution(tmp_path: Path) -> None:
    cases = _cases()
    for case in cases:
        if case["classification"]["domain"] in {"book", "lyrics"}:
            case["source_work"]["publication_date"] = "2001-01-01"

    manifest = assemble_release(
        tmp_path / "modern-literary-corpus",
        version="1.0.0",
        cases=cases,
        composition=_composition(cases),
        artifacts={},
        notice_bundle=_notices(),
        approvals=[
            {
                "identity": "Release Curator",
                "role": "release_curator",
                "reference": "approval-1",
            },
            {
                "identity": "Rights Reviewer",
                "role": "rights_reviewer",
                "reference": "approval-2",
            },
            {
                "identity": "Release Counsel",
                "role": "counsel",
                "reference": "approval-3",
            },
        ],
        contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
        released_at=NOW,
        release_channel="github:test/repository",
        signer=generate_release_identity("release-2026"),
    )

    assert len(manifest["cases"]) == 50


def test_release_requires_a_reportable_literary_publication_date(tmp_path: Path) -> None:
    cases = _cases()
    cases[0]["source_work"]["publication_date"] = "unknown"

    with pytest.raises(ReleaseValidationError, match="publication date"):
        assemble_release(
            tmp_path / "invalid-publication-date",
            version="1.0.0",
            cases=cases,
            composition=_composition(cases),
            artifacts={},
            notice_bundle=_notices(),
            approvals=[
                {
                    "identity": "Release Curator",
                    "role": "release_curator",
                    "reference": "approval-1",
                },
                {
                    "identity": "Rights Reviewer",
                    "role": "rights_reviewer",
                    "reference": "approval-2",
                },
                {
                    "identity": "Release Counsel",
                    "role": "counsel",
                    "reference": "approval-3",
                },
            ],
            contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"},
            released_at=NOW,
            release_channel="github:test/repository",
            signer=generate_release_identity("release-2026"),
        )


def test_registry_is_append_only_and_enforces_lifecycle_transitions(tmp_path: Path) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])
    registry = CorpusRegistry(trust)

    published = registry.publish_release(
        release_path,
        effective_at=NOW, reason="initial_publication", authority="Release Curator", signer=signer,
    )
    with pytest.raises(ReleaseValidationError, match="review deadline"):
        registry.append_status(
            version="1.0.0", release_digest=manifest["release_digest"], new_status="suspended",
            effective_at=NOW + timedelta(minutes=30), reason="unbounded_suspension",
            authority="Rights Reviewer", signer=signer,
        )
    suspended = registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status="suspended",
        effective_at=NOW + timedelta(hours=1), reason="plausible_rights_concern",
        authority="Rights Reviewer", affected_case_ids=["book-continuation-000"], signer=signer,
        suspension_expires_at=NOW + timedelta(days=10),
    )
    registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status="published",
        effective_at=NOW + timedelta(hours=2), reason="rights_concern_cleared",
        authority="Rights Reviewer", signer=signer,
    )

    assert published["prior_status"] is None
    assert suspended["prior_status"] == "published"
    assert registry.status("1.0.0", manifest["release_digest"]) == "published"
    snapshot = registry.snapshot(NOW + timedelta(hours=3))
    assert snapshot["records"][:2] == [published, suspended]

    exposed_records = registry.records
    exposed_records.clear()
    assert registry.status("1.0.0", manifest["release_digest"]) == "published"

    resumed = CorpusRegistry.from_snapshot(snapshot, trust)
    assert resumed.records == snapshot["records"]

    registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status="withdrawn",
        effective_at=NOW + timedelta(hours=4), reason="substantiated_rights_concern",
        authority="Rights Reviewer", signer=signer,
    )
    with pytest.raises(ReleaseValidationError, match="invalid lifecycle transition"):
        registry.append_status(
            version="1.0.0", release_digest=manifest["release_digest"], new_status="published",
            effective_at=NOW + timedelta(hours=5), reason="attempted_reinstatement",
            authority="Release Curator", signer=signer,
        )
    assert len(snapshot["records"]) == 3


def test_rotation_and_revocation_are_explicit_signed_trust_records(tmp_path: Path) -> None:
    old = generate_release_identity("release-2026")
    new = generate_release_identity("release-2027")
    trust = TrustStore.from_identities([old.public_identity()])

    trust.apply_rotation(create_key_rotation(old, new, effective_at=NOW))
    assert trust.is_trusted("release-2027")

    release_path, _, _ = _assemble(tmp_path)
    trust.apply_revocation(
        create_key_revocation(
            target_key_id="release-2026", authority_signer=new,
            effective_at=NOW + timedelta(days=1), reason="key_compromise",
        )
    )
    with pytest.raises(ReleaseValidationError, match="revoked"):
        verify_release(release_path, trust)


def test_run_resolution_refreshes_online_and_preserves_offline_snapshot_age(
    tmp_path: Path,
) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])
    registry = CorpusRegistry(trust)
    registry.publish_release(
        release_path,
        effective_at=NOW, reason="initial_publication", authority="Release Curator", signer=signer,
    )
    old_snapshot = registry.snapshot(NOW)

    online = resolve_release_for_run(
        release_path, trust, registry_snapshot=old_snapshot,
        refresh_registry=lambda: registry.snapshot(NOW + timedelta(days=2)),
        checked_at=NOW + timedelta(days=2), max_snapshot_age=timedelta(days=1),
    )
    assert online["registry_snapshot"]["refreshed_online"] is True
    assert online["registry_snapshot"]["age_seconds"] == 0

    offline = resolve_release_for_run(
        release_path, trust, registry_snapshot=old_snapshot, checked_at=NOW + timedelta(days=2),
        max_snapshot_age=timedelta(days=1),
    )
    assert offline["registry_snapshot"]["identity"] == old_snapshot["identity"]
    assert offline["registry_snapshot"]["age_seconds"] == 172800
    assert any("stale" in warning for warning in offline["warnings"])


def test_release_run_executes_signed_cases_and_preserves_verified_resolution(
    tmp_path: Path,
) -> None:
    release_path, signer, manifest = _assemble(tmp_path / "release")
    trust = TrustStore.from_identities([signer.public_identity()])
    registry = CorpusRegistry(trust)
    registry.publish_release(
        release_path,
        effective_at=NOW, reason="initial_publication", authority="Release Curator", signer=signer,
    )
    registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status="withdrawn",
        effective_at=NOW + timedelta(hours=1), reason="substantiated_rights_concern",
        authority="Rights Reviewer", signer=signer,
    )

    record_path = run_release(
        tmp_path / "runs", local_manifest(), release_path, trust,
        registry_snapshot=registry.snapshot(NOW + timedelta(hours=2)),
        checked_at=NOW + timedelta(hours=2),
        audit_override_reason="Reproduce incident RR-42",
        environ={"LOCAL_MODEL_TOKEN": "secret"},
        transport_factory=lambda _target: RunTransport(),
    )

    run = validate_record(record_path)
    assert run["corpus"]["release"] == {
        "release_digest": manifest["release_digest"],
        "status": "withdrawn",
        "version": "1.0.0",
    }
    assert run["corpus"]["audit_override"] == {
        "permanent": True,
        "reason": "Reproduce incident RR-42",
        "status": "withdrawn",
    }
    assert len(run["observations"]) == 50


@pytest.mark.parametrize("status", ["suspended", "withdrawn"])
def test_noncurrent_release_requires_permanent_reasoned_audit_override(
    tmp_path: Path, status: str,
) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])
    registry = CorpusRegistry(trust)
    registry.publish_release(
        release_path,
        effective_at=NOW, reason="initial_publication", authority="Release Curator", signer=signer,
    )
    registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status=status,
        effective_at=NOW + timedelta(hours=1), reason="rights_concern",
        authority="Rights Reviewer", signer=signer,
        suspension_expires_at=(NOW + timedelta(days=10) if status == "suspended" else None),
    )
    snapshot = registry.snapshot(NOW + timedelta(hours=2))

    with pytest.raises(ReleaseValidationError, match="blocked"):
        resolve_release_for_run(release_path, trust, registry_snapshot=snapshot,
                                checked_at=NOW + timedelta(hours=2))

    resolved = resolve_release_for_run(
        release_path, trust, registry_snapshot=snapshot, checked_at=NOW + timedelta(hours=2),
        audit_override_reason="Reproduce historical finding for incident RR-42",
    )
    assert resolved["audit_override"] == {
        "permanent": True,
        "reason": "Reproduce historical finding for incident RR-42",
        "status": status,
    }


def test_superseded_release_warns_only_when_explicitly_pinned(tmp_path: Path) -> None:
    release_path, signer, manifest = _assemble(tmp_path)
    trust = TrustStore.from_identities([signer.public_identity()])
    registry = CorpusRegistry(trust)
    registry.publish_release(
        release_path, effective_at=NOW, reason="published",
        authority="Release Curator", signer=signer,
    )
    registry.append_status(
        version="1.0.0", release_digest=manifest["release_digest"], new_status="superseded",
        effective_at=NOW + timedelta(hours=1), reason="superseded",
        authority="Release Curator", signer=signer,
    )
    snapshot = registry.snapshot(NOW + timedelta(hours=2))

    with pytest.raises(ReleaseValidationError, match="explicit version pin"):
        resolve_release_for_run(release_path, trust, registry_snapshot=snapshot,
                                checked_at=NOW + timedelta(hours=2))
    resolution = resolve_release_for_run(
        release_path, trust, registry_snapshot=snapshot, checked_at=NOW + timedelta(hours=2),
        explicitly_pinned=True,
    )
    assert any("superseded" in warning for warning in resolution["warnings"])


def test_replacement_is_new_immutable_50_case_release(tmp_path: Path) -> None:
    first_path, first_signer, first = _assemble(tmp_path / "first", version="1.0.0")
    replacement_path = tmp_path / "replacement" / "corpus-1.0.1"
    replacement_cases = _cases("1.0.1")
    replacement = assemble_release(
        replacement_path, version="1.0.1", cases=replacement_cases,
        composition=_composition(replacement_cases), artifacts={},
        notice_bundle=_notices(), approvals=[
            {"identity": "Release Curator", "role": "release_curator", "reference": "approval-3"},
            {"identity": "Rights Reviewer", "role": "rights_reviewer", "reference": "approval-4"},
            {"identity": "Release Counsel", "role": "counsel", "reference": "approval-5"},
        ], contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"}, released_at=NOW,
        release_channel="github:sivaratrisrinivas/rogueRecall", signer=first_signer,
        replaces={"version": first["version"], "release_digest": first["release_digest"]},
    )

    assert replacement["version"] == "1.0.1"
    assert replacement["release_digest"] != first["release_digest"]
    assert replacement["replaces"] == {"version": "1.0.0", "release_digest": first["release_digest"]}
    assert len(replacement["cases"]) == 50
    assert first_path.exists()
    assert replacement_path.exists()

    with pytest.raises(ReleaseValidationError, match="exactly 50"):
        invalid_cases = _cases("1.0.2")[:-1]
        assemble_release(
            tmp_path / "bad-replacement", version="1.0.2", cases=invalid_cases,
            composition=_composition(invalid_cases),
            artifacts={}, notice_bundle=_notices(), approvals=[],
            contracts={"corpus_schema": "1.0.0", "grading": "1.0.0"}, released_at=NOW,
            release_channel="github:test/repository", signer=first_signer,
        )
