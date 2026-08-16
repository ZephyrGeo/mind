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

    def append_user_message(
        self,
        conversation_id: UUID | str | None,
        content: str,
        mode: AgentMode | str,
        *,
        user_id: str,
    ) -> str:
        """Persist the user side of a long-running turn and return its conversation."""

        ...

    def append_assistant_message(
        self,
        conversation_id: UUID | str,
        content: str,
        *,
        user_id: str,
        research_job_id: UUID | str | None = None,
    ) -> str:
        """Persist one assistant message, idempotently for a research job."""

        ...
