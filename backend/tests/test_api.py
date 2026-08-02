from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app, is_authorized_header, validate_chat_payload
from backend.config import Settings
from backend.fake_agent import FakeAgentProvider
from backend.models import (
    AgentMode,
    Attachment,
    ChatRequest,
    Conversation,
    Memory,
    Message,
    ResearchJob,
    Routine,
    ToolCall,
    User,
)
from backend.store import (
    ConversationNotFoundError,
    JsonConversationRepository,
)


TEST_TOKEN = "test-only-token"


def parse_sse(body: str) -> list[dict[str, object]]:
    events = []
    for frame in body.split("\n\n"):
        data_line = next(
            (line for line in frame.splitlines() if line.startswith("data: ")),
            None,
        )
        if data_line:
            events.append(json.loads(data_line.removeprefix("data: ")))
    return events


class MindFastAPIContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        data_path = (
            Path(self.temporary_directory.name) / "conversations.json"
        )
        self.repository = JsonConversationRepository(data_path)
        self.provider = FakeAgentProvider(delay_seconds=0)
        self.settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            data_path=data_path,
            quiet=True,
        )
        self.client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=self.provider,
            )
        )
        self.addCleanup(self.client.close)
        self.auth_headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    def test_health_is_public_and_reports_a_zero_cost_provider(self) -> None:
        response = self.client.get(
            "/api/health",
            headers={"X-Request-ID": "health-contract-test"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "health-contract-test")
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "mind-api",
                "environment": "test",
                "provider": "fake",
                "billable_model_calls": False,
            },
        )

    def test_authentication_errors_use_the_standard_envelope(self) -> None:
        response = self.client.get("/api/conversations")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "authentication_required",
        )
        self.assertEqual(
            response.json()["error"]["request_id"],
            response.headers["X-Request-ID"],
        )
        self.assertTrue(
            is_authorized_header(
                f"Bearer {TEST_TOKEN}",
                expected_token=TEST_TOKEN,
            )
        )
        self.assertFalse(
            is_authorized_header(
                "Bearer incorrect",
                expected_token=TEST_TOKEN,
            )
        )

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
                "attachments": [{"name": "notes.txt", "size": 12}],
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

    def test_request_size_limit_is_enforced_before_json_parsing(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers={
                **self.auth_headers,
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:3000",
            },
            content=b"x" * (self.settings.max_request_bytes + 1),
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "http://127.0.0.1:3000",
        )
        self.assertEqual(
            response.json()["error"]["request_id"],
            response.headers["X-Request-ID"],
        )

    def test_cors_preflight_is_restricted_and_traceable(self) -> None:
        response = self.client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,x-request-id"
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "http://localhost:3000",
        )
        uuid.UUID(response.headers["X-Request-ID"])

        rejected = self.client.options(
            "/api/chat",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertNotIn("Access-Control-Allow-Origin", rejected.headers)
        uuid.UUID(rejected.headers["X-Request-ID"])

    def test_not_found_uses_the_standard_error_envelope(self) -> None:
        response = self.client.get("/api/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")
        self.assertEqual(
            response.json()["error"]["request_id"],
            response.headers["X-Request-ID"],
        )

    def test_openapi_documents_the_public_contract(self) -> None:
        response = self.client.get("/openapi.json")
        schema = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(schema["info"]["title"], "Mind Personal Agent API")
        self.assertIn("/api/health", schema["paths"])
        self.assertIn("/api/conversations", schema["paths"])
        self.assertIn("/api/chat", schema["paths"])
        self.assertIn("ChatRequest", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])


class MindDomainAndRepositoryTest(unittest.TestCase):
    def test_fake_provider_is_deterministic_and_bill_free(self) -> None:
        provider = FakeAgentProvider(delay_seconds=0)
        reply = provider.create_reply("Explain the local vertical slice.")
        streamed_reply = "".join(
            provider.stream_reply(
                "Explain the local vertical slice.",
                AgentMode.CHAT,
            )
        )
        self.assertEqual(reply, streamed_reply)
        self.assertIn("without calling an external model", reply)
        self.assertFalse(provider.billable_model_calls)

    def test_versioned_chat_evaluation_cases(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2] / "evals" / "chat-cases.json"
        )
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
        provider = FakeAgentProvider(delay_seconds=0)

        for case in cases:
            with self.subTest(case=case["id"]):
                reply = provider.create_reply(case["input"], case["mode"])
                for phrase in case["required_phrases"]:
                    self.assertIn(phrase, reply)
                for phrase in case["forbidden_phrases"]:
                    self.assertNotIn(phrase, reply)

    def test_json_repository_persists_and_enforces_tenant_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            repository = JsonConversationRepository(data_path)
            conversation_id = repository.append_exchange(
                None,
                "Explain the local vertical slice.",
                "This is a deterministic reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )
            repository.append_exchange(
                conversation_id,
                "Continue.",
                "This is the second reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )

            summaries = repository.list_conversations("user-a")
            self.assertEqual(len(summaries), 1)
            self.assertEqual(str(summaries[0].id), conversation_id)
            self.assertEqual(summaries[0].message_count, 4)
            self.assertEqual(repository.list_conversations("user-b"), [])
            with self.assertRaises(ConversationNotFoundError):
                repository.append_exchange(
                    conversation_id,
                    "Cross-tenant access.",
                    "This must not be written.",
                    AgentMode.CHAT,
                    user_id="user-b",
                )
            self.assertTrue(data_path.exists())

    def test_all_phase_one_domain_models_are_defined(self) -> None:
        model_names = {
            model.__name__
            for model in (
                User,
                Conversation,
                Message,
                Attachment,
                ResearchJob,
                Memory,
                Routine,
                ToolCall,
            )
        }
        self.assertEqual(
            model_names,
            {
                "User",
                "Conversation",
                "Message",
                "Attachment",
                "ResearchJob",
                "Memory",
                "Routine",
                "ToolCall",
            },
        )

    def test_production_rejects_the_local_demo_token(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "cannot be used outside development or test",
        ):
            Settings(environment="production")


if __name__ == "__main__":
    unittest.main()
