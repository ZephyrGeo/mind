"""Durable, provider-independent orchestration for Mind Deep Research."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator, Mapping
from math import ceil
from typing import Any, cast
from uuid import UUID

from .memory_service import MemoryService
from .models import (
    AgentMode,
    ResearchBrief,
    ResearchBriefQuestion,
    ResearchBudget,
    ResearchCitation,
    ResearchEvidenceGap,
    ResearchJob,
    ResearchRequest,
    ResearchSource,
    ResearchStatus,
    ResearchSubtask,
    ResearchTaskKind,
    ResearchTaskStatus,
    ResearchVerification,
    utc_now,
)
from .repositories import ConversationRepository
from .research_provider import (
    ResearchProvider,
    ResearchProviderError,
    ResearchProviderRequest,
    ResearchProviderResult,
)
from .research_quality import evaluate_research_quality
from .research_repositories import ResearchRepository
from .source_urls import canonical_source_url


ACTIVE_PROVIDER_STATUSES = {"queued", "in_progress"}
CANCELLED_PROVIDER_STATUSES = {"cancelled", "canceled"}
TERMINAL_JOB_STATUSES = {
    ResearchStatus.COMPLETED,
    ResearchStatus.CANCELLED,
}
PROMPT_VERSION = "research-harness-v3"
DEFAULT_MIN_CITATION_COVERAGE = 0.8
MAX_CITATION_REPAIR_ATTEMPTS = 2
OPENAI_BACKGROUND_GUIDE_URL = (
    "https://developers.openai.com/api/docs/guides/background"
)
OPENAI_DATA_CONTROLS_GUIDE_URL = (
    "https://developers.openai.com/api/docs/guides/your-data"
)
_NON_CONFLICT_PHRASES = (
    "not a conflict",
    "not conflict",
    "does not conflict",
    "documentation gap",
    "documentation omission",
    "missing documentation",
    "outdated source",
    "stale source",
    "resolved by",
    "并非冲突",
    "不是冲突",
    "不构成冲突",
    "文档缺口",
    "文档空白",
    "文档遗漏",
    "旧版文档",
    "过时来源",
    "已解决",
)


class ResearchJobConflictError(RuntimeError):
    """Raised when a terminal job cannot perform the requested transition."""


class ResearchService:
    """Run Mind's multi-response Research Harness over a provider interface."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        jobs: ResearchRepository,
        provider: ResearchProvider,
        poll_interval_seconds: float,
        max_search_rounds: int = 2,
        max_subquestions: int = 6,
        max_total_tool_calls: int = 24,
        tool_call_overrun_ratio: float = 0.15,
        max_tool_call_overrun: int = 3,
        min_citation_coverage: float = DEFAULT_MIN_CITATION_COVERAGE,
        job_timeout_seconds: int = 600,
        max_tool_calls_per_task: int = 8,
        memory_service: MemoryService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.conversations = conversations
        self.jobs = jobs
        self.provider = provider
        self.poll_interval_seconds = poll_interval_seconds
        self.max_search_rounds = max_search_rounds
        self.max_subquestions = max_subquestions
        self.max_total_tool_calls = max_total_tool_calls
        self.tool_call_overrun_ratio = tool_call_overrun_ratio
        self.max_tool_call_overrun = max_tool_call_overrun
        self.min_citation_coverage = min_citation_coverage
        self.job_timeout_seconds = job_timeout_seconds
        self.max_tool_calls_per_task = max_tool_calls_per_task
        self.memory_service = memory_service
        self.logger = logger or logging.getLogger(__name__)

    def start_job(self, request: ResearchRequest, user_id: str) -> ResearchJob:
        conversation_id = self.conversations.append_user_message(
            request.conversation_id,
            request.query,
            AgentMode.RESEARCH,
            user_id=user_id,
        )
        budget = ResearchBudget(
            max_search_rounds=self.max_search_rounds,
            max_subquestions=self.max_subquestions,
            max_total_tool_calls=self.max_total_tool_calls,
            max_tool_call_overrun=self._configured_tool_call_overrun(),
            timeout_seconds=self.job_timeout_seconds,
        )
        memory_ids: list[UUID] = []
        if self.memory_service is not None:
            memory_ids, _ = self.memory_service.context_for_query(
                user_id,
                request.query,
            )
        job = ResearchJob(
            user_id=user_id,
            conversation_id=UUID(conversation_id),
            query=request.query,
            model=self.provider.model,
            prompt_version=PROMPT_VERSION,
            budget=budget,
            memory_ids=memory_ids,
        )
        job.checkpoint.subtasks.append(self._brief_task(job))
        job = self.jobs.create_job(job)
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
        """Refresh saved responses only; a GET never starts provider work."""

        job = self.jobs.get_job(job_id, user_id)
        budget_changed = self._refresh_budget_state(job)
        if self._consolidate_source_ledger(job) or budget_changed:
            job.updated_at = utc_now()
            job = self.jobs.save_job(job, user_id)
        if job.status in TERMINAL_JOB_STATUSES | {ResearchStatus.FAILED}:
            return job
        try:
            return self._advance_once(job, allow_start=False)
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
        """Resume live responses or explicitly restart terminal provider tasks."""

        job = self.jobs.get_job(job_id, user_id)
        if job.status == ResearchStatus.COMPLETED:
            raise ResearchJobConflictError(
                "Completed research jobs cannot be resumed."
            )
        if job.status == ResearchStatus.CANCELLED:
            return self._restart_job(job)
        if job.status != ResearchStatus.FAILED:
            return job
        if job.failure_reason == "research_required_sources_missing":
            return self._restart_job(job)

        active = self._active_tasks(job)
        if active:
            job.status = self._phase_for_task(active[0])
            job.failure_reason = None
            job.updated_at = utc_now()
            return self.jobs.save_job(job, user_id)

        reset_any = False
        retry_cancelled = job.failure_reason == "research_timeout"
        for task in job.checkpoint.subtasks:
            if task.status != ResearchTaskStatus.FAILED and not (
                retry_cancelled
                and task.status == ResearchTaskStatus.CANCELLED
                and (
                    task.error_code == "research_timeout"
                    or task.kind == ResearchTaskKind.CITATION_REPAIR
                )
            ):
                continue
            self._remember_response(job, task.response_id)
            task.response_id = None
            task.provider_status = None
            task.status = ResearchTaskStatus.PENDING
            task.error_code = None
            task.output_text = ""
            task.updated_at = utc_now()
            reset_any = True
        if not reset_any:
            return self._restart_job(job)
        pending = next(
            (
                task
                for task in job.checkpoint.subtasks
                if task.status == ResearchTaskStatus.PENDING
            ),
            None,
        )
        job.status = self._phase_for_task(pending) if pending else job.status
        job.failure_reason = None
        job.run_started_at = utc_now()
        job.updated_at = utc_now()
        return self.jobs.save_job(job, user_id)

    def cancel_job(self, job_id: UUID | str, user_id: str) -> ResearchJob:
        job = self._ensure_harness_job(self.jobs.get_job(job_id, user_id))
        if job.status == ResearchStatus.COMPLETED:
            raise ResearchJobConflictError(
                "Completed research jobs cannot be cancelled."
            )
        if job.status == ResearchStatus.CANCELLED:
            return job

        errors: list[ResearchProviderError] = []
        for task in self._active_tasks(job):
            if not task.response_id:
                continue
            try:
                result = self.provider.parse_result(
                    self.provider.cancel(task.response_id)
                )
                self._apply_task_result(job, task, result)
            except ResearchProviderError as error:
                errors.append(error)
                task.status = ResearchTaskStatus.CANCELLED
                task.error_code = error.code
                task.updated_at = utc_now()

        for task in job.checkpoint.subtasks:
            if task.status in {
                ResearchTaskStatus.PENDING,
                ResearchTaskStatus.QUEUED,
                ResearchTaskStatus.RUNNING,
            }:
                task.status = ResearchTaskStatus.CANCELLED
                task.error_code = task.error_code or "research_cancelled"
                task.updated_at = utc_now()
        job.status = ResearchStatus.CANCELLED
        job.provider_status = "cancelled"
        job.failure_reason = "research_cancelled"
        job.updated_at = utc_now()
        saved = self.jobs.save_job(job, user_id)
        if errors:
            self.logger.warning(
                "research_cancel_partially_failed",
                extra={
                    "event_data": {
                        "job_id": str(job.id),
                        "failed_response_count": len(errors),
                    }
                },
            )
        return saved

    def stream_job(
        self,
        job_id: UUID | str,
        user_id: str,
        *,
        request_id: str,
    ) -> Iterator[dict[str, object]]:
        job = self.jobs.get_job(job_id, user_id)
        yield self._started_event(job, request_id=request_id)
        try:
            if job.status == ResearchStatus.COMPLETED:
                yield from self._completed_events(job, request_id=request_id)
                return
            if job.status == ResearchStatus.CANCELLED:
                yield self._status_event(job)
                return

            while True:
                previous_urls = {
                    canonical_source_url(source.url)
                    for source in job.checkpoint.sources
                }
                previous_report = job.checkpoint.report
                job = self._advance_once(job, allow_start=True)

                for source in job.checkpoint.sources:
                    if canonical_source_url(source.url) in previous_urls:
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
                    yield self._error_event(job, request_id=request_id)
                    return

                time.sleep(self.poll_interval_seconds)
                current = self.jobs.get_job(job.id, user_id)
                if current.status == ResearchStatus.CANCELLED:
                    yield self._status_event(current)
                    return
                job = current
        except ResearchProviderError as error:
            failed = self._mark_failure(job, error.code)
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
            # Provider Responses keep running in background. Their IDs have already
            # been persisted, so a later GET/resume retrieves instead of recreating.
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
            failed = self._mark_failure(job, "research_failed")
            if failed.status == ResearchStatus.CANCELLED:
                yield self._status_event(failed)
                return
            yield self._error_event(failed, request_id=request_id)

    def _advance_once(
        self,
        job: ResearchJob,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        job = self._ensure_harness_job(job)
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        if self._timed_out(job):
            self._cancel_active_tasks(job)
            job.status = ResearchStatus.FAILED
            job.failure_reason = "research_timeout"
            job.provider_status = "failed"
            job.updated_at = utc_now()
            return self.jobs.save_job(job, job.user_id)

        legacy = self._task(job, "legacy-response")
        if legacy is not None:
            return self._advance_legacy(job, legacy, allow_start=allow_start)

        if job.checkpoint.brief is None:
            job = self._advance_planning(job, allow_start=allow_start)
        elif job.status in {ResearchStatus.QUEUED, ResearchStatus.PLANNING}:
            job.status = ResearchStatus.COLLECTING

        if job.status == ResearchStatus.COLLECTING:
            job = self._advance_collecting(job, allow_start=allow_start)
        if job.status == ResearchStatus.VERIFYING:
            job = self._advance_verifying(job, allow_start=allow_start)
        if job.status == ResearchStatus.SYNTHESIZING:
            job = self._advance_synthesis(job, allow_start=allow_start)

        job.updated_at = utc_now()
        return self.jobs.save_job(job, job.user_id)

    def _advance_planning(
        self,
        job: ResearchJob,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        job.status = ResearchStatus.PLANNING
        job.progress = max(job.progress, 0.05)
        task = self._task(job, "brief")
        if task is None:
            task = self._brief_task(job)
            job.checkpoint.subtasks.append(task)
        self._advance_task(
            job,
            task,
            self._brief_request(job),
            allow_start=allow_start,
        )
        if task.status == ResearchTaskStatus.COMPLETED:
            job.checkpoint.brief = self._parse_brief(job, task.output_text)
            self._create_search_tasks(job, round_index=1)
            job.search_round = 1
            job.status = ResearchStatus.COLLECTING
            job.progress = max(job.progress, 0.15)
        return job

    def _advance_collecting(
        self,
        job: ResearchJob,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        round_tasks = [
            task
            for task in job.checkpoint.subtasks
            if task.kind == ResearchTaskKind.SEARCH
            and task.round_index == job.search_round
        ]
        if not round_tasks:
            self._create_verification_task(job)
            job.status = ResearchStatus.VERIFYING
            return job

        for task in round_tasks:
            if task.status in {
                ResearchTaskStatus.COMPLETED,
                ResearchTaskStatus.CANCELLED,
            }:
                continue
            if not task.response_id:
                if self._soft_budget_reached(job):
                    self._stop_pending_search_tasks_for_budget(job)
                    continue
                if not self._can_start_search_task(job, task):
                    continue
            self._advance_task(
                job,
                task,
                self._search_request(job, task),
                allow_start=allow_start,
            )
            if task.status == ResearchTaskStatus.FAILED:
                self._fail_from_task(job, task)
                return job
            if job.hard_budget_reached:
                self._stop_search_tasks_for_budget(job)
                break
            if self._soft_budget_reached(job):
                self._stop_pending_search_tasks_for_budget(job)

        completed = sum(
            task.status == ResearchTaskStatus.COMPLETED for task in round_tasks
        )
        settled = sum(
            task.status
            in {
                ResearchTaskStatus.COMPLETED,
                ResearchTaskStatus.CANCELLED,
            }
            for task in round_tasks
        )
        fraction = completed / len(round_tasks)
        base = 0.15 if job.search_round == 1 else 0.58
        span = 0.35 if job.search_round == 1 else 0.12
        job.progress = max(job.progress, base + span * fraction)
        if settled == len(round_tasks):
            self._create_verification_task(job)
            job.status = ResearchStatus.VERIFYING
            job.progress = max(job.progress, 0.52 if job.search_round == 1 else 0.72)
        return job

    def _advance_verifying(
        self,
        job: ResearchJob,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        task_id = f"verify-r{job.search_round}"
        task = self._task(job, task_id)
        if task is None:
            task = self._create_verification_task(job)
        self._advance_task(
            job,
            task,
            self._verification_request(job),
            allow_start=allow_start,
        )
        if task.status == ResearchTaskStatus.FAILED:
            self._fail_from_task(job, task)
            return job
        if task.status != ResearchTaskStatus.COMPLETED:
            job.progress = max(job.progress, 0.55 if job.search_round == 1 else 0.74)
            return job

        verification = self._parse_verification(task.output_text)
        required_source_gaps = self._required_official_source_gaps(job)
        if required_source_gaps:
            verification = verification.model_copy(
                update={
                    "gaps": (
                        required_source_gaps + verification.gaps
                    )[:8],
                    "coverage_notes": (
                        verification.coverage_notes
                        + [
                            "Current canonical official sources required by the "
                            "topic are still missing from the source ledger."
                        ]
                    )[:20],
                }
            )
        job.checkpoint.verification = verification
        if (
            required_source_gaps
            and job.search_round >= job.budget.max_search_rounds
        ):
            task.status = ResearchTaskStatus.FAILED
            task.provider_status = "failed"
            task.error_code = "research_required_sources_missing"
            task.updated_at = utc_now()
            self._fail_from_task(job, task)
            return job
        can_search_again = (
            bool(verification.gaps)
            and job.search_round < job.budget.max_search_rounds
            and self._remaining_tool_calls(job) > 0
        )
        if can_search_again:
            self._create_follow_up_tasks(job, verification.gaps)
            job.search_round += 1
            job.status = ResearchStatus.COLLECTING
            job.progress = max(job.progress, 0.58)
        else:
            self._create_synthesis_task(job)
            job.status = ResearchStatus.SYNTHESIZING
            job.progress = max(job.progress, 0.78)
        return job

    def _advance_synthesis(
        self,
        job: ResearchJob,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        task = self._task(job, "synthesis")
        if task is None:
            task = self._create_synthesis_task(job)
        self._advance_task(
            job,
            task,
            self._synthesis_request(job),
            allow_start=allow_start,
        )
        if task.status == ResearchTaskStatus.FAILED:
            self._fail_from_task(job, task)
            return job
        if task.status != ResearchTaskStatus.COMPLETED:
            job.progress = max(job.progress, 0.82)
            return job

        candidate = task.output_text.strip()
        coverage = self._report_citation_coverage(job, candidate)
        job.citation_coverage = coverage
        if coverage >= self.min_citation_coverage:
            self._finalize_report(job, candidate)
            return job

        last_repair: ResearchSubtask | None = None
        for attempt in range(1, MAX_CITATION_REPAIR_ATTEMPTS + 1):
            repair = self._create_citation_repair_task(job, attempt)
            last_repair = repair
            self._advance_task(
                job,
                repair,
                self._citation_repair_request(
                    job,
                    candidate,
                    coverage,
                    attempt=attempt,
                ),
                allow_start=allow_start,
            )
            if repair.status == ResearchTaskStatus.FAILED:
                self._fail_from_task(job, repair)
                return job
            if repair.status != ResearchTaskStatus.COMPLETED:
                job.progress = max(job.progress, 0.9 + 0.03 * attempt)
                return job

            candidate = repair.output_text.strip()
            coverage = self._report_citation_coverage(job, candidate)
            job.citation_coverage = coverage
            if coverage >= self.min_citation_coverage:
                self._finalize_report(job, candidate)
                return job

        assert last_repair is not None
        last_repair.status = ResearchTaskStatus.FAILED
        last_repair.provider_status = "failed"
        last_repair.error_code = "research_citation_coverage_low"
        last_repair.updated_at = utc_now()
        self._fail_from_task(job, last_repair)
        return job

    def _advance_legacy(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
        *,
        allow_start: bool,
    ) -> ResearchJob:
        del allow_start
        job.status = ResearchStatus.SYNTHESIZING
        if not task.response_id:
            job.status = ResearchStatus.FAILED
            job.failure_reason = "research_invalid_response"
            return self.jobs.save_job(job, job.user_id)
        if task.status not in {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.CANCELLED,
        }:
            result = self.provider.parse_result(
                self.provider.retrieve(task.response_id)
            )
            self._apply_task_result(job, task, result)
        if task.status == ResearchTaskStatus.COMPLETED:
            job.checkpoint.citations = list(task.citations)
            self._finalize_report(job, task.output_text, preserve_citations=True)
        elif task.status == ResearchTaskStatus.FAILED:
            self._fail_from_task(job, task)
        elif task.status == ResearchTaskStatus.CANCELLED:
            job.status = ResearchStatus.CANCELLED
            job.failure_reason = task.error_code or "research_cancelled"
        job.updated_at = utc_now()
        return self.jobs.save_job(job, job.user_id)

    def _advance_task(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
        request: ResearchProviderRequest,
        *,
        allow_start: bool,
    ) -> None:
        if task.status in {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.CANCELLED,
        }:
            return
        if task.response_id:
            raw_response = self.provider.retrieve(task.response_id)
        elif allow_start:
            raw_response = self.provider.start(request)
        else:
            return
        result = self.provider.parse_result(raw_response)
        self._apply_task_result(job, task, result)
        # Persist each response ID immediately. Other tasks in the same search
        # round may still be starting, so browser refresh can recover all work
        # that has already reached the provider.
        self.jobs.save_job(job, job.user_id)

    def _apply_task_result(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
        result: ResearchProviderResult,
    ) -> None:
        if task.response_id and task.response_id != result.response_id:
            raise ResearchProviderError(
                "research_response_mismatch",
                "OpenAI returned an unexpected research response.",
                retryable=False,
            )
        task.response_id = result.response_id
        task.provider_status = result.status
        task.tool_call_count = max(
            task.tool_call_count,
            result.tool_call_count,
        )
        task.error_code = result.error_code
        job.provider_response_id = result.response_id
        job.provider_status = result.status
        self._merge_task_evidence(job, task, result)

        if result.status == "queued":
            task.status = ResearchTaskStatus.QUEUED
        elif result.status == "in_progress":
            task.status = ResearchTaskStatus.RUNNING
        elif result.status == "completed":
            output = result.output_text.strip()
            if not output:
                raise ResearchProviderError(
                    "research_task_empty",
                    "OpenAI returned an empty Research task. Please retry it.",
                    retryable=True,
                )
            task.output_text = output
            task.status = ResearchTaskStatus.COMPLETED
            task.error_code = None
        elif result.status in CANCELLED_PROVIDER_STATUSES:
            task.status = ResearchTaskStatus.CANCELLED
            task.error_code = result.error_code or "research_cancelled"
        else:
            task.status = ResearchTaskStatus.FAILED
            task.error_code = result.error_code or "research_provider_failed"
        task.updated_at = utc_now()
        job.total_tool_calls = sum(
            item.tool_call_count for item in job.checkpoint.subtasks
        )
        self._refresh_budget_state(job)

    def _merge_task_evidence(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
        result: ResearchProviderResult,
    ) -> None:
        self._consolidate_source_ledger(job)
        source_by_url = {
            canonical_source_url(source.url): source
            for source in job.checkpoint.sources
        }
        task_urls = {
            canonical_source_url(source.url) for source in task.sources
        }
        for provider_source in result.sources:
            canonical = canonical_source_url(provider_source.url)
            if not canonical:
                continue
            source = source_by_url.get(canonical)
            if source is None:
                source = ResearchSource(
                    id=self._next_source_id(job),
                    step_id=task.id,
                    title=(provider_source.title or provider_source.url)[:1_000],
                    url=canonical[:4_096],
                )
                job.checkpoint.sources.append(source)
                source_by_url[canonical] = source
            if canonical not in task_urls:
                task.sources.append(source.model_copy(deep=True))
                task_urls.add(canonical)

        citations: list[ResearchCitation] = []
        seen: set[tuple[str, int, int]] = set()
        for provider_citation in result.citations:
            source = source_by_url.get(
                canonical_source_url(provider_citation.url)
            )
            if source is None:
                continue
            key = (
                source.id,
                provider_citation.start_index,
                provider_citation.end_index,
            )
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                ResearchCitation(
                    source_id=source.id,
                    title=(provider_citation.title or source.title)[:1_000],
                    url=source.url,
                    start_index=provider_citation.start_index,
                    end_index=provider_citation.end_index,
                )
            )
        if citations:
            task.citations = citations

    def _consolidate_source_ledger(self, job: ResearchJob) -> bool:
        """Merge equivalent persisted sources while preserving the first ID."""

        changed = False
        kept_by_url: dict[str, ResearchSource] = {}
        id_map: dict[str, str] = {}
        unique_sources: list[ResearchSource] = []
        for source in job.checkpoint.sources:
            canonical = canonical_source_url(source.url)
            if not canonical:
                changed = True
                continue
            kept = kept_by_url.get(canonical)
            if kept is not None:
                id_map[source.id] = kept.id
                changed = True
                if kept.title == kept.url and source.title != source.url:
                    kept.title = source.title
                if not kept.snippet and source.snippet:
                    kept.snippet = source.snippet
                if not kept.content and source.content:
                    kept.content = source.content
                if kept.published_at is None and source.published_at is not None:
                    kept.published_at = source.published_at
                continue
            if source.url != canonical:
                source.url = canonical
                changed = True
            kept_by_url[canonical] = source
            id_map[source.id] = source.id
            unique_sources.append(source)

        if job.checkpoint.sources != unique_sources:
            job.checkpoint.sources = unique_sources
            changed = True

        source_by_id = {source.id: source for source in unique_sources}
        for task in job.checkpoint.subtasks:
            task_sources: list[ResearchSource] = []
            seen_urls: set[str] = set()
            for task_source in task.sources:
                canonical = canonical_source_url(task_source.url)
                source = kept_by_url.get(canonical)
                if source is None or canonical in seen_urls:
                    changed = True
                    continue
                task_sources.append(source.model_copy(deep=True))
                seen_urls.add(canonical)
            if task.sources != task_sources:
                task.sources = task_sources
                changed = True
            remapped = _remap_citations(task.citations, source_by_id, id_map)
            if task.citations != remapped:
                task.citations = remapped
                changed = True

        report = _replace_source_markers(job.checkpoint.report, id_map)
        if report != job.checkpoint.report:
            job.checkpoint.report = report
            changed = True
        checkpoint_citations = (
            self._citations_from_markers(job, report)
            if re.search(r"\[S\d+\]", report)
            else _remap_citations(
                job.checkpoint.citations,
                source_by_id,
                id_map,
            )
        )
        if job.checkpoint.citations != checkpoint_citations:
            job.checkpoint.citations = checkpoint_citations
            changed = True

        verification = job.checkpoint.verification
        if verification is not None:
            rewritten = verification.model_copy(
                update={
                    "summary": _replace_source_markers(
                        verification.summary,
                        id_map,
                    ),
                    "conflicts": [
                        _replace_source_markers(value, id_map)
                        for value in verification.conflicts
                    ],
                    "gaps": [
                        gap.model_copy(
                            update={
                                "question": _replace_source_markers(
                                    gap.question,
                                    id_map,
                                ),
                                "reason": _replace_source_markers(
                                    gap.reason,
                                    id_map,
                                ),
                            }
                        )
                        for gap in verification.gaps
                    ],
                    "coverage_notes": [
                        _replace_source_markers(value, id_map)
                        for value in verification.coverage_notes
                    ],
                }
            )
            if verification != rewritten:
                job.checkpoint.verification = rewritten
                changed = True
        return changed

    @staticmethod
    def _next_source_id(job: ResearchJob) -> str:
        numeric_ids = [
            int(match.group(1))
            for source in job.checkpoint.sources
            if (match := re.fullmatch(r"S(\d+)", source.id)) is not None
        ]
        return f"S{max(numeric_ids, default=0) + 1}"

    def _finalize_report(
        self,
        job: ResearchJob,
        report: str,
        *,
        preserve_citations: bool = False,
    ) -> None:
        normalized = report.strip()
        if not normalized:
            raise ResearchProviderError(
                "research_report_empty",
                "OpenAI Research returned an empty report. Please retry it.",
                retryable=True,
            )
        job.checkpoint.report = normalized
        if not preserve_citations:
            job.checkpoint.citations = self._citations_from_markers(job, normalized)
        job.citation_coverage = self._report_citation_coverage(
            job,
            normalized,
            citations=(job.checkpoint.citations if preserve_citations else None),
        )
        message_id = self.conversations.append_assistant_message(
            job.conversation_id,
            normalized,
            user_id=job.user_id,
            research_job_id=job.id,
        )
        job.checkpoint.assistant_message_id = UUID(message_id)
        job.status = ResearchStatus.COMPLETED
        job.provider_status = "completed"
        job.progress = 1.0
        job.failure_reason = None
        if self.memory_service is not None:
            try:
                self.memory_service.capture_research_report_candidates(
                    user_id=job.user_id,
                    conversation_id=job.conversation_id,
                    research_job_id=job.id,
                    report=normalized,
                )
            except Exception:
                self.logger.exception(
                    "research_memory_candidate_capture_failed",
                    extra={"event_data": {"job_id": str(job.id)}},
                )

    def _report_citation_coverage(
        self,
        job: ResearchJob,
        report: str,
        *,
        citations: list[ResearchCitation] | None = None,
    ) -> float:
        resolved_citations = (
            citations
            if citations is not None
            else self._citations_from_markers(job, report)
        )
        return evaluate_research_quality(
            report=report,
            sources=job.checkpoint.sources,
            citations=resolved_citations,
            detected_conflicts=(
                job.checkpoint.verification.conflicts
                if job.checkpoint.verification
                else []
            ),
        ).citation_coverage

    def _citations_from_markers(
        self,
        job: ResearchJob,
        report: str,
    ) -> list[ResearchCitation]:
        source_by_id = {
            source.id: source for source in job.checkpoint.sources
        }
        citations: list[ResearchCitation] = []
        for match in re.finditer(r"\[(S\d+)\]", report):
            source = source_by_id.get(match.group(1))
            if source is None:
                continue
            citations.append(
                ResearchCitation(
                    source_id=source.id,
                    title=source.title,
                    url=source.url,
                    start_index=match.start(),
                    end_index=match.end(),
                )
            )
        return citations

    def _brief_task(self, job: ResearchJob) -> ResearchSubtask:
        return ResearchSubtask(
            id="brief",
            kind=ResearchTaskKind.BRIEF,
            question=job.query,
            objective="Clarify the research objective and create a bounded brief.",
        )

    def _create_search_tasks(
        self,
        job: ResearchJob,
        *,
        round_index: int,
    ) -> None:
        brief = job.checkpoint.brief
        if brief is None:
            return
        for question in brief.subquestions[: job.budget.max_subquestions]:
            task_id = f"search-r{round_index}-{question.id}"
            if self._task(job, task_id) is not None:
                continue
            job.checkpoint.subtasks.append(
                ResearchSubtask(
                    id=task_id,
                    kind=ResearchTaskKind.SEARCH,
                    round_index=round_index,
                    subquestion_id=question.id,
                    question=question.question,
                    objective=question.objective,
                    tool_call_limit=self._tool_limit_for_search(job),
                )
            )

    def _create_follow_up_tasks(
        self,
        job: ResearchJob,
        gaps: list[ResearchEvidenceGap],
    ) -> None:
        round_index = job.search_round + 1
        for gap in gaps[: job.budget.max_subquestions]:
            if self._unallocated_tool_calls(job) <= 0:
                break
            task_id = f"search-r{round_index}-{gap.id}"
            if self._task(job, task_id) is not None:
                continue
            job.checkpoint.subtasks.append(
                ResearchSubtask(
                    id=task_id,
                    kind=ResearchTaskKind.SEARCH,
                    round_index=round_index,
                    subquestion_id=gap.id,
                    question=gap.question,
                    objective=gap.reason,
                    tool_call_limit=self._tool_limit_for_search(job),
                )
            )

    def _create_verification_task(self, job: ResearchJob) -> ResearchSubtask:
        task_id = f"verify-r{job.search_round}"
        existing = self._task(job, task_id)
        if existing is not None:
            return existing
        task = ResearchSubtask(
            id=task_id,
            kind=ResearchTaskKind.VERIFY,
            round_index=job.search_round,
            question="Check the collected evidence for gaps and conflicts.",
            objective=(
                "Identify unsupported claims, conflicting evidence, and the "
                "smallest useful set of follow-up searches."
            ),
        )
        job.checkpoint.subtasks.append(task)
        return task

    def _create_synthesis_task(self, job: ResearchJob) -> ResearchSubtask:
        existing = self._task(job, "synthesis")
        if existing is not None:
            return existing
        task = ResearchSubtask(
            id="synthesis",
            kind=ResearchTaskKind.SYNTHESIS,
            round_index=job.search_round,
            question=job.query,
            objective=(
                "Write one evidence-grounded report with stable Mind source markers."
            ),
        )
        job.checkpoint.subtasks.append(task)
        return task

    def _create_citation_repair_task(
        self,
        job: ResearchJob,
        attempt: int,
    ) -> ResearchSubtask:
        task_id = f"citation-repair-{attempt}"
        existing = self._task(job, task_id)
        if existing is None and attempt == 1:
            existing = self._task(job, "citation-repair")
        if existing is not None:
            return existing
        task = ResearchSubtask(
            id=task_id,
            kind=ResearchTaskKind.CITATION_REPAIR,
            round_index=job.search_round,
            question=job.query,
            objective=(
                "Rewrite the draft so factual claims have sentence-level citations."
            ),
        )
        job.checkpoint.subtasks.append(task)
        return task

    def _parse_brief(self, job: ResearchJob, output_text: str) -> ResearchBrief:
        payload = _parse_json_object(output_text, "research_brief_invalid")
        raw_questions = payload.get("subquestions")
        if not isinstance(raw_questions, list):
            raise _invalid_structure("research_brief_invalid")
        questions: list[ResearchBriefQuestion] = []
        for index, raw_value in enumerate(cast(list[object], raw_questions)):
            raw_question = _object_mapping(raw_value)
            if raw_question is None:
                continue
            question = str(raw_question.get("question", "")).strip()
            objective = str(raw_question.get("objective", "")).strip()
            if not question or not objective:
                continue
            identifier = str(raw_question.get("id", f"q{index + 1}")).strip()
            questions.append(
                ResearchBriefQuestion(
                    id=_safe_identifier(identifier, fallback=f"q{index + 1}"),
                    question=question,
                    objective=objective,
                )
            )
        questions = questions[: job.budget.max_subquestions]
        if len(questions) < 4:
            raise _invalid_structure("research_brief_invalid")
        return ResearchBrief(
            objective=str(payload.get("objective", "")).strip() or job.query,
            scope=_string_list(payload.get("scope"), limit=12),
            assumptions=_string_list(payload.get("assumptions"), limit=12),
            success_criteria=_string_list(
                payload.get("success_criteria"),
                limit=12,
            ),
            subquestions=questions,
        )

    def _parse_verification(self, output_text: str) -> ResearchVerification:
        payload = _parse_json_object(
            output_text,
            "research_verification_invalid",
        )
        raw_gaps = payload.get("gaps")
        gaps: list[ResearchEvidenceGap] = []
        if isinstance(raw_gaps, list):
            for index, raw_value in enumerate(
                cast(list[object], raw_gaps)[:8]
            ):
                raw_gap = _object_mapping(raw_value)
                if raw_gap is None:
                    continue
                question = str(raw_gap.get("question", "")).strip()
                reason = str(raw_gap.get("reason", "")).strip()
                if not question or not reason:
                    continue
                identifier = str(raw_gap.get("id", f"gap{index + 1}"))
                gaps.append(
                    ResearchEvidenceGap(
                        id=_safe_identifier(
                            identifier,
                            fallback=f"gap{index + 1}",
                        ),
                        question=question,
                        reason=reason,
                    )
                )
        raw_conflicts = _string_list(payload.get("conflicts"), limit=20)
        conflicts: list[str] = []
        reclassified: list[str] = []
        for conflict in raw_conflicts:
            if _is_material_conflict(conflict):
                conflicts.append(conflict)
            else:
                reclassified.append(
                    f"Reclassified as a gap or resolved discrepancy: {conflict}"
                )
        coverage_notes = _string_list(
            payload.get("coverage_notes"),
            limit=20,
        )
        coverage_notes.extend(reclassified[: 20 - len(coverage_notes)])
        return ResearchVerification(
            summary=str(payload.get("summary", "")).strip(),
            conflicts=conflicts,
            gaps=gaps,
            coverage_notes=coverage_notes,
        )

    def _brief_request(self, job: ResearchJob) -> ResearchProviderRequest:
        official_requirements = _official_topic_requirements(job.query)
        memory_context = self._memory_context(job)
        prompt = f"""You are the planning stage of Mind's Research Harness.
Clarify the user's research goal without asking a follow-up question. Produce a
bounded Research Brief and decompose it into 4 to {job.budget.max_subquestions}
independent, non-overlapping research subquestions.

User request:
{job.query}

{memory_context}

{official_requirements}

Return JSON only with this exact shape:
{{
  "objective": "...",
  "scope": ["..."],
  "assumptions": ["..."],
  "success_criteria": ["..."],
  "subquestions": [
    {{"id": "q1", "question": "...", "objective": "..."}}
  ]
}}
Do not search the web and do not include Markdown fences."""
        return ResearchProviderRequest(prompt=prompt, task_kind="brief")

    def _search_request(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
    ) -> ResearchProviderRequest:
        brief = job.checkpoint.brief
        objective = brief.objective if brief else job.query
        official_requirements = _official_topic_requirements(job.query)
        prompt = f"""You are one evidence collection worker inside Mind's Research Harness.
Research only the assigned subquestion. Use OpenAI Web Search, prefer primary and
authoritative sources, note publication and retrieval dates, and return a concise
evidence memo with factual claims linked to the web citations generated by the tool.

Freshness rules:
- For OpenAI API or product questions, search the exact topic in the current canonical
  documentation on developers.openai.com first. Treat equivalent platform.openai.com
  guide URLs, older announcements, SDK comments, community posts, cached pages, and
  search snippets as lower-priority evidence.
- Inspect the current page section that directly covers the claim. Never infer that a
  feature is unsupported merely because an older or different-scope page omits it.
- When sources differ, record each source's scope, conditions, and date. A current
  canonical official page superseding an older page is a resolution, not an unresolved
  conflict.

Overall objective: {objective}
Assigned subquestion: {task.question}
Worker objective: {task.objective}
Search round: {task.round_index} of {job.budget.max_search_rounds}

{official_requirements}

Do not write the final report. Focus on evidence useful to a later verifier and
synthesizer."""
        return ResearchProviderRequest(
            prompt=prompt,
            task_kind="search",
            use_web_search=True,
            max_tool_calls=task.tool_call_limit,
        )

    def _verification_request(self, job: ResearchJob) -> ResearchProviderRequest:
        evidence = self._evidence_packet(job)
        official_requirements = _official_topic_requirements(job.query)
        prompt = f"""You are the evidence verification stage of Mind's Research Harness.
Inspect the collected memos and source ledger. Identify material conflicts,
unsupported areas, and evidence gaps. Request follow-up searches only when they can
materially improve the final answer. Do not search the web yourself.

A true conflict requires two evidence-backed factual claims about the same scope,
time, and conditions that cannot both be true. Put only unresolved true conflicts in
`conflicts`, and include at least two distinct source IDs in every item: claim A with
its source, claim B with its source, shared scope, and why they are incompatible.
Omissions, missing details, weak evidence, different scopes, implementation advice,
and absence from an older page belong in `gaps` or `coverage_notes`, not `conflicts`.
If current primary or canonical official documentation resolves an older claim, put
the resolution in `coverage_notes` and leave it out of `conflicts`. For OpenAI API
topics, current canonical developers.openai.com documentation has priority over
equivalent platform.openai.com guides, announcements, SDK comments, cached pages,
community posts, and search snippets.

Original request:
{job.query}

{official_requirements}

Collected evidence:
{evidence}

Return JSON only with this exact shape:
{{
  "summary": "...",
  "conflicts": ["..."],
  "gaps": [{{"id": "gap1", "question": "...", "reason": "..."}}],
  "coverage_notes": ["..."]
}}
Use an empty gaps array when no second search round is needed. Do not use Markdown
fences."""
        return ResearchProviderRequest(prompt=prompt, task_kind="verify")

    def _synthesis_request(self, job: ResearchJob) -> ResearchProviderRequest:
        verification = job.checkpoint.verification
        verification_text = (
            json.dumps(
                verification.model_dump(mode="json"),
                ensure_ascii=False,
            )
            if verification
            else "No separate verification record."
        )
        official_requirements = _official_topic_requirements(job.query)
        memory_context = self._memory_context(job)
        prompt = f"""You are the final writing stage of Mind's Research Harness.
Write one clear, comprehensive answer to the original request using only the
collected evidence. Reconcile only true unresolved conflicts explicitly and state
important uncertainty. Do not present documentation omissions, different scopes, or
stale claims resolved by newer evidence as conflicts. Give current primary and
canonical official hosted documentation greater weight than older announcements,
SDK comments, cached pages, community posts, and search snippets. For OpenAI API
topics, prefer the current developers.openai.com page for the exact feature. Never
turn an unresolved evidence gap into a definite claim.

Citation rules are sentence-level, not paragraph-level. Every sentence or bullet
containing an externally verifiable factual claim must end with one or more stable
Mind source markers exactly as [S1], [S2], etc. A citation elsewhere in the same
paragraph does not cover an uncited sentence. Cite factual premises behind
recommendations. If a sentence is pure engineering judgment with no source-backed
factual premise, start it exactly with `工程建议（非来源事实）：` or
`Engineering judgment (not a sourced fact):`; never use that label to hide an API
behavior or other verifiable fact. Use only IDs present in the source ledger and
target at least {self.min_citation_coverage:.0%} factual-claim coverage. Do not
output raw URLs unless the URL itself is the subject. Include a brief Sources
section at the end listing the most important source markers.

Original request:
{job.query}

{memory_context}

{official_requirements}

Evidence verification:
{verification_text}

Evidence and source ledger:
{self._evidence_packet(job)}
"""
        return ResearchProviderRequest(prompt=prompt, task_kind="synthesis")

    def _memory_context(self, job: ResearchJob) -> str:
        if self.memory_service is None or not job.memory_ids:
            return "No confirmed user memory was selected for this task."
        context = self.memory_service.context_for_ids(job.user_id, job.memory_ids)
        return context or "No currently enabled user memory applies to this task."

    def _required_official_source_gaps(
        self,
        job: ResearchJob,
    ) -> list[ResearchEvidenceGap]:
        required = _required_official_source_urls(job.query)
        present = {
            canonical_source_url(source.url)
            for source in job.checkpoint.sources
        }
        missing = [url for url in required if url not in present]
        if not missing:
            return []
        return [
            ResearchEvidenceGap(
                id="current-official-docs",
                question=(
                    "Open and inspect these exact current canonical official pages: "
                    + ", ".join(missing)
                    + ". Capture the relevant sections and cite the pages directly."
                ),
                reason=(
                    "The current source ledger lacks mandatory canonical evidence "
                    "for Background polling, cancellation, retention/ZDR, or "
                    "stream reconnection. Older pages and omissions cannot replace it."
                ),
            )
        ]

    def _citation_repair_request(
        self,
        job: ResearchJob,
        draft: str,
        coverage: float,
        *,
        attempt: int,
    ) -> ResearchProviderRequest:
        prompt = f"""You are the citation quality gate of Mind's Research Harness.
Rewrite the draft report because deterministic sentence-level citation coverage is
{coverage:.0%}, below the required {self.min_citation_coverage:.0%}.
This is bounded repair attempt {attempt} of {MAX_CITATION_REPAIR_ATTEMPTS}.

Preserve the useful conclusions and structure, but use only the supplied evidence.
Remove or qualify unsupported factual claims. Every sentence or bullet containing an
externally verifiable factual claim must end with one or more valid source markers
such as [S1]. A marker in another sentence does not count. Do not invent source IDs,
facts, conflicts, quotations, or URLs. Keep true unresolved conflicts distinct from
documentation gaps and stale claims resolved by current canonical evidence. For a
pure design recommendation with no source-backed factual premise, start the sentence
exactly with `工程建议（非来源事实）：` or
`Engineering judgment (not a sourced fact):`; never apply that label to an API
behavior or any externally verifiable claim. Prefer removing redundant prose to
leaving uncited factual sentences. Return only the complete revised report, without
commentary or Markdown fences.

Original request:
{job.query}

Draft report:
{draft}

Evidence and source ledger:
{self._evidence_packet(job)}
"""
        return ResearchProviderRequest(
            prompt=prompt,
            task_kind="citation_repair",
        )

    def _evidence_packet(self, job: ResearchJob) -> str:
        source_lines = [
            f"{source.id}: {source.title} — {source.url}"
            for source in job.checkpoint.sources
        ]
        memo_lines: list[str] = []
        for task in job.checkpoint.subtasks:
            if task.kind != ResearchTaskKind.SEARCH or not task.output_text:
                continue
            source_ids = ", ".join(source.id for source in task.sources) or "none"
            memo_lines.append(
                f"\n### {task.id}: {task.question}\n"
                f"Sources: {source_ids}\n{task.output_text}"
            )
        return (
            "SOURCE LEDGER\n"
            + "\n".join(source_lines)
            + "\n\nEVIDENCE MEMOS\n"
            + "\n".join(memo_lines)
        )

    def _ensure_harness_job(self, job: ResearchJob) -> ResearchJob:
        self._consolidate_source_ledger(job)
        if job.checkpoint.subtasks:
            return job
        if job.provider_response_id:
            provider_status = job.provider_status or "queued"
            task_status = ResearchTaskStatus.QUEUED
            if provider_status == "in_progress":
                task_status = ResearchTaskStatus.RUNNING
            elif provider_status == "completed":
                task_status = ResearchTaskStatus.COMPLETED
            elif provider_status in CANCELLED_PROVIDER_STATUSES:
                task_status = ResearchTaskStatus.CANCELLED
            elif provider_status not in ACTIVE_PROVIDER_STATUSES:
                task_status = ResearchTaskStatus.FAILED
            job.checkpoint.subtasks.append(
                ResearchSubtask(
                    id="legacy-response",
                    kind=ResearchTaskKind.SYNTHESIS,
                    question=job.query,
                    objective="Complete a Research response created before the harness.",
                    status=task_status,
                    response_id=job.provider_response_id,
                    provider_status=provider_status,
                )
            )
        else:
            job.checkpoint.subtasks.append(self._brief_task(job))
        return job

    def _restart_job(self, job: ResearchJob) -> ResearchJob:
        for task in job.checkpoint.subtasks:
            self._remember_response(job, task.response_id)
        job.model = self.provider.model
        job.prompt_version = PROMPT_VERSION
        job.provider_response_id = None
        job.provider_status = None
        job.search_round = 0
        job.total_tool_calls = 0
        job.budget_exceeded = False
        job.hard_budget_reached = False
        job.citation_coverage = None
        job.checkpoint.plan = None
        job.checkpoint.brief = None
        job.checkpoint.verification = None
        job.checkpoint.subtasks = [self._brief_task(job)]
        job.checkpoint.sources = []
        job.checkpoint.citations = []
        job.checkpoint.completed_step_ids = []
        job.checkpoint.report = ""
        job.status = ResearchStatus.QUEUED
        job.progress = 0
        job.failure_reason = None
        job.created_at = utc_now()
        job.run_started_at = job.created_at
        job.updated_at = job.created_at
        return self.jobs.save_job(
            job,
            job.user_id,
            allow_cancelled_transition=True,
        )

    def _cancel_active_tasks(self, job: ResearchJob) -> None:
        for task in self._active_tasks(job):
            if not task.response_id:
                continue
            try:
                result = self.provider.parse_result(
                    self.provider.cancel(task.response_id)
                )
                self._apply_task_result(job, task, result)
                if task.status == ResearchTaskStatus.CANCELLED:
                    task.error_code = "research_timeout"
            except ResearchProviderError as error:
                task.status = ResearchTaskStatus.FAILED
                task.error_code = error.code or "research_timeout"
                task.updated_at = utc_now()

    def _stop_search_tasks_for_budget(self, job: ResearchJob) -> None:
        for task in self._active_tasks(job):
            if task.kind != ResearchTaskKind.SEARCH or not task.response_id:
                continue
            try:
                result = self.provider.parse_result(
                    self.provider.cancel(task.response_id)
                )
                self._apply_task_result(job, task, result)
                if task.status == ResearchTaskStatus.CANCELLED:
                    task.error_code = "research_hard_budget_reached"
            except ResearchProviderError:
                task.status = ResearchTaskStatus.CANCELLED
                task.error_code = "research_hard_budget_reached"
                task.updated_at = utc_now()
        for task in job.checkpoint.subtasks:
            if task.kind != ResearchTaskKind.SEARCH:
                continue
            if task.status in {
                ResearchTaskStatus.PENDING,
                ResearchTaskStatus.QUEUED,
                ResearchTaskStatus.RUNNING,
            }:
                task.status = ResearchTaskStatus.CANCELLED
                task.error_code = "research_hard_budget_reached"
                task.updated_at = utc_now()

    @staticmethod
    def _stop_pending_search_tasks_for_budget(job: ResearchJob) -> None:
        for task in job.checkpoint.subtasks:
            if (
                task.kind == ResearchTaskKind.SEARCH
                and task.status == ResearchTaskStatus.PENDING
            ):
                task.status = ResearchTaskStatus.CANCELLED
                task.error_code = "research_soft_budget_reached"
                task.updated_at = utc_now()

    def _active_tasks(self, job: ResearchJob) -> list[ResearchSubtask]:
        return [
            task
            for task in job.checkpoint.subtasks
            if task.response_id
            and task.status
            in {ResearchTaskStatus.QUEUED, ResearchTaskStatus.RUNNING}
        ]

    def _fail_from_task(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
    ) -> None:
        job.status = ResearchStatus.FAILED
        job.provider_status = task.provider_status or "failed"
        job.failure_reason = task.error_code or "research_provider_failed"

    def _mark_failure(self, job: ResearchJob, reason: str) -> ResearchJob:
        current = self.jobs.get_job(job.id, job.user_id)
        if current.status in TERMINAL_JOB_STATUSES:
            return current
        current.status = ResearchStatus.FAILED
        current.failure_reason = reason
        current.updated_at = utc_now()
        return self.jobs.save_job(current, current.user_id)

    def _timed_out(self, job: ResearchJob) -> bool:
        elapsed = (utc_now() - job.run_started_at).total_seconds()
        return elapsed > job.budget.timeout_seconds

    def _remaining_tool_calls(self, job: ResearchJob) -> int:
        return max(0, job.budget.max_total_tool_calls - job.total_tool_calls)

    @staticmethod
    def _hard_max_total_tool_calls(job: ResearchJob) -> int:
        return (
            job.budget.max_total_tool_calls
            + job.budget.max_tool_call_overrun
        )

    def _refresh_budget_state(self, job: ResearchJob) -> bool:
        budget_exceeded = (
            job.total_tool_calls > job.budget.max_total_tool_calls
        )
        hard_budget_reached = (
            job.total_tool_calls >= self._hard_max_total_tool_calls(job)
        )
        changed = (
            job.budget_exceeded != budget_exceeded
            or job.hard_budget_reached != hard_budget_reached
        )
        job.budget_exceeded = budget_exceeded
        job.hard_budget_reached = hard_budget_reached
        return changed

    @staticmethod
    def _soft_budget_reached(job: ResearchJob) -> bool:
        return job.total_tool_calls >= job.budget.max_total_tool_calls

    def _hard_unallocated_tool_calls(self, job: ResearchJob) -> int:
        per_task_reserve = 1 if job.budget.max_tool_call_overrun else 0
        reserved = sum(
            max(
                0,
                task.tool_call_limit
                + per_task_reserve
                - task.tool_call_count,
            )
            for task in job.checkpoint.subtasks
            if task.kind == ResearchTaskKind.SEARCH
            and task.status
            in {ResearchTaskStatus.QUEUED, ResearchTaskStatus.RUNNING}
        )
        return max(
            0,
            self._hard_max_total_tool_calls(job)
            - job.total_tool_calls
            - reserved,
        )

    def _can_start_search_task(
        self,
        job: ResearchJob,
        task: ResearchSubtask,
    ) -> bool:
        per_task_reserve = 1 if job.budget.max_tool_call_overrun else 0
        expected_charge = task.tool_call_limit + per_task_reserve
        return (
            task.tool_call_limit > 0
            and expected_charge <= self._hard_unallocated_tool_calls(job)
        )

    def _unallocated_tool_calls(self, job: ResearchJob) -> int:
        reserved = sum(
            max(0, task.tool_call_limit - task.tool_call_count)
            for task in job.checkpoint.subtasks
            if task.kind == ResearchTaskKind.SEARCH
            and task.status
            in {
                ResearchTaskStatus.PENDING,
                ResearchTaskStatus.QUEUED,
                ResearchTaskStatus.RUNNING,
            }
        )
        return max(0, self._remaining_tool_calls(job) - reserved)

    def _tool_limit_for_search(self, job: ResearchJob) -> int:
        planned_workers = (
            job.budget.max_subquestions * job.budget.max_search_rounds
        )
        fair_share = max(1, job.budget.max_total_tool_calls // planned_workers)
        return min(
            self.max_tool_calls_per_task,
            fair_share,
            self._unallocated_tool_calls(job),
        )

    def _configured_tool_call_overrun(self) -> int:
        if (
            self.max_tool_call_overrun <= 0
            or self.tool_call_overrun_ratio <= 0
        ):
            return 0
        percentage_allowance = max(
            1,
            ceil(
                self.max_total_tool_calls
                * self.tool_call_overrun_ratio
            ),
        )
        return min(self.max_tool_call_overrun, percentage_allowance)

    @staticmethod
    def _task(job: ResearchJob, task_id: str) -> ResearchSubtask | None:
        return next(
            (task for task in job.checkpoint.subtasks if task.id == task_id),
            None,
        )

    @staticmethod
    def _phase_for_task(task: ResearchSubtask | None) -> ResearchStatus:
        if task is None or task.kind == ResearchTaskKind.BRIEF:
            return ResearchStatus.PLANNING
        if task.kind == ResearchTaskKind.SEARCH:
            return ResearchStatus.COLLECTING
        if task.kind == ResearchTaskKind.VERIFY:
            return ResearchStatus.VERIFYING
        return ResearchStatus.SYNTHESIZING

    @staticmethod
    def _remember_response(job: ResearchJob, response_id: str | None) -> None:
        if response_id and response_id not in job.previous_response_ids:
            job.previous_response_ids.append(response_id)

    def _started_event(
        self,
        job: ResearchJob,
        *,
        request_id: str,
    ) -> dict[str, object]:
        event = self._progress_fields(job)
        event.update(
            {
                "type": "research_started",
                "job_id": str(job.id),
                "conversation_id": str(job.conversation_id),
                "restarted": bool(job.previous_response_ids),
                "request_id": request_id,
            }
        )
        return event

    def _status_event(self, job: ResearchJob) -> dict[str, object]:
        event = self._progress_fields(job)
        event.update({"type": "status", "job_id": str(job.id)})
        return event

    @staticmethod
    def _progress_fields(job: ResearchJob) -> dict[str, object]:
        terminal = {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.CANCELLED,
        }
        return {
            "status": job.status.value,
            "provider_status": job.provider_status,
            "progress": job.progress,
            "search_round": job.search_round,
            "max_search_rounds": job.budget.max_search_rounds,
            "completed_subtasks": sum(
                task.status == ResearchTaskStatus.COMPLETED
                for task in job.checkpoint.subtasks
            ),
            "settled_subtasks": sum(
                task.status in terminal for task in job.checkpoint.subtasks
            ),
            "total_subtasks": len(job.checkpoint.subtasks),
            "total_tool_calls": job.total_tool_calls,
            "max_total_tool_calls": job.budget.max_total_tool_calls,
            "max_tool_call_overrun": job.budget.max_tool_call_overrun,
            "hard_max_total_tool_calls": ResearchService._hard_max_total_tool_calls(
                job
            ),
            "budget_exceeded": job.budget_exceeded,
            "hard_budget_reached": job.hard_budget_reached,
            "citation_coverage": job.citation_coverage,
            "memory_ids": [str(memory_id) for memory_id in job.memory_ids],
        }

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
            "total_tool_calls": job.total_tool_calls,
            "max_total_tool_calls": job.budget.max_total_tool_calls,
            "max_tool_call_overrun": job.budget.max_tool_call_overrun,
            "hard_max_total_tool_calls": ResearchService._hard_max_total_tool_calls(
                job
            ),
            "budget_exceeded": job.budget_exceeded,
            "hard_budget_reached": job.hard_budget_reached,
            "citation_coverage": job.citation_coverage,
            "memory_ids": [str(memory_id) for memory_id in job.memory_ids],
            "citations": [
                citation.model_dump(mode="json")
                for citation in job.checkpoint.citations
            ],
            "request_id": request_id,
        }

    @staticmethod
    def _error_event(
        job: ResearchJob,
        *,
        request_id: str,
    ) -> dict[str, object]:
        code = job.failure_reason or "research_failed"
        messages = {
            "research_timeout": (
                "Research reached its configured time limit. You can retry it."
            ),
            "research_brief_invalid": (
                "Mind could not create a valid Research Brief. Please retry it."
            ),
            "research_verification_invalid": (
                "Mind could not verify the collected evidence. Please retry it."
            ),
            "research_citation_coverage_low": (
                "Mind could not reach the required citation coverage. "
                "Resume Research to retry the citation revision."
            ),
            "research_required_sources_missing": (
                "Mind could not verify the required current official sources. "
                "Retry Research before relying on the report."
            ),
        }
        return {
            "type": "error",
            "job_id": str(job.id),
            "code": code,
            "message": messages.get(
                code,
                "OpenAI Research could not complete the report.",
            ),
            "retryable": True,
            "request_id": request_id,
        }


def _parse_json_object(output_text: str, error_code: str) -> dict[str, Any]:
    candidate = output_text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise _invalid_structure(error_code)
    try:
        payload = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as error:
        raise _invalid_structure(error_code) from error
    if not isinstance(payload, dict):
        raise _invalid_structure(error_code)
    return cast(dict[str, Any], payload)


def _invalid_structure(error_code: str) -> ResearchProviderError:
    return ResearchProviderError(
        error_code,
        "OpenAI returned an invalid Research stage result. Please retry it.",
        retryable=True,
    )


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()[:2_000]
        for item in cast(list[object], value)[:limit]
        if str(item).strip()
    ]


def _is_material_conflict(value: str) -> bool:
    normalized = value.casefold()
    source_ids = set(re.findall(r"\bS\d+\b", value, flags=re.IGNORECASE))
    return (
        len(source_ids) >= 2
        and not any(phrase in normalized for phrase in _NON_CONFLICT_PHRASES)
    )


def _required_official_source_urls(query: str) -> tuple[str, ...]:
    normalized = query.casefold()
    is_openai_background_topic = "openai" in normalized and (
        "background" in normalized or "后台模式" in normalized
    )
    if not is_openai_background_topic:
        return ()
    return (
        OPENAI_BACKGROUND_GUIDE_URL,
        OPENAI_DATA_CONTROLS_GUIDE_URL,
    )


def _official_topic_requirements(query: str) -> str:
    if not _required_official_source_urls(query):
        return "No topic-specific mandatory source checklist applies."
    return f"""Mandatory current-official evidence checklist for this request:
- Inspect and cite the exact current canonical Background guide:
  {OPENAI_BACKGROUND_GUIDE_URL}
- Inspect and cite the exact current canonical data-controls guide:
  {OPENAI_DATA_CONTROLS_GUIDE_URL}
- Verify polling/retrieve status, cancellation including repeated-cancel semantics,
  default versus ZDR/background retention, and both polling recovery by response ID
  and stream reconnection using `sequence_number`/`starting_after` with the
  `stream=true` creation prerequisite.
- Do not describe Background mode as categorically ZDR-incompatible when the current
  docs instead describe ZDR requests running with `store=false` plus roughly ten
  minutes of temporary response storage. Do not confuse that exception with the
  default/store=true Responses retention period.
If either exact page is absent from the source ledger, treat that as a blocking
evidence gap rather than relying on a legacy URL or an older policy page."""


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _safe_identifier(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "-", value).strip("-")
    return (normalized or fallback)[:32]


def _public_source(source: ResearchSource) -> dict[str, object]:
    return {
        "id": source.id,
        "step_id": source.step_id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet,
        "published_at": source.published_at,
    }


def _remap_citations(
    citations: list[ResearchCitation],
    source_by_id: dict[str, ResearchSource],
    id_map: dict[str, str],
) -> list[ResearchCitation]:
    remapped: list[ResearchCitation] = []
    seen: set[tuple[str, int, int]] = set()
    for citation in citations:
        source_id = id_map.get(citation.source_id, citation.source_id)
        source = source_by_id.get(source_id)
        if source is None:
            continue
        key = (source.id, citation.start_index, citation.end_index)
        if key in seen:
            continue
        seen.add(key)
        remapped.append(
            ResearchCitation(
                source_id=source.id,
                title=source.title,
                url=source.url,
                start_index=citation.start_index,
                end_index=citation.end_index,
            )
        )
    return remapped


def _replace_source_markers(value: str, id_map: dict[str, str]) -> str:
    if not value or not id_map:
        return value
    rewritten = re.sub(
        r"\[(S\d+)\]",
        lambda match: f"[{id_map.get(match.group(1), match.group(1))}]",
        value,
    )
    return re.sub(r"\[(S\d+)\](?:\s*\[\1\])+", r"[\1]", rewritten)
