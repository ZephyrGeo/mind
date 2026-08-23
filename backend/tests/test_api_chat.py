from __future__ import annotations

from backend.app import create_app
from backend.app import validate_chat_payload
from backend.models import AgentMode
from backend.models import ChatRequest
from backend.models import ResearchJob
from backend.models import ResearchRequest
from backend.research_store import ResearchJobNotFoundError
from fastapi.testclient import TestClient
from pydantic import ValidationError
import uuid

from backend.tests.api_test_support import (
    MindApiTestCase,
    FailingModelProvider,
    RecordingModelProvider,
    parse_sse,
)


class ApiChatTest(MindApiTestCase):
    def test_chat_validation_uses_typed_pydantic_models(self) -> None:
        message, mode, conversation_id = validate_chat_payload(
            {"message": "  Investigate this topic.  ", "mode": "research"}
        )
        self.assertEqual(message, "Investigate this topic.")
        self.assertEqual(mode, "research")
        self.assertIsNone(conversation_id)

        with self.assertRaises(ValidationError):
            ChatRequest(message="   ")
        with self.assertRaises(ValidationError):
            ChatRequest(message="hello", mode="unsupported")
        with self.assertRaises(ValidationError):
            ResearchRequest(query="   ")

        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "   "},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertTrue(response.json()["error"]["details"])

    def test_chat_streams_and_persists_an_exchange(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers={
                **self.auth_headers,
                "X-Request-ID": "chat-contract-test",
            },
            json={
                "message": "Explain the local vertical slice.",
                "mode": "chat",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        events = parse_sse(response.text)
        self.assertGreater(len(events), 2)
        self.assertEqual(events[0]["type"], "delta")
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["request_id"], "chat-contract-test")

        summaries = self.repository.list_conversations("local-developer")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(str(summaries[0].id), events[-1]["conversation_id"])
        self.assertEqual(summaries[0].message_count, 2)
        self.assertEqual(summaries[0].mode, AgentMode.CHAT)

        listing = self.client.get("/api/conversations", headers=self.auth_headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["conversations"][0]["mode"], "chat")

        detail = self.client.get(
            f"/api/conversations/{events[-1]['conversation_id']}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], events[-1]["conversation_id"])
        self.assertEqual(
            [message["role"] for message in detail.json()["messages"]],
            ["user", "assistant"],
        )

    def test_second_turn_receives_persisted_history(self) -> None:
        provider = RecordingModelProvider()
        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=provider,
            )
        )
        self.addCleanup(client.close)

        first_response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Remember the code word lantern."},
        )
        first_events = parse_sse(first_response.text)
        second_response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={
                "conversation_id": first_events[-1]["conversation_id"],
                "message": "What was the code word?",
            },
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(provider.history_calls[0], [])
        self.assertEqual(
            [message.model_dump(mode="json") for message in provider.history_calls[1]],
            [
                {
                    "role": "user",
                    "content": "Remember the code word lantern.",
                },
                {
                    "role": "assistant",
                    "content": "Reply to Remember the code word lantern.",
                },
            ],
        )
        detail = self.repository.get_conversation(
            first_events[-1]["conversation_id"],
            "local-developer",
        )
        self.assertEqual(len(detail.messages), 4)

    def test_delete_conversation_removes_only_the_owned_record(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Temporary conversation."},
        )
        conversation_id = parse_sse(response.text)[-1]["conversation_id"]
        other_conversation_id = self.repository.append_exchange(
            None,
            "Private to another user.",
            "Must remain intact.",
            AgentMode.CHAT,
            user_id="other-user",
        )
        research_job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Temporary research",
            )
        )

        rejected = self.client.delete(
            f"/api/conversations/{other_conversation_id}",
            headers=self.auth_headers,
        )
        deleted = self.client.delete(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_headers,
        )

        self.assertEqual(rejected.status_code, 404)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "conversation_not_found",
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
        )
        self.assertEqual(
            len(self.repository.list_conversations("other-user")),
            1,
        )
        detail = self.client.get(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 404)
        with self.assertRaises(ResearchJobNotFoundError):
            self.research_repository.get_job(
                research_job.id,
                "local-developer",
            )

    def test_unknown_conversation_is_not_silently_recreated(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={
                "conversation_id": str(uuid.uuid4()),
                "message": "Continue the missing conversation.",
                "mode": "chat",
            },
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "conversation_not_found")
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
        )

        detail = self.client.get(
            f"/api/conversations/{uuid.uuid4()}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(
            detail.json()["error"]["code"],
            "conversation_not_found",
        )

    def test_provider_failures_are_safe_retryable_sse_events(self) -> None:
        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=FailingModelProvider(),
            )
        )
        self.addCleanup(client.close)

        response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Try the hosted provider."},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(
            events,
            [
                {
                    "type": "error",
                    "code": "provider_rate_limited",
                    "message": (
                        "DeepSeek is receiving too many requests. Please retry shortly."
                    ),
                    "retryable": True,
                    "request_id": events[0]["request_id"],
                }
            ],
        )
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
        )
