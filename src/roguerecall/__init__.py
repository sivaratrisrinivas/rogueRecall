"""RogueRecall's local Evaluation Run engine."""

__version__ = "0.1.0"

from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .benchmark import run_benchmark
from .grading import grade_observation
from .targets import (
    EngineExecutionError,
    TargetManifestError,
    execute_target_system,
    execute_target_systems,
    validate_target_manifest,
)

__all__ = [
    "EvaluationCaseValidationError",
    "EngineExecutionError",
    "TargetManifestError",
    "execute_target_system",
    "execute_target_systems",
    "grade_observation",
    "run_benchmark",
    "validate_evaluation_case",
    "validate_target_manifest",
]
