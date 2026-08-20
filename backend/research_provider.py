"""Provider boundary for long-running Deep Research responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ProviderCitation:
    """One URL citation located within the provider's final output text."""

    url: str
    title: str
    start_index: int
    end_index: int


@dataclass(frozen=True, slots=True)
class ProviderSource:
    """One complete web source consulted by the provider."""

    url: str
    title: str


@dataclass(frozen=True, slots=True)
class ResearchProviderRequest:
    """One bounded harness task executed by a replaceable provider."""

    prompt: str
    task_kind: str
    use_web_search: bool = False
    max_tool_calls: int = 0


@dataclass(frozen=True, slots=True)
class ResearchProviderResult:
    """Normalized result shared by ResearchService and provider implementations."""

    response_id: str
    status: str
    output_text: str = ""
    citations: tuple[ProviderCitation, ...] = ()
    sources: tuple[ProviderSource, ...] = ()
    error_code: str | None = None
    public_message: str | None = None
    retryable: bool = False
    tool_call_count: int = 0


class ResearchProvider(Protocol):
    """Replaceable transport boundary for asynchronous research providers."""

    name: str
    billable_calls: bool
    configured: bool
    model: str

    def start(self, request: ResearchProviderRequest) -> Mapping[str, Any]:
        """Start a new provider task and return its raw response object."""

        ...

    def retrieve(self, response_id: str) -> Mapping[str, Any]:
        """Retrieve an existing provider task without creating a new one."""

        ...

    def cancel(self, response_id: str) -> Mapping[str, Any]:
        """Cancel an in-flight provider task and return its final response object."""

        ...

    def parse_result(self, response: Mapping[str, Any]) -> ResearchProviderResult:
        """Normalize provider output, citations, sources, status, and failures."""

        ...


class ResearchProviderError(RuntimeError):
    """Safe provider-independent failure suitable for API error mapping."""

    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
        provider_status_code: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.provider_status_code = provider_status_code
