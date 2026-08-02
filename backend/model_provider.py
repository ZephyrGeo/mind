"""Replaceable model provider boundary for the Agent Kernel."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from .models import AgentMode


class ModelProvider(Protocol):
    """The minimal streaming contract implemented by Fake and Gemini providers."""

    name: str
    billable_model_calls: bool

    def stream_reply(self, message: str, mode: AgentMode) -> Iterator[str]:
        """Yield ordered text deltas for a single assistant response."""

        ...
