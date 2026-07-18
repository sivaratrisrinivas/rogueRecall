"""RogueRecall's local Evaluation Run engine."""

__version__ = "0.1.0"

from .benchmark import format_benchmark_summary, run_benchmark
from .cases import EvaluationCaseValidationError, validate_evaluation_case
from .corpus import BenchmarkCorpusValidationError, load_benchmark_corpus, validate_benchmark_corpus
from .grading import grade_observation

__all__ = [
    "BenchmarkCorpusValidationError",
    "EvaluationCaseValidationError",
    "format_benchmark_summary",
    "grade_observation",
    "load_benchmark_corpus",
    "run_benchmark",
    "validate_benchmark_corpus",
    "validate_evaluation_case",
]
