from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

from backend.models import (
    ResearchJob,
    ResearchSubtask,
    ResearchTaskStatus,
)
from backend.research_provider import ResearchProviderError
from backend.research_resilience import (
    MAX_RATE_LIMIT_WAIT_SECONDS,
    MAX_RETRY_DELAY_SECONDS,
    retry_delay_seconds,
)
from backend.research_service import ResearchService


class ResearchResilienceTest(unittest.TestCase):
    def test_provider_retry_after_is_capped_at_thirty_seconds(self) -> None:
        delay = retry_delay_seconds(
            1,
            base_seconds=2,
            retry_after_seconds=1_530,
            jitter_key="rate-limit",
        )

        self.assertEqual(delay, MAX_RETRY_DELAY_SECONDS)

    def test_persisted_retry_deadline_is_clamped_during_recovery(self) -> None:
        now = datetime(2026, 8, 22, tzinfo=timezone.utc)
        task = ResearchSubtask(
            id="brief",
            kind="brief",
            question="Question",
            objective="Create a brief.",
            status=ResearchTaskStatus.RETRY_WAIT,
            next_retry_at=now + timedelta(seconds=1_530),
        )
        job = ResearchJob(
            user_id="user",
            conversation_id=uuid4(),
            query="Question",
            provider_backoff_until=now + timedelta(seconds=1_530),
        )
        job.checkpoint.subtasks = [task]

        changed = ResearchService._normalize_retry_deadlines(job, now=now)

        self.assertTrue(changed)
        expected = now + timedelta(seconds=MAX_RETRY_DELAY_SECONDS)
        self.assertEqual(job.provider_backoff_until, expected)
        self.assertEqual(task.next_retry_at, expected)
        progress = ResearchService._progress_fields(job)
        self.assertLessEqual(
            cast(int, progress["retry_after_seconds"]),
            int(MAX_RETRY_DELAY_SECONDS),
        )

    def test_cumulative_rate_limit_wait_pauses_research(self) -> None:
        service = ResearchService(
            conversations=cast(Any, object()),
            jobs=cast(Any, object()),
            provider=cast(Any, object()),
            poll_interval_seconds=1,
        )
        task = ResearchSubtask(
            id="brief",
            kind="brief",
            question="Question",
            objective="Create a brief.",
        )
        job = ResearchJob(
            user_id="user",
            conversation_id=uuid4(),
            query="Question",
            rate_limit_wait_seconds=MAX_RATE_LIMIT_WAIT_SECONDS,
        )

        service._schedule_recovery(
            job,
            task,
            ResearchProviderError(
                "research_rate_limited",
                "Too many requests.",
                retryable=True,
                retry_after_seconds=1_530,
            ),
            operation="start",
        )

        self.assertEqual(task.status, ResearchTaskStatus.FAILED)
        self.assertEqual(task.error_code, "research_rate_limited")
        self.assertIsNone(task.next_retry_at)
        self.assertIsNone(job.provider_backoff_until)


if __name__ == "__main__":
    unittest.main()
