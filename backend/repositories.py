"""Persistence interfaces used by API services."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import AgentMode, Conversation, ConversationSummary


class ConversationRepository(Protocol):
    def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        """Return summaries visible to exactly one user."""

        ...

    def get_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> Conversation:
        """Return one complete conversation visible to exactly one user."""

        ...

    def delete_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> None:
        """Permanently delete one conversation owned by exactly one user."""

        ...

    def append_exchange(
        self,
        conversation_id: UUID | str | None,
        user_message: str,
        assistant_message: str,
        mode: AgentMode | str,
        *,
        user_id: str,
    ) -> str:
        """Atomically persist a user/assistant exchange and return its conversation ID."""

        ...
