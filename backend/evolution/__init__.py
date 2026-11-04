"""
Autonomous Evolutionary Optimization Engine Package.
"""

from backend.evolution.failure_clusterer import (
    ClusterDiagnostic,
    ClusteringResult,
    FailureClusterer,
    get_failure_clusterer,
)
from backend.evolution.eval_harness import (
    EvaluationSampleResult,
    BenchmarkResult,
    GoldenBenchmarkHarness,
    get_benchmark_harness,
    calculate_answer_relevance,
    calculate_context_recall,
)
from backend.evolution.regression_gate import (
    CandidateConfig,
    GateEvaluationDecision,
    RegressionGate,
    get_regression_gate,
)
from backend.evolution.parameter_tuner import (
    TuningCycleResult,
    ParameterTuner,
    get_parameter_tuner,
)

__all__ = [
    "ClusterDiagnostic",
    "ClusteringResult",
    "FailureClusterer",
    "get_failure_clusterer",
    "EvaluationSampleResult",
    "BenchmarkResult",
    "GoldenBenchmarkHarness",
    "get_benchmark_harness",
    "calculate_answer_relevance",
    "calculate_context_recall",
    "CandidateConfig",
    "GateEvaluationDecision",
    "RegressionGate",
    "get_regression_gate",
    "TuningCycleResult",
    "ParameterTuner",
    "get_parameter_tuner",
]
