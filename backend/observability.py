"""Structured JSON logging without prompts, file contents, or credentials."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


LOGGER_NAME = "mind.api"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO", quiet: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.CRITICAL + 1 if quiet else level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def log_event(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.INFO,
    **event_data: Any,
) -> None:
    logger.log(level, message, extra={"event_data": event_data})
