"""Shared fixtures for Mind API and provider tests."""

from __future__ import annotations

from backend.app import create_app
from backend.config import Settings
from backend.fake_agent import FakeAgentProvider
from backend.file_service import FileService
from backend.file_storage import LocalFileStorage
from backend.file_store import JsonAttachmentRepository
from backend.memory_retrieval import LocalMemoryRetriever
from backend.memory_service import MemoryService
from backend.memory_store import JsonMemoryRepository
from backend.model_provider import ModelProviderError
from backend.models import AgentMode
from backend.models import ModelMessage
from backend.openai_research_provider import OpenAIResearchProvider
from backend.research_provider import ResearchProviderError
from backend.research_provider import ResearchProviderRequest
from backend.research_provider import ResearchProviderResult
from backend.research_store import JsonResearchRepository
from backend.store import JsonConversationRepository
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from fastapi.testclient import TestClient
from pathlib import Path
import json
import tempfile
import unittest

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
        self.start_attempts = 0
        self.start_calls: list[ResearchProviderRequest] = []
        self.retrieve_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self.responses: dict[str, list[dict[str, object]]] = {}
        self.fail_retrieve_once = False
        self.rate_limit_start_failures = 0
        self.context_limit_once_for_kind: str | None = None
        self.incomplete_once_for_kind: str | None = None
        self.invalid_output_once_for_kind: str | None = None
        self.permanently_fail_first_search = False
        self.search_failure_code: str | None = None
        self.failing_search_prompt: str | None = None
        self.active_response_ids: set[str] = set()
        self.max_active_responses = 0
        self.return_verification_gap_once = False
        self.search_tool_call_count = 1
        self.search_tool_call_counts: list[int] = []
        self.synthesis_outputs: list[str] = []
        self.comparison_outputs: list[str] = []
        self.file_analysis_output: str | None = None

    def start(self, request: ResearchProviderRequest) -> Mapping[str, object]:
        self.start_attempts += 1
        if self.rate_limit_start_failures:
            self.rate_limit_start_failures -= 1
            raise ResearchProviderError(
                "research_rate_limited",
                "Too many requests. Research will continue shortly.",
                retryable=True,
                retry_after_seconds=0.001,
                provider_status_code=429,
            )
        if self.context_limit_once_for_kind == request.task_kind:
            self.context_limit_once_for_kind = None
            raise ResearchProviderError(
                "research_context_limit",
                "Research needs to reduce its working context before continuing.",
                retryable=True,
                provider_status_code=400,
            )
        self.start_calls.append(request)
        response_id = f"resp_mock_{len(self.start_calls)}"
        if self.invalid_output_once_for_kind == request.task_kind:
            self.invalid_output_once_for_kind = None
            completed = completed_text_response(response_id, "{invalid")
        elif self.incomplete_once_for_kind == request.task_kind:
            self.incomplete_once_for_kind = None
            completed = {
                "id": response_id,
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            }
        elif request.task_kind == "brief":
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
        elif request.task_kind == "file_analysis":
            completed = completed_text_response(
                response_id,
                self.file_analysis_output
                or json.dumps(
                    {
                        "summary": "The attached file contains user-provided claims.",
                        "claims": [
                            {
                                "id": "F1.C1",
                                "file_ref": "F1",
                                "text": "The document states a material fact.",
                                "claim_type": "other",
                                "externally_verifiable": True,
                            }
                        ],
                        "suspicious_instructions": [],
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
                        "file_claims": [],
                    }
                ),
            )
        elif request.task_kind == "compare":
            completed = completed_text_response(
                response_id,
                self.comparison_outputs.pop(0)
                if self.comparison_outputs
                else json.dumps(
                    {
                        "claims": [
                            {
                                "id": "change-1",
                                "kind": "changed",
                                "section": "Research summary",
                                "baseline_claim": "The earlier report supported the result.",
                                "latest_claim": "The latest evidence supports a revised result.",
                                "baseline_source_ids": ["S1"],
                                "latest_source_ids": ["S1"],
                                "confidence": 0.92,
                                "rationale": "The latest evidence replaces the earlier conclusion.",
                            }
                        ]
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
            if self.search_failure_code:
                completed = {
                    "id": response_id,
                    "status": "failed",
                    "error": {"code": self.search_failure_code},
                    "output": [],
                }
            elif self.permanently_fail_first_search and (
                self.failing_search_prompt is None
                or self.failing_search_prompt == request.prompt
            ):
                self.failing_search_prompt = request.prompt
                completed = {
                    "id": response_id,
                    "status": "failed",
                    "error": {"code": "server_error"},
                    "output": [],
                }
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
        self.active_response_ids.add(response_id)
        self.max_active_responses = max(
            self.max_active_responses,
            len(self.active_response_ids),
        )
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
            response = queue.pop(0)
        else:
            response = queue[0]
        if response.get("status") in {"completed", "failed", "cancelled"}:
            self.active_response_ids.discard(response_id)
        return response

    def cancel(self, response_id: str) -> Mapping[str, object]:
        self.cancel_calls.append(response_id)
        response = {"id": response_id, "status": "cancelled", "output": []}
        self.responses[response_id] = [response]
        self.active_response_ids.discard(response_id)
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
        self.file_context_calls: list[str] = []

    def stream_reply(
        self,
        message: str,
        _mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
        memory_context: str = "",
        file_context: str = "",
    ) -> Iterator[str]:
        self.history_calls.append(list(history))
        self.memory_context_calls.append(memory_context)
        self.file_context_calls.append(file_context)
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


class MindApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        data_path = Path(self.temporary_directory.name) / "conversations.json"
        research_data_path = Path(self.temporary_directory.name) / "research-jobs.json"
        memory_data_path = Path(self.temporary_directory.name) / "memories.json"
        attachment_data_path = Path(self.temporary_directory.name) / "attachments.json"
        usage_data_path = Path(self.temporary_directory.name) / "usage.json"
        local_file_path = Path(self.temporary_directory.name) / "files"
        self.local_file_path = local_file_path
        self.repository = JsonConversationRepository(data_path)
        self.research_repository = JsonResearchRepository(research_data_path)
        self.memory_repository = JsonMemoryRepository(memory_data_path)
        self.memory_service = MemoryService(
            repository=self.memory_repository,
            retriever=LocalMemoryRetriever(self.memory_repository),
        )
        self.attachment_repository = JsonAttachmentRepository(attachment_data_path)
        self.file_storage = LocalFileStorage(local_file_path)
        self.file_service = FileService(
            repository=self.attachment_repository,
            storage=self.file_storage,
        )
        self.provider = FakeAgentProvider(delay_seconds=0)
        self.research_provider = MockResearchProvider()
        self.settings = Settings(
            environment="test",
            local_token=TEST_TOKEN,
            data_path=data_path,
            research_data_path=research_data_path,
            memory_data_path=memory_data_path,
            attachment_data_path=attachment_data_path,
            usage_data_path=usage_data_path,
            local_file_path=local_file_path,
            research_poll_interval_seconds=0.001,
            research_retry_base_seconds=0.001,
            chat_daily_limit=1_000,
            research_daily_limit=100,
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
                attachment_repository=self.attachment_repository,
                file_storage=self.file_storage,
                file_service=self.file_service,
            )
        )
        self.addCleanup(self.client.close)
        self.auth_headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
