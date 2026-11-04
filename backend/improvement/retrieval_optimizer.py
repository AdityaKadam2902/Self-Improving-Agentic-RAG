"""
Retrieval Optimizer.

Analyses bad-retrieval failures and produces:
  1. Boosted keywords for future queries on the same topic.
  2. An optimised system prompt for prompt-issue failures.

Both outputs are persisted in the feedback DB and loaded at query time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from langchain_groq import ChatGroq

from backend.config import get_settings
from backend.improvement.feedback_collector import get_incorrect_records, _load_db, _save_db


# ── Path for optimized artifacts ─────────────────────────────────────────────

def _optimizer_path() -> Path:
    settings = get_settings()
    p = Path(settings.feedback_db_path).parent / "optimizer_state.json"
    return p


def _load_state() -> dict:
    p = _optimizer_path()
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"keyword_boosts": {}, "best_prompt": None}


def _save_state(state: dict) -> None:
    p = _optimizer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def get_boosted_keywords(query: str) -> list[str]:
    """
    Return boosted keywords for a query based on past failures.

    Simple strategy: for each bad-retrieval failure whose question overlaps
    with the current query, return the stored expanded keywords.
    """
    state = _load_state()
    boosts = state.get("keyword_boosts", {})
    query_lower = query.lower()
    accumulated: list[str] = []
    for key, keywords in boosts.items():
        if any(word in query_lower for word in key.lower().split()):
            accumulated.extend(keywords)
    return list(set(accumulated))


def get_optimized_prompt() -> str | None:
    """Return the current best system prompt, or None to use the default."""
    state = _load_state()
    return state.get("best_prompt")


def run_optimization() -> dict:
    """
    Run one optimization cycle:
      1. Find bad_retrieval failures → generate keyword expansions.
      2. Find prompt_issue failures → generate improved prompt.

    Returns:
        Summary dict of actions taken.
    """
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.3,
        max_tokens=512,
    )

    incorrect = get_incorrect_records(limit=20)
    state = _load_state()
    actions: dict = {"keyword_boosts_added": 0, "prompt_updated": False}

    # ── Keyword expansion for bad_retrieval ──────────────────────────────────
    bad_retrieval = [r for r in incorrect if r.get("failure_type") == "bad_retrieval"]

    for record in bad_retrieval:
        question = record["question"]
        key = " ".join(question.lower().split()[:5])  # 5-word key

        if key in state["keyword_boosts"]:
            continue  # already processed

        prompt = (
            "Generate 5 synonym/expansion keywords that would help retrieve context "
            f"relevant to: '{question}'\n"
            "Return ONLY a JSON array of strings, e.g. [\"term1\", \"term2\"]"
        )
        try:
            response = llm.invoke([("human", prompt)])
            raw = re.sub(r"```(?:json)?", "", response.content.strip()).strip().strip("`")
            keywords = json.loads(raw)
            if isinstance(keywords, list):
                state["keyword_boosts"][key] = keywords
                actions["keyword_boosts_added"] += 1
                logger.info(f"[Optimizer] Added keyword boosts for '{key}': {keywords}")
        except Exception as exc:
            logger.warning(f"[Optimizer] Keyword expansion failed: {exc}")

    # ── Prompt optimisation for prompt_issue ────────────────────────────────
    prompt_issues = [r for r in incorrect if r.get("failure_type") == "prompt_issue"]

    if len(prompt_issues) >= 2:
        examples = "\n\n".join(
            f"Q: {r['question']}\nWrong answer: {r['answer']}"
            for r in prompt_issues[:3]
        )
        prompt = (
            "You are a prompt engineer for a RAG system. "
            "The following questions were answered incorrectly due to prompt issues:\n\n"
            f"{examples}\n\n"
            "Write an improved system prompt (3-5 sentences) that would prevent these errors. "
            "Return ONLY the system prompt text."
        )
        try:
            response = llm.invoke([("human", prompt)])
            new_prompt = response.content.strip()
            state["best_prompt"] = new_prompt
            actions["prompt_updated"] = True
            logger.info(f"[Optimizer] Updated system prompt ({len(new_prompt)} chars)")
        except Exception as exc:
            logger.warning(f"[Optimizer] Prompt optimisation failed: {exc}")

    _save_state(state)
    return actions
