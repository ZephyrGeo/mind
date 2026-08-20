"""Persistence interfaces used by API services."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import AgentMode, Attachment, Conversation, ConversationSummary, Memory


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

    def delete_for_user(self, user_id: str) -> None:
        """Delete every conversation owned by exactly one user."""

        ...

    def append_exchange(
        self,
        conversation_id: UUID | str | None,
        user_message: str,
        assistant_message: str,
        mode: AgentMode | str,
        *,
        user_id: str,
        attachment_ids: list[UUID] | None = None,
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
        attachment_ids: list[UUID] | None = None,
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


class AttachmentRepository(Protocol):
    def list_attachments(self, user_id: str) -> list[Attachment]:
        """Return attachment metadata owned by exactly one user."""

        ...

    def get_attachment(
        self,
        attachment_id: UUID | str,
        user_id: str,
    ) -> Attachment:
        """Return one owned attachment or raise AttachmentNotFoundError."""

        ...

    def create_attachment(self, attachment: Attachment) -> Attachment:
        """Create attachment metadata with a unique ID."""

        ...

    def save_attachment(self, attachment: Attachment, user_id: str) -> Attachment:
        """Persist an owned attachment state transition."""

        ...

    def delete_attachment(self, attachment_id: UUID | str, user_id: str) -> None:
        """Delete one owned attachment metadata record."""

        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete every attachment metadata record owned by one user."""

        ...


class MemoryRepository(Protocol):
    def list_memories(self, user_id: str) -> list[Memory]:
        """Return every Memory Ledger entry owned by exactly one user."""

        ...

    def get_memory(self, memory_id: UUID | str, user_id: str) -> Memory:
        """Return one owned memory or raise MemoryNotFoundError."""

        ...

    def create_memory(self, memory: Memory) -> Memory:
        """Create a memory with a unique ID."""

        ...

    def upsert_memory(self, memory: Memory) -> Memory:
        """Idempotently persist an extracted memory candidate."""

        ...

    def save_memory(self, memory: Memory, user_id: str) -> Memory:
        """Persist a user-controlled change to an owned memory."""

        ...

    def memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
    ) -> tuple[str, list[float]] | None:
        """Return the stored embedding model and vector, if present."""

        ...

    def save_memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
        *,
        model: str,
        vector: list[float],
    ) -> None:
        """Persist an embedding without exposing it through the public model."""

        ...

    def find_similar_memories(
        self,
        user_id: str,
        vector: list[float],
        *,
        limit: int,
    ) -> list[tuple[Memory, float]]:
        """Return nearest memories with cosine similarity in descending order."""

        ...

    def delete_memory(self, memory_id: UUID | str, user_id: str) -> None:
        """Permanently delete one owned memory."""

        ...

    def delete_for_user(self, user_id: str) -> None:
        """Delete every memory owned by one user."""

        ...
