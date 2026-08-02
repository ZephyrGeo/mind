"""Typed API errors that are safe to return to clients."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ErrorDetail


@dataclass(slots=True)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    details: list[ErrorDetail] = field(default_factory=list)

    def __str__(self) -> str:
        return self.message
