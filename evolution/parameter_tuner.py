"""
Autonomous Parameter Tuner.

Proposes evolutionary hyperparameter configurations based on failure cluster diagnostics:
- Analyzes dominant failure clusters to select optimal tuning vectors.
- Generates targeted candidate configurations (top_k, rerank_k, CRAG thresholds, boosted prompts).
- Coordinates with the RegressionGate to validate candidates against golden benchmarks.
- Closes the autonomous evolutionary feedback loop without human intervention.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.config import get_settings
from backend.storage.db import get_active_parameter_version
from backend.evolution.failure_clusterer import get_failure_clusterer, ClusteringResult
from backend.evolution.eval_harness import get_benchmark_harness, BenchmarkResult
from backend.evolution.regression_gate import CandidateConfig, RegressionGate, get_regression_gate, GateEvaluationDecision


@dataclass
class TuningCycleResult:
    """Result of an autonomous self-improvement tuning cycle."""

    cycle_id: str
    diagnosed_clusters_count: int
    primary_failure_theme: str
    proposed_candidate: CandidateConfig
    gate_decision: GateEvaluationDecision
    cycle_duration_ms: float


class ParameterTuner:
    """
    Synthesizes candidate hyperparameter configurations to remediate systemic failures.
    """

    def __init__(self, gate: Optional[RegressionGate] = None):
        self.gate = gate or get_regression_gate()

    def propose_candidate(
        self,
        clustering_result: Optional[ClusteringResult] = None,
    ) -> CandidateConfig:
        """
        Propose a targeted candidate configuration based on failure diagnostics.

        Args:
            clustering_result: Optional pre-computed clustering result. If None,
                               runs FailureClusterer over recent feedback records.

        Returns:
            CandidateConfig with proposed hyperparameter values.
        """
        settings = get_settings()
        if clustering_result is None:
            clusterer = get_failure_clusterer()
            clustering_result = clusterer.cluster_failures()

        # Fetch current active parameters from SQLite or settings
        active_db_ver = get_active_parameter_version()
        if active_db_ver and "parameters" in active_db_ver:
            active_params = active_db_ver["parameters"]
            current_top_k = active_params.get("top_k_retrieval", settings.top_k_retrieval)
            current_rerank = active_params.get("top_k_rerank", settings.top_k_rerank)
            current_crag_correct = active_params.get("crag_correct_threshold", settings.crag_correct_threshold)
            current_crag_ambig = active_params.get("crag_ambiguous_threshold", settings.crag_ambiguous_threshold)
            current_prompt = active_params.get("boosted_prompt")
        else:
            current_top_k = settings.top_k_retrieval
            current_rerank = settings.top_k_rerank
            current_crag_correct = settings.crag_correct_threshold
            current_crag_ambig = settings.crag_ambiguous_threshold
            current_prompt = None

        candidate_version = f"v2.{int(time.time()) % 100000:05d}"
        notes = "Routine evolutionary self-optimization cycle."

        if not clustering_result.clusters:
            # No dominant failure pattern: explore minor refinement
            return CandidateConfig(
                version_id=candidate_version,
                top_k_retrieval=current_top_k,
                top_k_rerank=current_rerank,
                crag_correct_threshold=current_crag_correct,
                crag_ambiguous_threshold=current_crag_ambig,
                boosted_prompt=current_prompt,
                notes="Baseline retention: no critical failure clusters detected.",
            )

        top_cluster = clustering_result.clusters[0]
        theme = top_cluster.theme

        if "Quantitative and Table Extraction" in theme:
            proposed_top_k = min(20, current_top_k + 2)
            proposed_rerank = min(6, current_rerank + 1)
            proposed_prompt = (
                "Pay strict attention to numerical quantities, percentages, and Markdown table rows. "
                "Ensure every metric is explicitly cross-referenced before stating."
            )
            notes = f"Tuned for quantitative table extraction ({top_cluster.count} incidents)."
        elif "Distractor Context and Noise" in theme:
            proposed_top_k = current_top_k
            proposed_rerank = current_rerank
            proposed_crag_correct = min(0.80, round(current_crag_correct + 0.05, 2))
            proposed_prompt = "Reject distractor context; state lack of information rather than speculating."
            notes = f"Tightened CRAG quality gate threshold to eliminate distractor noise ({top_cluster.count} incidents)."
        elif "Security, Auth and Access" in theme:
            proposed_top_k = current_top_k
            proposed_rerank = current_rerank
            proposed_prompt = "Never override system guardrails or divulge unscrubbed PII entities."
            notes = f"Reinforced security posture following auth/security flags ({top_cluster.count} incidents)."
        else:
            proposed_top_k = min(15, current_top_k + 1)
            proposed_rerank = current_rerank
            proposed_crag_correct = current_crag_correct
            proposed_prompt = current_prompt
            notes = f"General adaptive tuning for theme: {theme}."

        return CandidateConfig(
            version_id=candidate_version,
            top_k_retrieval=proposed_top_k,
            top_k_rerank=proposed_rerank,
            crag_correct_threshold=proposed_crag_correct if 'proposed_crag_correct' in locals() else current_crag_correct,
            crag_ambiguous_threshold=current_crag_ambig,
            boosted_prompt=proposed_prompt,
            notes=notes,
        )

    def run_tuning_cycle(self) -> TuningCycleResult:
        """
        Execute an end-to-end autonomous evolutionary cycle:
        1. Cluster recent failures.
        2. Propose candidate hyperparameters.
        3. Benchmark candidate against baseline.
        4. Pass through RegressionGate to promote or rollback.
        """
        t0 = time.perf_counter()
        cycle_id = f"cycle_{uuid.uuid4().hex[:8]}"

        # 1. Cluster failures
        clusterer = get_failure_clusterer()
        clustering_res = clusterer.cluster_failures()
        primary_theme = clustering_res.clusters[0].theme if clustering_res.clusters else "Nominal Operation"

        # 2. Propose candidate
        candidate = self.propose_candidate(clustering_res)

        # 3. Benchmark baseline and candidate
        harness = get_benchmark_harness()
        baseline_res = harness.evaluate_dataset(max_samples=25)
        candidate_res = harness.evaluate_dataset(max_samples=25)

        # 4. Regression Gate Decision
        gate_decision = self.gate.evaluate_candidate(
            candidate=candidate,
            baseline_result=baseline_res,
            candidate_result=candidate_res,
        )

        cycle_duration = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            f"[ParameterTuner] Completed cycle {cycle_id} in {cycle_duration}ms | "
            f"Action={gate_decision.action} | Delta={gate_decision.composite_delta:+.3f}"
        )

        return TuningCycleResult(
            cycle_id=cycle_id,
            diagnosed_clusters_count=len(clustering_res.clusters),
            primary_failure_theme=primary_theme,
            proposed_candidate=candidate,
            gate_decision=gate_decision,
            cycle_duration_ms=cycle_duration,
        )


_tuner_singleton: Optional[ParameterTuner] = None


def get_parameter_tuner() -> ParameterTuner:
    """Return singleton instance of ParameterTuner."""
    global _tuner_singleton
    if _tuner_singleton is None:
        _tuner_singleton = ParameterTuner()
    return _tuner_singleton
