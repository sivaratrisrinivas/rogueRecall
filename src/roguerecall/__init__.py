"""RogueRecall's local Evaluation Run engine."""

from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .grading import grade_observation

__version__ = "0.1.0"

__all__ = [
    "EvaluationCaseValidationError",
    "grade_observation",
    "validate_evaluation_case",
]
