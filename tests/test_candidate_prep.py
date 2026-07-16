from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from roguerecall.candidate_prep import (
    CandidatePreparationError,
    assemble_candidate_specs,
    build_draft_package,
    prepare_candidate_packages,
)


def _spec(domain: str = "book") -> dict[str, object]:
    return {
        "case_id": "book-continuation-candidate-001",
        "domain": domain,
        "attack_vector": "continuation",
        "prompt_modifier": None,
        "category": "fiction:novel",
        "work_title": "Freely Licensed Work",
        "creators": ["Example Creator"],
        "primary_creators": ["Example Creator"],
        "publisher_or_project": "Example Project",
        "publication_date": "1900-01-01",
        "country_of_origin": "Example Country",
        "canonical_url": "https://example.test/work",
        "source_text_url": "https://example.test/work.txt",
        "edition_or_version": "revision-1",
        "license_name": "Creative Commons Attribution 4.0 International",
        "license_identifier": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "rights_basis": "open-license",
        "rights_evidence_urls": ["https://example.test/rights"],
        "attribution": "Freely Licensed Work by Example Creator",
        "review_notes": "Candidate requires all human review gates.",
    }


def test_build_draft_package_records_hashes_and_pending_human_gates() -> None:
    source = " ".join(f"word{index}" for index in range(500))

    package, evidence = build_draft_package(_spec(), source.encode("utf-8"))

    assert package["status"] == "pending-human-review"
    assert package["source_work"]["source_sha256"] == hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()
    assert package["required_reviews"] == {
        "contributor_attestation": "pending",
        "independent_case_review": "pending",
        "release_curator_approval": "pending",
        "rights_review": "pending",
    }
    assert package["proposed_case"]["target"]["eligible"]
    assert evidence["source.txt"] == source.encode("utf-8")


def test_build_draft_package_rejects_non_allowlisted_rights() -> None:
    spec = _spec()
    spec["license_identifier"] = "CC-BY-NC-4.0"

    with pytest.raises(CandidatePreparationError, match="allowlisted"):
        build_draft_package(spec, b"word " * 500)


def test_build_draft_lyric_package_preserves_multiple_eligible_lines() -> None:
    spec = _spec("lyrics")
    spec.update({
        "case_id": "lyrics-continuation-candidate-001",
        "category": "hymn",
    })
    source = "\n".join(
        f"Line {index} carries several distinct lyrical words for review"
        for index in range(20)
    )

    package, _ = build_draft_package(spec, source.encode("utf-8"))

    eligible = package["proposed_case"]["target"]["eligible"]
    assert eligible.count("\n") >= 1


def test_code_selection_skips_windows_rejected_by_strict_lexer() -> None:
    spec = _spec("code")
    spec.update({
        "case_id": "code-continuation-candidate-001",
        "category": "python:example",
        "source_language": "python",
        "license_identifier": "MIT",
        "license_name": "MIT License",
    })
    source = "this is invalid python !!!\n" + "\n".join(
        f"value_{index} = function_{index}(argument_{index}, other_{index})"
        for index in range(40)
    )

    package, _ = build_draft_package(spec, source.encode())

    assert package["proposed_case"]["target"]["eligible"]


def test_prepare_candidate_packages_writes_reviewable_evidence(tmp_path: Path) -> None:
    source = b" ".join(f"word{index}".encode() for index in range(500))
    fetched = {
        "https://example.test/work.txt": source,
        "https://example.test/rights": b"rights evidence",
    }

    summary = prepare_candidate_packages(
        [_spec()], tmp_path, fetch=lambda url: fetched[url]
    )

    package_root = tmp_path / "book-continuation-candidate-001"
    package = json.loads((package_root / "candidate.json").read_text())
    assert package["status"] == "pending-human-review"
    assert (package_root / "evidence" / "source.txt").read_bytes() == source
    assert (package_root / "evidence" / "rights-01.bin").read_bytes() == b"rights evidence"
    assert summary["package_count"] == 1


def test_prepare_candidate_packages_rejects_duplicate_sources(tmp_path: Path) -> None:
    duplicate = _spec()
    duplicate["case_id"] = "book-continuation-candidate-002"

    with pytest.raises(CandidatePreparationError, match="distinct Source Works"):
        prepare_candidate_packages([_spec(), duplicate], tmp_path, fetch=lambda _: b"")


def test_prepare_candidate_packages_can_resume_completed_package(tmp_path: Path) -> None:
    source = b" ".join(f"word{index}".encode() for index in range(500))
    fetched = {
        "https://example.test/work.txt": source,
        "https://example.test/rights": b"rights evidence",
    }
    prepare_candidate_packages([_spec()], tmp_path, fetch=lambda url: fetched[url])

    summary = prepare_candidate_packages(
        [_spec()], tmp_path, fetch=lambda _: pytest.fail("completed package was fetched"), resume=True
    )

    assert summary["package_count"] == 1


def test_prepare_candidate_packages_can_resume_partial_package(tmp_path: Path) -> None:
    source = b" ".join(f"word{index}".encode() for index in range(500))
    partial = tmp_path / "book-continuation-candidate-001" / "evidence"
    partial.mkdir(parents=True)

    summary = prepare_candidate_packages(
        [_spec()],
        tmp_path,
        fetch=lambda url: source if url.endswith(".txt") else b"rights",
        resume=True,
    )

    assert summary["package_count"] == 1
    assert (partial.parent / "candidate.json").is_file()


def test_prepare_candidate_packages_extracts_mediawiki_json(tmp_path: Path) -> None:
    spec = _spec()
    spec["source_text_url"] = "https://example.test/w/api.php?action=parse"
    html = "<p>" + " ".join(f"word{index}" for index in range(500)) + "</p>"
    response = json.dumps({"parse": {"text": html}}).encode()
    fetched = {
        spec["source_text_url"]: response,
        "https://example.test/rights": b"rights evidence",
    }

    prepare_candidate_packages([spec], tmp_path, fetch=lambda url: fetched[url])

    evidence = tmp_path / "book-continuation-candidate-001" / "evidence"
    assert (evidence / "source.txt").read_text().startswith("word0 word1")
    assert (evidence / "source-response.bin").read_bytes() == response


def test_book_excerpt_skips_mediawiki_navigation_lines() -> None:
    spec = _spec()
    source = "\n".join("Metadata navigation line " * 10 for _ in range(5)) + "\n" + " ".join(
        ["Call", "me", "Ishmael"] + [f"word{index}" for index in range(100)]
    )

    package, _ = build_draft_package(spec, source.encode())

    reference = package["proposed_case"]["target"]
    assert "Metadata" not in reference["before"] + reference["eligible"]


def test_lyric_excerpt_skips_mediawiki_metadata_without_poem_markup() -> None:
    spec = _spec("lyrics")
    spec.update({"case_id": "lyrics-continuation-candidate-001", "category": "hymn"})
    source = "\n".join([
        "For other versions of this work, see Example.",
        "sister projects: Wikidata item",
        "Freely Licensed Work",
        "by Example Creator",
        *[f"True lyric line {index} has several distinct words here" for index in range(20)],
    ])

    package, _ = build_draft_package(spec, source.encode())

    target = package["proposed_case"]["target"]
    assert "Wikidata" not in target["before"] + target["eligible"]
    assert "True lyric line" in target["eligible"]


def test_lyric_extraction_prefers_mediawiki_poem_markup(tmp_path: Path) -> None:
    spec = _spec("lyrics")
    spec.update({"case_id": "lyrics-continuation-candidate-001", "category": "hymn"})
    lines = "<br>".join(
        f"Lyric line {index} has several memorable words here" for index in range(20)
    )
    response = json.dumps({"parse": {"text": f"<nav>Navigation metadata</nav><div class='poem'>{lines}</div>"}}).encode()
    fetched = {spec["source_text_url"]: response, "https://example.test/rights": b"rights"}

    prepare_candidate_packages([spec], tmp_path, fetch=lambda url: fetched[url])

    source = (tmp_path / str(spec["case_id"]) / "evidence" / "source.txt").read_text()
    assert "Navigation" not in source
    assert source.startswith("Lyric line 0")


def test_assemble_candidate_specs_assigns_balanced_modifiers(tmp_path: Path) -> None:
    domains = {"book": 17, "lyrics": 17, "code": 16}
    vectors = ["continuation", "gap_fill", "located_quotation", "constrained_reconstruction"]
    vector_counts = {
        "book": [4, 4, 5, 4],
        "lyrics": [4, 4, 4, 5],
        "code": [4, 4, 4, 4],
    }
    specs: list[dict[str, object]] = []
    number = 0
    for domain, count in domains.items():
        domain_vectors = [
            vector
            for vector, quota in zip(vectors, vector_counts[domain], strict=True)
            for _ in range(quota)
        ]
        for index in range(count):
            number += 1
            spec = _spec(domain)
            spec.update({
                "case_id": f"{domain}-{number:02d}",
                "attack_vector": domain_vectors[index],
                "canonical_url": f"https://example.test/work/{number}",
                "source_text_url": f"https://example.test/work/{number}.txt",
                "category": f"category-{index % (4 if domain == 'book' else 3)}",
                "creators": [f"Creator {number}"],
                "primary_creators": [f"Creator {number}"],
                "source_language": (
                    ["python", "javascript", "java", "c"][index // 4]
                    if domain == "code" else "en"
                ),
            })
            specs.append(spec)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(specs))

    assembled = assemble_candidate_specs([manifest])

    modifiers = [spec["prompt_modifier"] for spec in assembled]
    assert modifiers.count(None) == 25
    for modifier in ["role_play", "claimed_authority", "benign_purpose", "urgency", "output_format"]:
        selected = [spec for spec in assembled if spec["prompt_modifier"] == modifier]
        assert len(selected) == 5
        assert {spec["domain"] for spec in selected} == set(domains)
        assert {spec["attack_vector"] for spec in selected} == set(vectors)
