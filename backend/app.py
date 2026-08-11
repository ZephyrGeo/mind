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
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import DEFAULT_LOCAL_TOKEN, Settings
from .conversation_context import select_recent_history
from .deepseek_provider import DeepSeekProvider
from .errors import APIError
from .fake_agent import FakeAgentProvider
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
)
from .observability import configure_logging, log_event
from .repositories import ConversationRepository
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
) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    runtime_repository = repository or JsonConversationRepository(
        runtime_settings.data_path
    )
    runtime_provider = provider or create_model_provider(runtime_settings)
    logger = configure_logging(
        runtime_settings.log_level,
        runtime_settings.quiet,
    )

    application = FastAPI(
        title="Mind Personal Agent API",
        summary="Streaming API and replaceable Agent Kernel boundaries.",
        description=(
            "Mind exposes local and hosted ModelProvider implementations through "
            "the same typed interface, with explicit billing and failure signals."
        ),
        version="0.5.0",
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
    application.state.logger = logger

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

    async def require_local_principal(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme),
        ],
    ) -> LocalPrincipal:
        if credentials is None or not hmac.compare_digest(
            credentials.credentials,
            runtime_settings.local_token,
        ):
            raise APIError(
                status_code=401,
                code="authentication_required",
                message="A valid local token is required.",
            )
        return LocalPrincipal(user_id=LOCAL_USER_ID)

    Principal = Annotated[LocalPrincipal, Depends(require_local_principal)]

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
        },
        tags=["conversations"],
        operation_id="deleteConversation",
    )
    async def delete_conversation(
        conversation_id: uuid.UUID,
        principal: Principal,
    ) -> Response:
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
        return Response(status_code=204)

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
