# Mind API

The FastAPI service exposes a typed, streaming contract with a deterministic
Fake Provider by default and an opt-in DeepSeek Provider for real model calls.

Interactive documentation is available while the API is running:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

## Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | Public | Runtime, environment, provider, and billing status |
| `GET` | `/api/conversations` | Local bearer token | Conversation summaries for the current user |
| `GET` | `/api/conversations/{conversation_id}` | Local bearer token | Full tenant-scoped conversation for reopening and context |
| `DELETE` | `/api/conversations/{conversation_id}` | Local bearer token | Permanently delete one owned conversation; returns 204 |
| `POST` | `/api/chat` | Local bearer token | Stream an assistant response using Server-Sent Events |

The current token is only a local development boundary. It is not production
authentication and will be replaced by verified Firebase ID tokens.

## Chat request

```json
{
  "conversation_id": null,
  "message": "Explain this design.",
  "mode": "chat",
  "attachments": []
}
```

`mode` accepts `chat` or `research`. With DeepSeek enabled, research mode uses
the model's thinking mode, but the checkpointed workflow and search tools are
not implemented yet. Attachment entries only carry staged filename and size
metadata; no file content is uploaded yet.

## Streaming response

Text is sent as ordered SSE frames:

```text
data: {"type":"delta","delta":"I’m "}

data: {"type":"delta","delta":"Mind’s "}

data: {"type":"done","conversation_id":"...","request_id":"..."}
```

If generation fails after streaming has begun, the final frame has
`"type":"error"`. Provider failures include a stable `code` and `retryable`
boolean. HTTP validation and authentication errors use the standard JSON
envelope below.

```text
data: {"type":"error","code":"provider_rate_limited","message":"...","retryable":true,"request_id":"..."}
```

## Error envelope

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request did not match the API schema.",
    "request_id": "3b326622-2520-42ec-930b-d6d53c98e976",
    "details": [
      {
        "location": ["body", "message"],
        "message": "Value error, Message cannot be empty.",
        "type": "value_error"
      }
    ]
  }
}
```

Every HTTP response includes `X-Request-ID`. A caller-provided request ID is
accepted only when it contains 1–128 alphanumeric characters, dots, underscores,
or hyphens.

## Architecture boundaries

`ModelProvider` owns model streaming. `FakeAgentProvider` declares that it makes
no billable calls. `DeepSeekProvider` uses the OpenAI-compatible streaming Chat
Completions endpoint and declares that calls are billable. The health endpoint
lets the UI display this distinction before a message is sent.

Chat mode disables DeepSeek thinking for lower latency. Research mode enables
thinking but streams only final answer content; reasoning content is not exposed
or persisted. For an existing conversation, Mind reads complete persisted turns,
keeps the newest turns that fit `MIND_MAX_CONTEXT_CHARACTERS`, and sends them in
user/assistant order before the new user message. The limit includes the new
message and prevents history from growing model cost without bound.

The wire format and current model IDs follow the
[official DeepSeek Chat Completions documentation](https://api-docs.deepseek.com/api/create-chat-completion).

`ConversationRepository` owns tenant-scoped conversation reads and atomic
exchange writes. `JsonConversationRepository` is the current ignored local
implementation. The detail endpoint and model-context lookup return the same 404
for missing and cross-tenant IDs. Firestore can replace the repository without
changing route handlers.

Milestone-one local JSON records are normalized in memory when read, so older
conversations that predate typed message IDs and tenant fields remain openable.
The compatibility read does not rewrite the local data file.

Deletion is permanent and atomically rewrites the local repository only after
ownership is verified. Missing and cross-tenant IDs both return
`conversation_not_found`; the frontend requires an explicit confirmation before
calling the endpoint.

The shared Pydantic models define `User`, `Conversation`, `Message`,
`Attachment`, `ResearchJob`, `Memory`, `Routine`, and `ToolCall` before their
production repositories and endpoints are implemented.
