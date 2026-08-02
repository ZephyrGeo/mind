# Mind API

The FastAPI service exposes a typed, streaming contract while the model
provider remains the deterministic, zero-cost Fake Provider.

Interactive documentation is available while the API is running:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

## Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | Public | Runtime, environment, provider, and billing status |
| `GET` | `/api/conversations` | Local bearer token | Conversation summaries for the current user |
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

`mode` accepts `chat` or `research`. Research remains a simulation until the
checkpointed workflow and search tools are implemented. Attachment entries only
carry staged filename and size metadata; no file content is uploaded yet.

## Streaming response

Text is sent as ordered SSE frames:

```text
data: {"type":"delta","delta":"I’m "}

data: {"type":"delta","delta":"Mind’s "}

data: {"type":"done","conversation_id":"...","request_id":"..."}
```

If generation fails after streaming has begun, the final frame has
`"type":"error"`. HTTP validation and authentication errors use the standard
JSON envelope below.

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

`ModelProvider` owns model streaming. `FakeAgentProvider` is its current
implementation and declares that it makes no billable model calls.

`ConversationRepository` owns tenant-scoped conversation reads and atomic
exchange writes. `JsonConversationRepository` is the current ignored local
implementation. Firestore can replace it without changing route handlers.

The shared Pydantic models define `User`, `Conversation`, `Message`,
`Attachment`, `ResearchJob`, `Memory`, `Routine`, and `ToolCall` before their
production repositories and endpoints are implemented.

