"""Deterministic local agent used before connecting a billable model."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, Sequence

from .models import AgentMode, ModelMessage


class FakeAgentProvider:
    """Produces stable, streamable replies for local development and CI."""

    name = "fake"
    billable_model_calls = False

    def __init__(self, delay_seconds: float = 0.018) -> None:
        self.delay_seconds = delay_seconds

    def create_reply(
        self,
        message: str,
        mode: AgentMode | str = AgentMode.CHAT,
    ) -> str:
        normalized = message.strip()
        if mode == AgentMode.RESEARCH:
            return (
                "I’m running in local research simulation mode, so no external model or "
                "search service was called.\n\n"
                f"For “{normalized}”, I would begin with three steps:\n"
                "1. Define the decision the report needs to support.\n"
                "2. Gather independent sources and record evidence for each claim.\n"
                "3. Challenge the first conclusion, then publish a cited report with open questions.\n\n"
                "The next implementation phase will replace this deterministic response with the "
                "checkpointed Deep Research workflow."
            )

        return (
            "I’m Mind’s local Fake Agent. Your message reached the Python API and this "
            "reply is being streamed back to the React interface without calling an external model.\n\n"
            f"You asked: “{normalized}”\n\n"
            "This first vertical slice proves the conversation path, authentication boundary, "
            "streaming transport, and local persistence. A hosted provider can be selected "
            "behind the same interface without changing the chat experience."
        )

    def stream_reply(
        self,
        message: str,
        mode: AgentMode | str = AgentMode.CHAT,
        *,
        history: Sequence[ModelMessage] = (),
        memory_context: str = "",
    ) -> Iterator[str]:
        del history
        reply = self.create_reply(message, mode)
        if memory_context:
            remembered = next(
                (
                    line.removeprefix("- ").strip()
                    for line in memory_context.splitlines()
                    if line.startswith("- ")
                ),
                "confirmed Memory Ledger context",
            )
            reply = f"I used this relevant memory: {remembered}\n\n{reply}"
        for token in re.findall(r"\S+\s*|\n", reply):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            yield token


# Backward-compatible name for evaluation fixtures and external local imports.
FakeAgent = FakeAgentProvider
