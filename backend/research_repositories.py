"""Persistence boundary for tenant-scoped Deep Research jobs."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import ResearchJob


class ResearchRepository(Protocol):
    def create_job(self, job: ResearchJob) -> ResearchJob:
        ...

    def get_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        ...

    def save_job(
        self,
        job: ResearchJob,
        user_id: str,
        *,
        allow_cancelled_transition: bool = False,
    ) -> ResearchJob:
        ...

    def delete_for_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> None:
        ...
