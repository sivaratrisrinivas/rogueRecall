from __future__ import annotations

import importlib.util

import pytest

import roguerecall
from roguerecall.cli import main


def test_removed_corpus_governance_surfaces_are_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    removed_names = (
        "CorpusRegistry",
        "QualificationValidationError",
        "ReleaseIdentity",
        "ReleaseValidationError",
        "TrustStore",
        "assemble_and_publish_release",
        "assemble_release",
        "create_key_revocation",
        "create_key_rotation",
        "generate_release_identity",
        "load_release_identity",
        "load_verified_release_cases",
        "resolve_release_for_run",
        "run_release",
        "run_synthetic",
        "run_targets",
        "validate_corpus_candidate",
        "validate_qualification_report",
        "validate_record",
        "verify_release",
        "create_server",
        "discover_paths",
        "purge",
        "run_doctor",
    )
    for name in removed_names:
        assert not hasattr(roguerecall, name)

    for module_name in (
        "roguerecall.dashboard",
        "roguerecall.dashboard_data",
        "roguerecall.dashboard_exports",
        "roguerecall.installation",
        "roguerecall.candidate_prep",
        "roguerecall.qualification",
        "roguerecall.releases",
    ):
        assert importlib.util.find_spec(module_name) is None

    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    for command in (
        "benchmark",
        "run-synthetic",
        "run",
        "validate",
        "dashboard",
        "paths",
        "doctor",
        "purge",
        "validate-corpus-candidate",
        "validate-qualification",
        "verify-release",
    ):
        if command == "benchmark":
            assert command in help_text
            continue
        assert command not in help_text
