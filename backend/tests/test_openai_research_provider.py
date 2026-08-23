from __future__ import annotations

from backend.app import create_research_provider
from backend.config import Settings
from backend.openai_research_provider import OpenAIResearchProvider
from backend.research_provider import ResearchProviderError
from backend.research_provider import ResearchProviderRequest
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request
import json
import unittest

from backend.tests.api_test_support import (
    StubJsonResponse,
    completed_research_response,
)


class OpenAIResearchProviderTest(unittest.TestCase):
    def test_rate_limit_exposes_retry_after_without_provider_branding(self) -> None:
        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "7"},
                BytesIO(
                    json.dumps({"error": {"code": "rate_limit_exceeded"}}).encode()
                ),
            )

        provider = OpenAIResearchProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ResearchProviderError) as context:
            provider.start(ResearchProviderRequest(prompt="test", task_kind="brief"))

        self.assertEqual(context.exception.code, "research_rate_limited")
        self.assertEqual(context.exception.retry_after_seconds, 7)
        self.assertTrue(context.exception.retryable)
        self.assertNotIn("OpenAI", context.exception.public_message)

    def test_failed_background_response_maps_exhausted_credit_to_quota(
        self,
    ) -> None:
        provider = OpenAIResearchProvider(api_key="test-key")

        result = provider.parse_result(
            {
                "id": "resp_no_credit",
                "status": "failed",
                "error": {"code": "credit_balance_exhausted"},
                "output": [],
            }
        )

        self.assertEqual(result.error_code, "research_quota_exhausted")
        self.assertFalse(result.retryable)

    def test_http_credit_error_maps_to_non_retryable_quota_failure(self) -> None:
        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                402,
                "Payment Required",
                {},
                BytesIO(
                    json.dumps({"error": {"code": "credit_balance_exhausted"}}).encode()
                ),
            )

        provider = OpenAIResearchProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ResearchProviderError) as context:
            provider.start(ResearchProviderRequest(prompt="test", task_kind="search"))

        self.assertEqual(context.exception.code, "research_quota_exhausted")
        self.assertFalse(context.exception.retryable)

    def test_context_limit_is_classified_for_bounded_stage_retry(self) -> None:
        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                BytesIO(
                    json.dumps({"error": {"code": "context_length_exceeded"}}).encode()
                ),
            )

        provider = OpenAIResearchProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ResearchProviderError) as context:
            provider.start(
                ResearchProviderRequest(prompt="oversized", task_kind="synthesis")
            )

        self.assertEqual(context.exception.code, "research_context_limit")
        self.assertTrue(context.exception.retryable)

    def test_deadline_exceeded_is_retryable_without_provider_branding(self) -> None:
        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                408,
                "Request Timeout",
                {},
                BytesIO(json.dumps({"error": {"code": "deadline_exceeded"}}).encode()),
            )

        provider = OpenAIResearchProvider(api_key="test-key", opener=opener)

        with self.assertRaises(ResearchProviderError) as context:
            provider.retrieve("resp_saved")

        self.assertEqual(context.exception.code, "research_provider_timeout")
        self.assertTrue(context.exception.retryable)
        self.assertNotIn("OpenAI", context.exception.public_message)

    def test_start_uses_background_responses_web_search_and_bounded_tools(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return StubJsonResponse(
                {"id": "resp_test", "status": "queued", "output": []}
            )

        provider = OpenAIResearchProvider(
            api_key="test-openai-key",
            opener=opener,
        )
        result = provider.parse_result(
            provider.start(
                ResearchProviderRequest(
                    prompt="test query",
                    task_kind="search",
                    use_web_search=True,
                    max_tool_calls=5,
                )
            )
        )

        self.assertEqual(result.response_id, "resp_test")
        self.assertEqual(result.status, "queued")
        self.assertEqual(captured["timeout"], 120.0)
        request = captured["request"]
        self.assertIsInstance(request, Request)
        assert isinstance(request, Request)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-openai-key",
        )
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "gpt-5.6-terra")
        self.assertTrue(body["background"])
        self.assertTrue(body["store"])
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertEqual(
            body["include"],
            ["web_search_call.action.sources"],
        )
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertEqual(body["max_tool_calls"], 5)
        self.assertEqual(body["input"], "test query")

    def test_non_search_stage_does_not_enable_web_search(self) -> None:
        captured: dict[str, object] = {}

        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            captured["request"] = request
            return StubJsonResponse(
                {"id": "resp_brief", "status": "queued", "output": []}
            )

        provider = OpenAIResearchProvider(
            api_key="test-openai-key",
            opener=opener,
        )
        provider.start(
            ResearchProviderRequest(
                prompt="create a brief",
                task_kind="brief",
            )
        )

        request = captured["request"]
        assert isinstance(request, Request)
        body = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("tools", body)
        self.assertNotIn("max_tool_calls", body)

    def test_parse_result_keeps_output_citations_and_complete_sources(self) -> None:
        provider = OpenAIResearchProvider(api_key="test-key")

        result = provider.parse_result(completed_research_response("resp_done"))

        self.assertEqual(result.status, "completed")
        self.assertIn("Research summary", result.output_text)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].title, "Example source")
        self.assertEqual(
            result.output_text[
                result.citations[0].start_index : result.citations[0].end_index
            ],
            "Example source",
        )
        self.assertEqual(
            [source.url for source in result.sources],
            [
                "https://example.com/primary",
                "https://example.com/complete-list-only",
            ],
        )

    def test_parse_result_deduplicates_tracking_url_variants(self) -> None:
        provider = OpenAIResearchProvider(api_key="test-key")
        response = completed_research_response("resp_duplicates")
        output = response["output"]
        assert isinstance(output, list)
        search_call = output[0]
        assert isinstance(search_call, dict)
        action = search_call["action"]
        assert isinstance(action, dict)
        sources = action["sources"]
        assert isinstance(sources, list)
        sources.append(
            {
                "type": "url",
                "url": "https://example.com/primary/?utm_source=openai",
                "title": "Duplicate Example source",
            }
        )

        result = provider.parse_result(response)

        self.assertEqual(
            [source.url for source in result.sources],
            [
                "https://example.com/primary",
                "https://example.com/complete-list-only",
            ],
        )

    def test_retrieve_and_cancel_use_the_saved_response_id(self) -> None:
        requests: list[Request] = []

        def opener(request: Request, *, timeout: float) -> StubJsonResponse:
            del timeout
            requests.append(request)
            status = (
                "cancelled" if request.full_url.endswith("/cancel") else "in_progress"
            )
            return StubJsonResponse(
                {"id": "resp_saved", "status": status, "output": []}
            )

        provider = OpenAIResearchProvider(
            api_key="test-key",
            opener=opener,
        )

        provider.retrieve("resp_saved")
        provider.cancel("resp_saved")

        self.assertEqual(
            [request.full_url for request in requests],
            [
                "https://api.openai.com/v1/responses/resp_saved",
                "https://api.openai.com/v1/responses/resp_saved/cancel",
            ],
        )
        self.assertEqual([request.method for request in requests], ["GET", "POST"])

    def test_configuration_allows_only_openai_and_fails_closed_in_production(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "must be openai"):
            Settings(research_provider="fake")
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            Settings(
                environment="production",
                auth_provider="firebase",
                firebase_project_id="mind-production",
                allowed_user_emails=("owner@example.com",),
                persistence_provider="firestore",
                allowed_origins=("https://mind.example",),
            )
        provider = create_research_provider(Settings(openai_api_key="test-openai-key"))
        self.assertIsInstance(provider, OpenAIResearchProvider)
        self.assertEqual(provider.name, "openai")
        self.assertTrue(provider.billable_calls)

        unconfigured = create_research_provider(Settings())
        self.assertFalse(unconfigured.configured)
        with self.assertRaises(ResearchProviderError) as context:
            unconfigured.start(
                ResearchProviderRequest(prompt="test", task_kind="brief")
            )
        self.assertEqual(context.exception.code, "research_not_configured")
