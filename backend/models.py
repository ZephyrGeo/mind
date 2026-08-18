"""Shared Pydantic models for API, provider, and persistence boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentMode(str, Enum):
    CHAT = "chat"
    RESEARCH = "research"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ResearchStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    COLLECTING = "collecting"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchStepStatus(str, Enum):
    """Legacy checkpoint compatibility; OpenAI production jobs do not plan steps."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResearchTaskKind(str, Enum):
    BRIEF = "brief"
    SEARCH = "search"
    VERIFY = "verify"
    SYNTHESIS = "synthesis"
    CITATION_REPAIR = "citation_repair"


class ResearchTaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class User(StrictModel):
    id: str
    email: str | None = None
    display_name: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: MessageRole
    content: str
    research_job_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ModelMessage(StrictModel):
    """Minimal, provider-safe message included in model context."""

    role: MessageRole
    content: str = Field(min_length=1)

    @field_validator("role")
    @classmethod
    def role_must_be_conversational(cls, value: MessageRole) -> MessageRole:
        if value not in {MessageRole.USER, MessageRole.ASSISTANT}:
            raise ValueError("Model history accepts only user and assistant roles.")
        return value


class Conversation(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    title: str
    mode: AgentMode = AgentMode.CHAT
    messages: list[Message] = Field(default_factory=list[Message])
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ConversationSummary(StrictModel):
    id: UUID
    title: str
    updated_at: datetime
    message_count: int = Field(ge=0)


class Attachment(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID | None = None
    name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    storage_uri: str | None = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)


class ResearchStep(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=1_000)
    objective: str = Field(min_length=1, max_length=1_000)
    status: ResearchStepStatus = ResearchStepStatus.PENDING
    result_count: int = Field(default=0, ge=0)


class ResearchPlan(StrictModel):
    """Legacy checkpoint shape retained so existing local jobs remain readable."""

    summary: str = Field(min_length=1, max_length=2_000)
    steps: list[ResearchStep] = Field(min_length=1, max_length=6)


class ResearchSource(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    step_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=1_000)
    url: str = Field(min_length=1, max_length=4_096)
    snippet: str = Field(default="", max_length=8_000)
    content: str = ""
    published_at: str | None = Field(default=None, max_length=128)
    retrieved_at: datetime = Field(default_factory=utc_now)


class ResearchCitation(StrictModel):
    source_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=1_000)
    url: str = Field(min_length=1, max_length=4_096)
    start_index: int = Field(ge=0)
    end_index: int = Field(gt=0)


class ResearchBriefQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    question: str = Field(min_length=1, max_length=1_000)
    objective: str = Field(min_length=1, max_length=1_000)


class ResearchBrief(StrictModel):
    objective: str = Field(min_length=1, max_length=2_000)
    scope: list[str] = Field(default_factory=list[str], max_length=12)
    assumptions: list[str] = Field(default_factory=list[str], max_length=12)
    success_criteria: list[str] = Field(default_factory=list[str], max_length=12)
    subquestions: list[ResearchBriefQuestion] = Field(min_length=4, max_length=8)


class ResearchEvidenceGap(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    question: str = Field(min_length=1, max_length=1_000)
    reason: str = Field(min_length=1, max_length=2_000)


class ResearchVerification(StrictModel):
    summary: str = Field(default="", max_length=4_000)
    conflicts: list[str] = Field(default_factory=list[str], max_length=20)
    gaps: list[ResearchEvidenceGap] = Field(
        default_factory=list[ResearchEvidenceGap],
        max_length=8,
    )
    coverage_notes: list[str] = Field(default_factory=list[str], max_length=20)


class ResearchBudget(StrictModel):
    max_search_rounds: int = Field(default=2, ge=1, le=2)
    max_subquestions: int = Field(default=6, ge=4, le=8)
    max_total_tool_calls: int = Field(default=24, ge=1, le=100)
    max_tool_call_overrun: int = Field(default=3, ge=0, le=20)
    timeout_seconds: int = Field(default=600, ge=60, le=3_600)


class ResearchSubtask(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    kind: ResearchTaskKind
    round_index: int = Field(default=0, ge=0, le=2)
    subquestion_id: str | None = Field(default=None, max_length=32)
    question: str = Field(min_length=1, max_length=2_000)
    objective: str = Field(default="", max_length=2_000)
    status: ResearchTaskStatus = ResearchTaskStatus.PENDING
    response_id: str | None = None
    provider_status: str | None = None
    output_text: str = ""
    sources: list[ResearchSource] = Field(default_factory=list[ResearchSource])
    citations: list[ResearchCitation] = Field(
        default_factory=list[ResearchCitation]
    )
    tool_call_limit: int = Field(default=0, ge=0, le=100)
    tool_call_count: int = Field(default=0, ge=0, le=100)
    error_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchCheckpoint(StrictModel):
    # Legacy plan fields stay readable while the harness owns the durable brief,
    # subtask, evidence, verification, and synthesis state.
    plan: ResearchPlan | None = None
    brief: ResearchBrief | None = None
    verification: ResearchVerification | None = None
    subtasks: list[ResearchSubtask] = Field(default_factory=list[ResearchSubtask])
    sources: list[ResearchSource] = Field(default_factory=list[ResearchSource])
    citations: list[ResearchCitation] = Field(default_factory=list[ResearchCitation])
    completed_step_ids: list[str] = Field(default_factory=list)
    report: str = ""
    assistant_message_id: UUID | None = None


class ResearchJob(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID
    query: str
    model: str = "gpt-5.6-terra"
    prompt_version: str = "research-harness-v3"
    status: ResearchStatus = ResearchStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=1)
    provider_response_id: str | None = None
    provider_status: str | None = None
    previous_response_ids: list[str] = Field(default_factory=list)
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    search_round: int = Field(default=0, ge=0, le=2)
    total_tool_calls: int = Field(default=0, ge=0, le=1_000)
    budget_exceeded: bool = False
    hard_budget_reached: bool = False
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    checkpoint: ResearchCheckpoint = Field(default_factory=ResearchCheckpoint)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    run_started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Memory(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    content: str
    source_message_id: UUID | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    pinned: bool = False
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Routine(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    name: str
    prompt: str
    schedule: str
    enabled: bool = True
    max_tool_calls: int = Field(default=10, ge=0, le=100)
    budget_usd: float = Field(default=0, ge=0)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolCall(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID | None = None
    research_job_id: UUID | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus = ToolCallStatus.PENDING
    latency_ms: float | None = Field(default=None, ge=0)
    result_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AttachmentInput(StrictModel):
    """Metadata staged by the current UI; file ingestion is not implemented yet."""

    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=25_000_000)


class ChatRequest(StrictModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=32_000)
    mode: AgentMode = AgentMode.CHAT
    attachments: list[AttachmentInput] = Field(
        default_factory=list[AttachmentInput],
        max_length=10,
    )

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty.")
        return normalized


class ResearchRequest(StrictModel):
    conversation_id: UUID | None = None
    query: str = Field(min_length=1, max_length=8_000)

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Research query cannot be empty.")
        return normalized


class ConversationsResponse(StrictModel):
    conversations: list[ConversationSummary]


class HealthResponse(StrictModel):
    status: str
    service: str
    environment: str
    provider: str
    billable_model_calls: bool
    research_provider: str
    billable_research_calls: bool
    research_mode: str


class ErrorDetail(StrictModel):
    location: list[str | int] = Field(default_factory=list[str | int])
    message: str
    type: str


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] = Field(default_factory=list[ErrorDetail])


class ErrorResponse(StrictModel):
    error: ErrorBody


class LocalPrincipal(StrictModel):
    """Authenticated identity; name retained for API compatibility."""

    user_id: str
    email: str | None = None
    display_name: str | None = None
    email_verified: bool = False
    authenticated_at: datetime | None = None
    authentication_method: str = "local_token"
