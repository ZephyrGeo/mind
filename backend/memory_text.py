"""Shared text normalization rules for Memory extraction and lifecycle checks."""

from __future__ import annotations

import re


def is_memory_question(value: str) -> bool:
    """Return whether a bounded statement is phrased as a question."""

    normalized = value.strip().casefold()
    if normalized.endswith(("?", "？")):
        return True
    return bool(
        re.match(
            r"^(?:什么|谁|哪|如何|怎么|为什么|是否|能否|可以吗|"
            r"what|who|which|how|why|do |does |did |is |are |can |could |would )",
            normalized,
        )
    )


def normalize_memory_text(value: str) -> str:
    """Normalize text for exact matching and stable Memory keys."""

    return re.sub(r"[^\w\u3400-\u9fff]+", "", value.casefold())
