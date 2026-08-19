from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import (
    create_app,
    create_model_provider,
    create_research_provider,
    is_authorized_header,
    validate_chat_payload,
)
from backend.auth import LocalAccountManager
from backend.config import Settings
from backend.conversation_context import select_recent_history
from backend.deepseek_provider import DeepSeekProvider
from backend.fake_agent import FakeAgentProvider
from backend.memory_retrieval import LocalMemoryRetriever
from backend.memory_service import MemoryService
from backend.memory_store import JsonMemoryRepository
from backend.model_provider import ModelProviderError
from backend.models import (
    AgentMode,
    Attachment,
    ChatRequest,
    Conversation,
    LocalPrincipal,
    Memory,
    MemoryCreateRequest,
    MemoryStatus,
    MemoryType,
    Message,
    MessageRole,
    ModelMessage,
    ResearchJob,
    ResearchBrief,
    ResearchBriefQuestion,
    ResearchRequest,
    ResearchCitation,
    ResearchSource,
    ResearchStatus,
    ResearchSubtask,
    ResearchTaskKind,
    ResearchTaskStatus,
    Routine,
    ToolCall,
    User,
)
from backend.openai_research_provider import OpenAIResearchProvider
from backend.research_provider import (
    ResearchProviderError,
    ResearchProviderRequest,
    ResearchProviderResult,
)
from backend.research_store import (
    JsonResearchRepository,
    ResearchJobNotFoundError,
)
from backend.store import (
    ConversationNotFoundError,
    JsonConversationRepository,
)


TEST_TOKEN = "test-only-token"


class StubStreamingResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "StubStreamingResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.lines)


class StubJsonResponse:
    def __init__(self, payload: object) -> None:
        self.encoded = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "StubJsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.encoded


def completed_research_response(response_id: str) -> dict[str, object]:
    text = "## Research summary\n\nEvidence from Example source supports the result."
    cited_text = "Example source"
    start_index = text.index(cited_text)
    return {
        "id": response_id,
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_test",
                "status": "completed",
                "action": {
                    "type": "search",
                    "sources": [
                        {
                            "type": "url",
                            "url": "https://example.com/primary",
                            "title": "Example source",
                        },
                        {
                            "type": "url",
                            "url": "https://example.com/complete-list-only",
                            "title": "Complete source list item",
                        },
                    ],
                },
            },
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/primary",
                                "title": "Example source",
                                "start_index": start_index,
                                "end_index": start_index + len(cited_text),
                            }
                        ],
                    }
                ],
            },
        ],
    }


def completed_text_response(
    response_id: str,
    text: str,
) -> dict[str, object]:
    return {
        "id": response_id,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


class MockResearchProvider:
    """Test-only provider; production selection remains OpenAI-only."""

    name = "openai"
    billable_calls = False
    configured = True
    model = "gpt-5.6-terra"

    def __init__(self) -> None:
        self.parser = OpenAIResearchProvider(api_key="test-openai-key")
        self.start_calls: list[ResearchProviderRequest] = []
        self.retrieve_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self.responses: dict[str, list[dict[str, object]]] = {}
        self.fail_retrieve_once = False
        self.return_verification_gap_once = False
        self.search_tool_call_count = 1
        self.search_tool_call_counts: list[int] = []
        self.synthesis_outputs: list[str] = []

    def start(self, request: ResearchProviderRequest) -> Mapping[str, object]:
        self.start_calls.append(request)
        response_id = f"resp_mock_{len(self.start_calls)}"
        if request.task_kind == "brief":
            completed = completed_text_response(
                response_id,
                json.dumps(
                    {
                        "objective": "Evaluate evidence for a personal agent.",
                        "scope": ["current evidence practices"],
                        "assumptions": [],
                        "success_criteria": ["cited recommendations"],
                        "subquestions": [
                            {
                                "id": f"q{index}",
                                "question": f"Research evidence dimension {index}",
                                "objective": f"Collect evidence for dimension {index}",
                            }
                            for index in range(1, 5)
                        ],
                    }
                ),
            )
        elif request.task_kind == "verify":
            gaps = []
            if self.return_verification_gap_once:
                self.return_verification_gap_once = False
                gaps = [
                    {
                        "id": "gap1",
                        "question": "Find one missing authoritative source.",
                        "reason": "The first round lacks primary evidence.",
                    }
                ]
            completed = completed_text_response(
                response_id,
                json.dumps(
                    {
                        "summary": "Evidence is sufficient.",
                        "conflicts": [],
                        "gaps": gaps,
                        "coverage_notes": ["Four dimensions covered."],
                    }
                ),
            )
        elif request.task_kind in {"synthesis", "citation_repair"}:
            output_text = (
                self.synthesis_outputs.pop(0)
                if self.synthesis_outputs
                else "## Research summary\n\nEvidence supports the result [S1]."
            )
            completed = completed_text_response(
                response_id,
                output_text,
            )
        else:
            completed = completed_research_response(response_id)
            output = completed["output"]
            assert isinstance(output, list)
            search_call = output[0]
            assert isinstance(search_call, dict)
            tool_call_count = (
                self.search_tool_call_counts.pop(0)
                if self.search_tool_call_counts
                else self.search_tool_call_count
            )
            output[0:1] = [
                {**search_call, "id": f"ws_test_{index}"}
                for index in range(tool_call_count)
            ]
        self.responses[response_id] = [
            {"id": response_id, "status": "in_progress", "output": []},
            completed,
        ]
        return {"id": response_id, "status": "queued", "output": []}

    def retrieve(self, response_id: str) -> Mapping[str, object]:
        self.retrieve_calls.append(response_id)
        if self.fail_retrieve_once:
            self.fail_retrieve_once = False
            raise ResearchProviderError(
                "research_provider_unavailable",
                "OpenAI Research is temporarily unavailable. Please try again.",
                retryable=True,
            )
        queue = self.responses[response_id]
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    def cancel(self, response_id: str) -> Mapping[str, object]:
        self.cancel_calls.append(response_id)
        response = {"id": response_id, "status": "cancelled", "output": []}
        self.responses[response_id] = [response]
        return response

    def parse_result(
        self,
        response: Mapping[str, object],
    ) -> ResearchProviderResult:
        return self.parser.parse_result(response)

    def register(
        self,
        response_id: str,
        *responses: dict[str, object],
    ) -> None:
        self.responses[response_id] = list(responses)


class FailingModelProvider:
    name = "deepseek"
    billable_model_calls = True

    def stream_reply(
        self,
        _message: str,
        _mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
        memory_context: str = "",
    ) -> Iterator[str]:
        del history, memory_context
        raise ModelProviderError(
            "provider_rate_limited",
            "DeepSeek is receiving too many requests. Please retry shortly.",
            retryable=True,
        )


class RecordingModelProvider:
    name = "recording"
    billable_model_calls = False

    def __init__(self) -> None:
        self.history_calls: list[list[ModelMessage]] = []
        self.memory_context_calls: list[str] = []

    def stream_reply(
        self,
        message: str,
        _mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
        memory_context: str = "",
    ) -> Iterator[str]:
        self.history_calls.append(list(history))
        self.memory_context_calls.append(memory_context)
        yield f"Reply to {message}"


def parse_sse(body: str) -> list[dict[str, object]]:
    events = []
    for frame in body.split("\n\n"):
        data_line = next(
            (line for line in frame.splitlines() if line.startswith("data: ")),
            None,
        )
        if data_line:
            events.append(json.loads(data_line.removeprefix("data: ")))
    return events


class MindFastAPIContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        data_path = (
            Path(self.temporary_directory.name) / "conversations.json"
        )
        research_data_path = (
            Path(self.temporary_directory.name) / "research-jobs.json"
        )
        memory_data_path = Path(self.temporary_directory.name) / "memories.json"
        self.repository = JsonConversationRepository(data_path)
        self.research_repository = JsonResearchRepository(research_data_path)
        self.memory_repository = JsonMemoryRepository(memory_data_path)
        self.memory_service = MemoryService(
            repository=self.memory_repository,
            retriever=LocalMemoryRetriever(self.memory_repository),
        )
        self.provider = FakeAgentProvider(delay_seconds=0)
        self.research_provider = MockResearchProvider()
        self.settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            data_path=data_path,
            research_data_path=research_data_path,
            memory_data_path=memory_data_path,
            research_poll_interval_seconds=0.001,
            quiet=True,
        )
        self.client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=self.provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                memory_repository=self.memory_repository,
                memory_service=self.memory_service,
            )
        )
        self.addCleanup(self.client.close)
        self.auth_headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

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

    def test_chat_validation_uses_typed_pydantic_models(self) -> None:
        message, mode, conversation_id = validate_chat_payload(
            {"message": "  Investigate this topic.  ", "mode": "research"}
        )
        self.assertEqual(message, "Investigate this topic.")
        self.assertEqual(mode, "research")
        self.assertIsNone(conversation_id)

        with self.assertRaises(ValidationError):
            ChatRequest(message="   ")
        with self.assertRaises(ValidationError):
            ChatRequest(message="hello", mode="unsupported")
        with self.assertRaises(ValidationError):
            ResearchRequest(query="   ")

        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "   "},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertTrue(response.json()["error"]["details"])

    def test_chat_streams_and_persists_an_exchange(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers={
                **self.auth_headers,
                "X-Request-ID": "chat-contract-test",
            },
            json={
                "message": "Explain the local vertical slice.",
                "mode": "chat",
                "attachments": [{"name": "notes.txt", "size": 12}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        events = parse_sse(response.text)
        self.assertGreater(len(events), 2)
        self.assertEqual(events[0]["type"], "delta")
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["request_id"], "chat-contract-test")

        summaries = self.repository.list_conversations("local-developer")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(str(summaries[0].id), events[-1]["conversation_id"])
        self.assertEqual(summaries[0].message_count, 2)

        detail = self.client.get(
            f"/api/conversations/{events[-1]['conversation_id']}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], events[-1]["conversation_id"])
        self.assertEqual(
            [message["role"] for message in detail.json()["messages"]],
            ["user", "assistant"],
        )

    def test_memory_ledger_lifecycle_is_tenant_scoped_and_user_controlled(
        self,
    ) -> None:
        created = self.client.post(
            "/api/memories",
            headers=self.auth_headers,
            json={
                "type": "preference",
                "content": "I prefer concise answers with clear next steps.",
                "pinned": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        memory = created.json()
        self.assertEqual(memory["status"], "active")
        self.assertTrue(memory["enabled"])
        self.assertTrue(memory["pinned"])

        listed = self.client.get("/api/memories", headers=self.auth_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()["memories"]], [memory["id"]])

        updated = self.client.patch(
            f"/api/memories/{memory['id']}",
            headers=self.auth_headers,
            json={"enabled": False, "pinned": False},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["enabled"])
        self.assertFalse(updated.json()["pinned"])

        deleted = self.client.delete(
            f"/api/memories/{memory['id']}",
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get("/api/memories", headers=self.auth_headers).json(),
            {"memories": []},
        )

    def test_chat_creates_disabled_candidate_and_confirmed_memory_is_retrieved(
        self,
    ) -> None:
        first = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "我喜欢简洁的回答。", "mode": "chat"},
        )
        first_events = parse_sse(first.text)
        self.assertEqual(first_events[-1]["memory_candidate_count"], 1)
        candidate = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(
            first_events[-1]["memory_candidates"],
            [
                {
                    "id": str(candidate.id),
                    "type": candidate.type.value,
                    "status": candidate.status.value,
                    "review_reason": (
                        candidate.review_reason.value
                        if candidate.review_reason is not None
                        else None
                    ),
                }
            ],
        )
        self.assertEqual(candidate.type, MemoryType.PREFERENCE)
        self.assertEqual(candidate.status, MemoryStatus.CANDIDATE)
        self.assertFalse(candidate.enabled)

        confirmed = self.client.post(
            f"/api/memories/{candidate.id}/confirm",
            headers=self.auth_headers,
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["status"], "active")

        recording_provider = RecordingModelProvider()
        recording_client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=recording_provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                memory_repository=self.memory_repository,
                memory_service=self.memory_service,
            )
        )
        self.addCleanup(recording_client.close)
        second = recording_client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请简洁说明下一步。", "mode": "chat"},
        )
        second_events = parse_sse(second.text)
        self.assertIn("我喜欢简洁的回答", recording_provider.memory_context_calls[-1])
        self.assertEqual(second_events[-1]["memory_ids"], [str(candidate.id)])

        self.client.patch(
            f"/api/memories/{candidate.id}",
            headers=self.auth_headers,
            json={"enabled": False},
        )
        recording_client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请简洁说明风险。", "mode": "chat"},
        )
        self.assertEqual(recording_provider.memory_context_calls[-1], "")

    def test_memory_filters_credentials_and_marks_sensitive_candidates(self) -> None:
        rejected = self.client.post(
            "/api/memories",
            headers=self.auth_headers,
            json={
                "type": "fact",
                "content": "API key: sk-testcredential1234567890",
            },
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "memory_content_rejected")

        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请记住我的医疗诊断需要定期复查。", "mode": "chat"},
        )
        self.assertEqual(parse_sse(response.text)[-1]["memory_candidate_count"], 1)
        candidate = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(candidate.sensitivity.value, "sensitive")
        self.assertFalse(candidate.enabled)

    def test_explicit_non_sensitive_memory_is_saved_without_review(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请记住，我的项目叫 Mind。", "mode": "chat"},
        )

        done = parse_sse(response.text)[-1]
        self.assertEqual(done["memory_candidate_count"], 0)
        self.assertEqual(done["memory_candidates"], [])
        self.assertEqual(done["memory_saved_count"], 1)
        memory = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(memory.status, MemoryStatus.ACTIVE)
        self.assertTrue(memory.enabled)

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
            all(
                task["response_id"]
                for task in job["checkpoint"]["subtasks"]
            )
        )
        search_tasks = [
            task
            for task in job["checkpoint"]["subtasks"]
            if task["kind"] == "search"
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

    def test_research_persists_and_uses_relevant_confirmed_memory(self) -> None:
        memory = self.memory_service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.PROJECT,
                content="My project uses Firebase authentication.",
            ),
            "local-developer",
        )
        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Research Firebase authentication patterns."},
        )
        events = parse_sse(response.text)
        job = self.research_repository.get_job(
            str(events[0]["job_id"]),
            "local-developer",
        )

        self.assertEqual(job.memory_ids, [memory.id])
        self.assertIn(
            "My project uses Firebase authentication",
            self.research_provider.start_calls[0].prompt,
        )

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
            any(
                "Reclassified as a gap" in note
                for note in verification.coverage_notes
            )
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
                    url=(
                        "https://platform.openai.com/docs/guides/background"
                    ),
                ),
                ResearchSource(
                    id="S2",
                    step_id="search-r1-q2",
                    title="Data controls",
                    url=(
                        "https://developers.openai.com/api/docs/guides/your-data"
                    ),
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

    def test_failed_poll_resumes_the_same_openai_response_without_restarting(
        self,
    ) -> None:
        self.research_provider.fail_retrieve_once = True

        first = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Checkpointed research"},
        )
        first_events = parse_sse(first.text)
        self.assertEqual(first_events[-1]["type"], "error")
        self.assertEqual(
            first_events[-1]["code"],
            "research_provider_unavailable",
        )
        job_id = first_events[0]["job_id"]
        failed = self.research_repository.get_job(job_id, "local-developer")
        self.assertEqual(failed.status, ResearchStatus.FAILED)
        self.assertEqual(failed.provider_response_id, "resp_mock_1")
        self.assertEqual(failed.provider_status, "queued")
        failed_conversation = self.repository.get_conversation(
            failed.conversation_id,
            "local-developer",
        )
        self.assertEqual(failed_conversation.messages[-1].content, "")
        self.assertEqual(
            str(failed_conversation.messages[-1].research_job_id),
            job_id,
        )
        resumed = self.client.post(
            f"/api/research/{job_id}/resume",
            headers=self.auth_headers,
        )
        resumed_events = parse_sse(resumed.text)
        self.assertEqual(resumed_events[-1]["type"], "done")
        completed = self.research_repository.get_job(job_id, "local-developer")
        self.assertEqual(completed.status, ResearchStatus.COMPLETED)
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

    def test_get_refreshes_by_response_id_and_does_not_duplicate_assistant(self) -> None:
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

    def test_second_turn_receives_persisted_history(self) -> None:
        provider = RecordingModelProvider()
        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=provider,
            )
        )
        self.addCleanup(client.close)

        first_response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Remember the code word lantern."},
        )
        first_events = parse_sse(first_response.text)
        second_response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={
                "conversation_id": first_events[-1]["conversation_id"],
                "message": "What was the code word?",
            },
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(provider.history_calls[0], [])
        self.assertEqual(
            [message.model_dump(mode="json") for message in provider.history_calls[1]],
            [
                {
                    "role": "user",
                    "content": "Remember the code word lantern.",
                },
                {
                    "role": "assistant",
                    "content": "Reply to Remember the code word lantern.",
                },
            ],
        )
        detail = self.repository.get_conversation(
            first_events[-1]["conversation_id"],
            "local-developer",
        )
        self.assertEqual(len(detail.messages), 4)

    def test_delete_conversation_removes_only_the_owned_record(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Temporary conversation."},
        )
        conversation_id = parse_sse(response.text)[-1]["conversation_id"]
        other_conversation_id = self.repository.append_exchange(
            None,
            "Private to another user.",
            "Must remain intact.",
            AgentMode.CHAT,
            user_id="other-user",
        )
        research_job = self.research_repository.create_job(
            ResearchJob(
                user_id="local-developer",
                conversation_id=uuid.UUID(conversation_id),
                query="Temporary research",
            )
        )

        rejected = self.client.delete(
            f"/api/conversations/{other_conversation_id}",
            headers=self.auth_headers,
        )
        deleted = self.client.delete(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_headers,
        )

        self.assertEqual(rejected.status_code, 404)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "conversation_not_found",
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
        )
        self.assertEqual(
            len(self.repository.list_conversations("other-user")),
            1,
        )
        detail = self.client.get(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 404)
        with self.assertRaises(ResearchJobNotFoundError):
            self.research_repository.get_job(
                research_job.id,
                "local-developer",
            )

    def test_unknown_conversation_is_not_silently_recreated(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={
                "conversation_id": str(uuid.uuid4()),
                "message": "Continue the missing conversation.",
                "mode": "chat",
            },
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "conversation_not_found")
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
        )

        detail = self.client.get(
            f"/api/conversations/{uuid.uuid4()}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(
            detail.json()["error"]["code"],
            "conversation_not_found",
        )

    def test_provider_failures_are_safe_retryable_sse_events(self) -> None:
        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=FailingModelProvider(),
            )
        )
        self.addCleanup(client.close)

        response = client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "Try the hosted provider."},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(
            events,
            [
                {
                    "type": "error",
                    "code": "provider_rate_limited",
                    "message": (
                        "DeepSeek is receiving too many requests. "
                        "Please retry shortly."
                    ),
                    "retryable": True,
                    "request_id": events[0]["request_id"],
                }
            ],
        )
        self.assertEqual(
            self.repository.list_conversations("local-developer"),
            [],
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
        self.assertIn("/api/memories", schema["paths"])
        self.assertIn("/api/memories/{memory_id}", schema["paths"])
        self.assertIn("/api/memories/{memory_id}/confirm", schema["paths"])
        self.assertIn("/api/account", schema["paths"])
        self.assertIn("ResearchRequest", schema["components"]["schemas"])
        self.assertIn("ResearchJob", schema["components"]["schemas"])
        self.assertIn("ChatRequest", schema["components"]["schemas"])
        self.assertIn("MemoryCreateRequest", schema["components"]["schemas"])
        self.assertIn("MemoryUpdateRequest", schema["components"]["schemas"])
        self.assertIn("ErrorResponse", schema["components"]["schemas"])

    def test_account_deletion_stops_active_research_and_removes_owned_data(
        self,
    ) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Research before deleting my account.",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        job = ResearchJob(
            user_id="local-developer",
            conversation_id=uuid.UUID(conversation_id),
            query="Research before deleting my account.",
            status=ResearchStatus.COLLECTING,
            provider_response_id="resp_account_delete",
            provider_status="in_progress",
        )
        self.research_repository.create_job(job)
        self.research_provider.register(
            "resp_account_delete",
            {"id": "resp_account_delete", "status": "in_progress", "output": []},
        )
        self.memory_service.create_memory(
            MemoryCreateRequest(content="Remember this before account deletion."),
            "local-developer",
        )

        response = self.client.delete(
            "/api/account",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.research_provider.cancel_calls,
            ["resp_account_delete"],
        )
        self.assertEqual(self.repository.list_conversations("local-developer"), [])
        self.assertEqual(self.research_repository.list_jobs("local-developer"), [])
        self.assertEqual(self.memory_repository.list_memories("local-developer"), [])

    def test_firebase_account_deletion_requires_recent_authentication(self) -> None:
        class OldFirebasePrincipalVerifier:
            method = "firebase"

            def verify(self, _token: str) -> LocalPrincipal:
                return LocalPrincipal(
                    user_id="firebase-user",
                    email="owner@example.com",
                    email_verified=True,
                    authenticated_at=datetime.now(timezone.utc)
                    - timedelta(hours=1),
                    authentication_method="firebase",
                )

        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=self.provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                principal_verifier=OldFirebasePrincipalVerifier(),
                account_manager=LocalAccountManager(),
            )
        )
        self.addCleanup(client.close)

        response = client.delete(
            "/api/account",
            headers={"Authorization": "Bearer firebase-token"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "recent_authentication_required",
        )


class MindDomainAndRepositoryTest(unittest.TestCase):
    def test_fake_provider_is_deterministic_and_bill_free(self) -> None:
        provider = FakeAgentProvider(delay_seconds=0)
        reply = provider.create_reply("Explain the local vertical slice.")
        streamed_reply = "".join(
            provider.stream_reply(
                "Explain the local vertical slice.",
                AgentMode.CHAT,
            )
        )
        self.assertEqual(reply, streamed_reply)
        self.assertIn("without calling an external model", reply)
        self.assertFalse(provider.billable_model_calls)

    def test_versioned_chat_evaluation_cases(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2] / "evals" / "chat-cases.json"
        )
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
        provider = FakeAgentProvider(delay_seconds=0)

        for case in cases:
            with self.subTest(case=case["id"]):
                reply = provider.create_reply(case["input"], case["mode"])
                for phrase in case["required_phrases"]:
                    self.assertIn(phrase, reply)
                for phrase in case["forbidden_phrases"]:
                    self.assertNotIn(phrase, reply)

    def test_json_repository_persists_and_enforces_tenant_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            repository = JsonConversationRepository(data_path)
            conversation_id = repository.append_exchange(
                None,
                "Explain the local vertical slice.",
                "This is a deterministic reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )
            repository.append_exchange(
                conversation_id,
                "Continue.",
                "This is the second reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )

            summaries = repository.list_conversations("user-a")
            self.assertEqual(len(summaries), 1)
            self.assertEqual(str(summaries[0].id), conversation_id)
            self.assertEqual(summaries[0].message_count, 4)
            self.assertEqual(repository.list_conversations("user-b"), [])
            conversation = repository.get_conversation(
                conversation_id,
                "user-a",
            )
            self.assertEqual(len(conversation.messages), 4)
            self.assertEqual(conversation.messages[0].role, MessageRole.USER)
            with self.assertRaises(ConversationNotFoundError):
                repository.get_conversation(conversation_id, "user-b")
            with self.assertRaises(ConversationNotFoundError):
                repository.append_exchange(
                    conversation_id,
                    "Cross-tenant access.",
                    "This must not be written.",
                    AgentMode.CHAT,
                    user_id="user-b",
                )
            repository.delete_conversation(conversation_id, "user-a")
            self.assertEqual(repository.list_conversations("user-a"), [])
            with self.assertRaises(ConversationNotFoundError):
                repository.delete_conversation(conversation_id, "user-a")
            self.assertTrue(data_path.exists())

    def test_repository_reads_legacy_conversations_without_rewriting_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            conversation_id = str(uuid.uuid4())
            timestamp = "2026-01-01T00:00:00+00:00"
            legacy_payload = {
                "conversations": [
                    {
                        "id": conversation_id,
                        "title": "Legacy conversation",
                        "mode": "chat",
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Legacy question",
                                "created_at": timestamp,
                            },
                            {
                                "role": "assistant",
                                "content": "Legacy answer",
                                "created_at": timestamp,
                            },
                        ],
                    }
                ]
            }
            original_json = json.dumps(legacy_payload, ensure_ascii=False)
            data_path.write_text(original_json, encoding="utf-8")
            repository = JsonConversationRepository(data_path)

            first_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )
            second_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )

            self.assertEqual(first_read.user_id, "local-developer")
            self.assertEqual(len(first_read.messages), 2)
            self.assertEqual(
                first_read.messages[0].conversation_id,
                first_read.id,
            )
            self.assertEqual(
                first_read.messages[0].id,
                second_read.messages[0].id,
            )
            self.assertEqual(
                data_path.read_text(encoding="utf-8"),
                original_json,
            )

    def test_context_selection_keeps_only_recent_complete_turns(self) -> None:
        conversation_id = uuid.uuid4()
        messages = [
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="old question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="old answer",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="new question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="new answer",
            ),
        ]

        history = select_recent_history(
            messages,
            max_characters=len("new questionnew answer"),
        )

        self.assertEqual(
            [message.content for message in history],
            ["new question", "new answer"],
        )
        self.assertEqual(select_recent_history(messages, max_characters=1), [])

    def test_all_phase_one_domain_models_are_defined(self) -> None:
        model_names = {
            model.__name__
            for model in (
                User,
                Conversation,
                Message,
                Attachment,
                ResearchJob,
                Memory,
                Routine,
                ToolCall,
            )
        }
        self.assertEqual(
            model_names,
            {
                "User",
                "Conversation",
                "Message",
                "Attachment",
                "ResearchJob",
                "Memory",
                "Routine",
                "ToolCall",
            },
        )

    def test_production_requires_firebase_and_restricted_access(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Firebase authentication",
        ):
            Settings(environment="production")

        with self.assertRaisesRegex(ValueError, "MIND_ALLOWED_USER_EMAILS"):
            Settings(
                environment="production",
                auth_provider="firebase",
                firebase_project_id="mind-production",
                openai_api_key="test-key",
                allowed_origins=("https://mind.example",),
            )

        with self.assertRaisesRegex(
            ValueError,
            "MIND_MAX_CONTEXT_CHARACTERS",
        ):
            Settings(max_context_characters=0)


class OpenAIResearchProviderTest(unittest.TestCase):
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
            status = "cancelled" if request.full_url.endswith("/cancel") else "in_progress"
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
        provider = create_research_provider(
            Settings(openai_api_key="test-openai-key")
        )
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


if __name__ == "__main__":
    unittest.main()
