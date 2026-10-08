"""Deterministic narrative compaction with source provenance."""

from __future__ import annotations

import hashlib
from typing import Any


def estimate_tokens(text: str) -> int:
    """Return a conservative, deterministic token estimate without a model tokenizer."""
    return max(1, (len(text) + 3) // 4)


def compact_narrative(items: list[str], token_budget: int) -> dict[str, Any]:
    """Keep recent narrative verbatim and summarize only older items when over budget."""
    if token_budget < 32:
        raise ValueError("token budget must be at least 32")
    cleaned = [item.strip() for item in items if item.strip()]
    total = sum(estimate_tokens(item) for item in cleaned)
    if total <= token_budget:
        return {
            "summary": None,
            "recent": cleaned,
            "estimated_tokens": total,
            "provenance": {
                "method": "none",
                "summarized_items": 0,
                "source_hashes": [],
                "original_estimated_tokens": total,
            },
        }

    recent_budget = token_budget * 2 // 3
    if estimate_tokens(cleaned[-1]) > recent_budget:
        raise ValueError("most recent narrative item exceeds the context budget")
    recent: list[str] = []
    recent_tokens = 0
    split_at = len(cleaned)
    for index in range(len(cleaned) - 1, -1, -1):
        item_tokens = estimate_tokens(cleaned[index])
        if recent and recent_tokens + item_tokens > recent_budget:
            break
        recent.insert(0, cleaned[index])
        recent_tokens += item_tokens
        split_at = index

    older = cleaned[:split_at]
    summary_budget = max(1, token_budget - recent_tokens)
    summary_words: list[str] = []
    for item in older:
        first_sentence = item.split(".", 1)[0].strip()
        summary_words.extend(first_sentence.split()[:12])
    summary = " ".join(summary_words)[: summary_budget * 4].strip()
    return {
        "summary": summary or "Earlier narrative entries were compacted.",
        "recent": recent,
        "estimated_tokens": min(
            token_budget,
            estimate_tokens(summary or "Earlier narrative entries were compacted.") + recent_tokens,
        ),
        "provenance": {
            "method": "deterministic_first_sentence_v1",
            "summarized_items": len(older),
            "source_hashes": [hashlib.sha256(item.encode()).hexdigest() for item in older],
            "original_estimated_tokens": total,
        },
    }
