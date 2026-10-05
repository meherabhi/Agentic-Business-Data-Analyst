"""Deterministic intent planner.

Maps a natural-language question to one of five analytical intents plus
parameters, using ordered keyword rules and a small vocabulary. There is no
LLM here. The point is to show the agent architecture (plan / act / observe /
reflect + tool use + guardrails) with a planner that is fully inspectable and
reproducible. A confidence score comes out of how strongly the rules matched,
and questions that reference something the schema cannot express (for example
a profit-margin metric that does not exist) resolve to an 'unsupported' intent
so the agent can fail honestly rather than fabricate SQL.

Intents: top_n, trend, comparison, aggregate, filter, unsupported.
"""
from __future__ import annotations

import re

# Recognised category vocabulary. "Accessories" is intentionally included even
# though the warehouse ships no such products, so a question about it produces
# a valid-but-empty result the agent must reflect on.
CATEGORY_VOCAB = {
    "electronics": "Electronics",
    "furniture": "Furniture",
    "office": "Office Supplies",
    "office supplies": "Office Supplies",
    "software": "Software",
    "accessories": "Accessories",
}

REGION_VOCAB = {"north": "North", "south": "South", "east": "East", "west": "West"}
SEGMENT_VOCAB = {"consumer": "Consumer", "smb": "SMB", "enterprise": "Enterprise"}

# Metrics the schema can actually express.
SUPPORTED_METRICS = {"revenue", "orders", "order", "sales", "quantity"}
# Metrics a user might ask for that the schema cannot express.
UNSUPPORTED_METRICS = {"margin", "profit", "churn", "retention", "ltv", "cac"}

_NUM_WORDS = {"three": 3, "five": 5, "ten": 10, "four": 4, "seven": 7}


def _extract_n(q: str, default: int = 5) -> int:
    m = re.search(r"top\s+(\d+)", q)
    if m:
        return int(m.group(1))
    for word, val in _NUM_WORDS.items():
        if re.search(rf"top\s+{word}\b", q):
            return val
    return default


def _find(vocab: dict, q: str):
    # longest key first so "office supplies" beats "office"
    for key in sorted(vocab, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", q):
            return vocab[key]
    return None


def plan(question: str) -> dict:
    """Return a plan dict: intent, params, confidence, rationale."""
    q = question.lower().strip()

    # Unsupported metric check comes first: if the user asks for a metric the
    # warehouse cannot compute, do not pretend otherwise.
    for m in UNSUPPORTED_METRICS:
        if re.search(rf"\b{m}\b", q):
            return {
                "intent": "unsupported",
                "params": {"metric": m},
                "confidence": 0.25,
                "rationale": f"metric '{m}' is not present in the warehouse schema",
            }

    region = _find(REGION_VOCAB, q)
    category = _find(CATEGORY_VOCAB, q)
    segment = _find(SEGMENT_VOCAB, q)

    # metric: default to revenue unless orders/count is clearly requested
    if re.search(r"\border(s|\b)|how many|count\b|number of", q):
        metric = "orders"
    else:
        metric = "revenue"

    # 1. top-N
    if re.search(r"\btop\b|\brank|\bbest|\bhighest\b", q):
        n = _extract_n(q)
        if "region" in q:
            dim = "region"
        elif "segment" in q or "customer type" in q:
            dim = "segment"
        elif "categor" in q:
            dim = "category"
        else:
            dim = "product"
        return {
            "intent": "top_n",
            "params": {"n": n, "dimension": dim, "metric": metric},
            "confidence": 0.94,
            "rationale": f"top-{n} ranking of {dim} by {metric}",
        }

    # 2. trend over time
    if re.search(r"\btrend|over time|monthly|quarterly|by month|by quarter|over the year", q):
        grain = "quarter" if re.search(r"quarter", q) else "month"
        return {
            "intent": "trend",
            "params": {"grain": grain, "metric": metric},
            "confidence": 0.9,
            "rationale": f"{metric} trend by {grain}",
        }

    # 3. comparison across a dimension
    if re.search(r"\bcompare|comparison|across|by region|by segment|versus|vs\b", q):
        dim = "region" if (region or "region" in q) else ("segment" if ("segment" in q or segment) else "region")
        return {
            "intent": "comparison",
            "params": {"dimension": dim, "metric": metric},
            "confidence": 0.88,
            "rationale": f"compare {metric} across {dim}",
        }

    # 4. filter (region and/or category), often "list / show orders in ..."
    if region or category:
        return {
            "intent": "filter",
            "params": {"region": region, "category": category, "metric": metric},
            "confidence": 0.82,
            "rationale": "filtered slice: "
            + ", ".join(x for x in [region, category] if x),
        }

    # 5. plain aggregate
    if re.search(r"total|average|avg|mean|sum|overall|how much", q):
        agg = "avg" if re.search(r"average|avg|mean", q) else "sum"
        return {
            "intent": "aggregate",
            "params": {"agg": agg, "metric": metric},
            "confidence": 0.86,
            "rationale": f"{agg} of {metric} across all orders",
        }

    # fallback: low-confidence aggregate
    return {
        "intent": "aggregate",
        "params": {"agg": "sum", "metric": metric},
        "confidence": 0.4,
        "rationale": "no strong intent match; defaulting to total revenue",
    }
