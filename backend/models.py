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
    messages: list[Message] = Field(default_factory=list)
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


class ResearchJob(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID
    query: str
    status: ResearchStatus = ResearchStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=1)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
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
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=10)

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty.")
        return normalized


class ConversationsResponse(StrictModel):
    conversations: list[ConversationSummary]


class HealthResponse(StrictModel):
    status: str
    service: str
    environment: str
    provider: str
    billable_model_calls: bool


class ErrorDetail(StrictModel):
    location: list[str | int] = Field(default_factory=list)
    message: str
    type: str


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    error: ErrorBody


class LocalPrincipal(StrictModel):
    user_id: str
    authentication_method: str = "local_token"
