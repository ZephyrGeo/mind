"""Atomic JSON implementation of the conversation repository."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AgentMode, Conversation, ConversationSummary


LOCAL_USER_ID = "local-developer"


class ConversationNotFoundError(LookupError):
    """Raised when a conversation is absent or belongs to another user."""


class JsonConversationRepository:
    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.file_path.exists():
            return {"conversations": []}
        with self.file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.file_path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, self.file_path)

    @staticmethod
    def _to_conversation_model(
        conversation: dict[str, Any],
    ) -> Conversation:
        """Normalize milestone-one records without mutating persisted content."""

        conversation_id = str(conversation["id"])
        fallback_created_at = conversation.get(
            "created_at",
            conversation.get("updated_at"),
        )
        normalized_messages = []
        for index, message in enumerate(conversation.get("messages", [])):
            normalized_message = dict(message)
            normalized_message.setdefault(
                "id",
                str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"mind:{conversation_id}:message:{index}",
                    )
                ),
            )
            normalized_message.setdefault(
                "conversation_id",
                conversation_id,
            )
            normalized_message.setdefault("created_at", fallback_created_at)
            normalized_messages.append(normalized_message)

        normalized_conversation = {
            **conversation,
            "user_id": conversation.get("user_id") or LOCAL_USER_ID,
            "mode": conversation.get("mode") or AgentMode.CHAT.value,
            "messages": normalized_messages,
        }
        return Conversation.model_validate(normalized_conversation)

    def list_conversations(
        self,
        user_id: str = LOCAL_USER_ID,
    ) -> list[ConversationSummary]:
        with self._lock:
            conversations = [
                conversation
                for conversation in self._read()["conversations"]
                if conversation.get("user_id", LOCAL_USER_ID) == user_id
            ]
            ordered = sorted(
                conversations,
                key=lambda conversation: conversation["updated_at"],
                reverse=True,
            )
            return [
                ConversationSummary(
                    id=conversation["id"],
                    title=conversation["title"],
                    updated_at=conversation["updated_at"],
                    message_count=len(conversation["messages"]),
                )
                for conversation in ordered
            ]

    def get_conversation(
        self,
        conversation_id: uuid.UUID | str,
        user_id: str = LOCAL_USER_ID,
    ) -> Conversation:
        requested_id = str(conversation_id)
        with self._lock:
            conversation = next(
                (
                    item
                    for item in self._read()["conversations"]
                    if item["id"] == requested_id
                    and item.get("user_id", LOCAL_USER_ID) == user_id
                ),
                None,
            )
            if conversation is None:
                raise ConversationNotFoundError(
                    "Conversation does not exist for this user."
                )
            return self._to_conversation_model(conversation)

    def delete_conversation(
        self,
        conversation_id: uuid.UUID | str,
        user_id: str = LOCAL_USER_ID,
    ) -> None:
        requested_id = str(conversation_id)
        with self._lock:
            payload = self._read()
            conversations = payload["conversations"]
            conversation_index = next(
                (
                    index
                    for index, item in enumerate(conversations)
                    if item["id"] == requested_id
                    and item.get("user_id", LOCAL_USER_ID) == user_id
                ),
                None,
            )
            if conversation_index is None:
                raise ConversationNotFoundError(
                    "Conversation does not exist for this user."
                )
            conversations.pop(conversation_index)
            self._write(payload)

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            payload = self._read()
            payload["conversations"] = [
                conversation
                for conversation in payload["conversations"]
                if conversation.get("user_id", LOCAL_USER_ID) != user_id
            ]
            self._write(payload)

    def append_exchange(
        self,
        conversation_id: uuid.UUID | str | None,
        user_message: str,
        assistant_message: str,
        mode: AgentMode | str,
        *,
        user_id: str = LOCAL_USER_ID,
    ) -> str:
        with self._lock:
            payload = self._read()
            conversations = payload["conversations"]
            requested_id = str(conversation_id) if conversation_id else None
            conversation = next(
                (
                    item
                    for item in conversations
                    if requested_id
                    and item["id"] == requested_id
                    and item.get("user_id", LOCAL_USER_ID) == user_id
                ),
                None,
            )
            if requested_id and conversation is None:
                raise ConversationNotFoundError(
                    "Conversation does not exist for this user."
                )

            now = datetime.now(timezone.utc).isoformat()
            if conversation is None:
                requested_id = str(uuid.uuid4())
                title = user_message.strip().replace("\n", " ")[:56] or "New conversation"
                conversation = {
                    "id": requested_id,
                    "user_id": user_id,
                    "title": title,
                    "created_at": now,
                    "updated_at": now,
                    "mode": AgentMode(mode).value,
                    "messages": [],
                }
                conversations.append(conversation)

            conversation["messages"].extend(
                [
                    {
                        "id": str(uuid.uuid4()),
                        "conversation_id": requested_id,
                        "role": "user",
                        "content": user_message,
                        "created_at": now,
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "conversation_id": requested_id,
                        "role": "assistant",
                        "content": assistant_message,
                        "created_at": now,
                    },
                ]
            )
            conversation["updated_at"] = now
            self._write(payload)
            return str(requested_id)

    def append_user_message(
        self,
        conversation_id: uuid.UUID | str | None,
        content: str,
        mode: AgentMode | str,
        *,
        user_id: str = LOCAL_USER_ID,
    ) -> str:
        with self._lock:
            payload = self._read()
            conversations = payload["conversations"]
            requested_id = str(conversation_id) if conversation_id else None
            conversation = next(
                (
                    item
                    for item in conversations
                    if requested_id
                    and item["id"] == requested_id
                    and item.get("user_id", LOCAL_USER_ID) == user_id
                ),
                None,
            )
            if requested_id and conversation is None:
                raise ConversationNotFoundError(
                    "Conversation does not exist for this user."
                )

            now = datetime.now(timezone.utc).isoformat()
            if conversation is None:
                requested_id = str(uuid.uuid4())
                conversation = {
                    "id": requested_id,
                    "user_id": user_id,
                    "title": content.strip().replace("\n", " ")[:56]
                    or "New research",
                    "created_at": now,
                    "updated_at": now,
                    "mode": AgentMode(mode).value,
                    "messages": [],
                }
                conversations.append(conversation)

            conversation["messages"].append(
                {
                    "id": str(uuid.uuid4()),
                    "conversation_id": requested_id,
                    "role": "user",
                    "content": content,
                    "created_at": now,
                }
            )
            conversation["updated_at"] = now
            self._write(payload)
            return str(requested_id)

    def append_assistant_message(
        self,
        conversation_id: uuid.UUID | str,
        content: str,
        *,
        user_id: str = LOCAL_USER_ID,
        research_job_id: uuid.UUID | str | None = None,
    ) -> str:
        requested_id = str(conversation_id)
        requested_job_id = (
            str(research_job_id) if research_job_id is not None else None
        )
        with self._lock:
            payload = self._read()
            conversation = next(
                (
                    item
                    for item in payload["conversations"]
                    if item["id"] == requested_id
                    and item.get("user_id", LOCAL_USER_ID) == user_id
                ),
                None,
            )
            if conversation is None:
                raise ConversationNotFoundError(
                    "Conversation does not exist for this user."
                )
            if requested_job_id is not None:
                existing = next(
                    (
                        message
                        for message in conversation["messages"]
                        if message.get("research_job_id") == requested_job_id
                    ),
                    None,
                )
                if existing is not None:
                    if content and existing.get("content") != content:
                        existing["content"] = content
                        conversation["updated_at"] = (
                            datetime.now(timezone.utc).isoformat()
                        )
                        self._write(payload)
                    return str(existing["id"])

            now = datetime.now(timezone.utc).isoformat()
            message_id = str(uuid.uuid4())
            message = {
                "id": message_id,
                "conversation_id": requested_id,
                "role": "assistant",
                "content": content,
                "created_at": now,
            }
            if requested_job_id is not None:
                message["research_job_id"] = requested_job_id
            conversation["messages"].append(message)
            conversation["updated_at"] = now
            self._write(payload)
            return message_id


# Preserve the milestone-one import while callers migrate to the repository name.
ConversationStore = JsonConversationRepository
