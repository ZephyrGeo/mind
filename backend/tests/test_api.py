from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from collections.abc import Iterator, Sequence
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
from backend.conversation_context import select_recent_history
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
    MessageRole,
    ModelMessage,
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

    def stream_reply(
        self,
        _message: str,
        _mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
    ) -> Iterator[str]:
        del history
        raise ModelProviderError(
            "provider_rate_limited",
            "DeepSeek is receiving too many requests. Please retry shortly.",
            retryable=True,
        )


class RecordingModelProvider:
    name = "recording"
    billable_model_calls = False

    def __init__(self) -> None:
        self.history_calls: list[list[ModelMessage]] = []

    def stream_reply(
        self,
        message: str,
        _mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
    ) -> Iterator[str]:
        self.history_calls.append(list(history))
        yield f"Reply to {message}"


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

        delete_preflight = self.client.options(
            f"/api/conversations/{uuid.uuid4()}",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(delete_preflight.status_code, 200)
        self.assertIn(
            "DELETE",
            delete_preflight.headers["Access-Control-Allow-Methods"],
        )

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
        self.assertIn(
            "/api/conversations/{conversation_id}",
            schema["paths"],
        )
        self.assertIn(
            "delete",
            schema["paths"]["/api/conversations/{conversation_id}"],
        )
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
            conversation = repository.get_conversation(
                conversation_id,
                "user-a",
            )
            self.assertEqual(len(conversation.messages), 4)
            self.assertEqual(conversation.messages[0].role, MessageRole.USER)
            with self.assertRaises(ConversationNotFoundError):
                repository.get_conversation(conversation_id, "user-b")
            with self.assertRaises(ConversationNotFoundError):
                repository.append_exchange(
                    conversation_id,
                    "Cross-tenant access.",
                    "This must not be written.",
                    AgentMode.CHAT,
                    user_id="user-b",
                )
            repository.delete_conversation(conversation_id, "user-a")
            self.assertEqual(repository.list_conversations("user-a"), [])
            with self.assertRaises(ConversationNotFoundError):
                repository.delete_conversation(conversation_id, "user-a")
            self.assertTrue(data_path.exists())

    def test_repository_reads_legacy_conversations_without_rewriting_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            conversation_id = str(uuid.uuid4())
            timestamp = "2026-01-01T00:00:00+00:00"
            legacy_payload = {
                "conversations": [
                    {
                        "id": conversation_id,
                        "title": "Legacy conversation",
                        "mode": "chat",
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Legacy question",
                                "created_at": timestamp,
                            },
                            {
                                "role": "assistant",
                                "content": "Legacy answer",
                                "created_at": timestamp,
                            },
                        ],
                    }
                ]
            }
            original_json = json.dumps(legacy_payload, ensure_ascii=False)
            data_path.write_text(original_json, encoding="utf-8")
            repository = JsonConversationRepository(data_path)

            first_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )
            second_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )

            self.assertEqual(first_read.user_id, "local-developer")
            self.assertEqual(len(first_read.messages), 2)
            self.assertEqual(
                first_read.messages[0].conversation_id,
                first_read.id,
            )
            self.assertEqual(
                first_read.messages[0].id,
                second_read.messages[0].id,
            )
            self.assertEqual(
                data_path.read_text(encoding="utf-8"),
                original_json,
            )

    def test_context_selection_keeps_only_recent_complete_turns(self) -> None:
        conversation_id = uuid.uuid4()
        messages = [
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="old question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="old answer",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="new question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="new answer",
            ),
        ]

        history = select_recent_history(
            messages,
            max_characters=len("new questionnew answer"),
        )

        self.assertEqual(
            [message.content for message in history],
            ["new question", "new answer"],
        )
        self.assertEqual(select_recent_history(messages, max_characters=1), [])

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

        with self.assertRaisesRegex(
            ValueError,
            "MIND_MAX_CONTEXT_CHARACTERS",
        ):
            Settings(max_context_characters=0)


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

    def test_sends_history_before_the_new_user_message(self) -> None:
        captured_body: dict[str, object] = {}

        def opener(request: Request, *, timeout: float) -> StubStreamingResponse:
            del timeout
            captured_body.update(json.loads(request.data.decode("utf-8")))
            return StubStreamingResponse(
                [
                    b'data: {"choices":[{"delta":{"content":"Lantern"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

        provider = DeepSeekProvider(api_key="test-key", opener=opener)
        history = [
            ModelMessage(role=MessageRole.USER, content="Remember lantern."),
            ModelMessage(role=MessageRole.ASSISTANT, content="I will remember it."),
        ]

        result = "".join(
            provider.stream_reply(
                "What was it?",
                AgentMode.CHAT,
                history=history,
            )
        )

        self.assertEqual(result, "Lantern")
        messages = captured_body["messages"]
        self.assertIsInstance(messages, list)
        assert isinstance(messages, list)
        self.assertEqual(
            messages[1:],
            [
                {"role": "user", "content": "Remember lantern."},
                {"role": "assistant", "content": "I will remember it."},
                {"role": "user", "content": "What was it?"},
            ],
        )

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
