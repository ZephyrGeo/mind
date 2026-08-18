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

    Staging and production reject local identity and persistence fallbacks.
    """

    environment: str = "development"
    auth_provider: str = "local"
    local_token: str = DEFAULT_LOCAL_TOKEN
    firebase_project_id: str | None = None
    allowed_user_emails: tuple[str, ...] = field(default_factory=tuple)
    require_verified_email: bool = False
    firebase_check_revoked: bool = True
    account_deletion_max_auth_age_seconds: int = 600
    persistence_provider: str = "json"
    firestore_database_id: str = "(default)"
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
    research_max_search_rounds: int = 2
    research_max_subquestions: int = 6
    research_max_total_tool_calls: int = 24
    research_tool_call_overrun_ratio: float = 0.15
    research_max_tool_call_overrun: int = 3
    research_min_citation_coverage: float = 0.8
    research_job_timeout_seconds: int = 600
    research_poll_interval_seconds: float = 2.0
    openai_timeout_seconds: float = 120.0
    log_level: str = "INFO"
    quiet: bool = False

    def __post_init__(self) -> None:
        environment = self.environment.lower()
        if environment not in {"development", "test", "staging", "production"}:
            raise ValueError(f"Unsupported MIND_ENV: {self.environment}")
        if self.auth_provider not in {"local", "firebase"}:
            raise ValueError("MIND_AUTH_PROVIDER must be local or firebase.")
        if self.auth_provider == "firebase" and not (
            self.firebase_project_id and self.firebase_project_id.strip()
        ):
            raise ValueError(
                "MIND_FIREBASE_PROJECT_ID is required for Firebase authentication."
            )
        if self.persistence_provider not in {"json", "firestore"}:
            raise ValueError(
                "MIND_PERSISTENCE_PROVIDER must be json or firestore."
            )
        if self.persistence_provider == "firestore" and not (
            self.firebase_project_id and self.firebase_project_id.strip()
        ):
            raise ValueError(
                "MIND_FIREBASE_PROJECT_ID is required for Firestore persistence."
            )
        if self.account_deletion_max_auth_age_seconds < 1:
            raise ValueError(
                "MIND_ACCOUNT_DELETION_MAX_AUTH_AGE_SECONDS must be positive."
            )
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
        if not 1 <= self.research_max_search_rounds <= 2:
            raise ValueError("MIND_RESEARCH_MAX_SEARCH_ROUNDS must be 1 or 2.")
        if not 4 <= self.research_max_subquestions <= 8:
            raise ValueError("MIND_RESEARCH_MAX_SUBQUESTIONS must be between 4 and 8.")
        if self.research_max_total_tool_calls < self.research_max_subquestions:
            raise ValueError(
                "MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS must cover every subquestion."
            )
        if not 0 <= self.research_tool_call_overrun_ratio <= 0.5:
            raise ValueError(
                "MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO must be between 0 and 0.5."
            )
        if not 0 <= self.research_max_tool_call_overrun <= 20:
            raise ValueError(
                "MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN must be between 0 and 20."
            )
        if not 0 <= self.research_min_citation_coverage <= 1:
            raise ValueError(
                "MIND_RESEARCH_MIN_CITATION_COVERAGE must be between 0 and 1."
            )
        if not 60 <= self.research_job_timeout_seconds <= 3_600:
            raise ValueError(
                "MIND_RESEARCH_JOB_TIMEOUT_SECONDS must be between 60 and 3600."
            )
        if self.research_poll_interval_seconds <= 0:
            raise ValueError(
                "MIND_RESEARCH_POLL_INTERVAL_SECONDS must be positive."
            )
        if self.openai_timeout_seconds <= 0:
            raise ValueError("MIND_OPENAI_TIMEOUT_SECONDS must be positive.")
        if environment in {"staging", "production"}:
            if self.auth_provider != "firebase":
                raise ValueError(
                    "Firebase authentication is required outside development or test."
                )
            if not self.allowed_user_emails:
                raise ValueError(
                    "MIND_ALLOWED_USER_EMAILS is required for restricted access."
                )
            if self.persistence_provider != "firestore":
                raise ValueError(
                    "Firestore persistence is required outside development or test."
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
            auth_provider=os.environ.get("MIND_AUTH_PROVIDER", "local"),
            local_token=os.environ.get("MIND_LOCAL_TOKEN", DEFAULT_LOCAL_TOKEN),
            firebase_project_id=os.environ.get("MIND_FIREBASE_PROJECT_ID"),
            allowed_user_emails=_csv(
                os.environ.get("MIND_ALLOWED_USER_EMAILS"),
                (),
            ),
            require_verified_email=(
                os.environ.get("MIND_REQUIRE_VERIFIED_EMAIL", "0") == "1"
            ),
            firebase_check_revoked=(
                os.environ.get("MIND_FIREBASE_CHECK_REVOKED", "1") == "1"
            ),
            account_deletion_max_auth_age_seconds=int(
                os.environ.get(
                    "MIND_ACCOUNT_DELETION_MAX_AUTH_AGE_SECONDS",
                    "600",
                )
            ),
            persistence_provider=os.environ.get(
                "MIND_PERSISTENCE_PROVIDER",
                "json",
            ),
            firestore_database_id=os.environ.get(
                "MIND_FIRESTORE_DATABASE_ID",
                "(default)",
            ),
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
            research_max_search_rounds=int(
                os.environ.get("MIND_RESEARCH_MAX_SEARCH_ROUNDS", "2")
            ),
            research_max_subquestions=int(
                os.environ.get("MIND_RESEARCH_MAX_SUBQUESTIONS", "6")
            ),
            research_max_total_tool_calls=int(
                os.environ.get("MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS", "24")
            ),
            research_tool_call_overrun_ratio=float(
                os.environ.get("MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO", "0.15")
            ),
            research_max_tool_call_overrun=int(
                os.environ.get("MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN", "3")
            ),
            research_min_citation_coverage=float(
                os.environ.get("MIND_RESEARCH_MIN_CITATION_COVERAGE", "0.8")
            ),
            research_job_timeout_seconds=int(
                os.environ.get("MIND_RESEARCH_JOB_TIMEOUT_SECONDS", "600")
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
