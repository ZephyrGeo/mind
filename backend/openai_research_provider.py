"""OpenAI Responses API implementation of Mind's ResearchProvider boundary."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Mapping
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .research_provider import (
    ProviderCitation,
    ProviderSource,
    ResearchProviderError,
    ResearchProviderRequest,
    ResearchProviderResult,
)
from .source_urls import canonical_source_url


class OpenAIResearchProvider:
    """Run one bounded background task for Mind's Research Harness."""

    name = "openai"
    billable_calls = True

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gpt-5.6-terra",
        base_url: str = "https://api.openai.com/v1",
        reasoning_effort: str = "high",
        max_tool_calls: int = 12,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = 20_000_000,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OpenAI base URL must be a safe HTTPS origin.")
        if not model or any(character.isspace() for character in model):
            raise ValueError("OpenAI research model must be a non-empty model ID.")
        if reasoning_effort not in {
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("Unsupported OpenAI research reasoning effort.")
        if max_tool_calls < 1:
            raise ValueError("OpenAI research max tool calls must be positive.")
        if timeout_seconds <= 0:
            raise ValueError("OpenAI timeout must be positive.")
        if max_response_bytes < 1:
            raise ValueError("OpenAI response limit must be positive.")
        self._api_key = (api_key or "").strip()
        self.configured = bool(self._api_key)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort
        self.max_tool_calls = max_tool_calls
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._opener = opener

    def start(self, request: ResearchProviderRequest) -> Mapping[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "input": request.prompt,
            "background": True,
            "store": True,
            "reasoning": {"effort": self.reasoning_effort},
        }
        if request.use_web_search:
            body.update(
                {
                    "tools": [{"type": "web_search"}],
                    "tool_choice": "auto",
                    "include": ["web_search_call.action.sources"],
                    "max_tool_calls": max(
                        1,
                        min(request.max_tool_calls, self.max_tool_calls),
                    ),
                }
            )
        return self._request("POST", "/responses", body)

    def retrieve(self, response_id: str) -> Mapping[str, Any]:
        return self._request("GET", f"/responses/{quote(response_id, safe='')}")

    def cancel(self, response_id: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            f"/responses/{quote(response_id, safe='')}/cancel",
            {},
        )

    def parse_result(self, response: Mapping[str, Any]) -> ResearchProviderResult:
        response_id = response.get("id")
        status = response.get("status")
        if not isinstance(response_id, str) or not response_id:
            raise _invalid_response_error()
        if not isinstance(status, str) or not status:
            raise _invalid_response_error()

        text_parts: list[str] = []
        citations: list[ProviderCitation] = []
        sources: list[ProviderSource] = []
        source_urls: set[str] = set()
        tool_call_count = 0
        output = response.get("output")
        if isinstance(output, list):
            for raw_item in cast(list[object], output):
                item = _object_mapping(raw_item)
                if item is None:
                    continue
                if item.get("type") == "web_search_call":
                    tool_call_count += 1
                    action = _object_mapping(item.get("action"))
                    if action is not None:
                        raw_sources = action.get("sources")
                        if isinstance(raw_sources, list):
                            for raw_source in cast(list[object], raw_sources):
                                source = _parse_source(raw_source)
                                if source is None or source.url in source_urls:
                                    continue
                                source_urls.add(source.url)
                                sources.append(source)
                if item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for raw_content_item in cast(list[object], content):
                    content_item = _object_mapping(raw_content_item)
                    if content_item is None:
                        continue
                    if content_item.get("type") != "output_text":
                        continue
                    text = content_item.get("text")
                    if not isinstance(text, str):
                        continue
                    offset = sum(len(part) for part in text_parts) + (
                        2 * len(text_parts)
                    )
                    text_parts.append(text)
                    annotations = content_item.get("annotations")
                    if not isinstance(annotations, list):
                        continue
                    for annotation in cast(list[object], annotations):
                        citation = _parse_citation(annotation, offset=offset)
                        if citation is not None:
                            citations.append(citation)

        output_text = "\n\n".join(text_parts).strip()
        if not output_text and isinstance(response.get("output_text"), str):
            output_text = str(response["output_text"]).strip()

        for citation in citations:
            if citation.url in source_urls:
                continue
            source_urls.add(citation.url)
            sources.append(ProviderSource(url=citation.url, title=citation.title))

        error_code, public_message, retryable = _response_failure(response, status)
        return ResearchProviderResult(
            response_id=response_id,
            status=status,
            output_text=output_text,
            citations=tuple(citations),
            sources=tuple(sources),
            error_code=error_code,
            public_message=public_message,
            retryable=retryable,
            tool_call_count=tool_call_count,
        )

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not self.configured:
            raise ResearchProviderError(
                "research_not_configured",
                "OpenAI Research is not configured. Add OPENAI_API_KEY on the server.",
                retryable=False,
            )
        encoded = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            if body is not None
            else None
        )
        request = Request(
            f"{self.base_url}{path}",
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "mind-personal-agent/0.7",
            },
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
        except HTTPError as error:
            raise _http_error(error.code) from None
        except (TimeoutError, URLError, OSError):
            raise ResearchProviderError(
                "research_provider_unavailable",
                "OpenAI Research is temporarily unavailable. Please try again.",
                retryable=True,
            ) from None

        try:
            with response:
                encoded_response = response.read(self.max_response_bytes + 1)
        except (TimeoutError, URLError, OSError):
            raise ResearchProviderError(
                "research_provider_unavailable",
                "OpenAI Research is temporarily unavailable. Please try again.",
                retryable=True,
            ) from None
        if len(encoded_response) > self.max_response_bytes:
            raise _invalid_response_error()
        try:
            payload = json.loads(encoded_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _invalid_response_error() from None
        if not isinstance(payload, Mapping):
            raise _invalid_response_error()
        return cast(Mapping[str, Any], payload)


def _parse_source(value: object) -> ProviderSource | None:
    payload = _object_mapping(value)
    if payload is None:
        return None
    url = payload.get("url")
    if not isinstance(url, str) or not _is_public_web_url(url):
        return None
    canonical_url = canonical_source_url(url)
    if not canonical_url:
        return None
    title = payload.get("title")
    return ProviderSource(
        url=canonical_url,
        title=(
            title.strip()
            if isinstance(title, str) and title.strip()
            else canonical_url
        ),
    )


def _parse_citation(value: object, *, offset: int) -> ProviderCitation | None:
    annotation = _object_mapping(value)
    if annotation is None or annotation.get("type") != "url_citation":
        return None
    payload = _object_mapping(annotation.get("url_citation")) or annotation
    url = payload.get("url")
    title = payload.get("title")
    start_index = payload.get("start_index")
    end_index = payload.get("end_index")
    if (
        not isinstance(url, str)
        or not _is_public_web_url(url)
        or not isinstance(start_index, int)
        or not isinstance(end_index, int)
        or start_index < 0
        or end_index <= start_index
    ):
        return None
    canonical_url = canonical_source_url(url)
    if not canonical_url:
        return None
    return ProviderCitation(
        url=canonical_url,
        title=(
            title.strip()
            if isinstance(title, str) and title.strip()
            else canonical_url
        ),
        start_index=offset + start_index,
        end_index=offset + end_index,
    )


def _response_failure(
    response: Mapping[str, Any],
    status: str,
) -> tuple[str | None, str | None, bool]:
    if status in {"queued", "in_progress", "completed"}:
        return None, None, False
    error = response.get("error")
    error_payload = _object_mapping(error)
    provider_code = error_payload.get("code") if error_payload else None
    if status in {"cancelled", "canceled"}:
        return "research_cancelled", "Research was cancelled.", False
    if status == "incomplete":
        details = response.get("incomplete_details")
        details_payload = _object_mapping(details)
        reason = details_payload.get("reason") if details_payload else None
        code = f"research_incomplete_{reason}" if isinstance(reason, str) else "research_incomplete"
        return code, "OpenAI Research ended before producing a complete report.", True
    code = (
        f"research_provider_{provider_code}"
        if isinstance(provider_code, str) and provider_code
        else "research_provider_failed"
    )
    return code, "OpenAI Research could not complete the report.", True


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _is_public_web_url(value: str) -> bool:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or hostname.lower() == "localhost"
        or hostname.lower().endswith((".localhost", ".local"))
    ):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global


def _http_error(status_code: int) -> ResearchProviderError:
    if status_code in {401, 403}:
        return ResearchProviderError(
            "research_authentication_failed",
            "OpenAI authentication failed. Check OPENAI_API_KEY on the server.",
            retryable=False,
        )
    if status_code == 404:
        return ResearchProviderError(
            "research_response_not_found",
            "The OpenAI research response is no longer available. Restart the research task.",
            retryable=False,
        )
    if status_code == 429:
        return ResearchProviderError(
            "research_rate_limited",
            "OpenAI Research is receiving too many requests. Please retry shortly.",
            retryable=True,
        )
    return ResearchProviderError(
        "research_request_failed",
        "OpenAI Research could not complete the request.",
        retryable=status_code >= 500,
    )


def _invalid_response_error() -> ResearchProviderError:
    return ResearchProviderError(
        "research_invalid_response",
        "OpenAI Research returned an invalid response. Please try again.",
        retryable=True,
    )
