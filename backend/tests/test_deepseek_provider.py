from __future__ import annotations

from backend.app import create_model_provider
from backend.config import Settings
from backend.deepseek_provider import DeepSeekProvider
from backend.model_provider import ModelProviderError
from backend.models import AgentMode
from backend.models import MessageRole
from backend.models import ModelMessage
from urllib.error import HTTPError
from urllib.request import Request
import json
import unittest

from backend.tests.api_test_support import (
    StubStreamingResponse,
    TEST_TOKEN,
)


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
        system_prompt = body["messages"][0]["content"]
        self.assertIn("Do not output Markdown horizontal rules", system_prompt)
        self.assertIn("Use fenced code blocks only for actual code", system_prompt)
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
