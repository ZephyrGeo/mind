from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.models import AgentMode, ResearchJob
from backend.tests.api_test_support import MindApiTestCase, parse_sse
from backend.usage_limits import (
    ActiveResearchLimitExceeded,
    DailyUsageLimitExceeded,
    JsonUsageLimitRepository,
    utc_usage_day,
)


class ApiUsageLimitTest(MindApiTestCase):
    def _limited_client(
        self,
        *,
        chat_daily_limit: int = 30,
        research_daily_limit: int = 2,
    ) -> TestClient:
        client = TestClient(
            create_app(
                settings=replace(
                    self.settings,
                    chat_daily_limit=chat_daily_limit,
                    research_daily_limit=research_daily_limit,
                    research_max_active_per_user=1,
                ),
                repository=self.repository,
                provider=self.provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                memory_repository=self.memory_repository,
                memory_service=self.memory_service,
                attachment_repository=self.attachment_repository,
                file_storage=self.file_storage,
                file_service=self.file_service,
            )
        )
        self.addCleanup(client.close)
        return client

    def test_chat_daily_limit_rejects_before_an_extra_exchange(self) -> None:
        client = self._limited_client(chat_daily_limit=2)

        for index in range(2):
            response = client.post(
                "/api/chat",
                headers=self.auth_headers,
                json={"message": f"Allowed Chat request {index + 1}."},
            )
            self.assertEqual(response.status_code, 200)

        rejected = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "This request exceeds the allowance."},
        )

        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "daily_usage_limit_reached",
        )
        self.assertIn("Chat limit of 2", rejected.json()["error"]["message"])
        summaries = self.repository.list_conversations("local-developer")
        self.assertEqual(sum(item.message_count for item in summaries), 4)

    def test_research_daily_limit_counts_new_jobs_but_releases_active_slot(
        self,
    ) -> None:
        client = self._limited_client(research_daily_limit=2)

        for index in range(2):
            response = client.post(
                "/api/research",
                headers=self.auth_headers,
                json={"query": f"Allowed Research request {index + 1}."},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(parse_sse(response.text)[-1]["status"], "completed")

        rejected = client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "This Research request exceeds the allowance."},
        )

        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "daily_usage_limit_reached",
        )
        self.assertIn(
            "Research limit of 2",
            rejected.json()["error"]["message"],
        )

    def test_second_active_research_is_rejected_for_the_same_user(self) -> None:
        client = self._limited_client()
        conversation_id = self.repository.append_user_message(
            None,
            "An existing long-running request.",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        active_job = ResearchJob(
            user_id="local-developer",
            conversation_id=uuid.UUID(conversation_id),
            query="An existing long-running request.",
        )
        self.research_repository.create_job(active_job)

        rejected = client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Do not start while another task is active."},
        )

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "active_research_limit_reached",
        )
        self.assertEqual(
            len(self.research_repository.list_jobs("local-developer")),
            1,
        )


class JsonUsageLimitRepositoryTest(unittest.TestCase):
    def test_daily_counters_are_tenant_scoped_and_reset_by_utc_day(self) -> None:
        with TemporaryDirectory() as directory:
            repository = JsonUsageLimitRepository(Path(directory) / "usage.json")
            first_day = utc_usage_day(
                datetime(2026, 8, 23, 23, 59, tzinfo=timezone.utc)
            )
            next_day = utc_usage_day(
                datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
            )

            self.assertEqual(
                repository.consume_chat("user-a", day=first_day, limit=1),
                1,
            )
            with self.assertRaises(DailyUsageLimitExceeded):
                repository.consume_chat("user-a", day=first_day, limit=1)
            self.assertEqual(
                repository.consume_chat("user-a", day=next_day, limit=1),
                1,
            )
            self.assertEqual(
                repository.consume_chat("user-b", day=first_day, limit=1),
                1,
            )

    def test_research_reservations_are_idempotent_and_release_without_refund(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            repository = JsonUsageLimitRepository(Path(directory) / "usage.json")
            day = "2026-08-23"

            self.assertEqual(
                repository.reserve_research(
                    "user-a",
                    "job-1",
                    day=day,
                    daily_limit=2,
                    active_limit=1,
                    count_daily=True,
                ),
                1,
            )
            self.assertEqual(
                repository.reserve_research(
                    "user-a",
                    "job-1",
                    day=day,
                    daily_limit=2,
                    active_limit=1,
                    count_daily=False,
                ),
                1,
            )
            with self.assertRaises(ActiveResearchLimitExceeded):
                repository.reserve_research(
                    "user-a",
                    "job-2",
                    day=day,
                    daily_limit=2,
                    active_limit=1,
                    count_daily=True,
                )

            repository.release_research("user-a", "job-1")
            self.assertEqual(
                repository.reserve_research(
                    "user-a",
                    "job-2",
                    day=day,
                    daily_limit=2,
                    active_limit=1,
                    count_daily=True,
                ),
                2,
            )
            repository.release_research("user-a", "job-2")
            with self.assertRaises(DailyUsageLimitExceeded):
                repository.reserve_research(
                    "user-a",
                    "job-3",
                    day=day,
                    daily_limit=2,
                    active_limit=1,
                    count_daily=True,
                )
