"""Dependency-free local HTTP API for Mind's first vertical slice."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .fake_agent import FakeAgent
from .store import ConversationStore

LOCAL_TOKEN = os.environ.get("MIND_LOCAL_TOKEN", "local-demo-token")
DEFAULT_DATA_PATH = Path(
    os.environ.get(
        "MIND_DATA_PATH",
        Path(__file__).resolve().parents[1] / "work" / "local-data" / "conversations.json",
    )
)


def is_authorized_header(value: str | None) -> bool:
    return value == f"Bearer {LOCAL_TOKEN}"


def validate_chat_payload(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    message = str(payload.get("message", "")).strip()
    if not message:
        raise ValueError("Message cannot be empty.")
    mode = "research" if payload.get("mode") == "research" else "chat"
    conversation_id = payload.get("conversation_id")
    return message, mode, str(conversation_id) if conversation_id else None


class MindServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        store: ConversationStore,
        agent: FakeAgent,
    ) -> None:
        super().__init__(server_address, MindRequestHandler)
        self.store = store
        self.agent = agent


class MindRequestHandler(BaseHTTPRequestHandler):
    server: MindServer

    def log_message(self, format_string: str, *args: Any) -> None:
        if os.environ.get("MIND_QUIET") != "1":
            super().log_message(format_string, *args)

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed_origin = origin if origin in {"http://127.0.0.1:3000", "http://localhost:3000"} else "http://127.0.0.1:3000"
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_authenticated(self) -> bool:
        return is_authorized_header(self.headers.get("Authorization"))

    def _require_authentication(self) -> bool:
        if self._is_authenticated():
            return True
        self._send_json(
            HTTPStatus.UNAUTHORIZED,
            {"error": "authentication_required", "message": "A valid local token is required."},
        )
        return False

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 64_000:
            raise ValueError("Request body must be between 1 and 64000 bytes.")
        return json.loads(self.rfile.read(content_length))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "mind-local-api",
                    "provider": "fake",
                    "billable_model_calls": False,
                },
            )
            return

        if path == "/api/conversations":
            if not self._require_authentication():
                return
            self._send_json(
                HTTPStatus.OK,
                {"conversations": self.server.store.list_conversations()},
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._require_authentication():
            return

        try:
            payload = self._read_json()
            message, mode, conversation_id = validate_chat_payload(payload)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "message": str(error)},
            )
            return

        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            reply_parts: list[str] = []
            for delta in self.server.agent.stream_reply(message, mode):
                reply_parts.append(delta)
                event = json.dumps({"type": "delta", "delta": delta}, ensure_ascii=False)
                self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
                self.wfile.flush()

            stored_id = self.server.store.append_exchange(
                conversation_id,
                message,
                "".join(reply_parts),
                mode,
            )
            done_event = json.dumps(
                {"type": "done", "conversation_id": stored_id},
                ensure_ascii=False,
            )
            self.wfile.write(f"data: {done_event}\n\n".encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def create_server(
    port: int = 8000,
    data_path: str | Path = DEFAULT_DATA_PATH,
    delay_seconds: float = 0.018,
) -> MindServer:
    return MindServer(
        ("127.0.0.1", port),
        ConversationStore(data_path),
        FakeAgent(delay_seconds=delay_seconds),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mind local API.")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()

    server = create_server(port=arguments.port)
    host, port = server.server_address
    print(f"Mind API is ready at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
