"""
RAG Evaluation Pipeline.

Uses RAGAS to compute standard RAG metrics on a test dataset.

Metrics:
  - faithfulness     (answer supported by context)
  - answer_relevancy (answer addresses the question)
  - context_recall   (context covers ground truth)
  - context_precision (retrieved context is precise)

Usage:
    python -m evaluation.rag_evaluator --dataset eval_dataset.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_recall,
        context_precision,
    )
    RAGAS_AVAILABLE = True
except ImportError:
    RAGAS_AVAILABLE = False
    logger.warning("RAGAS not installed. Evaluation will use simplified metrics.")


# ── Simplified fallback metrics ───────────────────────────────────────────────

def _simple_faithfulness(answer: str, contexts: list[str]) -> float:
    """Rough faithfulness: fraction of answer sentences that overlap with context."""
    if not contexts or not answer:
        return 0.0
    context_text = " ".join(contexts).lower()
    sentences = [s.strip() for s in answer.split(".") if s.strip()]
    if not sentences:
        return 0.0
    supported = sum(
        1 for s in sentences
        if any(word in context_text for word in s.lower().split() if len(word) > 4)
    )
    return round(supported / len(sentences), 3)


def _simple_relevancy(question: str, answer: str) -> float:
    """Rough relevancy: keyword overlap between question and answer."""
    if not question or not answer:
        return 0.0
    q_words = set(question.lower().split())
    a_words = set(answer.lower().split())
    overlap = q_words & a_words
    return round(len(overlap) / max(len(q_words), 1), 3)


# ── Main evaluation logic ─────────────────────────────────────────────────────

def evaluate_rag(
    questions: list[str],
    answers: list[str],
    contexts: list[list[str]],
    ground_truths: list[str] | None = None,
) -> dict[str, Any]:
    """
    Evaluate RAG pipeline outputs.

    Args:
        questions:     List of user questions.
        answers:       Corresponding generated answers.
        contexts:      List of context chunk lists per question.
        ground_truths: Optional reference answers for recall metrics.

    Returns:
        Dict of metric names to scores.
    """
    if RAGAS_AVAILABLE and ground_truths:
        logger.info("Running full RAGAS evaluation …")
        data = {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
        dataset = Dataset.from_dict(data)
        metrics = [faithfulness, answer_relevancy, context_recall, context_precision]
        result = evaluate(dataset, metrics=metrics)
        return dict(result)
    else:
        logger.info("Running simplified evaluation (RAGAS unavailable or no ground truth).")
        faithfulness_scores = [
            _simple_faithfulness(a, c) for a, c in zip(answers, contexts)
        ]
        relevancy_scores = [
            _simple_relevancy(q, a) for q, a in zip(questions, answers)
        ]
        return {
            "faithfulness": round(sum(faithfulness_scores) / len(faithfulness_scores), 3),
            "answer_relevancy": round(sum(relevancy_scores) / len(relevancy_scores), 3),
            "num_samples": len(questions),
        }


def evaluate_from_feedback(feedback_path: str) -> dict[str, Any]:
    """
    Evaluate using stored feedback records.

    Loads the feedback JSON and computes evaluation metrics on all records
    that have context chunks.

    Args:
        feedback_path: Path to feedback.json.

    Returns:
        Evaluation results dict.
    """
    path = Path(feedback_path)
    if not path.exists():
        logger.warning(f"Feedback file not found: {feedback_path}")
        return {}

    with open(path) as f:
        records = json.load(f)

    if not records:
        logger.warning("No feedback records to evaluate.")
        return {}

    questions = [r["question"] for r in records]
    answers = [r["answer"] for r in records]
    contexts = [
        [c.get("chunk_id", "") for c in r.get("context_chunks", [])]
        for r in records
    ]

    # Simple accuracy from user feedback
    correct = sum(1 for r in records if r.get("is_correct", False))
    accuracy = round(correct / len(records), 3)

    result = evaluate_rag(questions, answers, contexts)
    result["user_feedback_accuracy"] = accuracy
    result["total_samples"] = len(records)

    logger.info(f"Evaluation complete: {result}")
    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG Evaluator")
    parser.add_argument(
        "--feedback",
        type=str,
        default="./vector_db/feedback.json",
        help="Path to feedback.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./evaluation/report.json",
        help="Path to save evaluation report",
    )
    args = parser.parse_args()

    results = evaluate_from_feedback(args.feedback)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print("RAG Evaluation Report")
    print(f"{'='*50}")
    for metric, score in results.items():
        print(f"  {metric:<35} {score}")
    print(f"\nReport saved to: {output_path}")
