"""Runtime configuration with production-safe defaults and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "work" / "local-data" / "conversations.json"
DEFAULT_RESEARCH_DATA_PATH = (
    PROJECT_ROOT / "work" / "local-data" / "research-jobs.json"
)
DEFAULT_LOCAL_TOKEN = "local-demo-token"
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_RESEARCH_MODEL = "gpt-5.6-terra"


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated application settings.

    Staging and production deliberately reject the milestone-one local token.
    Firebase authentication will replace that token in the next milestone.
    """

    environment: str = "development"
    local_token: str = DEFAULT_LOCAL_TOKEN
    data_path: Path = DEFAULT_DATA_PATH
    research_data_path: Path = DEFAULT_RESEARCH_DATA_PATH
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_ALLOWED_ORIGINS
    )
    max_request_bytes: int = 64_000
    max_context_characters: int = 64_000
    host: str = "127.0.0.1"
    port: int = 8000
    provider: str = "fake"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    deepseek_timeout_seconds: float = 120.0
    deepseek_max_tokens: int = 2_048
    research_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    research_model: str = DEFAULT_RESEARCH_MODEL
    research_reasoning_effort: str = "high"
    research_max_tool_calls: int = 12
    research_poll_interval_seconds: float = 2.0
    openai_timeout_seconds: float = 120.0
    log_level: str = "INFO"
    quiet: bool = False

    def __post_init__(self) -> None:
        environment = self.environment.lower()
        if environment not in {"development", "test", "staging", "production"}:
            raise ValueError(f"Unsupported MIND_ENV: {self.environment}")
        if self.max_request_bytes < 1:
            raise ValueError("MIND_MAX_REQUEST_BYTES must be positive.")
        if self.max_context_characters < 1:
            raise ValueError("MIND_MAX_CONTEXT_CHARACTERS must be positive.")
        if not 1 <= self.port <= 65_535:
            raise ValueError("MIND_API_PORT must be between 1 and 65535.")
        if self.provider not in {"fake", "deepseek"}:
            raise ValueError("MIND_MODEL_PROVIDER must be fake or deepseek.")
        if self.provider == "deepseek" and not (
            self.deepseek_api_key and self.deepseek_api_key.strip()
        ):
            raise ValueError(
                "DEEPSEEK_API_KEY is required when MIND_MODEL_PROVIDER=deepseek."
            )
        parsed_base_url = urlsplit(self.deepseek_base_url)
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username
            or parsed_base_url.password
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError(
                "MIND_DEEPSEEK_BASE_URL must be an HTTPS origin without "
                "credentials, query parameters, or fragments."
            )
        if not self.deepseek_model or any(
            character.isspace() for character in self.deepseek_model
        ):
            raise ValueError("MIND_DEEPSEEK_MODEL must be a non-empty model ID.")
        if self.deepseek_timeout_seconds <= 0:
            raise ValueError("MIND_DEEPSEEK_TIMEOUT_SECONDS must be positive.")
        if self.deepseek_max_tokens < 1:
            raise ValueError("MIND_DEEPSEEK_MAX_TOKENS must be positive.")
        if self.research_provider != "openai":
            raise ValueError("MIND_RESEARCH_PROVIDER must be openai.")
        parsed_openai_url = urlsplit(self.openai_base_url)
        if (
            parsed_openai_url.scheme != "https"
            or not parsed_openai_url.hostname
            or parsed_openai_url.username
            or parsed_openai_url.password
            or parsed_openai_url.query
            or parsed_openai_url.fragment
        ):
            raise ValueError(
                "MIND_OPENAI_BASE_URL must be an HTTPS origin without "
                "credentials, query parameters, or fragments."
            )
        if not self.research_model or any(
            character.isspace() for character in self.research_model
        ):
            raise ValueError("MIND_RESEARCH_MODEL must be a non-empty model ID.")
        if self.research_reasoning_effort not in {
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("MIND_RESEARCH_REASONING_EFFORT is unsupported.")
        if self.research_max_tool_calls < 1:
            raise ValueError("MIND_RESEARCH_MAX_TOOL_CALLS must be positive.")
        if self.research_poll_interval_seconds <= 0:
            raise ValueError(
                "MIND_RESEARCH_POLL_INTERVAL_SECONDS must be positive."
            )
        if self.openai_timeout_seconds <= 0:
            raise ValueError("MIND_OPENAI_TIMEOUT_SECONDS must be positive.")
        if environment in {"staging", "production"}:
            if self.local_token == DEFAULT_LOCAL_TOKEN:
                raise ValueError(
                    "The local development token cannot be used outside development or test."
                )
            if not self.allowed_origins:
                raise ValueError("At least one CORS origin is required.")
            if not (self.openai_api_key and self.openai_api_key.strip()):
                raise ValueError(
                    "OPENAI_API_KEY is required outside development or test."
                )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            environment=os.environ.get("MIND_ENV", "development"),
            local_token=os.environ.get("MIND_LOCAL_TOKEN", DEFAULT_LOCAL_TOKEN),
            data_path=Path(
                os.environ.get("MIND_DATA_PATH", str(DEFAULT_DATA_PATH))
            ),
            research_data_path=Path(
                os.environ.get(
                    "MIND_RESEARCH_DATA_PATH",
                    str(DEFAULT_RESEARCH_DATA_PATH),
                )
            ),
            allowed_origins=_csv(
                os.environ.get("MIND_ALLOWED_ORIGINS"),
                DEFAULT_ALLOWED_ORIGINS,
            ),
            max_request_bytes=int(
                os.environ.get("MIND_MAX_REQUEST_BYTES", "64000")
            ),
            max_context_characters=int(
                os.environ.get("MIND_MAX_CONTEXT_CHARACTERS", "64000")
            ),
            host=os.environ.get("MIND_API_HOST", "127.0.0.1"),
            port=int(os.environ.get("MIND_API_PORT", "8000")),
            provider=os.environ.get("MIND_MODEL_PROVIDER", "fake"),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY"),
            deepseek_base_url=os.environ.get(
                "MIND_DEEPSEEK_BASE_URL",
                DEFAULT_DEEPSEEK_BASE_URL,
            ),
            deepseek_model=os.environ.get(
                "MIND_DEEPSEEK_MODEL",
                DEFAULT_DEEPSEEK_MODEL,
            ),
            deepseek_timeout_seconds=float(
                os.environ.get("MIND_DEEPSEEK_TIMEOUT_SECONDS", "120")
            ),
            deepseek_max_tokens=int(
                os.environ.get("MIND_DEEPSEEK_MAX_TOKENS", "2048")
            ),
            research_provider=os.environ.get(
                "MIND_RESEARCH_PROVIDER",
                "openai",
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_base_url=os.environ.get(
                "MIND_OPENAI_BASE_URL",
                DEFAULT_OPENAI_BASE_URL,
            ),
            research_model=os.environ.get(
                "MIND_RESEARCH_MODEL",
                DEFAULT_RESEARCH_MODEL,
            ),
            research_reasoning_effort=os.environ.get(
                "MIND_RESEARCH_REASONING_EFFORT",
                "high",
            ),
            research_max_tool_calls=int(
                os.environ.get("MIND_RESEARCH_MAX_TOOL_CALLS", "12")
            ),
            research_poll_interval_seconds=float(
                os.environ.get("MIND_RESEARCH_POLL_INTERVAL_SECONDS", "2")
            ),
            openai_timeout_seconds=float(
                os.environ.get("MIND_OPENAI_TIMEOUT_SECONDS", "120")
            ),
            log_level=os.environ.get("MIND_LOG_LEVEL", "INFO"),
            quiet=os.environ.get("MIND_QUIET") == "1",
        )
