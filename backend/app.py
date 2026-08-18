"""FastAPI application for Mind's replaceable Agent Kernel foundation."""

import argparse
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import DEFAULT_LOCAL_TOKEN, Settings
from .auth import (
    AccountManager,
    FirebasePrincipalVerifier,
    IdentityVerificationError,
    LocalAccountManager,
    LocalTokenPrincipalVerifier,
    PrincipalVerifier,
)
from .conversation_context import select_recent_history
from .deepseek_provider import DeepSeekProvider
from .errors import APIError
from .fake_agent import FakeAgentProvider
from .firestore_store import (
    FirestoreConversationRepository,
    FirestoreResearchRepository,
)
from .model_provider import ModelProvider, ModelProviderError
from .models import (
    ChatRequest,
    Conversation,
    ConversationsResponse,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    LocalPrincipal,
    ResearchJob,
    ResearchRequest,
)
from .observability import configure_logging, log_event
from .openai_research_provider import OpenAIResearchProvider
from .repositories import ConversationRepository
from .research_provider import ResearchProvider, ResearchProviderError
from .research_repositories import ResearchRepository
from .research_service import (
    ResearchJobConflictError,
    ResearchService,
)
from .research_store import JsonResearchRepository, ResearchJobNotFoundError
from .store import (
    LOCAL_USER_ID,
    ConversationNotFoundError,
    JsonConversationRepository,
)


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
LOCAL_TOKEN = DEFAULT_LOCAL_TOKEN
bearer_scheme = HTTPBearer(auto_error=False)


def create_model_provider(settings: Settings) -> ModelProvider:
    """Build the configured provider without making a model request."""

    if settings.provider == "fake":
        return FakeAgentProvider()
    if settings.provider == "deepseek":
        if settings.deepseek_api_key is None:
            raise ValueError("DeepSeek API key is missing.")
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.deepseek_timeout_seconds,
            max_tokens=settings.deepseek_max_tokens,
        )
    raise ValueError(f"Unsupported model provider: {settings.provider}")


def create_research_provider(settings: Settings) -> ResearchProvider:
    """Build the sole production ResearchProvider without making a request."""

    if settings.research_provider != "openai":
        raise ValueError(
            f"Unsupported research provider: {settings.research_provider}"
        )
    return OpenAIResearchProvider(
        api_key=settings.openai_api_key,
        model=settings.research_model,
        base_url=settings.openai_base_url,
        reasoning_effort=settings.research_reasoning_effort,
        max_tool_calls=settings.research_max_tool_calls,
        timeout_seconds=settings.openai_timeout_seconds,
    )


def create_principal_verifier(settings: Settings) -> PrincipalVerifier:
    """Build the configured identity boundary without handling a request."""

    if settings.auth_provider == "local":
        return LocalTokenPrincipalVerifier(
            expected_token=settings.local_token,
            user_id=LOCAL_USER_ID,
        )
    if settings.auth_provider == "firebase":
        if settings.firebase_project_id is None:
            raise ValueError("Firebase project ID is missing.")
        return FirebasePrincipalVerifier(
            project_id=settings.firebase_project_id,
            allowed_user_emails=settings.allowed_user_emails,
            require_verified_email=settings.require_verified_email,
            check_revoked=settings.firebase_check_revoked,
        )
    raise ValueError(f"Unsupported auth provider: {settings.auth_provider}")


def create_conversation_repository(settings: Settings) -> ConversationRepository:
    """Build local JSON or production Firestore persistence."""

    if settings.persistence_provider == "json":
        return JsonConversationRepository(settings.data_path)
    if settings.persistence_provider == "firestore":
        if settings.firebase_project_id is None:
            raise ValueError("Firebase project ID is missing.")
        return FirestoreConversationRepository(
            project_id=settings.firebase_project_id,
            database_id=settings.firestore_database_id,
        )
    raise ValueError(
        f"Unsupported persistence provider: {settings.persistence_provider}"
    )


def create_research_repository(settings: Settings) -> ResearchRepository:
    """Build local JSON or production Firestore Research persistence."""

    if settings.persistence_provider == "json":
        return JsonResearchRepository(settings.research_data_path)
    if settings.persistence_provider == "firestore":
        if settings.firebase_project_id is None:
            raise ValueError("Firebase project ID is missing.")
        return FirestoreResearchRepository(
            project_id=settings.firebase_project_id,
            database_id=settings.firestore_database_id,
        )
    raise ValueError(
        f"Unsupported persistence provider: {settings.persistence_provider}"
    )


def create_account_manager(
    settings: Settings,
    principal_verifier: PrincipalVerifier,
) -> AccountManager:
    """Build the account-lifecycle boundary for the configured identity mode."""

    if settings.auth_provider == "local":
        return LocalAccountManager()
    delete_user = getattr(principal_verifier, "delete_user", None)
    if settings.auth_provider == "firebase" and callable(delete_user):
        return principal_verifier  # type: ignore[return-value]
    raise ValueError("Firebase account deletion requires FirebasePrincipalVerifier.")


def is_authorized_header(
    value: str | None,
    expected_token: str = LOCAL_TOKEN,
) -> bool:
    if value is None or not value.startswith("Bearer "):
        return False
    supplied_token = value.removeprefix("Bearer ")
    return hmac.compare_digest(supplied_token, expected_token)


def validate_chat_payload(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    """Compatibility helper retained for callers of the milestone-one module."""

    request = ChatRequest.model_validate(payload)
    conversation_id = (
        str(request.conversation_id) if request.conversation_id else None
    )
    return request.message, request.mode.value, conversation_id


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=_request_id(request),
            details=details or [],
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"X-Request-ID": payload.error.request_id},
    )


def _validation_details(error: RequestValidationError) -> list[ErrorDetail]:
    return [
        ErrorDetail(
            location=list(item.get("loc", [])),
            message=item.get("msg", "Invalid value."),
            type=item.get("type", "validation_error"),
        )
        for item in error.errors()
    ]


def _sse_event(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"data: {serialized}\n\n"


def create_app(
    *,
    settings: Settings | None = None,
    repository: ConversationRepository | None = None,
    provider: ModelProvider | None = None,
    research_repository: ResearchRepository | None = None,
    research_provider: ResearchProvider | None = None,
    principal_verifier: PrincipalVerifier | None = None,
    account_manager: AccountManager | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    runtime_repository = repository or create_conversation_repository(
        runtime_settings
    )
    runtime_provider = provider or create_model_provider(runtime_settings)
    runtime_research_repository = (
        research_repository or create_research_repository(runtime_settings)
    )
    runtime_research_provider = (
        research_provider or create_research_provider(runtime_settings)
    )
    runtime_principal_verifier = (
        principal_verifier or create_principal_verifier(runtime_settings)
    )
    runtime_account_manager = account_manager or create_account_manager(
        runtime_settings,
        runtime_principal_verifier,
    )
    logger = configure_logging(
        runtime_settings.log_level,
        runtime_settings.quiet,
    )

    application = FastAPI(
        title="Mind Personal Agent API",
        summary="Streaming API and replaceable Agent Kernel boundaries.",
        description=(
            "Mind exposes replaceable Chat ModelProvider and long-running "
            "ResearchProvider boundaries with explicit billing and failure signals."
        ),
        version="0.6.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={
            "name": "Mind Personal Agent",
            "url": "https://github.com/ZephyrGeo/mind",
        },
        license_info={"name": "Private project"},
    )
    application.state.settings = runtime_settings
    application.state.repository = runtime_repository
    application.state.provider = runtime_provider
    application.state.research_repository = runtime_research_repository
    application.state.research_provider = runtime_research_provider
    application.state.principal_verifier = runtime_principal_verifier
    application.state.account_manager = runtime_account_manager
    application.state.logger = logger
    research_service = ResearchService(
        conversations=runtime_repository,
        jobs=runtime_research_repository,
        provider=runtime_research_provider,
        poll_interval_seconds=runtime_settings.research_poll_interval_seconds,
        max_search_rounds=runtime_settings.research_max_search_rounds,
        max_subquestions=runtime_settings.research_max_subquestions,
        max_total_tool_calls=runtime_settings.research_max_total_tool_calls,
        tool_call_overrun_ratio=(
            runtime_settings.research_tool_call_overrun_ratio
        ),
        max_tool_call_overrun=(
            runtime_settings.research_max_tool_call_overrun
        ),
        min_citation_coverage=(
            runtime_settings.research_min_citation_coverage
        ),
        job_timeout_seconds=runtime_settings.research_job_timeout_seconds,
        max_tool_calls_per_task=runtime_settings.research_max_tool_calls,
        logger=logger,
    )
    application.state.research_service = research_service

    @application.middleware("http")
    async def request_size_limit(request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                too_large = int(content_length) > runtime_settings.max_request_bytes
            except ValueError:
                too_large = True
            if too_large:
                response = _error_response(
                    request,
                    status_code=413,
                    code="request_too_large",
                    message=(
                        "Request body exceeds the configured "
                        f"{runtime_settings.max_request_bytes}-byte limit."
                    ),
                )
                return response
        return await call_next(request)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid.uuid4())
        )

        response = await call_next(request)

        response.headers["X-Request-ID"] = request.state.request_id
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        log_event(
            logger,
            "request_completed",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
            result_status="success" if response.status_code < 400 else "error",
        )
        return response

    @application.exception_handler(APIError)
    async def api_error_handler(request: Request, error: APIError) -> JSONResponse:
        return _error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="The request did not match the API schema.",
            details=_validation_details(error),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        code = "not_found" if error.status_code == 404 else "http_error"
        message = (
            "The requested resource was not found."
            if error.status_code == 404
            else str(error.detail)
        )
        return _error_response(
            request,
            status_code=error.status_code,
            code=code,
            message=message,
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            extra={
                "event_data": {
                    "request_id": _request_id(request),
                    "method": request.method,
                    "path": request.url.path,
                    "result_status": "error",
                }
            },
        )
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="The request could not be completed.",
        )

    async def require_principal(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme),
        ],
    ) -> LocalPrincipal:
        if credentials is None:
            raise APIError(
                status_code=401,
                code="authentication_required",
                message="A bearer token is required.",
            )
        try:
            return runtime_principal_verifier.verify(credentials.credentials)
        except IdentityVerificationError as error:
            raise APIError(
                status_code=error.status_code,
                code=error.code,
                message=error.message,
            ) from error

    Principal = Annotated[LocalPrincipal, Depends(require_principal)]

    @application.get(
        "/api/health",
        response_model=HealthResponse,
        tags=["system"],
        operation_id="getHealth",
    )
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="mind-api",
            environment=runtime_settings.environment,
            provider=runtime_provider.name,
            billable_model_calls=runtime_provider.billable_model_calls,
            research_provider=runtime_research_provider.name,
            billable_research_calls=runtime_research_provider.billable_calls,
            research_mode=(
                "live"
                if runtime_research_provider.configured
                else "unavailable"
            ),
        )

    @application.get(
        "/api/conversations",
        response_model=ConversationsResponse,
        responses={401: {"model": ErrorResponse}},
        tags=["conversations"],
        operation_id="listConversations",
    )
    async def list_conversations(principal: Principal) -> ConversationsResponse:
        return ConversationsResponse(
            conversations=runtime_repository.list_conversations(
                principal.user_id
            )
        )

    @application.get(
        "/api/conversations/{conversation_id}",
        response_model=Conversation,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
        tags=["conversations"],
        operation_id="getConversation",
    )
    async def get_conversation(
        conversation_id: uuid.UUID,
        principal: Principal,
    ) -> Conversation:
        try:
            return runtime_repository.get_conversation(
                conversation_id,
                principal.user_id,
            )
        except ConversationNotFoundError:
            raise APIError(
                status_code=404,
                code="conversation_not_found",
                message="Conversation does not exist for this user.",
            ) from None

    @application.delete(
        "/api/conversations/{conversation_id}",
        status_code=204,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["conversations"],
        operation_id="deleteConversation",
    )
    async def delete_conversation(
        conversation_id: uuid.UUID,
        principal: Principal,
    ) -> Response:
        active_statuses = {
            "queued",
            "planning",
            "collecting",
            "verifying",
            "synthesizing",
        }
        for job in runtime_research_repository.list_jobs(principal.user_id):
            if (
                job.conversation_id != conversation_id
                or job.status.value not in active_statuses
            ):
                continue
            try:
                research_service.cancel_job(job.id, principal.user_id)
            except ResearchJobConflictError:
                continue
            except ResearchProviderError as error:
                raise APIError(
                    status_code=503,
                    code="conversation_cleanup_blocked",
                    message=(
                        "Mind could not stop the active Research task. "
                        "Please retry conversation deletion."
                    ),
                ) from error
        try:
            runtime_repository.delete_conversation(
                conversation_id,
                principal.user_id,
            )
        except ConversationNotFoundError:
            raise APIError(
                status_code=404,
                code="conversation_not_found",
                message="Conversation does not exist for this user.",
            ) from None
        runtime_research_repository.delete_for_conversation(
            conversation_id,
            principal.user_id,
        )
        return Response(status_code=204)

    @application.delete(
        "/api/account",
        status_code=204,
        responses={
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["account"],
        operation_id="deleteAccount",
    )
    async def delete_account(principal: Principal) -> Response:
        if principal.authentication_method == "firebase":
            authenticated_at = principal.authenticated_at
            age_seconds = (
                (datetime.now(timezone.utc) - authenticated_at).total_seconds()
                if authenticated_at is not None
                else float("inf")
            )
            if age_seconds > runtime_settings.account_deletion_max_auth_age_seconds:
                raise APIError(
                    status_code=401,
                    code="recent_authentication_required",
                    message=(
                        "Sign out and sign in again before deleting your account."
                    ),
                )

        active_statuses = {
            "queued",
            "planning",
            "collecting",
            "verifying",
            "synthesizing",
        }
        for job in runtime_research_repository.list_jobs(principal.user_id):
            if job.status.value not in active_statuses:
                continue
            try:
                research_service.cancel_job(job.id, principal.user_id)
            except ResearchJobConflictError:
                continue
            except ResearchProviderError as error:
                raise APIError(
                    status_code=503,
                    code="account_cleanup_blocked",
                    message=(
                        "Mind could not stop an active Research task. "
                        "Please retry account deletion."
                    ),
                ) from error

        runtime_repository.delete_for_user(principal.user_id)
        runtime_research_repository.delete_for_user(principal.user_id)
        try:
            runtime_account_manager.delete_user(principal.user_id)
        except Exception as error:
            logger.exception(
                "account_identity_deletion_failed",
                extra={
                    "event_data": {
                        "user_id_hash": hashlib.sha256(
                            principal.user_id.encode("utf-8")
                        ).hexdigest()[:16],
                        "result_status": "error",
                    }
                },
            )
            raise APIError(
                status_code=503,
                code="identity_deletion_failed",
                message=(
                    "Your Mind data was removed, but the sign-in account could "
                    "not be deleted. Please retry."
                ),
            ) from error
        return Response(status_code=204)

    @application.get(
        "/api/research/{job_id}",
        response_model=ResearchJob,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
        tags=["research"],
        operation_id="getResearchJob",
    )
    async def get_research_job(
        job_id: uuid.UUID,
        principal: Principal,
    ) -> ResearchJob:
        try:
            return research_service.get_job(job_id, principal.user_id)
        except ResearchJobNotFoundError:
            raise APIError(
                status_code=404,
                code="research_job_not_found",
                message="Research job does not exist for this user.",
            ) from None

    @application.post(
        "/api/research",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Research progress, sources, and report deltas as SSE.",
                "content": {"text/event-stream": {}},
            },
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
        tags=["research"],
        operation_id="startResearch",
    )
    async def start_research(
        payload: ResearchRequest,
        principal: Principal,
        request: Request,
    ) -> StreamingResponse:
        try:
            job = research_service.start_job(payload, principal.user_id)
        except ConversationNotFoundError:
            raise APIError(
                status_code=404,
                code="conversation_not_found",
                message="Conversation does not exist for this user.",
            ) from None
        request_id = _request_id(request)

        def research_events() -> Iterator[str]:
            for event in research_service.stream_job(
                job.id,
                principal.user_id,
                request_id=request_id,
            ):
                yield _sse_event(event)

        return StreamingResponse(
            research_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.post(
        "/api/research/{job_id}/resume",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": (
                    "Continue the saved OpenAI Response or start a new one after "
                    "a terminal failure or cancellation."
                ),
                "content": {"text/event-stream": {}},
            },
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
        tags=["research"],
        operation_id="resumeResearch",
    )
    async def resume_research(
        job_id: uuid.UUID,
        principal: Principal,
        request: Request,
    ) -> StreamingResponse:
        try:
            job = research_service.prepare_resume(job_id, principal.user_id)
        except ResearchJobNotFoundError:
            raise APIError(
                status_code=404,
                code="research_job_not_found",
                message="Research job does not exist for this user.",
            ) from None
        except ResearchJobConflictError as error:
            raise APIError(
                status_code=409,
                code="research_job_conflict",
                message=str(error),
            ) from None
        except ResearchProviderError as error:
            raise APIError(
                status_code=503 if error.retryable else 502,
                code=error.code,
                message=error.public_message,
            ) from None
        request_id = _request_id(request)

        def research_events() -> Iterator[str]:
            for event in research_service.stream_job(
                job.id,
                principal.user_id,
                request_id=request_id,
            ):
                yield _sse_event(event)

        return StreamingResponse(
            research_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.post(
        "/api/research/{job_id}/cancel",
        response_model=ResearchJob,
        responses={
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
        tags=["research"],
        operation_id="cancelResearch",
    )
    async def cancel_research(
        job_id: uuid.UUID,
        principal: Principal,
    ) -> ResearchJob:
        try:
            return research_service.cancel_job(job_id, principal.user_id)
        except ResearchJobNotFoundError:
            raise APIError(
                status_code=404,
                code="research_job_not_found",
                message="Research job does not exist for this user.",
            ) from None
        except ResearchJobConflictError as error:
            raise APIError(
                status_code=409,
                code="research_job_conflict",
                message=str(error),
            ) from None
        except ResearchProviderError as error:
            raise APIError(
                status_code=503 if error.retryable else 502,
                code=error.code,
                message=error.public_message,
            ) from None

    @application.post(
        "/api/chat",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Ordered Server-Sent Events containing text deltas.",
                "content": {"text/event-stream": {}},
            },
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
        tags=["conversations"],
        operation_id="streamChat",
    )
    async def chat(
        payload: ChatRequest,
        principal: Principal,
        request: Request,
    ) -> StreamingResponse:
        request_id = _request_id(request)
        user_id_hash = hashlib.sha256(
            principal.user_id.encode("utf-8")
        ).hexdigest()[:16]

        def event_stream() -> Iterator[str]:
            reply_parts: list[str] = []
            try:
                history = []
                if payload.conversation_id is not None:
                    conversation = runtime_repository.get_conversation(
                        payload.conversation_id,
                        principal.user_id,
                    )
                    history = select_recent_history(
                        conversation.messages,
                        max_characters=max(
                            0,
                            runtime_settings.max_context_characters
                            - len(payload.message),
                        ),
                    )
                for delta in runtime_provider.stream_reply(
                    payload.message,
                    payload.mode,
                    history=history,
                ):
                    reply_parts.append(delta)
                    yield _sse_event({"type": "delta", "delta": delta})

                conversation_id = runtime_repository.append_exchange(
                    payload.conversation_id,
                    payload.message,
                    "".join(reply_parts),
                    payload.mode,
                    user_id=principal.user_id,
                )
                log_event(
                    logger,
                    "chat_completed",
                    request_id=request_id,
                    user_id_hash=user_id_hash,
                    conversation_id=conversation_id,
                    provider=runtime_provider.name,
                    mode=payload.mode.value,
                    history_message_count=len(history),
                    history_character_count=sum(
                        len(message.content) for message in history
                    ),
                    token_usage=(
                        None if runtime_provider.billable_model_calls else 0
                    ),
                    estimated_cost=(
                        None if runtime_provider.billable_model_calls else 0
                    ),
                    result_status="success",
                )
                yield _sse_event(
                    {
                        "type": "done",
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    }
                )
            except ConversationNotFoundError:
                yield _sse_event(
                    {
                        "type": "error",
                        "code": "conversation_not_found",
                        "message": "Conversation does not exist for this user.",
                        "request_id": request_id,
                    }
                )
            except ModelProviderError as error:
                log_event(
                    logger,
                    "chat_failed",
                    level=logging.ERROR,
                    request_id=request_id,
                    user_id_hash=user_id_hash,
                    provider=runtime_provider.name,
                    provider_error_code=error.code,
                    retryable=error.retryable,
                    result_status="error",
                )
                yield _sse_event(
                    {
                        "type": "error",
                        "code": error.code,
                        "message": error.public_message,
                        "retryable": error.retryable,
                        "request_id": request_id,
                    }
                )
            except Exception:
                log_event(
                    logger,
                    "chat_failed",
                    level=logging.ERROR,
                    request_id=request_id,
                    user_id_hash=user_id_hash,
                    provider=runtime_provider.name,
                    result_status="error",
                )
                yield _sse_event(
                    {
                        "type": "error",
                        "code": "generation_failed",
                        "message": "The response could not be generated.",
                        "request_id": request_id,
                    }
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return application


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mind FastAPI service.")
    parser.add_argument("--host", default=app.state.settings.host)
    parser.add_argument("--port", type=int, default=app.state.settings.port)
    parser.add_argument("--reload", action="store_true")
    arguments = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level=app.state.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
