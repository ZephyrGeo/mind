"""Deterministic local agent used before connecting a billable model."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator


class FakeAgent:
    """Produces stable, streamable replies for local development and CI."""

    def __init__(self, delay_seconds: float = 0.018) -> None:
        self.delay_seconds = delay_seconds

    def create_reply(self, message: str, mode: str = "chat") -> str:
        normalized = message.strip()
        if mode == "research":
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
            "streaming transport, and local persistence. The Gemini provider can be connected "
            "later behind the same interface without changing the chat experience."
        )

    def stream_reply(self, message: str, mode: str = "chat") -> Iterator[str]:
        reply = self.create_reply(message, mode)
        for token in re.findall(r"\S+\s*|\n", reply):
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            yield token
