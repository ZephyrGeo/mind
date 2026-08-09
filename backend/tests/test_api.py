from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import (
    create_app,
    create_model_provider,
    is_authorized_header,
    validate_chat_payload,
)
from backend.config import Settings
from backend.deepseek_provider import DeepSeekProvider
from backend.fake_agent import FakeAgentProvider
from backend.model_provider import ModelProviderError
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


class StubStreamingResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "StubStreamingResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.lines)


class FailingModelProvider:
    name = "deepseek"
    billable_model_calls = True

    def stream_reply(self, _message: str, _mode: AgentMode):  # type: ignore[no-untyped-def]
        raise ModelProviderError(
            "provider_rate_limited",
            "DeepSeek is receiving too many requests. Please retry shortly.",
            retryable=True,
        )


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
                        "DeepSeek is receiving too many requests. "
                        "Please retry shortly."
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


class DeepSeekProviderTest(unittest.TestCase):
    def test_streams_chat_completion_without_a_network_call(self) -> None:
        captured: dict[str, object] = {}

        def opener(request: Request, *, timeout: float) -> StubStreamingResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return StubStreamingResponse(
                [
                    b'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
                    b'data: {"choices":[{"delta":{"content":" from Mind"}}]}\n',
                    b'data: {"choices":[],"usage":{"total_tokens":12}}\n',
                    b"data: [DONE]\n",
                ]
            )

        provider = DeepSeekProvider(
            api_key="test-deepseek-key",
            opener=opener,
        )

        result = "".join(provider.stream_reply("你好", AgentMode.CHAT))

        self.assertEqual(result, "Hello from Mind")
        self.assertEqual(captured["timeout"], 120.0)
        request = captured["request"]
        self.assertIsInstance(request, Request)
        assert isinstance(request, Request)
        self.assertEqual(
            request.full_url,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-deepseek-key",
        )
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "你好"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertTrue(body["stream"])
        self.assertEqual(body["stream_options"], {"include_usage": True})

    def test_research_mode_enables_thinking(self) -> None:
        captured_body: dict[str, object] = {}

        def opener(request: Request, *, timeout: float) -> StubStreamingResponse:
            del timeout
            captured_body.update(json.loads(request.data.decode("utf-8")))
            return StubStreamingResponse(
                [
                    b'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"Result"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

        provider = DeepSeekProvider(api_key="test-key", opener=opener)

        result = "".join(
            provider.stream_reply("Investigate this.", AgentMode.RESEARCH)
        )

        self.assertEqual(result, "Result")
        self.assertEqual(captured_body["thinking"], {"type": "enabled"})
        self.assertEqual(captured_body["reasoning_effort"], "high")
        self.assertNotIn("private reasoning", result)

    def test_maps_upstream_status_without_exposing_response_body(self) -> None:
        def opener(_request: Request, *, timeout: float) -> StubStreamingResponse:
            del timeout
            raise HTTPError(
                "https://api.deepseek.com/chat/completions",
                402,
                "secret upstream body",
                hdrs=None,
                fp=None,
            )

        provider = DeepSeekProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ModelProviderError) as context:
            list(provider.stream_reply("Hello", AgentMode.CHAT))

        self.assertEqual(context.exception.code, "provider_balance_exhausted")
        self.assertFalse(context.exception.retryable)
        self.assertNotIn("secret", context.exception.public_message)

    def test_rejects_incomplete_streams(self) -> None:
        def opener(_request: Request, *, timeout: float) -> StubStreamingResponse:
            del timeout
            return StubStreamingResponse(
                [b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n']
            )

        provider = DeepSeekProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ModelProviderError) as context:
            list(provider.stream_reply("Hello", AgentMode.CHAT))

        self.assertEqual(context.exception.code, "provider_invalid_response")
        self.assertTrue(context.exception.retryable)

    def test_configuration_selects_deepseek_and_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            Settings(provider="deepseek")

        settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            provider="deepseek",
            deepseek_api_key="test-key",
        )
        provider = create_model_provider(settings)

        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.name, "deepseek")
        self.assertTrue(provider.billable_model_calls)
        self.assertEqual(provider.model, "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
