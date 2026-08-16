"""Atomic JSON implementation of the local research-job repository."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from .models import ResearchJob, ResearchStatus


class ResearchJobNotFoundError(LookupError):
    """Raised when a job is absent or belongs to another user."""


class JsonResearchRepository:
    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.file_path.exists():
            return {"research_jobs": []}
        with self.file_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("research_jobs"), list
        ):
            raise ValueError("Research data file has an invalid shape.")
        return payload

    def _write(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.file_path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, self.file_path)

    def list_jobs(self, user_id: str) -> list[ResearchJob]:
        with self._lock:
            jobs = [
                ResearchJob.model_validate(item)
                for item in self._read()["research_jobs"]
                if item.get("user_id") == user_id
            ]
        return sorted(jobs, key=lambda job: job.updated_at, reverse=True)

    def create_job(self, job: ResearchJob) -> ResearchJob:
        with self._lock:
            payload = self._read()
            if any(item.get("id") == str(job.id) for item in payload["research_jobs"]):
                raise ValueError("Research job already exists.")
            payload["research_jobs"].append(job.model_dump(mode="json"))
            self._write(payload)
        return job

    def get_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        requested_id = str(job_id)
        with self._lock:
            item = next(
                (
                    candidate
                    for candidate in self._read()["research_jobs"]
                    if candidate.get("id") == requested_id
                    and candidate.get("user_id") == user_id
                ),
                None,
            )
            if item is None:
                raise ResearchJobNotFoundError(
                    "Research job does not exist for this user."
                )
            return ResearchJob.model_validate(item)

    def save_job(
        self,
        job: ResearchJob,
        user_id: str,
        *,
        allow_cancelled_transition: bool = False,
    ) -> ResearchJob:
        if job.user_id != user_id:
            raise ResearchJobNotFoundError(
                "Research job does not exist for this user."
            )
        with self._lock:
            payload = self._read()
            index = next(
                (
                    item_index
                    for item_index, candidate in enumerate(payload["research_jobs"])
                    if candidate.get("id") == str(job.id)
                    and candidate.get("user_id") == user_id
                ),
                None,
            )
            if index is None:
                raise ResearchJobNotFoundError(
                    "Research job does not exist for this user."
                )
            current = ResearchJob.model_validate(payload["research_jobs"][index])
            if (
                current.status == ResearchStatus.CANCELLED
                and job.status != ResearchStatus.CANCELLED
                and not allow_cancelled_transition
            ):
                return current
            payload["research_jobs"][index] = job.model_dump(mode="json")
            self._write(payload)
        return job

    def delete_for_conversation(
        self,
        conversation_id: UUID | str,
        user_id: str,
    ) -> None:
        requested_id = str(conversation_id)
        with self._lock:
            payload = self._read()
            retained = [
                item
                for item in payload["research_jobs"]
                if not (
                    item.get("conversation_id") == requested_id
                    and item.get("user_id") == user_id
                )
            ]
            if len(retained) == len(payload["research_jobs"]):
                return
            payload["research_jobs"] = retained
            self._write(payload)

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            payload = self._read()
            payload["research_jobs"] = [
                job
                for job in payload["research_jobs"]
                if job.get("user_id") != user_id
            ]
            self._write(payload)
