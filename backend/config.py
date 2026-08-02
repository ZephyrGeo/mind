"""Runtime configuration with production-safe defaults and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "work" / "local-data" / "conversations.json"
DEFAULT_LOCAL_TOKEN = "local-demo-token"
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


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
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_ALLOWED_ORIGINS
    )
    max_request_bytes: int = 64_000
    host: str = "127.0.0.1"
    port: int = 8000
    provider: str = "fake"
    log_level: str = "INFO"
    quiet: bool = False

    def __post_init__(self) -> None:
        environment = self.environment.lower()
        if environment not in {"development", "test", "staging", "production"}:
            raise ValueError(f"Unsupported MIND_ENV: {self.environment}")
        if self.max_request_bytes < 1:
            raise ValueError("MIND_MAX_REQUEST_BYTES must be positive.")
        if not 1 <= self.port <= 65_535:
            raise ValueError("MIND_API_PORT must be between 1 and 65535.")
        if self.provider != "fake":
            raise ValueError(
                "Only the zero-cost fake provider is available in milestone 2."
            )
        if environment in {"staging", "production"}:
            if self.local_token == DEFAULT_LOCAL_TOKEN:
                raise ValueError(
                    "The local development token cannot be used outside development or test."
                )
            if not self.allowed_origins:
                raise ValueError("At least one CORS origin is required.")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            environment=os.environ.get("MIND_ENV", "development"),
            local_token=os.environ.get("MIND_LOCAL_TOKEN", DEFAULT_LOCAL_TOKEN),
            data_path=Path(
                os.environ.get("MIND_DATA_PATH", str(DEFAULT_DATA_PATH))
            ),
            allowed_origins=_csv(
                os.environ.get("MIND_ALLOWED_ORIGINS"),
                DEFAULT_ALLOWED_ORIGINS,
            ),
            max_request_bytes=int(
                os.environ.get("MIND_MAX_REQUEST_BYTES", "64000")
            ),
            host=os.environ.get("MIND_API_HOST", "127.0.0.1"),
            port=int(os.environ.get("MIND_API_PORT", "8000")),
            provider=os.environ.get("MIND_MODEL_PROVIDER", "fake"),
            log_level=os.environ.get("MIND_LOG_LEVEL", "INFO"),
            quiet=os.environ.get("MIND_QUIET") == "1",
        )
