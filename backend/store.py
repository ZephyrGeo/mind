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

from .models import AgentMode, ConversationSummary


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


# Preserve the milestone-one import while callers migrate to the repository name.
ConversationStore = JsonConversationRepository
