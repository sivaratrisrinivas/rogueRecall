"""RogueRecall's local Evaluation Run engine."""

__version__ = "0.1.0"

from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .grading import grade_observation
from .engine import run_release
from .releases import (
    CorpusRegistry,
    ReleaseIdentity,
    ReleaseValidationError,
    TrustStore,
    assemble_and_publish_release,
    assemble_release,
    create_key_revocation,
    create_key_rotation,
    generate_release_identity,
    load_release_identity,
    load_verified_release_cases,
    resolve_release_for_run,
    validate_corpus_candidate,
    verify_release,
)
from .targets import (
    EngineExecutionError,
    TargetManifestError,
    execute_target_system,
    execute_target_systems,
    validate_target_manifest,
)
from .qualification import QualificationValidationError, validate_qualification_report

__all__ = [
    "EvaluationCaseValidationError",
    "EngineExecutionError",
    "CorpusRegistry",
    "ReleaseIdentity",
    "ReleaseValidationError",
    "QualificationValidationError",
    "TargetManifestError",
    "TrustStore",
    "assemble_and_publish_release",
    "assemble_release",
    "create_key_revocation",
    "create_key_rotation",
    "execute_target_system",
    "execute_target_systems",
    "grade_observation",
    "generate_release_identity",
    "load_release_identity",
    "load_verified_release_cases",
    "resolve_release_for_run",
    "run_release",
    "validate_evaluation_case",
    "validate_corpus_candidate",
    "validate_target_manifest",
    "validate_qualification_report",
    "verify_release",
]
