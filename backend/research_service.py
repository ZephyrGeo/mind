"""Persistent orchestration for OpenAI background Research responses."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from .models import (
    AgentMode,
    ResearchCitation,
    ResearchJob,
    ResearchRequest,
    ResearchSource,
    ResearchStatus,
    utc_now,
)
from .repositories import ConversationRepository
from .research_provider import (
    ResearchProvider,
    ResearchProviderError,
    ResearchProviderResult,
)
from .research_repositories import ResearchRepository


ACTIVE_PROVIDER_STATUSES = {"queued", "in_progress"}
CANCELLED_PROVIDER_STATUSES = {"cancelled", "canceled"}


class ResearchJobConflictError(RuntimeError):
    """Raised when a terminal job cannot perform the requested transition."""


class ResearchService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        jobs: ResearchRepository,
        provider: ResearchProvider,
        poll_interval_seconds: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self.conversations = conversations
        self.jobs = jobs
        self.provider = provider
        self.poll_interval_seconds = poll_interval_seconds
        self.logger = logger or logging.getLogger(__name__)

    def start_job(self, request: ResearchRequest, user_id: str) -> ResearchJob:
        conversation_id = self.conversations.append_user_message(
            request.conversation_id,
            request.query,
            AgentMode.RESEARCH,
            user_id=user_id,
        )
        job = self.jobs.create_job(
            ResearchJob(
                user_id=user_id,
                conversation_id=UUID(conversation_id),
                query=request.query,
            )
        )
        message_id = self.conversations.append_assistant_message(
            conversation_id,
            "",
            user_id=user_id,
            research_job_id=job.id,
        )
        job.checkpoint.assistant_message_id = UUID(message_id)
        job.updated_at = utc_now()
        return self.jobs.save_job(job, user_id)

    def get_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        """Refresh an owned active job by response_id without creating a task."""

        job = self.jobs.get_job(job_id, user_id)
        if (
            not job.provider_response_id
            or job.status in {ResearchStatus.COMPLETED, ResearchStatus.CANCELLED}
        ):
            return job
        try:
            result = self.provider.parse_result(
                self.provider.retrieve(job.provider_response_id)
            )
            return self._apply_provider_result(job, result)
        except ResearchProviderError as error:
            self.logger.warning(
                "research_refresh_failed",
                extra={
                    "event_data": {
                        "job_id": str(job.id),
                        "provider_error_code": error.code,
                    }
                },
            )
            return job

    def prepare_resume(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        """Continue an active Response, or explicitly start a new one if terminal."""

        job = self.jobs.get_job(job_id, user_id)
        if job.status == ResearchStatus.COMPLETED:
            raise ResearchJobConflictError(
                "Completed research jobs cannot be resumed."
            )
        if job.status not in {ResearchStatus.FAILED, ResearchStatus.CANCELLED}:
            return job
        if (
            job.status == ResearchStatus.FAILED
            and job.provider_response_id
            and job.provider_status in ACTIVE_PROVIDER_STATUSES
            and job.failure_reason != "research_response_not_found"
        ):
            job.status = ResearchStatus.QUEUED
            job.failure_reason = None
            job.updated_at = utc_now()
            return self.jobs.save_job(job, user_id)
        return self._restart_job(job)

    def cancel_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        job = self.jobs.get_job(job_id, user_id)
        if job.status == ResearchStatus.COMPLETED:
            raise ResearchJobConflictError(
                "Completed research jobs cannot be cancelled."
            )
        if job.status == ResearchStatus.CANCELLED:
            return job
        if job.provider_response_id and job.provider_status in ACTIVE_PROVIDER_STATUSES:
            result = self.provider.parse_result(
                self.provider.cancel(job.provider_response_id)
            )
            job = self._apply_provider_result(job, result)
            if job.status in {ResearchStatus.CANCELLED, ResearchStatus.COMPLETED}:
                return job
        job.status = ResearchStatus.CANCELLED
        job.provider_status = job.provider_status or "cancelled"
        job.failure_reason = "research_cancelled"
        job.updated_at = utc_now()
        return self.jobs.save_job(job, user_id)

    def stream_job(
        self,
        job_id: UUID | str,
        user_id: str,
        *,
        request_id: str,
    ) -> Iterator[dict[str, object]]:
        job = self.jobs.get_job(job_id, user_id)
        yield {
            "type": "research_started",
            "job_id": str(job.id),
            "conversation_id": str(job.conversation_id),
            "status": job.status.value,
            "progress": job.progress,
            "restarted": bool(job.previous_response_ids),
            "request_id": request_id,
        }
        try:
            if job.status == ResearchStatus.COMPLETED:
                yield from self._completed_events(job, request_id=request_id)
                return
            if job.status == ResearchStatus.CANCELLED:
                yield self._status_event(job)
                return

            if job.provider_response_id:
                raw_response = self.provider.retrieve(job.provider_response_id)
            else:
                raw_response = self.provider.start(job.query)

            while True:
                result = self.provider.parse_result(raw_response)
                previous_report = job.checkpoint.report
                previous_urls = {
                    _canonical_url(source.url)
                    for source in job.checkpoint.sources
                }
                job = self._apply_provider_result(job, result)

                for source in job.checkpoint.sources:
                    if _canonical_url(source.url) in previous_urls:
                        continue
                    yield {
                        "type": "source",
                        "job_id": str(job.id),
                        "source": _public_source(source),
                    }
                yield self._status_event(job)

                if job.status == ResearchStatus.COMPLETED:
                    if job.checkpoint.report and not previous_report:
                        yield {
                            "type": "delta",
                            "job_id": str(job.id),
                            "delta": job.checkpoint.report,
                        }
                    yield self._done_event(job, request_id=request_id)
                    return
                if job.status == ResearchStatus.CANCELLED:
                    return
                if job.status == ResearchStatus.FAILED:
                    yield {
                        "type": "error",
                        "job_id": str(job.id),
                        "code": result.error_code or "research_provider_failed",
                        "message": result.public_message
                        or "OpenAI Research could not complete the report.",
                        "retryable": result.retryable,
                        "request_id": request_id,
                    }
                    return

                time.sleep(self.poll_interval_seconds)
                current = self.jobs.get_job(job.id, user_id)
                if current.status == ResearchStatus.CANCELLED:
                    yield self._status_event(current)
                    return
                if not current.provider_response_id:
                    raise ResearchProviderError(
                        "research_invalid_response",
                        "OpenAI Research did not return a response ID.",
                        retryable=True,
                    )
                job = current
                raw_response = self.provider.retrieve(
                    current.provider_response_id
                )
        except ResearchProviderError as error:
            failed = self._mark_transport_failure(job, error.code)
            if failed.status == ResearchStatus.CANCELLED:
                yield self._status_event(failed)
                return
            yield {
                "type": "error",
                "job_id": str(job.id),
                "code": error.code,
                "message": error.public_message,
                "retryable": error.retryable,
                "request_id": request_id,
            }
        except GeneratorExit:
            # The OpenAI background Response continues. A later GET/resume uses the
            # persisted response_id instead of creating a duplicate provider task.
            raise
        except Exception:
            self.logger.exception(
                "research_job_failed",
                extra={
                    "event_data": {
                        "job_id": str(job.id),
                        "request_id": request_id,
                    }
                },
            )
            failed = self._mark_transport_failure(job, "research_failed")
            if failed.status == ResearchStatus.CANCELLED:
                yield self._status_event(failed)
                return
            yield {
                "type": "error",
                "job_id": str(job.id),
                "code": "research_failed",
                "message": "The research job could not be completed. You can retry it.",
                "retryable": True,
                "request_id": request_id,
            }

    def _apply_provider_result(
        self,
        job: ResearchJob,
        result: ResearchProviderResult,
    ) -> ResearchJob:
        current = self.jobs.get_job(job.id, job.user_id)
        if current.status == ResearchStatus.CANCELLED:
            return current
        if (
            current.provider_response_id
            and current.provider_response_id != result.response_id
        ):
            raise ResearchProviderError(
                "research_response_mismatch",
                "OpenAI returned an unexpected research response.",
                retryable=False,
            )
        current.provider_response_id = result.response_id
        current.provider_status = result.status
        self._merge_sources_and_citations(current, result)

        if result.status == "queued":
            current.status = ResearchStatus.QUEUED
            current.progress = max(current.progress, 0.05)
            current.failure_reason = None
        elif result.status == "in_progress":
            current.status = ResearchStatus.COLLECTING
            current.progress = max(current.progress, 0.55)
            current.failure_reason = None
        elif result.status == "completed":
            report = result.output_text.strip()
            if not report:
                raise ResearchProviderError(
                    "research_report_empty",
                    "OpenAI Research returned an empty report. Please retry it.",
                    retryable=True,
                )
            current.checkpoint.report = report
            message_id = self.conversations.append_assistant_message(
                current.conversation_id,
                report,
                user_id=current.user_id,
                research_job_id=current.id,
            )
            current.checkpoint.assistant_message_id = UUID(message_id)
            current.status = ResearchStatus.COMPLETED
            current.progress = 1.0
            current.failure_reason = None
        elif result.status in CANCELLED_PROVIDER_STATUSES:
            current.status = ResearchStatus.CANCELLED
            current.failure_reason = result.error_code or "research_cancelled"
        else:
            current.status = ResearchStatus.FAILED
            current.failure_reason = (
                result.error_code or "research_provider_failed"
            )
        current.updated_at = utc_now()
        return self.jobs.save_job(current, current.user_id)

    def _merge_sources_and_citations(
        self,
        job: ResearchJob,
        result: ResearchProviderResult,
    ) -> None:
        source_by_url = {
            _canonical_url(source.url): source
            for source in job.checkpoint.sources
        }
        for provider_source in result.sources:
            canonical = _canonical_url(provider_source.url)
            if not canonical or canonical in source_by_url:
                continue
            source = ResearchSource(
                id=f"S{len(job.checkpoint.sources) + 1}",
                step_id="openai-web-search",
                title=provider_source.title[:1_000] or provider_source.url,
                url=provider_source.url[:4_096],
            )
            job.checkpoint.sources.append(source)
            source_by_url[canonical] = source

        citations: list[ResearchCitation] = []
        seen: set[tuple[str, int, int]] = set()
        for provider_citation in result.citations:
            source = source_by_url.get(_canonical_url(provider_citation.url))
            if source is None:
                continue
            key = (
                provider_citation.url,
                provider_citation.start_index,
                provider_citation.end_index,
            )
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                ResearchCitation(
                    source_id=source.id,
                    title=provider_citation.title[:1_000]
                    or provider_citation.url,
                    url=provider_citation.url[:4_096],
                    start_index=provider_citation.start_index,
                    end_index=provider_citation.end_index,
                )
            )
        job.checkpoint.citations = citations

    def _restart_job(self, job: ResearchJob) -> ResearchJob:
        if (
            job.provider_response_id
            and job.provider_response_id not in job.previous_response_ids
        ):
            job.previous_response_ids.append(job.provider_response_id)
        job.provider_response_id = None
        job.provider_status = None
        job.checkpoint.plan = None
        job.checkpoint.sources = []
        job.checkpoint.citations = []
        job.checkpoint.completed_step_ids = []
        job.checkpoint.report = ""
        job.status = ResearchStatus.QUEUED
        job.progress = 0
        job.failure_reason = None
        job.updated_at = utc_now()
        return self.jobs.save_job(
            job,
            job.user_id,
            allow_cancelled_transition=True,
        )

    def _mark_transport_failure(
        self,
        job: ResearchJob,
        reason: str,
    ) -> ResearchJob:
        current = self.jobs.get_job(job.id, job.user_id)
        if current.status in {
            ResearchStatus.CANCELLED,
            ResearchStatus.COMPLETED,
        }:
            return current
        current.status = ResearchStatus.FAILED
        current.failure_reason = reason
        current.updated_at = utc_now()
        return self.jobs.save_job(current, current.user_id)

    def _completed_events(
        self,
        job: ResearchJob,
        *,
        request_id: str,
    ) -> Iterator[dict[str, object]]:
        for source in job.checkpoint.sources:
            yield {
                "type": "source",
                "job_id": str(job.id),
                "source": _public_source(source),
            }
        if job.checkpoint.report:
            yield {
                "type": "delta",
                "job_id": str(job.id),
                "delta": job.checkpoint.report,
            }
        yield self._done_event(job, request_id=request_id)

    @staticmethod
    def _status_event(job: ResearchJob) -> dict[str, object]:
        return {
            "type": "status",
            "job_id": str(job.id),
            "status": job.status.value,
            "provider_status": job.provider_status,
            "progress": job.progress,
        }

    @staticmethod
    def _done_event(
        job: ResearchJob,
        *,
        request_id: str,
    ) -> dict[str, object]:
        return {
            "type": "done",
            "job_id": str(job.id),
            "conversation_id": str(job.conversation_id),
            "status": job.status.value,
            "progress": job.progress,
            "source_count": len(job.checkpoint.sources),
            "citations": [
                citation.model_dump(mode="json")
                for citation in job.checkpoint.citations
            ],
            "request_id": request_id,
        }


def _public_source(source: ResearchSource) -> dict[str, object]:
    return {
        "id": source.id,
        "step_id": source.step_id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet,
        "published_at": source.published_at,
    }


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    host = parsed.hostname.lower()
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (parsed.scheme.lower(), f"{host}{port}", path, parsed.query, "")
    )
