"""Replaceable model provider boundary for the Agent Kernel."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol

from .models import AgentMode, ModelMessage


class ModelProvider(Protocol):
    """The minimal streaming contract implemented by local and hosted providers."""

    name: str
    billable_model_calls: bool

    def stream_reply(
        self,
        message: str,
        mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
    ) -> Iterator[str]:
        """Yield ordered text deltas for a single assistant response."""

        ...


class ModelProviderError(RuntimeError):
    """Safe, provider-independent failure surfaced after streaming has begun."""

    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable
