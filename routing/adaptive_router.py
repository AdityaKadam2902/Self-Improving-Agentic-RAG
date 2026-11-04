"""
Adaptive Intent and Complexity Router.

Analyzes query semantics and conversation state to route requests to the most
cost-effective execution tier:
  - Tier 1 (direct): Bypasses retrieval for conversational, greeting, or pure parametric queries.
  - Tier 2 (single_hop): Standard hybrid retrieval and reranking for document Q&A.
  - Tier 3 (multi_hop): Decomposes multi-part and comparative queries into parallel sub-searches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("adaptive_router")

from backend.config import get_settings


@dataclass
class RouteDecision:
    route: str  # "direct" | "single_hop" | "multi_hop"
    reasoning: str
    sub_queries: List[str] = field(default_factory=list)
    estimated_complexity: int = 1  # 1 (simplest) to 5 (most complex)
    requires_retrieval: bool = True


# Fast heuristic pattern matchers for instant deterministic routing (<1ms)
_DIRECT_CONVERSATIONAL_PATTERNS = [
    re.compile(r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|howdy)\b.*$", re.IGNORECASE),
    re.compile(r"\bhow\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"^(?:who\s+are\s+you|what\s+can\s+you\s+do|what\s+is\s+your\s+name|help)\b[!?.]*$", re.IGNORECASE),
    re.compile(r"^(?:thanks|thank\s+you|great|awesome|bye|goodbye)\b[!?.]*$", re.IGNORECASE),
    re.compile(r"^(?:what\s+is\s+\d+\s*[\+\-\*\/]\s*\d+)\b[!?.]*$", re.IGNORECASE),  # simple math
]

_MULTI_HOP_COMPARISON_PATTERNS = [
    re.compile(r"\bcompare\b", re.IGNORECASE),
    re.compile(r"\bdifference(?:s)?\s+between\b", re.IGNORECASE),
    re.compile(r"\bhow\s+does\s+.+\s+differ\s+from\b", re.IGNORECASE),
    re.compile(r"\bboth\s+.+\s+and\s+.+\b", re.IGNORECASE),
    re.compile(r"\bacross\s+(?:all|both|different)\s+(?:documents|files|reports)\b", re.IGNORECASE),
    re.compile(r"\bversus\b|\bvs\.?\b", re.IGNORECASE),
]


def classify_query_route(
    query: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    use_llm_classifier: bool = False,
) -> RouteDecision:
    """
    Classify query into an execution tier (direct, single_hop, multi_hop).
    Uses fast deterministic heuristics first, falling back to LLM intent classification if enabled.
    """
    clean_query = query.strip()

    # 1. Check for Direct Conversational / Parametric queries
    for pattern in _DIRECT_CONVERSATIONAL_PATTERNS:
        if pattern.search(clean_query):
            logger.info(f"[AdaptiveRouter] Route: DIRECT (heuristic match) | query='{clean_query[:50]}'")
            return RouteDecision(
                route="direct",
                reasoning="Query is conversational, greeting, or simple math not requiring document retrieval.",
                sub_queries=[],
                estimated_complexity=1,
                requires_retrieval=False,
            )

    # 2. Check for Multi-Hop / Comparative queries
    for pattern in _MULTI_HOP_COMPARISON_PATTERNS:
        if pattern.search(clean_query):
            sub_queries = _extract_heuristic_sub_queries(clean_query)
            logger.info(f"[AdaptiveRouter] Route: MULTI_HOP ({len(sub_queries)} sub-queries) | query='{clean_query[:50]}'")
            return RouteDecision(
                route="multi_hop",
                reasoning="Query requires multi-hop comparative reasoning across multiple topics or documents.",
                sub_queries=sub_queries,
                estimated_complexity=4,
                requires_retrieval=True,
            )

    # 3. Optional LLM-assisted classification for nuanced intent
    if use_llm_classifier:
        decision = _classify_with_llm(clean_query, conversation_history)
        if decision:
            return decision

    # 4. Default to Single-Hop Standard RAG
    logger.info(f"[AdaptiveRouter] Route: SINGLE_HOP (default document QA) | query='{clean_query[:50]}'")
    return RouteDecision(
        route="single_hop",
        reasoning="Standard factual question targeted at indexed document context.",
        sub_queries=[clean_query],
        estimated_complexity=2,
        requires_retrieval=True,
    )


def _extract_heuristic_sub_queries(query: str) -> List[str]:
    """
    Heuristically decompose a comparative query into two or more focused search queries.
    """
    # Pattern 1: compare X and/with/to/versus Y
    compare_match = re.search(r"compare\s+(.+?)\s+(?:and|with|to|versus|vs\.?)\s+(.+)", query, re.IGNORECASE)
    if compare_match:
        part_a = compare_match.group(1).strip()
        part_b = compare_match.group(2).strip()
        return [f"Details and metrics for {part_a}", f"Details and metrics for {part_b}"]

    # Pattern 2: difference between X and Y
    diff_match = re.search(r"difference(?:s)?\s+between\s+(.+?)\s+and\s+(.+)", query, re.IGNORECASE)
    if diff_match:
        part_a = diff_match.group(1).strip()
        part_b = diff_match.group(2).strip()
        return [f"Details for {part_a}", f"Details for {part_b}"]

    # Pattern 3: X versus Y
    vs_match = re.search(r"(.+?)\s+(?:versus|vs\.?)\s+(.+)", query, re.IGNORECASE)
    if vs_match:
        part_a = vs_match.group(1).strip()
        part_b = vs_match.group(2).strip()
        return [f"Details for {part_a}", f"Details for {part_b}"]

    # Fallback to original query
    return [query]


def _classify_with_llm(
    query: str,
    conversation_history: Optional[List[Dict[str, Any]]],
) -> Optional[RouteDecision]:
    """Optional LLM classification pass for complex queries."""
    settings = get_settings()
    if not settings.groq_api_key:
        return None

    try:
        from langchain_groq import ChatGroq
        import json

        llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=150,
        )

        prompt = (
            "Classify the following question for a document intelligence system into one tier:\n"
            "- direct: conversational pleasantry, greeting, or simple math\n"
            "- single_hop: factual question answerable from one document section\n"
            "- multi_hop: comparative or complex question requiring synthesis across multiple documents\n\n"
            f"Question: {query}\n\n"
            "Respond ONLY with valid JSON: {\"route\": \"direct|single_hop|multi_hop\", \"complexity\": 1-5, \"reasoning\": \"brief string\"}"
        )

        resp = llm.invoke([("human", prompt)])
        content = resp.content.strip().strip("`").replace("json", "").strip()
        data = json.loads(content)
        route = data.get("route", "single_hop")

        return RouteDecision(
            route=route,
            reasoning=data.get("reasoning", "LLM classified route"),
            sub_queries=[query] if route != "multi_hop" else _extract_heuristic_sub_queries(query),
            estimated_complexity=int(data.get("complexity", 2)),
            requires_retrieval=route != "direct",
        )
    except Exception as exc:
        logger.warning(f"[AdaptiveRouter] LLM classifier fallback ({exc}), using heuristic.")
        return None
