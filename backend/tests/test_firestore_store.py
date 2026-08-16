from __future__ import annotations

import unittest
import uuid
from dataclasses import dataclass
from typing import Any

from backend.firestore_store import (
    FirestoreConversationRepository,
    FirestoreResearchRepository,
)
from backend.models import AgentMode, ResearchJob, ResearchStatus
from backend.research_store import ResearchJobNotFoundError
from backend.store import ConversationNotFoundError


@dataclass
class FakeSnapshot:
    reference: "FakeDocument"
    payload: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.payload is not None

    @property
    def id(self) -> str:
        return self.reference.id

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self.payload) if self.payload is not None else None


class FakeDocument:
    def __init__(self, client: "FakeFirestore", path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path

    @property
    def id(self) -> str:
        return self.path[-1]

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self.client, (*self.path, name))

    def get(self, transaction: Any | None = None) -> FakeSnapshot:
        del transaction
        payload = self.client.documents.get(self.path)
        return FakeSnapshot(self, dict(payload) if payload is not None else None)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        if merge:
            current = self.client.documents.setdefault(self.path, {})
            current.update(payload)
        else:
            self.client.documents[self.path] = dict(payload)

    def delete(self) -> None:
        self.client.documents.pop(self.path, None)


class FakeQuery:
    def __init__(self, collection: "FakeCollection") -> None:
        self.collection = collection
        self.sort_field: str | None = None
        self.descending = False
        self.maximum: int | None = None
        self.filters: list[tuple[str, Any]] = []

    def order_by(self, field: str, direction: Any = None) -> "FakeQuery":
        self.sort_field = field
        self.descending = str(direction).upper() == "DESCENDING"
        return self

    def limit(self, maximum: int) -> "FakeQuery":
        self.maximum = maximum
        return self

    def where(self, field: str, operator: str, value: Any) -> "FakeQuery":
        if operator != "==":
            raise ValueError("The fake supports equality filters only.")
        self.filters.append((field, value))
        return self

    def stream(self) -> list[FakeSnapshot]:
        snapshots = self.collection._snapshots()
        for field, value in self.filters:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if (snapshot.payload or {}).get(field) == value
            ]
        if self.sort_field:
            snapshots.sort(
                key=lambda snapshot: (snapshot.payload or {}).get(
                    self.sort_field,
                    "",
                ),
                reverse=self.descending,
            )
        return snapshots[: self.maximum] if self.maximum is not None else snapshots


class FakeCollection:
    def __init__(self, client: "FakeFirestore", path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self.client, (*self.path, document_id))

    def _snapshots(self) -> list[FakeSnapshot]:
        expected_length = len(self.path) + 1
        return [
            FakeSnapshot(FakeDocument(self.client, path), dict(payload))
            for path, payload in self.client.documents.items()
            if len(path) == expected_length and path[:-1] == self.path
        ]

    def stream(self) -> list[FakeSnapshot]:
        return self._snapshots()

    def order_by(self, field: str, direction: Any = None) -> FakeQuery:
        return FakeQuery(self).order_by(field, direction)

    def limit(self, maximum: int) -> FakeQuery:
        return FakeQuery(self).limit(maximum)

    def where(self, field: str, operator: str, value: Any) -> FakeQuery:
        return FakeQuery(self).where(field, operator, value)


class FakeWriter:
    def set(
        self,
        reference: FakeDocument,
        payload: dict[str, Any],
        merge: bool = False,
    ) -> None:
        reference.set(payload, merge=merge)

    def delete(self, reference: FakeDocument) -> None:
        reference.delete()


class FakeBatch(FakeWriter):
    def commit(self) -> None:
        return None


class FakeFirestore:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def transaction(self) -> FakeWriter:
        return FakeWriter()

    def batch(self) -> FakeBatch:
        return FakeBatch()


def fake_transactional(operation):  # type: ignore[no-untyped-def]
    return lambda transaction: operation(transaction)


class FirestoreRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeFirestore()
        self.conversations = FirestoreConversationRepository(
            project_id="demo-mind-local",
            client=self.client,
            transactional=fake_transactional,
        )
        self.jobs = FirestoreResearchRepository(
            project_id="demo-mind-local",
            client=self.client,
            transactional=fake_transactional,
        )

    def test_conversations_are_ordered_tenant_scoped_and_idempotent(self) -> None:
        conversation_id = self.conversations.append_exchange(
            None,
            "First question",
            "First answer",
            AgentMode.CHAT,
            user_id="owner",
        )
        detail = self.conversations.get_conversation(conversation_id, "owner")
        self.assertEqual(
            [message.content for message in detail.messages],
            ["First question", "First answer"],
        )
        self.assertEqual(
            self.conversations.list_conversations("owner")[0].message_count,
            2,
        )
        with self.assertRaises(ConversationNotFoundError):
            self.conversations.get_conversation(conversation_id, "stranger")

        research_conversation_id = self.conversations.append_user_message(
            None,
            "Research question",
            AgentMode.RESEARCH,
            user_id="owner",
        )
        research_job_id = uuid.uuid4()
        first_message_id = self.conversations.append_assistant_message(
            research_conversation_id,
            "",
            user_id="owner",
            research_job_id=research_job_id,
        )
        second_message_id = self.conversations.append_assistant_message(
            research_conversation_id,
            "Final cited report",
            user_id="owner",
            research_job_id=research_job_id,
        )
        self.assertEqual(first_message_id, second_message_id)
        research_detail = self.conversations.get_conversation(
            research_conversation_id,
            "owner",
        )
        self.assertEqual(len(research_detail.messages), 2)
        self.assertEqual(research_detail.messages[-1].content, "Final cited report")

        self.conversations.delete_for_user("owner")
        self.assertEqual(self.conversations.list_conversations("owner"), [])

    def test_research_jobs_preserve_cancellation_and_tenant_boundaries(self) -> None:
        conversation_id = uuid.uuid4()
        job = ResearchJob(
            user_id="owner",
            conversation_id=conversation_id,
            query="Test Firestore persistence",
        )
        self.jobs.create_job(job)
        self.assertEqual(self.jobs.list_jobs("owner"), [job])
        with self.assertRaises(ResearchJobNotFoundError):
            self.jobs.get_job(job.id, "stranger")

        cancelled = job.model_copy(deep=True)
        cancelled.status = ResearchStatus.CANCELLED
        self.jobs.save_job(cancelled, "owner")
        stale = cancelled.model_copy(deep=True)
        stale.status = ResearchStatus.COLLECTING
        self.assertEqual(
            self.jobs.save_job(stale, "owner").status,
            ResearchStatus.CANCELLED,
        )

        self.jobs.delete_for_conversation(conversation_id, "owner")
        self.assertEqual(self.jobs.list_jobs("owner"), [])


if __name__ == "__main__":
    unittest.main()
