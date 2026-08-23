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
DEFAULT_MEMORY_DATA_PATH = PROJECT_ROOT / "work" / "local-data" / "memories.json"
DEFAULT_ATTACHMENT_DATA_PATH = (
    PROJECT_ROOT / "work" / "local-data" / "attachments.json"
)
DEFAULT_USAGE_DATA_PATH = PROJECT_ROOT / "work" / "local-data" / "usage.json"
DEFAULT_LOCAL_FILE_PATH = PROJECT_ROOT / "work" / "local-files"
DEFAULT_LOCAL_TOKEN = "local-demo-token"
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_RESEARCH_MODEL = "gpt-5.6-terra"
DEFAULT_MEMORY_MODEL = "gpt-5.4-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


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
    memory_data_path: Path = DEFAULT_MEMORY_DATA_PATH
    attachment_data_path: Path = DEFAULT_ATTACHMENT_DATA_PATH
    usage_data_path: Path = DEFAULT_USAGE_DATA_PATH
    file_storage_provider: str = "local"
    local_file_path: Path = DEFAULT_LOCAL_FILE_PATH
    file_storage_bucket: str | None = None
    max_file_bytes: int = 20_000_000
    max_file_pages: int = 200
    max_extracted_file_characters: int = 120_000
    max_file_context_characters: int = 24_000
    max_files_per_request: int = 5
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_ALLOWED_ORIGINS
    )
    max_request_bytes: int = 64_000
    max_context_characters: int = 64_000
    chat_daily_limit: int = 30
    research_daily_limit: int = 2
    research_max_active_per_user: int = 1
    memory_retrieval_limit: int = 5
    memory_max_context_characters: int = 4_000
    memory_provider: str = "rules"
    memory_model: str = DEFAULT_MEMORY_MODEL
    memory_reasoning_effort: str = "low"
    memory_timeout_seconds: float = 45.0
    embedding_provider: str = "local"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = 256
    memory_semantic_threshold: float = 0.68
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
    research_soft_timeout_seconds: int = 420
    research_job_timeout_seconds: int = 600
    research_max_concurrent_searches: int = 2
    research_max_transport_retries: int = 5
    research_max_rate_limit_retries: int = 3
    research_max_stage_attempts: int = 2
    research_retry_base_seconds: float = 2.0
    research_max_evidence_characters: int = 60_000
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
        if self.file_storage_provider not in {"local", "gcs"}:
            raise ValueError("MIND_FILE_STORAGE_PROVIDER must be local or gcs.")
        if self.file_storage_provider == "gcs" and not (
            self.file_storage_bucket and self.file_storage_bucket.strip()
        ):
            raise ValueError(
                "MIND_FILE_STORAGE_BUCKET is required with GCS file storage."
            )
        if not 1 <= self.max_file_bytes <= 20_000_000:
            raise ValueError("MIND_MAX_FILE_BYTES must be between 1 and 20000000.")
        if not 1 <= self.max_file_pages <= 500:
            raise ValueError("MIND_MAX_FILE_PAGES must be between 1 and 500.")
        if not 1_000 <= self.max_extracted_file_characters <= 500_000:
            raise ValueError(
                "MIND_MAX_EXTRACTED_FILE_CHARACTERS must be between 1000 and 500000."
            )
        if not 1_000 <= self.max_file_context_characters <= 64_000:
            raise ValueError(
                "MIND_MAX_FILE_CONTEXT_CHARACTERS must be between 1000 and 64000."
            )
        if not 1 <= self.max_files_per_request <= 10:
            raise ValueError("MIND_MAX_FILES_PER_REQUEST must be between 1 and 10.")
        if self.account_deletion_max_auth_age_seconds < 1:
            raise ValueError(
                "MIND_ACCOUNT_DELETION_MAX_AUTH_AGE_SECONDS must be positive."
            )
        if self.max_request_bytes < 1:
            raise ValueError("MIND_MAX_REQUEST_BYTES must be positive.")
        if self.max_context_characters < 1:
            raise ValueError("MIND_MAX_CONTEXT_CHARACTERS must be positive.")
        if not 1 <= self.chat_daily_limit <= 10_000:
            raise ValueError("MIND_CHAT_DAILY_LIMIT must be between 1 and 10000.")
        if not 1 <= self.research_daily_limit <= 100:
            raise ValueError("MIND_RESEARCH_DAILY_LIMIT must be between 1 and 100.")
        if not 1 <= self.research_max_active_per_user <= 10:
            raise ValueError(
                "MIND_RESEARCH_MAX_ACTIVE_PER_USER must be between 1 and 10."
            )
        if not 1 <= self.memory_retrieval_limit <= 20:
            raise ValueError("MIND_MEMORY_RETRIEVAL_LIMIT must be between 1 and 20.")
        if not 256 <= self.memory_max_context_characters <= 16_000:
            raise ValueError(
                "MIND_MEMORY_MAX_CONTEXT_CHARACTERS must be between 256 and 16000."
            )
        if self.memory_provider not in {"rules", "openai"}:
            raise ValueError("MIND_MEMORY_PROVIDER must be rules or openai.")
        if self.embedding_provider not in {"local", "openai"}:
            raise ValueError("MIND_EMBEDDING_PROVIDER must be local or openai.")
        if not self.memory_model or any(
            character.isspace() for character in self.memory_model
        ):
            raise ValueError("MIND_MEMORY_MODEL must be a non-empty model ID.")
        if self.memory_reasoning_effort not in {"none", "low", "medium", "high"}:
            raise ValueError("MIND_MEMORY_REASONING_EFFORT is unsupported.")
        if self.memory_timeout_seconds <= 0:
            raise ValueError("MIND_MEMORY_TIMEOUT_SECONDS must be positive.")
        if not self.embedding_model or any(
            character.isspace() for character in self.embedding_model
        ):
            raise ValueError("MIND_EMBEDDING_MODEL must be a non-empty model ID.")
        if not 32 <= self.embedding_dimensions <= 2_048:
            raise ValueError(
                "MIND_EMBEDDING_DIMENSIONS must be between 32 and 2048."
            )
        if not 0 <= self.memory_semantic_threshold <= 1:
            raise ValueError(
                "MIND_MEMORY_SEMANTIC_THRESHOLD must be between 0 and 1."
            )
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
        if not (
            1
            <= self.research_soft_timeout_seconds
            < self.research_job_timeout_seconds
        ):
            raise ValueError(
                "MIND_RESEARCH_SOFT_TIMEOUT_SECONDS must be positive and precede "
                "MIND_RESEARCH_JOB_TIMEOUT_SECONDS."
            )
        if not 1 <= self.research_max_concurrent_searches <= 8:
            raise ValueError(
                "MIND_RESEARCH_MAX_CONCURRENT_SEARCHES must be between 1 and 8."
            )
        if not 0 <= self.research_max_transport_retries <= 10:
            raise ValueError(
                "MIND_RESEARCH_MAX_TRANSPORT_RETRIES must be between 0 and 10."
            )
        if not 0 <= self.research_max_rate_limit_retries <= 10:
            raise ValueError(
                "MIND_RESEARCH_MAX_RATE_LIMIT_RETRIES must be between 0 and 10."
            )
        if not 1 <= self.research_max_stage_attempts <= 3:
            raise ValueError(
                "MIND_RESEARCH_MAX_STAGE_ATTEMPTS must be between 1 and 3."
            )
        if self.research_retry_base_seconds <= 0:
            raise ValueError(
                "MIND_RESEARCH_RETRY_BASE_SECONDS must be positive."
            )
        if not 10_000 <= self.research_max_evidence_characters <= 500_000:
            raise ValueError(
                "MIND_RESEARCH_MAX_EVIDENCE_CHARACTERS must be between 10000 "
                "and 500000."
            )
        if self.research_poll_interval_seconds <= 0:
            raise ValueError(
                "MIND_RESEARCH_POLL_INTERVAL_SECONDS must be positive."
            )
        if self.openai_timeout_seconds <= 0:
            raise ValueError("MIND_OPENAI_TIMEOUT_SECONDS must be positive.")
        if (
            self.memory_provider == "openai"
            or self.embedding_provider == "openai"
        ) and not (self.openai_api_key and self.openai_api_key.strip()):
            raise ValueError(
                "OPENAI_API_KEY is required for OpenAI Memory or Embeddings."
            )
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
            if self.memory_provider != "openai" or self.embedding_provider != "openai":
                raise ValueError(
                    "OpenAI Memory extraction and Embeddings are required outside "
                    "development or test."
                )
            if self.file_storage_provider != "gcs":
                raise ValueError(
                    "GCS file storage is required outside development or test."
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
            memory_data_path=Path(
                os.environ.get(
                    "MIND_MEMORY_DATA_PATH",
                    str(DEFAULT_MEMORY_DATA_PATH),
                )
            ),
            attachment_data_path=Path(
                os.environ.get(
                    "MIND_ATTACHMENT_DATA_PATH",
                    str(DEFAULT_ATTACHMENT_DATA_PATH),
                )
            ),
            usage_data_path=Path(
                os.environ.get(
                    "MIND_USAGE_DATA_PATH",
                    str(DEFAULT_USAGE_DATA_PATH),
                )
            ),
            file_storage_provider=os.environ.get(
                "MIND_FILE_STORAGE_PROVIDER",
                "local",
            ),
            local_file_path=Path(
                os.environ.get("MIND_LOCAL_FILE_PATH", str(DEFAULT_LOCAL_FILE_PATH))
            ),
            file_storage_bucket=os.environ.get("MIND_FILE_STORAGE_BUCKET"),
            max_file_bytes=int(
                os.environ.get("MIND_MAX_FILE_BYTES", "20000000")
            ),
            max_file_pages=int(os.environ.get("MIND_MAX_FILE_PAGES", "200")),
            max_extracted_file_characters=int(
                os.environ.get(
                    "MIND_MAX_EXTRACTED_FILE_CHARACTERS",
                    "120000",
                )
            ),
            max_file_context_characters=int(
                os.environ.get("MIND_MAX_FILE_CONTEXT_CHARACTERS", "24000")
            ),
            max_files_per_request=int(
                os.environ.get("MIND_MAX_FILES_PER_REQUEST", "5")
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
            chat_daily_limit=int(
                os.environ.get("MIND_CHAT_DAILY_LIMIT", "30")
            ),
            research_daily_limit=int(
                os.environ.get("MIND_RESEARCH_DAILY_LIMIT", "2")
            ),
            research_max_active_per_user=int(
                os.environ.get("MIND_RESEARCH_MAX_ACTIVE_PER_USER", "1")
            ),
            memory_retrieval_limit=int(
                os.environ.get("MIND_MEMORY_RETRIEVAL_LIMIT", "5")
            ),
            memory_max_context_characters=int(
                os.environ.get("MIND_MEMORY_MAX_CONTEXT_CHARACTERS", "4000")
            ),
            memory_provider=os.environ.get("MIND_MEMORY_PROVIDER", "rules"),
            memory_model=os.environ.get(
                "MIND_MEMORY_MODEL",
                DEFAULT_MEMORY_MODEL,
            ),
            memory_reasoning_effort=os.environ.get(
                "MIND_MEMORY_REASONING_EFFORT",
                "low",
            ),
            memory_timeout_seconds=float(
                os.environ.get("MIND_MEMORY_TIMEOUT_SECONDS", "45")
            ),
            embedding_provider=os.environ.get(
                "MIND_EMBEDDING_PROVIDER",
                "local",
            ),
            embedding_model=os.environ.get(
                "MIND_EMBEDDING_MODEL",
                DEFAULT_EMBEDDING_MODEL,
            ),
            embedding_dimensions=int(
                os.environ.get("MIND_EMBEDDING_DIMENSIONS", "256")
            ),
            memory_semantic_threshold=float(
                os.environ.get("MIND_MEMORY_SEMANTIC_THRESHOLD", "0.68")
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
            research_soft_timeout_seconds=int(
                os.environ.get("MIND_RESEARCH_SOFT_TIMEOUT_SECONDS", "420")
            ),
            research_job_timeout_seconds=int(
                os.environ.get("MIND_RESEARCH_JOB_TIMEOUT_SECONDS", "600")
            ),
            research_max_concurrent_searches=int(
                os.environ.get("MIND_RESEARCH_MAX_CONCURRENT_SEARCHES", "2")
            ),
            research_max_transport_retries=int(
                os.environ.get("MIND_RESEARCH_MAX_TRANSPORT_RETRIES", "5")
            ),
            research_max_rate_limit_retries=int(
                os.environ.get("MIND_RESEARCH_MAX_RATE_LIMIT_RETRIES", "3")
            ),
            research_max_stage_attempts=int(
                os.environ.get("MIND_RESEARCH_MAX_STAGE_ATTEMPTS", "2")
            ),
            research_retry_base_seconds=float(
                os.environ.get("MIND_RESEARCH_RETRY_BASE_SECONDS", "2")
            ),
            research_max_evidence_characters=int(
                os.environ.get("MIND_RESEARCH_MAX_EVIDENCE_CHARACTERS", "60000")
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
