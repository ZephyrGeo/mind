"""Shared Pydantic models for API, provider, and persistence boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    COMPARING = "comparing"
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
    FILE_ANALYSIS = "file_analysis"
    SEARCH = "search"
    VERIFY = "verify"
    COMPARE = "compare"
    SYNTHESIS = "synthesis"
    CITATION_REPAIR = "citation_repair"


class ResearchTaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class MemoryType(str, Enum):
    GOAL = "goal"
    PREFERENCE = "preference"
    PROJECT = "project"
    FACT = "fact"
    DECISION = "decision"


class MemorySensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    CONFLICT = "conflict"


class MemoryReviewReason(str, Enum):
    INFERRED = "inferred"
    SENSITIVE = "sensitive"
    UPDATE = "update"
    CONFLICT = "conflict"
    RESEARCH = "research"


class MemorySourceKind(str, Enum):
    MANUAL = "manual"
    CONVERSATION = "conversation"
    RESEARCH_REPORT = "research_report"


class AttachmentStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ResearchCitationKind(str, Enum):
    WEB = "web"
    FILE = "file"


class ResearchEvidenceStatus(str, Enum):
    WEB_VERIFIED = "web_verified"
    FILE_PROVIDED = "file_provided"
    CORROBORATED = "corroborated"
    CONFLICT = "conflict"
    UNVERIFIED = "unverified"


class ResearchDiffKind(str, Enum):
    CHANGED = "changed"
    NEW = "new"
    CONTRADICTED = "contradicted"
    STALE = "stale"


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
    attachment_ids: list[UUID] = Field(default_factory=list[UUID], max_length=5)
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
    mode: AgentMode = AgentMode.CHAT
    updated_at: datetime
    message_count: int = Field(ge=0)


class Attachment(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1, le=20_000_000)
    storage_uri: str = Field(min_length=1, max_length=2_048)
    status: AttachmentStatus = AttachmentStatus.PENDING
    extracted_text: str = Field(default="", max_length=120_000)
    extracted_character_count: int = Field(default=0, ge=0, le=120_000)
    error_code: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AttachmentSummary(StrictModel):
    id: UUID
    conversation_id: UUID | None = None
    name: str
    media_type: str
    size_bytes: int
    status: AttachmentStatus
    extracted_character_count: int
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class AttachmentsResponse(StrictModel):
    attachments: list[AttachmentSummary]


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
    url: str | None = Field(default=None, min_length=1, max_length=4_096)
    file_id: UUID | None = None
    kind: ResearchCitationKind = ResearchCitationKind.WEB
    verification_status: ResearchEvidenceStatus = (
        ResearchEvidenceStatus.WEB_VERIFIED
    )
    start_index: int = Field(ge=0)
    end_index: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_source_location(self) -> "ResearchCitation":
        if self.kind == ResearchCitationKind.WEB and self.url is None:
            raise ValueError("Web citations require a URL.")
        if self.kind == ResearchCitationKind.FILE and self.file_id is None:
            raise ValueError("File citations require a file ID.")
        return self


class ResearchDiffEvidence(StrictModel):
    source_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=1_000)
    url: str | None = Field(default=None, max_length=4_096)
    published_at: str | None = Field(default=None, max_length=128)


class ResearchDiffClaim(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    kind: ResearchDiffKind
    section: str = Field(min_length=1, max_length=500)
    baseline_claim: str | None = Field(default=None, max_length=4_000)
    latest_claim: str | None = Field(default=None, max_length=4_000)
    baseline_evidence: list[ResearchDiffEvidence] = Field(
        default_factory=list[ResearchDiffEvidence],
        max_length=20,
    )
    latest_evidence: list[ResearchDiffEvidence] = Field(
        default_factory=list[ResearchDiffEvidence],
        max_length=20,
    )
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_claim_sides(self) -> "ResearchDiffClaim":
        if self.kind == ResearchDiffKind.NEW and not self.latest_claim:
            raise ValueError("New Research changes require a latest claim.")
        if self.kind == ResearchDiffKind.STALE and not self.baseline_claim:
            raise ValueError("Stale Research changes require a baseline claim.")
        if self.kind in {
            ResearchDiffKind.CHANGED,
            ResearchDiffKind.CONTRADICTED,
        } and not (self.baseline_claim and self.latest_claim):
            raise ValueError(
                "Changed and contradicted Research changes require both claim sides."
            )
        return self


class ResearchInsightDiff(StrictModel):
    baseline_job_id: UUID
    baseline_created_at: datetime
    latest_created_at: datetime = Field(default_factory=utc_now)
    claims: list[ResearchDiffClaim] = Field(
        default_factory=list[ResearchDiffClaim],
        max_length=100,
    )


class ResearchReportSnapshot(StrictModel):
    job_id: UUID
    created_at: datetime
    report: str
    sources: list[ResearchSource] = Field(default_factory=list[ResearchSource])
    citations: list[ResearchCitation] = Field(
        default_factory=list[ResearchCitation]
    )


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


class ResearchFileClaim(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    file_ref: str = Field(pattern=r"^F\d+$", max_length=16)
    text: str = Field(min_length=1, max_length=2_000)
    claim_type: str = Field(default="other", max_length=64)
    externally_verifiable: bool = True


class ResearchFileReview(StrictModel):
    summary: str = Field(default="", max_length=4_000)
    claims: list[ResearchFileClaim] = Field(
        default_factory=list[ResearchFileClaim],
        max_length=40,
    )
    suspicious_instructions: list[str] = Field(
        default_factory=list[str],
        max_length=20,
    )


class ResearchFileClaimAssessment(StrictModel):
    claim_id: str = Field(min_length=1, max_length=32)
    status: ResearchEvidenceStatus = ResearchEvidenceStatus.UNVERIFIED
    source_ids: list[str] = Field(default_factory=list[str], max_length=20)
    note: str = Field(default="", max_length=2_000)


class ResearchVerification(StrictModel):
    summary: str = Field(default="", max_length=4_000)
    conflicts: list[str] = Field(default_factory=list[str], max_length=20)
    gaps: list[ResearchEvidenceGap] = Field(
        default_factory=list[ResearchEvidenceGap],
        max_length=8,
    )
    coverage_notes: list[str] = Field(default_factory=list[str], max_length=20)
    file_claims: list[ResearchFileClaimAssessment] = Field(
        default_factory=list[ResearchFileClaimAssessment],
        max_length=40,
    )


class ResearchBudget(StrictModel):
    max_search_rounds: int = Field(default=2, ge=1, le=2)
    max_subquestions: int = Field(default=6, ge=4, le=8)
    max_total_tool_calls: int = Field(default=24, ge=1, le=100)
    max_tool_call_overrun: int = Field(default=3, ge=0, le=20)
    # Optional keeps jobs persisted before Resilience Harness v1 loadable.
    # New jobs always persist an explicit value from Settings.
    soft_timeout_seconds: int | None = Field(default=None, ge=1, le=3_600)
    timeout_seconds: int = Field(default=600, ge=60, le=3_600)

    @model_validator(mode="after")
    def soft_timeout_precedes_hard_timeout(self) -> "ResearchBudget":
        if (
            self.soft_timeout_seconds is not None
            and self.soft_timeout_seconds >= self.timeout_seconds
        ):
            raise ValueError("Research soft timeout must precede hard timeout.")
        return self


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
    generation_attempts: int = Field(default=0, ge=0, le=20)
    transport_attempts: int = Field(default=0, ge=0, le=100)
    consecutive_errors: int = Field(default=0, ge=0, le=20)
    retry_strategy: str | None = Field(default=None, max_length=64)
    next_retry_at: datetime | None = None
    last_error_at: datetime | None = None
    last_progress_at: datetime = Field(default_factory=utc_now)
    error_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchCheckpoint(StrictModel):
    # Legacy plan fields stay readable while the harness owns the durable brief,
    # subtask, evidence, verification, and synthesis state.
    plan: ResearchPlan | None = None
    brief: ResearchBrief | None = None
    file_review: ResearchFileReview | None = None
    verification: ResearchVerification | None = None
    subtasks: list[ResearchSubtask] = Field(default_factory=list[ResearchSubtask])
    sources: list[ResearchSource] = Field(default_factory=list[ResearchSource])
    citations: list[ResearchCitation] = Field(default_factory=list[ResearchCitation])
    baseline_snapshot: ResearchReportSnapshot | None = None
    insight_diff: ResearchInsightDiff | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    report: str = ""
    assistant_message_id: UUID | None = None


class ResearchJob(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    conversation_id: UUID
    query: str
    baseline_job_id: UUID | None = None
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
    soft_deadline_reached: bool = False
    provider_backoff_until: datetime | None = None
    rate_limit_count: int = Field(default=0, ge=0, le=100)
    rate_limit_wait_seconds: float = Field(default=0, ge=0, le=3_600)
    context_reduction_level: int = Field(default=0, ge=0, le=2)
    degraded_reasons: list[str] = Field(default_factory=list[str], max_length=20)
    citation_coverage: float | None = Field(default=None, ge=0, le=1)
    web_citation_coverage: float | None = Field(default=None, ge=0, le=1)
    file_corroboration_coverage: float | None = Field(default=None, ge=0, le=1)
    quality_warning: str | None = Field(default=None, max_length=1_000)
    memory_ids: list[UUID] = Field(default_factory=list[UUID], max_length=20)
    input_file_ids: list[UUID] = Field(default_factory=list[UUID], max_length=5)
    checkpoint: ResearchCheckpoint = Field(default_factory=ResearchCheckpoint)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    run_started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryProvenance(StrictModel):
    source_kind: MemorySourceKind = MemorySourceKind.MANUAL
    conversation_id: UUID | None = None
    source_message_id: UUID | None = None
    research_job_id: UUID | None = None
    excerpt: str = Field(default="", max_length=1_000)


class Memory(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    type: MemoryType = MemoryType.FACT
    content: str = Field(min_length=1, max_length=1_000)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL
    status: MemoryStatus = MemoryStatus.CANDIDATE
    review_reason: MemoryReviewReason | None = None
    source_message_id: UUID | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    pinned: bool = False
    enabled: bool = False
    canonical_key: str = Field(default="", max_length=300)
    facets: list[str] = Field(default_factory=list[str], max_length=12)
    related_memory_ids: list[UUID] = Field(default_factory=list[UUID], max_length=20)
    supersedes_id: UUID | None = None
    revision: int = Field(default=1, ge=1)
    extraction_model: str | None = Field(default=None, max_length=120)
    embedding_model: str | None = Field(default=None, max_length=120)
    valid_from: datetime | None = None
    last_verified_at: datetime | None = None
    stale_after: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("content")
    @classmethod
    def memory_content_must_contain_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content cannot be empty.")
        return normalized

    @field_validator("facets")
    @classmethod
    def memory_facets_must_contain_text(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.split())[:500]
            key = normalized.casefold()
            if normalized and key not in seen:
                result.append(normalized)
                seen.add(key)
        return result


class MemoryCreateRequest(StrictModel):
    type: MemoryType = MemoryType.FACT
    content: str = Field(min_length=1, max_length=1_000)
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL
    pinned: bool = False
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def content_must_contain_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content cannot be empty.")
        return normalized


class MemoryUpdateRequest(StrictModel):
    type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=1_000)
    sensitivity: MemorySensitivity | None = None
    pinned: bool | None = None
    enabled: bool | None = None
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def optional_content_must_contain_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content cannot be empty.")
        return normalized

    @model_validator(mode="after")
    def at_least_one_field_is_required(self) -> "MemoryUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one memory field must be updated.")
        return self


class MemoriesResponse(StrictModel):
    memories: list[Memory]


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


class ChatRequest(StrictModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=32_000)
    mode: AgentMode = AgentMode.CHAT
    attachment_ids: list[UUID] = Field(default_factory=list[UUID], max_length=5)

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
    attachment_ids: list[UUID] = Field(default_factory=list[UUID], max_length=5)

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
