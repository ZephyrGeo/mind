from __future__ import annotations

from backend.app import create_app
from backend.app import is_authorized_header
from unittest.mock import patch
import uuid

from backend.tests.api_test_support import (
    MindApiTestCase,
    TEST_TOKEN,
)


class ApiContractTest(MindApiTestCase):
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
                "research_provider": "openai",
                "billable_research_calls": False,
                "research_mode": "live",
            },
        )

    def test_injected_memory_service_skips_provider_construction(self) -> None:
        with (
            patch("backend.app.create_memory_provider") as memory_provider_factory,
            patch(
                "backend.app.create_embedding_provider"
            ) as embedding_provider_factory,
        ):
            application = create_app(
                settings=self.settings,
                repository=self.repository,
                provider=self.provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                memory_repository=self.memory_repository,
                memory_service=self.memory_service,
            )

        memory_provider_factory.assert_not_called()
        embedding_provider_factory.assert_not_called()
        self.assertIs(application.state.memory_service, self.memory_service)
        self.assertIs(application.state.memory_repository, self.memory_repository)

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
        self.assertIn("/api/research", schema["paths"])
        self.assertIn("/api/research/{job_id}", schema["paths"])
        self.assertIn(
            "/api/research/{job_id}/compare",
            schema["paths"],
        )
        self.assertIn(
            "/api/research/{job_id}/cancel",
            schema["paths"],
        )
        self.assertIn("/api/memories", schema["paths"])
        self.assertIn("/api/memories/{memory_id}", schema["paths"])
        self.assertIn("/api/memories/{memory_id}/confirm", schema["paths"])
        self.assertIn("/api/files", schema["paths"])
        self.assertIn("/api/files/{attachment_id}", schema["paths"])
        self.assertIn("/api/account", schema["paths"])
        self.assertIn("ResearchRequest", schema["components"]["schemas"])
        self.assertIn("ResearchJob", schema["components"]["schemas"])
        self.assertIn("ChatRequest", schema["components"]["schemas"])
        self.assertIn("MemoryCreateRequest", schema["components"]["schemas"])
        self.assertIn("MemoryUpdateRequest", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])
