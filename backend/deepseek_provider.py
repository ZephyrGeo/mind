"""Streaming DeepSeek implementation of Mind's model-provider boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .model_provider import ModelProviderError
from .models import AgentMode, ModelMessage


CHAT_SYSTEM_PROMPT = (
    "You are Mind, a careful personal AI assistant. Be concise, useful, and "
    "honest about uncertainty. Never claim that you used files, tools, memory, "
    "or web search unless that context was explicitly provided."
)
RESEARCH_SYSTEM_PROMPT = (
    "You are Mind in preliminary research mode. Analyze the user's question "
    "carefully, organize the answer, distinguish facts from assumptions, and "
    "state what should be verified. You do not have web-search tools in this "
    "request, so never invent sources or citations."
)


class DeepSeekProvider:
    """Calls DeepSeek's OpenAI-compatible Chat Completions streaming API."""

    name = "deepseek"
    billable_model_calls = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 120.0,
        max_tokens: int = 2_048,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        parsed_base_url = urlsplit(base_url)
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("DeepSeek base URL must be a safe HTTPS origin.")
        if not api_key.strip():
            raise ValueError("A DeepSeek API key is required.")
        if not model or any(character.isspace() for character in model):
            raise ValueError("DeepSeek model must be a non-empty model ID.")
        if timeout_seconds <= 0:
            raise ValueError("DeepSeek timeout must be positive.")
        if max_tokens < 1:
            raise ValueError("DeepSeek max tokens must be positive.")

        self._api_key = api_key.strip()
        self.model = model
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self._opener = opener

    def stream_reply(
        self,
        message: str,
        mode: AgentMode,
        *,
        history: Sequence[ModelMessage] = (),
        memory_context: str = "",
        file_context: str = "",
    ) -> Iterator[str]:
        normalized_mode = AgentMode(mode)
        thinking_enabled = normalized_mode == AgentMode.RESEARCH
        base_system_prompt = (
            RESEARCH_SYSTEM_PROMPT if thinking_enabled else CHAT_SYSTEM_PROMPT
        )
        context_sections = [
            context for context in (memory_context, file_context) if context
        ]
        system_prompt = "\n\n".join([base_system_prompt, *context_sections])
        request_body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                *[
                    {
                        "role": context_message.role.value,
                        "content": context_message.content,
                    }
                    for context_message in history
                ],
                {"role": "user", "content": message},
            ],
            "thinking": {
                "type": "enabled" if thinking_enabled else "disabled"
            },
            "reasoning_effort": "high",
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        encoded_body = json.dumps(
            request_body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=encoded_body,
            method="POST",
            headers={
                "Accept": "text/event-stream",
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
            raise ModelProviderError(
                "provider_unavailable",
                "DeepSeek is temporarily unavailable. Please try again.",
                retryable=True,
            ) from None

        received_done = False
        received_text = False
        try:
            with response:
                for raw_line in response:
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        raise _invalid_response_error() from None
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        received_done = True
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        raise _invalid_response_error() from None

                    if not isinstance(chunk, dict):
                        raise _invalid_response_error()
                    choices = chunk.get("choices")
                    if choices == []:
                        continue
                    if not isinstance(choices, list) or not choices:
                        raise _invalid_response_error()
                    first_choice = choices[0]
                    if not isinstance(first_choice, dict):
                        raise _invalid_response_error()
                    delta = first_choice.get("delta")
                    if not isinstance(delta, dict):
                        raise _invalid_response_error()
                    content = delta.get("content")
                    if content is None or content == "":
                        continue
                    if not isinstance(content, str):
                        raise _invalid_response_error()
                    received_text = True
                    yield content
        except ModelProviderError:
            raise
        except (TimeoutError, URLError, OSError):
            raise ModelProviderError(
                "provider_unavailable",
                "DeepSeek is temporarily unavailable. Please try again.",
                retryable=True,
            ) from None

        if not received_done or not received_text:
            raise _invalid_response_error()


def _http_error(status_code: int) -> ModelProviderError:
    if status_code == 401:
        return ModelProviderError(
            "provider_authentication_failed",
            "DeepSeek authentication failed. Check the server configuration.",
            retryable=False,
        )
    if status_code == 402:
        return ModelProviderError(
            "provider_balance_exhausted",
            "The DeepSeek account has insufficient balance.",
            retryable=False,
        )
    if status_code == 429:
        return ModelProviderError(
            "provider_rate_limited",
            "DeepSeek is receiving too many requests. Please retry shortly.",
            retryable=True,
        )
    if status_code in {500, 503}:
        return ModelProviderError(
            "provider_unavailable",
            "DeepSeek is temporarily unavailable. Please try again.",
            retryable=True,
        )
    if status_code in {400, 422}:
        return ModelProviderError(
            "provider_request_rejected",
            "DeepSeek rejected the model request.",
            retryable=False,
        )
    return ModelProviderError(
        "provider_request_failed",
        "DeepSeek could not complete the model request.",
        retryable=status_code >= 500,
    )


def _invalid_response_error() -> ModelProviderError:
    return ModelProviderError(
        "provider_invalid_response",
        "DeepSeek returned an incomplete response. Please try again.",
        retryable=True,
    )
