"""Provider-neutral recovery decisions for the Research Harness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryAction(str, Enum):
    RETRY_SAME_RESPONSE = "retry_same_response"
    RETRY_START = "retry_start"
    RESTART_STAGE = "restart_stage"
    USER_ACTION_REQUIRED = "user_action_required"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str


_STAGE_RESTART_ERRORS = {
    "research_context_limit",
    "research_invalid_response",
    "research_task_empty",
    "research_report_empty",
    "research_brief_invalid",
    "research_file_analysis_invalid",
    "research_verification_invalid",
}

_TERMINAL_ERRORS = {
    "research_authentication_failed",
    "research_model_not_found",
    "research_not_configured",
    "research_quota_exhausted",
    "research_response_mismatch",
}


def classify_research_failure(
    *,
    code: str,
    retryable: bool,
    operation: str,
    has_response_id: bool,
) -> RecoveryDecision:
    """Choose recovery without exposing or depending on a concrete provider."""

    if code in _TERMINAL_ERRORS:
        return RecoveryDecision(RecoveryAction.TERMINAL, code)
    if code == "research_rate_limited":
        return RecoveryDecision(
            RecoveryAction.RETRY_SAME_RESPONSE
            if has_response_id
            else RecoveryAction.RETRY_START,
            code,
        )
    if code in _STAGE_RESTART_ERRORS or code.startswith("research_incomplete"):
        return RecoveryDecision(RecoveryAction.RESTART_STAGE, code)
    if operation == "terminal" and retryable:
        return RecoveryDecision(RecoveryAction.RESTART_STAGE, code)
    if retryable and has_response_id:
        return RecoveryDecision(RecoveryAction.RETRY_SAME_RESPONSE, code)
    if retryable and operation == "start":
        return RecoveryDecision(
            RecoveryAction.USER_ACTION_REQUIRED,
            "research_start_unknown",
        )
    return RecoveryDecision(RecoveryAction.TERMINAL, code)


def retry_delay_seconds(
    attempt: int,
    *,
    base_seconds: float,
    cap_seconds: float = 30.0,
    retry_after_seconds: float | None = None,
    jitter_key: str = "",
) -> float:
    """Return bounded exponential backoff with deterministic low jitter."""

    requested = max(0.0, retry_after_seconds or 0.0)
    exponential = min(cap_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    jitter_fraction = (sum(ord(character) for character in jitter_key) % 17) / 100
    jitter = min(1.0, exponential * jitter_fraction)
    return min(cap_seconds, max(requested, exponential) + jitter)
