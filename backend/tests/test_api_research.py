from __future__ import annotations

from backend.app import create_app
from backend.config import Settings
from backend.models import AgentMode
from backend.models import MessageRole
from backend.models import ResearchBrief
from backend.models import ResearchBriefQuestion
from backend.models import ResearchCitation
from backend.models import ResearchJob
from backend.models import ResearchRequest
from backend.models import ResearchSource
from backend.models import ResearchStatus
from backend.models import ResearchSubtask
from backend.models import ResearchTaskKind
from backend.models import ResearchTaskStatus
from backend.research_store import JsonResearchRepository
from backend.store import JsonConversationRepository
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from fastapi.testclient import TestClient
from pathlib import Path
import json
import uuid

from backend.tests.api_test_support import (
    MindApiTestCase,
    MockResearchProvider,
    TEST_TOKEN,
    completed_research_response,
    parse_sse,
)


class ApiResearchTest(MindApiTestCase):
    def test_low_citation_coverage_completes_with_a_warning(self) -> None:
        low_coverage = (
            "## Findings\n\n"
            "Background responses can be polled by identifier [S1]. "
            "Repeated cancellation behavior remains uncited."
        )
        self.research_provider.synthesis_outputs = [
            low_coverage,
            low_coverage,
            low_coverage,
        ]

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Exercise the citation warning fallback."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["status"], "completed")
        self.assertIn("below the 80% target", events[-1]["quality_warning"])
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(job.status, ResearchStatus.COMPLETED)
        self.assertEqual(job.citation_coverage, 0.5)

    def test_research_streams_checkpoints_sources_and_a_persisted_report(
        self,
    ) -> None:
        response = self.client.post(
            "/api/research",
            headers={
                **self.auth_headers,
                "X-Request-ID": "research-contract-test",
            },
            json={"query": "How should a personal agent evaluate evidence?"},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(
            response.headers["X-Research-Job-ID"],
            events[0]["job_id"],
        )
        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[0], "research_started")
        self.assertIn("source", event_types)
        self.assertIn("delta", event_types)
        self.assertEqual(event_types[-1], "done")
        self.assertEqual(events[-1]["request_id"], "research-contract-test")
        self.assertGreater(events[-1]["source_count"], 0)

        job_id = events[0]["job_id"]
        job_response = self.client.get(
            f"/api/research/{job_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(job_response.status_code, 200)
        job = job_response.json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress"], 1.0)
        self.assertEqual(job["provider_response_id"], "resp_mock_7")
        self.assertEqual(job["provider_status"], "completed")
        self.assertEqual(len(job["checkpoint"]["sources"]), 2)
        self.assertEqual(len(job["checkpoint"]["citations"]), 1)
        self.assertEqual(len(job["checkpoint"]["subtasks"]), 7)
        self.assertEqual(
            [task["kind"] for task in job["checkpoint"]["subtasks"]],
            [
                "brief",
                "search",
                "search",
                "search",
                "search",
                "verify",
                "synthesis",
            ],
        )
        self.assertTrue(
            all(task["response_id"] for task in job["checkpoint"]["subtasks"])
        )
        search_tasks = [
            task for task in job["checkpoint"]["subtasks"] if task["kind"] == "search"
        ]
        self.assertTrue(
            all(
                len(task["sources"]) == 2 and len(task["citations"]) == 1
                for task in search_tasks
            )
        )
        self.assertIn("Research summary", job["checkpoint"]["report"])

        conversation = self.repository.get_conversation(
            events[-1]["conversation_id"],
            "local-developer",
        )
        self.assertEqual(
            [message.role for message in conversation.messages],
            [MessageRole.USER, MessageRole.ASSISTANT],
        )
        self.assertEqual(
            str(conversation.messages[-1].research_job_id),
            job_id,
        )

    def test_research_comparison_preserves_snapshots_and_structured_diff(
        self,
    ) -> None:
        self.research_provider.synthesis_outputs = [
            "## Research summary\n\nThe baseline result is supported [S1].",
            "## Research summary\n\nThe latest result is supported [S1].",
        ]
        baseline_response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Track how the evidence changes over time."},
        )
        baseline_events = parse_sse(baseline_response.text)
        baseline_job_id = baseline_events[0]["job_id"]

        comparison_response = self.client.post(
            f"/api/research/{baseline_job_id}/compare",
            headers=self.auth_headers,
        )

        self.assertEqual(comparison_response.status_code, 200)
        comparison_events = parse_sse(comparison_response.text)
        self.assertEqual(
            comparison_response.headers["X-Research-Job-ID"],
            comparison_events[0]["job_id"],
        )
        self.assertEqual(comparison_events[-1]["type"], "done")
        self.assertEqual(
            comparison_events[-1]["baseline_job_id"],
            baseline_job_id,
        )
        comparison_job_id = comparison_events[0]["job_id"]
        comparison = self.client.get(
            f"/api/research/{comparison_job_id}",
            headers=self.auth_headers,
        ).json()
        self.assertEqual(comparison["status"], "completed")
        self.assertEqual(comparison["baseline_job_id"], baseline_job_id)
        self.assertEqual(
            comparison["checkpoint"]["baseline_snapshot"]["job_id"],
            baseline_job_id,
        )
        self.assertIn(
            "baseline result",
            comparison["checkpoint"]["baseline_snapshot"]["report"],
        )
        self.assertIn(
            "latest result",
            comparison["checkpoint"]["report"],
        )
        claims = comparison["checkpoint"]["insight_diff"]["claims"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["kind"], "changed")
        self.assertEqual(claims[0]["confidence"], 0.92)
        self.assertTrue(claims[0]["baseline_evidence"])
        self.assertTrue(claims[0]["latest_evidence"])
        self.assertIn(
            "IMMUTABLE BASELINE COMPARISON",
            next(
                call.prompt
                for call in self.research_provider.start_calls
                if call.task_kind == "synthesis"
                and "IMMUTABLE BASELINE COMPARISON" in call.prompt
            ),
        )

        conversation = self.repository.get_conversation(
            comparison_events[-1]["conversation_id"],
            "local-developer",
        )
        self.assertEqual(
            [message.role for message in conversation.messages],
            [
                MessageRole.USER,
                MessageRole.ASSISTANT,
                MessageRole.USER,
                MessageRole.ASSISTANT,
            ],
        )
        self.assertEqual(
            conversation.messages[-2].content,
            "Compare this report with the latest evidence.",
        )

    def test_research_comparison_accepts_no_material_changes(self) -> None:
        self.research_provider.synthesis_outputs = [
            "## Research summary\n\nThe result remains supported [S1].",
            "## Research summary\n\nThe result remains supported [S1].",
        ]
        self.research_provider.comparison_outputs = [json.dumps({"claims": []})]
        baseline = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Confirm whether the evidence changed."},
        )
        baseline_job_id = parse_sse(baseline.text)[0]["job_id"]

        comparison = self.client.post(
            f"/api/research/{baseline_job_id}/compare",
            headers=self.auth_headers,
        )

        self.assertEqual(comparison.status_code, 200)
        events = parse_sse(comparison.text)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["insight_diff"]["claims"], [])

    def test_research_repairs_low_sentence_level_citation_coverage(self) -> None:
        self.research_provider.synthesis_outputs = [
            (
                "## Findings\n\n"
                "Background responses can be polled by response identifier [S1]. "
                "Repeated cancellation is idempotent."
            ),
            (
                "## Findings\n\n"
                "Background responses can be polled by response identifier [S1]. "
                "Repeated cancellation is idempotent [S1]."
            ),
        ]

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Verify Background mode lifecycle behavior."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["citation_coverage"], 1.0)
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(job.citation_coverage, 1.0)
        self.assertEqual(job.checkpoint.subtasks[-1].id, "citation-repair-1")
        self.assertEqual(
            job.checkpoint.subtasks[-1].kind,
            ResearchTaskKind.CITATION_REPAIR,
        )
        self.assertIn("Repeated cancellation is idempotent [S1]", job.checkpoint.report)
        self.assertEqual(
            [request.task_kind for request in self.research_provider.start_calls][-2:],
            ["synthesis", "citation_repair"],
        )
        search_prompt = next(
            request.prompt
            for request in self.research_provider.start_calls
            if request.task_kind == "search"
        )
        verify_prompt = next(
            request.prompt
            for request in self.research_provider.start_calls
            if request.task_kind == "verify"
        )
        synthesis_prompt = next(
            request.prompt
            for request in self.research_provider.start_calls
            if request.task_kind == "synthesis"
        )
        self.assertIn("developers.openai.com first", search_prompt)
        self.assertIn("A true conflict requires two evidence-backed", verify_prompt)
        self.assertIn("Citation rules are sentence-level", synthesis_prompt)
        self.assertIn("Do not output Markdown horizontal rules", synthesis_prompt)
        self.assertIn("Do not output Markdown tables", synthesis_prompt)

    def test_verification_reclassifies_gaps_and_keeps_only_true_conflicts(
        self,
    ) -> None:
        service = self.client.app.state.research_service
        verification = service._parse_verification(  # noqa: SLF001
            json.dumps(
                {
                    "summary": "Checked current evidence.",
                    "conflicts": [
                        (
                            "S1 says the limit is 10 minutes while S2 says the same "
                            "scope has a 30-day limit; both cannot be true."
                        ),
                        (
                            "S3 omits reconnect details; this is a documentation gap, "
                            "not a conflict with S4."
                        ),
                    ],
                    "gaps": [],
                    "coverage_notes": [],
                }
            )
        )

        self.assertEqual(len(verification.conflicts), 1)
        self.assertIn("S1", verification.conflicts[0])
        self.assertTrue(
            any("Reclassified as a gap" in note for note in verification.coverage_notes)
        )

    def test_research_allows_two_bounded_citation_repair_attempts(self) -> None:
        low_coverage = (
            "## Findings\n\n"
            "Background responses can be polled by response identifier [S1]. "
            "Repeated cancellation is idempotent."
        )
        self.research_provider.synthesis_outputs = [
            low_coverage,
            low_coverage,
            low_coverage.replace("idempotent.", "idempotent [S1]."),
        ]

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Exercise the bounded citation quality gate."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(
            [task.id for task in job.checkpoint.subtasks[-2:]],
            ["citation-repair-1", "citation-repair-2"],
        )
        self.assertEqual(job.citation_coverage, 1.0)

    def test_background_research_requires_both_current_canonical_guides(
        self,
    ) -> None:
        service = self.client.app.state.research_service
        job = ResearchJob(
            user_id="local-developer",
            conversation_id=uuid.uuid4(),
            query="Research OpenAI Responses API Background mode.",
        )

        self.assertEqual(  # noqa: SLF001
            len(service._required_official_source_gaps(job)),
            1,
        )
        job.checkpoint.sources.extend(
            [
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Background mode",
                    url=("https://platform.openai.com/docs/guides/background"),
                ),
                ResearchSource(
                    id="S2",
                    step_id="search-r1-q2",
                    title="Data controls",
                    url=("https://developers.openai.com/api/docs/guides/your-data"),
                ),
            ]
        )

        self.assertEqual(  # noqa: SLF001
            service._required_official_source_gaps(job),
            [],
        )

    def test_get_consolidates_persisted_source_variants_and_markers(self) -> None:
        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Deduplicate source variants."},
        )
        events = parse_sse(response.text)
        job_id = str(events[0]["job_id"])
        job = self.research_repository.get_job(job_id, "local-developer")
        duplicate = ResearchSource(
            id="S9",
            step_id="search-r1-q4",
            title="Tracked Example source",
            url="https://example.com/primary/?utm_source=openai",
        )
        job.checkpoint.sources.append(duplicate)
        job.checkpoint.subtasks[-1].sources.append(duplicate.model_copy())
        job.checkpoint.report += "\n\nDuplicate evidence [S9]."
        marker = job.checkpoint.report.index("[S9]")
        job.checkpoint.citations.append(
            ResearchCitation(
                source_id="S9",
                title=duplicate.title,
                url=duplicate.url,
                start_index=marker,
                end_index=marker + 4,
            )
        )
        self.research_repository.save_job(job, "local-developer")

        refreshed = self.client.get(
            f"/api/research/{job_id}",
            headers=self.auth_headers,
        )

        self.assertEqual(refreshed.status_code, 200)
        payload = refreshed.json()
        self.assertEqual(len(payload["checkpoint"]["sources"]), 2)
        self.assertNotIn("S9", payload["checkpoint"]["report"])
        self.assertTrue(
            all(
                citation["source_id"] != "S9"
                for citation in payload["checkpoint"]["citations"]
            )
        )

    def test_transient_poll_recovers_the_same_response_without_restarting(
        self,
    ) -> None:
        self.research_provider.fail_retrieve_once = True

        first = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Checkpointed research"},
        )
        first_events = parse_sse(first.text)
        self.assertEqual(first_events[-1]["type"], "done")
        self.assertTrue(
            any(
                event.get("recovery_state") == "retrying"
                for event in first_events
                if event["type"] == "status"
            )
        )
        job_id = first_events[0]["job_id"]
        completed = self.research_repository.get_job(job_id, "local-developer")
        self.assertEqual(completed.status, ResearchStatus.COMPLETED)
        brief = next(
            task for task in completed.checkpoint.subtasks if task.id == "brief"
        )
        self.assertEqual(brief.response_id, "resp_mock_1")
        self.assertEqual(brief.transport_attempts, 1)
        self.assertEqual(brief.consecutive_errors, 0)
        completed_conversation = self.repository.get_conversation(
            completed.conversation_id,
            "local-developer",
        )
        self.assertTrue(completed_conversation.messages[-1].content)
        self.assertEqual(
            str(completed_conversation.messages[-1].research_job_id),
            job_id,
        )
        self.assertEqual(
            [request.task_kind for request in self.research_provider.start_calls],
            ["brief", "search", "search", "search", "search", "verify", "synthesis"],
        )
        self.assertEqual(
            sum(
                request.task_kind == "brief"
                for request in self.research_provider.start_calls
            ),
            1,
        )
        self.assertIn("resp_mock_1", self.research_provider.retrieve_calls)

    def test_rate_limit_waits_without_exposing_provider_or_losing_work(
        self,
    ) -> None:
        self.research_provider.rate_limit_start_failures = 1

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Recover from a temporary request limit."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        rate_event = next(
            event for event in events if event.get("recovery_state") == "rate_limited"
        )
        self.assertGreaterEqual(rate_event["retry_after_seconds"], 0)
        self.assertEqual(
            self.research_provider.start_attempts,
            len(self.research_provider.start_calls) + 1,
        )
        self.assertLessEqual(self.research_provider.max_active_responses, 2)

    def test_repeated_rate_limits_pause_research_for_manual_resume(self) -> None:
        self.research_provider.rate_limit_start_failures = 4

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Pause after repeated request limits."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "research_rate_limited")
        self.assertEqual(
            events[-1]["message"],
            "Too many requests. Research is paused. Resume to try again.",
        )
        self.assertEqual(self.research_provider.start_attempts, 4)

    def test_quota_exhaustion_stops_without_retrying_as_partial_evidence(
        self,
    ) -> None:
        self.research_provider.search_failure_code = "credit_balance_exhausted"

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Stop immediately when Research quota is exhausted."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "research_quota_exhausted")
        self.assertFalse(events[-1]["retryable"])
        self.assertEqual(
            events[-1]["message"],
            "Research usage is unavailable because its quota is exhausted.",
        )
        self.assertNotIn(
            "research_insufficient_evidence",
            [event.get("code") for event in events],
        )
        job = self.research_repository.get_job(
            uuid.UUID(events[0]["job_id"]),
            "local-developer",
        )
        self.assertEqual(job.degraded_reasons, [])
        search_calls = [
            call
            for call in self.research_provider.start_calls
            if call.task_kind == "search"
        ]
        self.assertLessEqual(len(search_calls), 2)
        self.assertTrue(self.research_provider.cancel_calls)

    def test_one_failed_search_degrades_instead_of_failing_the_report(
        self,
    ) -> None:
        self.research_provider.permanently_fail_first_search = True

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Continue when one research direction fails."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        failed_searches = [
            task
            for task in job.checkpoint.subtasks
            if task.kind == ResearchTaskKind.SEARCH
            and task.status == ResearchTaskStatus.FAILED
        ]
        self.assertEqual(len(failed_searches), 1)
        self.assertTrue(job.degraded_reasons)
        self.assertIn("could not complete", job.quality_warning or "")
        self.assertLessEqual(self.research_provider.max_active_responses, 2)

    def test_context_limit_compacts_once_and_retries_only_the_stage(self) -> None:
        self.research_provider.context_limit_once_for_kind = "synthesis"

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Bound the evidence packet before synthesis."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(job.context_reduction_level, 1)
        synthesis_attempts = [
            request
            for request in self.research_provider.start_calls
            if request.task_kind == "synthesis"
        ]
        self.assertEqual(len(synthesis_attempts), 1)
        self.assertEqual(
            self.research_provider.start_attempts,
            len(self.research_provider.start_calls) + 1,
        )

    def test_output_budget_exhaustion_retries_a_concise_stage_once(self) -> None:
        self.research_provider.incomplete_once_for_kind = "synthesis"

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Recover from an incomplete writing stage."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(job.context_reduction_level, 1)
        synthesis_attempts = [
            request
            for request in self.research_provider.start_calls
            if request.task_kind == "synthesis"
        ]
        self.assertEqual(len(synthesis_attempts), 2)
        self.assertIn("Keep the report concise", synthesis_attempts[-1].prompt)

    def test_invalid_stage_output_retries_only_that_stage(self) -> None:
        self.research_provider.invalid_output_once_for_kind = "brief"

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Recover from malformed planning output."},
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        brief_attempts = [
            request
            for request in self.research_provider.start_calls
            if request.task_kind == "brief"
        ]
        self.assertEqual(len(brief_attempts), 2)

    def test_soft_deadline_stops_search_and_completes_with_partial_evidence(
        self,
    ) -> None:
        service = self.client.app.state.research_service
        job = service.start_job(
            ResearchRequest(query="Complete before the hard deadline."),
            "local-developer",
        )
        source = ResearchSource(
            id="S1",
            step_id="search-r1-q1",
            title="Primary evidence",
            url="https://example.com/primary",
        )
        brief = ResearchBrief(
            objective="Complete a bounded report.",
            scope=["current evidence"],
            assumptions=[],
            success_criteria=["a cited report"],
            subquestions=[
                ResearchBriefQuestion(
                    id=f"q{index}",
                    question=f"Question {index}",
                    objective=f"Objective {index}",
                )
                for index in range(1, 5)
            ],
        )
        brief_task = job.checkpoint.subtasks[0]
        brief_task.status = ResearchTaskStatus.COMPLETED
        brief_task.output_text = json.dumps(brief.model_dump(mode="json"))
        search_tasks = [
            ResearchSubtask(
                id=f"search-r1-q{index}",
                kind=ResearchTaskKind.SEARCH,
                round_index=1,
                subquestion_id=f"q{index}",
                question=f"Question {index}",
                objective=f"Objective {index}",
                status=(
                    ResearchTaskStatus.COMPLETED
                    if index < 4
                    else ResearchTaskStatus.RUNNING
                ),
                response_id=(None if index < 4 else "resp_slow_search"),
                output_text=("Evidence memo [S1]." if index < 4 else ""),
                sources=([source] if index < 4 else []),
            )
            for index in range(1, 5)
        ]
        job.checkpoint.brief = brief
        job.checkpoint.sources = [source]
        job.checkpoint.subtasks = [brief_task, *search_tasks]
        job.status = ResearchStatus.COLLECTING
        job.search_round = 1
        job.run_started_at = datetime.now(timezone.utc) - timedelta(minutes=8)
        self.research_repository.save_job(job, "local-developer")

        response = self.client.post(
            f"/api/research/{job.id}/resume",
            headers=self.auth_headers,
        )

        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        completed = self.research_repository.get_job(job.id, "local-developer")
        self.assertTrue(completed.soft_deadline_reached)
        self.assertIn("resp_slow_search", self.research_provider.cancel_calls)
        self.assertIn("soft deadline", completed.quality_warning or "")

    def test_timeout_resume_refreshes_run_window_and_retries_cancelled_stage(
        self,
    ) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Resume a timed out citation repair",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        old_start = datetime.now(timezone.utc) - timedelta(minutes=20)
        job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Resume a timed out citation repair",
                status=ResearchStatus.FAILED,
                failure_reason="research_timeout",
                run_started_at=old_start,
                checkpoint={
                    "subtasks": [
                        ResearchSubtask(
                            id="synthesis",
                            kind=ResearchTaskKind.SYNTHESIS,
                            question="Write the report",
                            status=ResearchTaskStatus.COMPLETED,
                            response_id="resp_synthesis",
                            output_text="A cited draft [S1].",
                        ),
                        ResearchSubtask(
                            id="citation-repair-1",
                            kind=ResearchTaskKind.CITATION_REPAIR,
                            question="Repair citations",
                            status=ResearchTaskStatus.CANCELLED,
                            response_id="resp_timed_out_repair",
                            error_code="research_timeout",
                        ),
                    ]
                },
            )
        )

        resumed = self.client.app.state.research_service.prepare_resume(
            job.id,
            "local-developer",
        )

        repair = resumed.checkpoint.subtasks[-1]
        self.assertEqual(resumed.status, ResearchStatus.SYNTHESIZING)
        self.assertGreater(resumed.run_started_at, old_start)
        self.assertEqual(repair.status, ResearchTaskStatus.PENDING)
        self.assertIsNone(repair.response_id)
        self.assertIn("resp_timed_out_repair", resumed.previous_response_ids)

    def test_research_runs_a_bounded_second_search_round_for_evidence_gaps(
        self,
    ) -> None:
        self.research_provider.return_verification_gap_once = True

        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Find and close one evidence gap."},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "done")
        job = self.research_repository.get_job(
            events[0]["job_id"],
            "local-developer",
        )
        self.assertEqual(job.search_round, 2)
        self.assertEqual(job.status, ResearchStatus.COMPLETED)
        self.assertEqual(
            [task.kind.value for task in job.checkpoint.subtasks],
            [
                "brief",
                "search",
                "search",
                "search",
                "search",
                "verify",
                "search",
                "verify",
                "synthesis",
            ],
        )
        self.assertLessEqual(
            job.total_tool_calls,
            job.budget.max_total_tool_calls,
        )
        self.assertTrue(
            all(
                task.response_id
                for task in job.checkpoint.subtasks
                if task.kind != ResearchTaskKind.SEARCH
                or task.status == ResearchTaskStatus.COMPLETED
            )
        )

    def test_research_reports_real_tool_call_overrun_and_stops_searches(
        self,
    ) -> None:
        provider = MockResearchProvider()
        provider.search_tool_call_count = 2
        data_path = Path(self.temporary_directory.name) / "budget-conversations.json"
        research_path = Path(self.temporary_directory.name) / "budget-research.json"
        conversations = JsonConversationRepository(data_path)
        research_jobs = JsonResearchRepository(research_path)
        settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            data_path=data_path,
            research_data_path=research_path,
            usage_data_path=Path(self.temporary_directory.name) / "budget-usage.json",
            research_poll_interval_seconds=0.001,
            research_max_subquestions=4,
            research_max_total_tool_calls=5,
            quiet=True,
        )
        client = TestClient(
            create_app(
                settings=settings,
                repository=conversations,
                provider=self.provider,
                research_repository=research_jobs,
                research_provider=provider,
            )
        )
        self.addCleanup(client.close)

        response = client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Stay within a strict search budget."},
        )
        events = parse_sse(response.text)
        done = events[-1]
        job = research_jobs.get_job(str(events[0]["job_id"]), "local-developer")

        self.assertEqual(done["type"], "done")
        self.assertTrue(done["budget_exceeded"])
        self.assertTrue(done["hard_budget_reached"])
        self.assertEqual(done["max_total_tool_calls"], 5)
        self.assertEqual(done["hard_max_total_tool_calls"], 6)
        self.assertEqual(done["total_tool_calls"], 6)
        self.assertTrue(job.budget_exceeded)
        self.assertTrue(job.hard_budget_reached)
        self.assertTrue(
            any(
                task.error_code == "research_hard_budget_reached"
                for task in job.checkpoint.subtasks
            )
        )

    def test_research_allows_small_overrun_below_hard_limit(self) -> None:
        provider = MockResearchProvider()
        provider.search_tool_call_counts = [3, 2, 2, 2]
        data_path = Path(self.temporary_directory.name) / "soft-conversations.json"
        research_path = Path(self.temporary_directory.name) / "soft-research.json"
        conversations = JsonConversationRepository(data_path)
        research_jobs = JsonResearchRepository(research_path)
        settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            data_path=data_path,
            research_data_path=research_path,
            usage_data_path=Path(self.temporary_directory.name) / "soft-usage.json",
            research_poll_interval_seconds=0.001,
            research_max_subquestions=4,
            research_max_total_tool_calls=8,
            quiet=True,
        )
        client = TestClient(
            create_app(
                settings=settings,
                repository=conversations,
                provider=self.provider,
                research_repository=research_jobs,
                research_provider=provider,
            )
        )
        self.addCleanup(client.close)

        response = client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Use a small amount of extra search budget."},
        )
        events = parse_sse(response.text)
        done = events[-1]
        job = research_jobs.get_job(str(events[0]["job_id"]), "local-developer")

        self.assertEqual(done["type"], "done")
        self.assertEqual(done["max_total_tool_calls"], 8)
        self.assertEqual(done["hard_max_total_tool_calls"], 10)
        self.assertEqual(done["total_tool_calls"], 9)
        self.assertTrue(done["budget_exceeded"])
        self.assertFalse(done["hard_budget_reached"])
        self.assertTrue(job.budget_exceeded)
        self.assertFalse(job.hard_budget_reached)

    def test_research_jobs_are_tenant_scoped(self) -> None:
        other_job = self.research_repository.create_job(
            ResearchJob(
                user_id="other-user",
                conversation_id=uuid.uuid4(),
                query="Private research",
            )
        )

        response = self.client.get(
            f"/api/research/{other_job.id}",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["error"]["code"],
            "research_job_not_found",
        )

    def test_get_refreshes_by_response_id_and_does_not_duplicate_assistant(
        self,
    ) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Restore after browser disconnect",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Restore after browser disconnect",
                status=ResearchStatus.COLLECTING,
                provider_response_id="resp_existing",
                provider_status="in_progress",
            )
        )
        self.repository.append_assistant_message(
            conversation_id,
            "",
            user_id="local-developer",
            research_job_id=job.id,
        )
        self.research_provider.register(
            "resp_existing",
            completed_research_response("resp_existing"),
        )

        first = self.client.get(
            f"/api/research/{job.id}",
            headers=self.auth_headers,
        )
        second = self.client.get(
            f"/api/research/{job.id}",
            headers=self.auth_headers,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "completed")
        self.assertEqual(second.json()["status"], "completed")
        self.assertEqual(len(first.json()["checkpoint"]["citations"]), 1)
        self.assertEqual(len(second.json()["checkpoint"]["citations"]), 1)
        self.assertEqual(self.research_provider.start_calls, [])
        self.assertEqual(self.research_provider.retrieve_calls, ["resp_existing"])
        conversation = self.repository.get_conversation(
            conversation_id,
            "local-developer",
        )
        self.assertEqual(len(conversation.messages), 2)
        self.assertIn("Research summary", conversation.messages[-1].content)

    def test_get_recovers_every_saved_parallel_response_without_starting(self) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Restore parallel workers",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        brief = ResearchBrief(
            objective="Restore two saved workers.",
            subquestions=[
                ResearchBriefQuestion(
                    id=f"q{index}",
                    question=f"Question {index}",
                    objective=f"Objective {index}",
                )
                for index in range(1, 5)
            ],
        )
        job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Restore parallel workers",
                status=ResearchStatus.COLLECTING,
                provider_response_id="resp_parallel_restore_2",
                provider_status="in_progress",
                search_round=1,
                checkpoint={
                    "brief": brief,
                    "subtasks": [
                        ResearchSubtask(
                            id=f"search-r1-q{index}",
                            kind=ResearchTaskKind.SEARCH,
                            round_index=1,
                            subquestion_id=f"q{index}",
                            question=f"Question {index}",
                            status=ResearchTaskStatus.RUNNING,
                            response_id=f"resp_parallel_restore_{index}",
                            provider_status="in_progress",
                        )
                        for index in range(1, 3)
                    ],
                },
            )
        )
        for index in range(1, 3):
            response_id = f"resp_parallel_restore_{index}"
            self.research_provider.register(
                response_id,
                completed_research_response(response_id),
            )

        response = self.client.get(
            f"/api/research/{job.id}",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verifying")
        self.assertEqual(self.research_provider.start_calls, [])
        self.assertEqual(
            self.research_provider.retrieve_calls,
            ["resp_parallel_restore_1", "resp_parallel_restore_2"],
        )
        restored_search_tasks = [
            task
            for task in response.json()["checkpoint"]["subtasks"]
            if task["kind"] == "search"
        ]
        self.assertTrue(
            all(task["status"] == "completed" for task in restored_search_tasks)
        )

    def test_cancel_calls_openai_and_resume_starts_a_new_response(self) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Research cancellation",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Research cancellation",
                status=ResearchStatus.COLLECTING,
                provider_response_id="resp_cancelled",
                provider_status="in_progress",
            )
        )
        self.repository.append_assistant_message(
            conversation_id,
            "",
            user_id="local-developer",
            research_job_id=job.id,
        )
        self.research_provider.register(
            "resp_cancelled",
            {"id": "resp_cancelled", "status": "in_progress", "output": []},
        )

        cancelled_response = self.client.post(
            f"/api/research/{job.id}/cancel",
            headers=self.auth_headers,
        )
        self.assertEqual(cancelled_response.status_code, 200)
        self.assertEqual(cancelled_response.json()["status"], "cancelled")
        self.assertEqual(
            self.research_provider.cancel_calls,
            ["resp_cancelled"],
        )

        resumed_response = self.client.post(
            f"/api/research/{job.id}/resume",
            headers=self.auth_headers,
        )
        resumed_events = parse_sse(resumed_response.text)
        self.assertEqual(resumed_events[-1]["type"], "done")
        self.assertEqual(
            self.research_repository.get_job(job.id, "local-developer").status,
            ResearchStatus.COMPLETED,
        )
        restarted = self.research_repository.get_job(job.id, "local-developer")
        self.assertEqual(restarted.previous_response_ids, ["resp_cancelled"])
        self.assertNotEqual(restarted.provider_response_id, "resp_cancelled")
        self.assertEqual(
            [request.task_kind for request in self.research_provider.start_calls],
            ["brief", "search", "search", "search", "search", "verify", "synthesis"],
        )

    def test_cancel_stops_every_running_subtask_response(self) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Cancel parallel research",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Cancel parallel research",
                status=ResearchStatus.COLLECTING,
                provider_response_id="resp_parallel_2",
                provider_status="in_progress",
                search_round=1,
                checkpoint={
                    "subtasks": [
                        ResearchSubtask(
                            id="search-r1-q1",
                            kind=ResearchTaskKind.SEARCH,
                            round_index=1,
                            question="First parallel question",
                            status=ResearchTaskStatus.RUNNING,
                            response_id="resp_parallel_1",
                            provider_status="in_progress",
                        ),
                        ResearchSubtask(
                            id="search-r1-q2",
                            kind=ResearchTaskKind.SEARCH,
                            round_index=1,
                            question="Second parallel question",
                            status=ResearchTaskStatus.RUNNING,
                            response_id="resp_parallel_2",
                            provider_status="in_progress",
                        ),
                    ]
                },
            )
        )
        for response_id in ("resp_parallel_1", "resp_parallel_2"):
            self.research_provider.register(
                response_id,
                {"id": response_id, "status": "in_progress", "output": []},
            )

        response = self.client.post(
            f"/api/research/{job.id}/cancel",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(
            self.research_provider.cancel_calls,
            ["resp_parallel_1", "resp_parallel_2"],
        )
