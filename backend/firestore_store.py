"""Firestore repositories for tenant-isolated conversations and Research jobs."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from .memory_embedding import coerce_float_list, cosine_similarity
from .memory_store import MemoryNotFoundError
from .file_store import AttachmentNotFoundError
from .models import (
    AgentMode,
    Attachment,
    Conversation,
    ConversationSummary,
    Memory,
    Message,
    MessageRole,
    ResearchJob,
    ResearchStatus,
)
from .research_store import ResearchJobNotFoundError
from .store import ConversationNotFoundError


TransactionFactory = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_document(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _public_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"embedding", "vector_distance"}
    }


def _vector_values(value: object) -> list[float]:
    raw = getattr(value, "value", value)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return coerce_float_list(cast(Sequence[object], raw)) or []


class _FirestoreRepository:
    """Shared Firestore client and safe recursive-deletion helpers."""

    def __init__(
        self,
        *,
        project_id: str,
        database_id: str = "(default)",
        client: Any | None = None,
        transactional: TransactionFactory | None = None,
        descending: Any = "DESCENDING",
    ) -> None:
        if client is None:
            try:
                from google.cloud import firestore
            except ImportError as error:  # pragma: no cover - packaging guard
                raise RuntimeError(
                    "google-cloud-firestore is required when "
                    "MIND_PERSISTENCE_PROVIDER=firestore."
                ) from error
            client = firestore.Client(
                project=project_id,
                database=database_id,
            )
            transactional = firestore.transactional
            descending = firestore.Query.DESCENDING
        if transactional is None:
            raise ValueError("A transactional adapter is required with a custom client.")

        self.client = client
        self._transactional = transactional
        self._descending = descending

    def _user(self, user_id: str) -> Any:
        return self.client.collection("users").document(user_id)

    def _run_transaction(self, operation: Callable[[Any], Any]) -> Any:
        return self._transactional(operation)(self.client.transaction())

    @staticmethod
    def _require_owned_document(
        snapshot: Any,
        *,
        user_id: str,
        error: type[LookupError],
        message: str,
    ) -> dict[str, Any]:
        payload = snapshot.to_dict() if snapshot.exists else None
        if not payload or payload.get("user_id") != user_id:
            raise error(message)
        return payload

    def _delete_collection(self, collection: Any, *, batch_size: int = 400) -> None:
        while True:
            documents = list(collection.limit(batch_size).stream())
            if not documents:
                return
            batch = self.client.batch()
            for snapshot in documents:
                batch.delete(snapshot.reference)
            batch.commit()
            if len(documents) < batch_size:
                return


class FirestoreConversationRepository(_FirestoreRepository):
    """Persist conversation metadata and messages below an authenticated user."""

    def _conversations(self, user_id: str) -> Any:
        return self._user(user_id).collection("conversations")

    def _conversation(self, user_id: str, conversation_id: UUID | str) -> Any:
        return self._conversations(user_id).document(str(conversation_id))

    @staticmethod
    def _conversation_payload(
        *,
        conversation_id: str,
        user_id: str,
        title: str,
        mode: AgentMode | str,
        now: datetime,
        message_count: int,
    ) -> dict[str, Any]:
        return {
            "id": conversation_id,
            "user_id": user_id,
            "title": title,
            "mode": AgentMode(mode).value,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "message_count": message_count,
        }

    @staticmethod
    def _message_payload(
        *,
        message_id: str,
        conversation_id: str,
        role: MessageRole,
        content: str,
        now: datetime,
        sequence: int,
        attachment_ids: list[UUID] | None = None,
        research_job_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role.value,
            "content": content,
            "created_at": now.isoformat(),
            "sequence": sequence,
            "attachment_ids": [
                str(attachment_id) for attachment_id in (attachment_ids or [])
            ],
        }
        if research_job_id is not None:
            payload["research_job_id"] = research_job_id
        return payload

    def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        query = self._conversations(user_id).order_by(
            "updated_at",
            direction=self._descending,
        )
        summaries: list[ConversationSummary] = []
        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            if payload.get("user_id") != user_id:
                continue
            summaries.append(
                ConversationSummary(
                    id=payload.get("id", snapshot.id),
                    title=payload.get("title") or "New conversation",
                    mode=payload.get("mode") or AgentMode.CHAT.value,
                    updated_at=payload["updated_at"],
                    message_count=max(0, int(payload.get("message_count", 0))),
                )
            )
        return summaries

    def get_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> Conversation:
        reference = self._conversation(user_id, conversation_id)
        payload = self._require_owned_document(
            reference.get(),
            user_id=user_id,
            error=ConversationNotFoundError,
            message="Conversation does not exist for this user.",
        )
        messages = []
        for snapshot in (
            reference.collection("messages").order_by("sequence").stream()
        ):
            message_payload = snapshot.to_dict() or {}
            message_payload.pop("sequence", None)
            messages.append(Message.model_validate(message_payload))
        return Conversation.model_validate(
            {
                "id": payload.get("id", str(conversation_id)),
                "user_id": user_id,
                "title": payload.get("title") or "New conversation",
                "mode": payload.get("mode", AgentMode.CHAT.value),
                "messages": messages,
                "created_at": payload["created_at"],
                "updated_at": payload["updated_at"],
            }
        )

    def delete_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> None:
        reference = self._conversation(user_id, conversation_id)
        self._require_owned_document(
            reference.get(),
            user_id=user_id,
            error=ConversationNotFoundError,
            message="Conversation does not exist for this user.",
        )
        self._delete_collection(reference.collection("messages"))
        reference.delete()

    def delete_for_user(self, user_id: str) -> None:
        for conversation in list(self._conversations(user_id).stream()):
            self._delete_collection(conversation.reference.collection("messages"))
            conversation.reference.delete()

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
        requested_id = str(conversation_id or uuid.uuid4())
        reference = self._conversation(user_id, requested_id)
        now = _utc_now()

        def operation(transaction: Any) -> str:
            snapshot = reference.get(transaction=transaction)
            if conversation_id is not None:
                payload = self._require_owned_document(
                    snapshot,
                    user_id=user_id,
                    error=ConversationNotFoundError,
                    message="Conversation does not exist for this user.",
                )
                message_count = int(payload.get("message_count", 0))
            else:
                message_count = 0
                transaction.set(
                    reference,
                    self._conversation_payload(
                        conversation_id=requested_id,
                        user_id=user_id,
                        title=user_message.strip().replace("\n", " ")[:56]
                        or "New conversation",
                        mode=mode,
                        now=now,
                        message_count=0,
                    ),
                )

            user_message_id = str(uuid.uuid4())
            assistant_message_id = str(uuid.uuid4())
            messages = reference.collection("messages")
            transaction.set(
                messages.document(user_message_id),
                self._message_payload(
                    message_id=user_message_id,
                    conversation_id=requested_id,
                    role=MessageRole.USER,
                    content=user_message,
                    now=now,
                    sequence=message_count,
                    attachment_ids=attachment_ids,
                ),
            )
            transaction.set(
                messages.document(assistant_message_id),
                self._message_payload(
                    message_id=assistant_message_id,
                    conversation_id=requested_id,
                    role=MessageRole.ASSISTANT,
                    content=assistant_message,
                    now=now,
                    sequence=message_count + 1,
                ),
            )
            transaction.set(
                reference,
                {
                    "updated_at": now.isoformat(),
                    "message_count": message_count + 2,
                },
                merge=True,
            )
            return requested_id

        return str(self._run_transaction(operation))

    def append_user_message(
        self,
        conversation_id: UUID | str | None,
        content: str,
        mode: AgentMode | str,
        *,
        user_id: str,
        attachment_ids: list[UUID] | None = None,
    ) -> str:
        requested_id = str(conversation_id or uuid.uuid4())
        reference = self._conversation(user_id, requested_id)
        now = _utc_now()

        def operation(transaction: Any) -> str:
            snapshot = reference.get(transaction=transaction)
            if conversation_id is not None:
                payload = self._require_owned_document(
                    snapshot,
                    user_id=user_id,
                    error=ConversationNotFoundError,
                    message="Conversation does not exist for this user.",
                )
                message_count = int(payload.get("message_count", 0))
            else:
                message_count = 0
                transaction.set(
                    reference,
                    self._conversation_payload(
                        conversation_id=requested_id,
                        user_id=user_id,
                        title=content.strip().replace("\n", " ")[:56]
                        or "New research",
                        mode=mode,
                        now=now,
                        message_count=0,
                    ),
                )

            message_id = str(uuid.uuid4())
            transaction.set(
                reference.collection("messages").document(message_id),
                self._message_payload(
                    message_id=message_id,
                    conversation_id=requested_id,
                    role=MessageRole.USER,
                    content=content,
                    now=now,
                    sequence=message_count,
                    attachment_ids=attachment_ids,
                ),
            )
            transaction.set(
                reference,
                {
                    "updated_at": now.isoformat(),
                    "message_count": message_count + 1,
                },
                merge=True,
            )
            return requested_id

        return str(self._run_transaction(operation))

    def append_assistant_message(
        self,
        conversation_id: UUID | str,
        content: str,
        *,
        user_id: str,
        research_job_id: UUID | str | None = None,
    ) -> str:
        requested_id = str(conversation_id)
        requested_job_id = str(research_job_id) if research_job_id else None
        reference = self._conversation(user_id, requested_id)
        message_id = (
            str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"mind:{user_id}:research:{requested_job_id}:assistant",
                )
            )
            if requested_job_id
            else str(uuid.uuid4())
        )
        message_reference = reference.collection("messages").document(message_id)
        now = _utc_now()

        def operation(transaction: Any) -> str:
            conversation_snapshot = reference.get(transaction=transaction)
            payload = self._require_owned_document(
                conversation_snapshot,
                user_id=user_id,
                error=ConversationNotFoundError,
                message="Conversation does not exist for this user.",
            )
            existing = message_reference.get(transaction=transaction)
            if existing.exists:
                existing_payload = existing.to_dict() or {}
                if content and existing_payload.get("content") != content:
                    transaction.set(
                        message_reference,
                        {"content": content},
                        merge=True,
                    )
                    transaction.set(
                        reference,
                        {"updated_at": now.isoformat()},
                        merge=True,
                    )
                return message_id

            message_count = int(payload.get("message_count", 0))
            transaction.set(
                message_reference,
                self._message_payload(
                    message_id=message_id,
                    conversation_id=requested_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    now=now,
                    sequence=message_count,
                    research_job_id=requested_job_id,
                ),
            )
            transaction.set(
                reference,
                {
                    "updated_at": now.isoformat(),
                    "message_count": message_count + 1,
                },
                merge=True,
            )
            return message_id

        return str(self._run_transaction(operation))


class FirestoreMemoryRepository(_FirestoreRepository):
    """Persist the complete user-controlled Memory Ledger below one user."""

    def _memories(self, user_id: str) -> Any:
        return self._user(user_id).collection("memories")

    def _memory(self, user_id: str, memory_id: UUID | str) -> Any:
        return self._memories(user_id).document(str(memory_id))

    def list_memories(self, user_id: str) -> list[Memory]:
        query = self._memories(user_id).order_by(
            "updated_at",
            direction=self._descending,
        )
        memories: list[Memory] = []
        for snapshot in query.stream():
            payload = cast(dict[str, Any], snapshot.to_dict() or {})
            if payload.get("user_id") == user_id:
                memories.append(
                    Memory.model_validate(_public_memory_payload(payload))
                )
        return memories

    def get_memory(self, memory_id: UUID | str, user_id: str) -> Memory:
        snapshot = self._memory(user_id, memory_id).get()
        payload = self._require_owned_document(
            snapshot,
            user_id=user_id,
            error=MemoryNotFoundError,
            message="Memory does not exist for this user.",
        )
        return Memory.model_validate(_public_memory_payload(payload))

    def create_memory(self, memory: Memory) -> Memory:
        reference = self._memory(memory.user_id, memory.id)

        def operation(transaction: Any) -> Memory:
            if reference.get(transaction=transaction).exists:
                raise ValueError("Memory already exists.")
            transaction.set(reference, _json_document(memory))
            return memory

        return self._run_transaction(operation)

    def upsert_memory(self, memory: Memory) -> Memory:
        reference = self._memory(memory.user_id, memory.id)

        def operation(transaction: Any) -> Memory:
            snapshot = reference.get(transaction=transaction)
            if snapshot.exists:
                payload = self._require_owned_document(
                    snapshot,
                    user_id=memory.user_id,
                    error=MemoryNotFoundError,
                    message="Memory does not exist for this user.",
                )
                return Memory.model_validate(_public_memory_payload(payload))
            transaction.set(reference, _json_document(memory))
            return memory

        return self._run_transaction(operation)

    def save_memory(self, memory: Memory, user_id: str) -> Memory:
        if memory.user_id != user_id:
            raise MemoryNotFoundError("Memory does not exist for this user.")
        reference = self._memory(user_id, memory.id)

        def operation(transaction: Any) -> Memory:
            payload = self._require_owned_document(
                reference.get(transaction=transaction),
                user_id=user_id,
                error=MemoryNotFoundError,
                message="Memory does not exist for this user.",
            )
            document = _json_document(memory)
            if "embedding" in payload:
                document["embedding"] = payload["embedding"]
                document["embedding_model"] = payload.get("embedding_model")
            transaction.set(reference, document)
            return memory

        return self._run_transaction(operation)

    def memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
    ) -> tuple[str, list[float]] | None:
        payload = self._require_owned_document(
            self._memory(user_id, memory_id).get(),
            user_id=user_id,
            error=MemoryNotFoundError,
            message="Memory does not exist for this user.",
        )
        model = payload.get("embedding_model")
        vector = _vector_values(payload.get("embedding"))
        return (str(model), vector) if isinstance(model, str) and vector else None

    def save_memory_embedding(
        self,
        memory_id: UUID | str,
        user_id: str,
        *,
        model: str,
        vector: list[float],
    ) -> None:
        reference = self._memory(user_id, memory_id)
        self._require_owned_document(
            reference.get(),
            user_id=user_id,
            error=MemoryNotFoundError,
            message="Memory does not exist for this user.",
        )
        try:
            from google.cloud.firestore_v1.vector import Vector
        except ImportError as error:  # pragma: no cover - packaging guard
            raise RuntimeError("Firestore vector support is unavailable.") from error
        reference.update(
            {
                "embedding": Vector(vector),
                "embedding_model": model,
            }
        )

    def find_similar_memories(
        self,
        user_id: str,
        vector: list[float],
        *,
        limit: int,
    ) -> list[tuple[Memory, float]]:
        try:
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
            from google.cloud.firestore_v1.vector import Vector

            query = self._memories(user_id).find_nearest(
                "embedding",
                Vector(vector),
                max(1, limit),
                DistanceMeasure.COSINE,
                distance_result_field="vector_distance",
            )
            matches: list[tuple[Memory, float]] = []
            for snapshot in query.stream():
                payload = cast(dict[str, Any], snapshot.to_dict() or {})
                if payload.get("user_id") != user_id:
                    continue
                distance = float(payload.get("vector_distance", 1.0))
                matches.append(
                    (
                        Memory.model_validate(_public_memory_payload(payload)),
                        max(-1.0, min(1.0, 1.0 - distance)),
                    )
                )
            return matches
        except Exception:
            # A bounded scan keeps a new or locally emulated database functional
            # while its vector index is still building. Production deployment also
            # creates the index so this is not the steady-state query path.
            return self._scan_vector_matches(user_id, vector, limit=limit)

    def _scan_vector_matches(
        self,
        user_id: str,
        vector: list[float],
        *,
        limit: int,
    ) -> list[tuple[Memory, float]]:
        matches: list[tuple[Memory, float]] = []
        for snapshot in self._memories(user_id).limit(200).stream():
            payload = cast(dict[str, Any], snapshot.to_dict() or {})
            if payload.get("user_id") != user_id:
                continue
            stored = _vector_values(payload.get("embedding"))
            if not stored:
                continue
            matches.append(
                (
                    Memory.model_validate(_public_memory_payload(payload)),
                    cosine_similarity(vector, stored),
                )
            )
        matches.sort(key=lambda item: item[1], reverse=True)
        return matches[:limit]

    def delete_memory(self, memory_id: UUID | str, user_id: str) -> None:
        reference = self._memory(user_id, memory_id)
        self._require_owned_document(
            reference.get(),
            user_id=user_id,
            error=MemoryNotFoundError,
            message="Memory does not exist for this user.",
        )
        reference.delete()

    def delete_for_user(self, user_id: str) -> None:
        self._delete_collection(self._memories(user_id))


class FirestoreAttachmentRepository(_FirestoreRepository):
    """Persist private attachment metadata below one authenticated user."""

    def _attachments(self, user_id: str) -> Any:
        return self._user(user_id).collection("attachments")

    def _attachment(self, user_id: str, attachment_id: UUID | str) -> Any:
        return self._attachments(user_id).document(str(attachment_id))

    def list_attachments(self, user_id: str) -> list[Attachment]:
        query = self._attachments(user_id).order_by(
            "updated_at",
            direction=self._descending,
        )
        return [
            Attachment.model_validate(snapshot.to_dict())
            for snapshot in query.stream()
            if (snapshot.to_dict() or {}).get("user_id") == user_id
        ]

    def get_attachment(
        self,
        attachment_id: UUID | str,
        user_id: str,
    ) -> Attachment:
        snapshot = self._attachment(user_id, attachment_id).get()
        payload = self._require_owned_document(
            snapshot,
            user_id=user_id,
            error=AttachmentNotFoundError,
            message="Attachment does not exist for this user.",
        )
        return Attachment.model_validate(payload)

    def create_attachment(self, attachment: Attachment) -> Attachment:
        reference = self._attachment(attachment.user_id, attachment.id)

        def operation(transaction: Any) -> Attachment:
            if reference.get(transaction=transaction).exists:
                raise ValueError("Attachment already exists.")
            transaction.set(reference, _json_document(attachment))
            return attachment

        return self._run_transaction(operation)

    def save_attachment(self, attachment: Attachment, user_id: str) -> Attachment:
        if attachment.user_id != user_id:
            raise AttachmentNotFoundError(
                "Attachment does not exist for this user."
            )
        reference = self._attachment(user_id, attachment.id)

        def operation(transaction: Any) -> Attachment:
            self._require_owned_document(
                reference.get(transaction=transaction),
                user_id=user_id,
                error=AttachmentNotFoundError,
                message="Attachment does not exist for this user.",
            )
            transaction.set(reference, _json_document(attachment))
            return attachment

        return self._run_transaction(operation)

    def delete_attachment(self, attachment_id: UUID | str, user_id: str) -> None:
        reference = self._attachment(user_id, attachment_id)
        self._require_owned_document(
            reference.get(),
            user_id=user_id,
            error=AttachmentNotFoundError,
            message="Attachment does not exist for this user.",
        )
        reference.delete()

    def delete_for_user(self, user_id: str) -> None:
        self._delete_collection(self._attachments(user_id))


class FirestoreResearchRepository(_FirestoreRepository):
    """Persist OpenAI background job checkpoints below one authenticated user."""

    def _jobs(self, user_id: str) -> Any:
        return self._user(user_id).collection("research_jobs")

    def _job(self, user_id: str, job_id: UUID | str) -> Any:
        return self._jobs(user_id).document(str(job_id))

    def list_jobs(self, user_id: str) -> list[ResearchJob]:
        query = self._jobs(user_id).order_by(
            "updated_at",
            direction=self._descending,
        )
        return [
            ResearchJob.model_validate(snapshot.to_dict())
            for snapshot in query.stream()
            if (snapshot.to_dict() or {}).get("user_id") == user_id
        ]

    def create_job(self, job: ResearchJob) -> ResearchJob:
        reference = self._job(job.user_id, job.id)

        def operation(transaction: Any) -> ResearchJob:
            if reference.get(transaction=transaction).exists:
                raise ValueError("Research job already exists.")
            transaction.set(reference, _json_document(job))
            return job

        return self._run_transaction(operation)

    def get_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        snapshot = self._job(user_id, job_id).get()
        payload = self._require_owned_document(
            snapshot,
            user_id=user_id,
            error=ResearchJobNotFoundError,
            message="Research job does not exist for this user.",
        )
        return ResearchJob.model_validate(payload)

    def save_job(
        self,
        job: ResearchJob,
        user_id: str,
        *,
        allow_cancelled_transition: bool = False,
    ) -> ResearchJob:
        if job.user_id != user_id:
            raise ResearchJobNotFoundError(
                "Research job does not exist for this user."
            )
        reference = self._job(user_id, job.id)

        def operation(transaction: Any) -> ResearchJob:
            snapshot = reference.get(transaction=transaction)
            payload = self._require_owned_document(
                snapshot,
                user_id=user_id,
                error=ResearchJobNotFoundError,
                message="Research job does not exist for this user.",
            )
            current = ResearchJob.model_validate(payload)
            if (
                current.status == ResearchStatus.CANCELLED
                and job.status != ResearchStatus.CANCELLED
                and not allow_cancelled_transition
            ):
                return current
            transaction.set(reference, _json_document(job))
            return job

        return self._run_transaction(operation)

    def delete_for_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> None:
        query = self._jobs(user_id).where(
            "conversation_id",
            "==",
            str(conversation_id),
        )
        documents = list(query.stream())
        for offset in range(0, len(documents), 400):
            batch = self.client.batch()
            for snapshot in documents[offset : offset + 400]:
                batch.delete(snapshot.reference)
            batch.commit()

    def delete_for_user(self, user_id: str) -> None:
        self._delete_collection(self._jobs(user_id))
