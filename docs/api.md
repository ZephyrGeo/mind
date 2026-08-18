# Mind API

The FastAPI service exposes typed streaming contracts for Chat and Research.
Chat defaults to a deterministic Fake Provider and can opt in to DeepSeek;
Research uses an independent OpenAI provider.

Interactive documentation is available while the API is running:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

## Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | Public | Runtime, environment, provider, and billing status |
| `GET` | `/api/conversations` | Bearer token | Conversation summaries for the current user |
| `GET` | `/api/conversations/{conversation_id}` | Bearer token | Full tenant-scoped conversation for reopening and context |
| `DELETE` | `/api/conversations/{conversation_id}` | Bearer token | Permanently delete one owned conversation; returns 204 |
| `DELETE` | `/api/account` | Bearer token + recent sign-in | Stop active Research, delete owned data, and delete the Firebase identity |
| `POST` | `/api/chat` | Bearer token | Stream an assistant response using Server-Sent Events |
| `POST` | `/api/research` | Bearer token | Create and stream a checkpointed research job |
| `GET` | `/api/research/{job_id}` | Bearer token | Refresh one owned job from its saved subtask response IDs without starting work |
| `POST` | `/api/research/{job_id}/resume` | Bearer token | Continue saved Responses or explicitly restart terminal provider tasks |
| `POST` | `/api/research/{job_id}/cancel` | Bearer token | Cancel every running OpenAI background Response in the job |

Development defaults to a local token. Firebase mode verifies ID tokens in
FastAPI, optionally requires a verified email, and applies the configured email
allowlist before any tenant-scoped repository operation.

## Chat request

```json
{
  "conversation_id": null,
  "message": "Explain this design.",
  "mode": "chat",
  "attachments": []
}
```

`mode` accepts `chat` or `research`. The latter remains a single-model reasoning
call for compatibility; the frontend uses the dedicated `/api/research`
workflow for actual search. Attachment entries only carry staged filename and
size metadata; no file content is uploaded yet.

## Research request

```json
{
  "conversation_id": null,
  "query": "Compare the evidence for two personal-agent architectures."
}
```

A new job persists the user message and conversation ID, then Mind runs a
multi-stage Research Harness:

1. Terra creates a structured Research Brief with 4–8 subquestions.
2. Each subquestion gets its own background Response with built-in `web_search`.
3. Terra checks the aggregated evidence for gaps and conflicts without searching.
4. Material gaps trigger one bounded second round of search workers.
5. Terra writes one report using Mind's stable `[S#]` source markers.

Every stage is a provider-independent subtask with its own response ID, status,
output, sources, citations, and tool usage. DeepSeek Chat is not part of this
workflow.

Research SSE frames are ordered but not every type occurs exactly once:

```text
data: {"type":"research_started","job_id":"...","conversation_id":"...","status":"queued","progress":0}

data: {"type":"status","job_id":"...","status":"collecting","provider_status":"in_progress","progress":0.42,"search_round":1,"max_search_rounds":2,"completed_subtasks":3,"total_subtasks":5,"total_tool_calls":4,"max_total_tool_calls":24,"max_tool_call_overrun":3,"hard_max_total_tool_calls":27,"budget_exceeded":false,"hard_budget_reached":false,"citation_coverage":null}

data: {"type":"source","job_id":"...","source":{"id":"S1","title":"...","url":"https://..."}}

data: {"type":"delta","job_id":"...","delta":"## Findings"}

data: {"type":"done","job_id":"...","conversation_id":"...","status":"completed","progress":1,"source_count":8,"citation_coverage":0.92,"citations":[{"source_id":"S1","url":"https://...","start_index":41,"end_index":44}]}
```

OpenAI `queued`, `in_progress`, `completed`, `failed`/`incomplete`, and
`cancelled` states map onto persisted Mind subtasks and the enclosing phase.
Response IDs are saved per subtask before further polling, so a browser
disconnect or page reload retrieves existing Responses instead of starting
duplicates. User cancellation calls the OpenAI cancel endpoint for every active
subtask. Restarting a cancelled job begins a fresh Harness run and archives all
previous response IDs.

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

`ModelProvider` owns chat model streaming. `FakeAgentProvider` declares that it makes
no billable calls. `DeepSeekProvider` uses the OpenAI-compatible streaming Chat
Completions endpoint and declares that calls are billable. The health endpoint
lets the UI display this distinction before a message is sent.

Chat mode disables DeepSeek thinking for lower latency. Research mode enables
thinking but streams only final answer content; reasoning content is not exposed
or persisted. For an existing conversation, Mind reads complete persisted turns,
keeps the newest turns that fit `MIND_MAX_CONTEXT_CHARACTERS`, and sends them in
user/assistant order before the new user message. The limit includes the new
message and prevents history from growing model cost without bound.

`ResearchProvider` owns start, retrieve, cancel, and result parsing for one
bounded subtask. The sole production implementation is
`OpenAIResearchProvider`; tests inject a mock at the same boundary. It uses the
Responses API with a configurable model (default `gpt-5.6-terra`) and background
mode. Only search subtasks enable built-in web search. Parsed search output
includes `output_text`, URL citation annotations, and the complete
`web_search_call.action.sources` list.
The frontend renders inline citations and source cards as external links. See
OpenAI's official [background mode](https://developers.openai.com/api/docs/guides/background),
[web search](https://developers.openai.com/api/docs/guides/tools-web-search), and
[GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
documentation for the upstream contract.

`ResearchService` owns Brief planning, parallel subquestions, evidence-gap and
conflict checks, the optional second search round, final synthesis, overall
budgets, persistence, polling, SSE progress, cancel-all, refresh recovery, and
idempotent assistant-message writes. It depends only on `ResearchProvider`, not
on an SDK, concrete client, or a specialized Deep Research model.

The wire format and current model IDs follow the
[official DeepSeek Chat Completions documentation](https://api-docs.deepseek.com/api/create-chat-completion).

`ConversationRepository` owns tenant-scoped conversation reads and atomic
exchange writes. `JsonConversationRepository` is the ignored local
implementation; `FirestoreConversationRepository` stores metadata and ordered
message subcollections below `users/{uid}`. The detail endpoint and model-context
lookup return the same 404 for missing and cross-tenant IDs.

`ResearchRepository` persists tenant-scoped jobs either in the ignored JSON file
or below the same Firestore user subtree. Every subtask response ID, status,
output, source list, citation list, and tool usage is stored in the checkpoint;
the unified report and global source ledger live beside it. Final
assistant-message writes are idempotent by `research_job_id`, so polling or
reconnecting cannot duplicate a completed report.

Milestone-one local JSON records are normalized in memory when read, so older
conversations that predate typed message IDs and tenant fields remain openable.
The compatibility read does not rewrite the local data file.

Deletion is permanent and atomically rewrites the local repository only after
ownership is verified. Missing and cross-tenant IDs both return
`conversation_not_found`; the frontend requires an explicit confirmation before
calling the endpoint.

The shared Pydantic models define `User`, `Conversation`, `Message`,
`Attachment`, typed research jobs/checkpoints/sources/citations, `Memory`,
`Routine`, and `ToolCall`. Memory, routine, file, and voice repositories and
endpoints remain future work.
