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
| `GET` | `/api/memories` | Bearer token | List the complete ledger, including active, review, stale, conflicting, and superseded entries |
| `POST` | `/api/memories` | Bearer token | Add an immediately confirmed manual memory |
| `POST` | `/api/memories/{memory_id}/confirm` | Bearer token | Confirm a candidate, conflict, update, or stale fact; accepted replacements supersede the prior version |
| `PATCH` | `/api/memories/{memory_id}` | Bearer token | Edit, pin, enable/disable, retype, or expire one owned memory |
| `DELETE` | `/api/memories/{memory_id}` | Bearer token | Permanently delete one owned memory; returns 204 |
| `GET` | `/api/files` | Bearer token | List safe metadata for the current user's uploaded files |
| `POST` | `/api/files?name={filename}` | Bearer token | Upload one raw TXT or PDF body for private extraction; returns 201 |
| `DELETE` | `/api/files/{attachment_id}` | Bearer token | Delete one owned original and its metadata; returns 204 |
| `DELETE` | `/api/account` | Bearer token + recent sign-in | Stop active Research, delete owned data, and delete the Firebase identity |
| `POST` | `/api/chat` | Bearer token | Stream an assistant response using Server-Sent Events |
| `POST` | `/api/research` | Bearer token | Create and stream a checkpointed research job |
| `GET` | `/api/research/{job_id}` | Bearer token | Refresh one owned job from its saved subtask response IDs without starting work |
| `POST` | `/api/research/{job_id}/resume` | Bearer token | Continue saved Responses or explicitly restart terminal provider tasks |
| `POST` | `/api/research/{job_id}/cancel` | Bearer token | Cancel every running OpenAI background Response in the job |

Development defaults to a local token. Firebase mode verifies ID tokens in
FastAPI, optionally requires a verified email, and applies the configured email
allowlist before any tenant-scoped repository operation.

## Per-user usage limits

Before provider work, the API atomically enforces server-owned counters for the
authenticated user:

- Chat: 30 requests per UTC day by default.
- Research: 2 newly created Research or comparison jobs per UTC day by default.
- Active Research: 1 job per user by default.

Daily exhaustion returns HTTP `429` with
`daily_usage_limit_reached`. Starting a second active Research job returns HTTP
`409` with `active_research_limit_reached`. The frontend shows the returned safe
message. Completed, failed, and cancelled Research jobs release their active
slot. Resuming the same persisted job does not consume a new daily Research job;
its existing per-job Harness budgets still apply.

## Chat request

```json
{
  "conversation_id": null,
  "message": "Explain this design.",
  "mode": "chat",
  "attachment_ids": ["00000000-0000-0000-0000-000000000001"]
}
```

`mode` accepts `chat` or `research`. The latter remains a single-model reasoning
call for compatibility; the frontend uses the dedicated `/api/research`
workflow for actual search. Upload files first, then send their returned IDs in
`attachment_ids`. Mind reloads only files owned by the authenticated user,
injects bounded extracted text as untrusted reference data, and stores the IDs
on the user message for provenance.

## Research request

```json
{
  "conversation_id": null,
  "query": "Compare this brief with current evidence.",
  "attachment_ids": ["00000000-0000-0000-0000-000000000001"]
}
```

A new job persists the user message and conversation ID, then Mind runs a
multi-stage Research Harness:

1. Terra creates a structured Research Brief from the user request, without raw
   attachment contents.
2. A separate no-tool Response extracts bounded claims from attachments and flags
   likely embedded instructions. Only the sanitized claim ledger can reach search.
3. Each subquestion gets its own background Response with built-in `web_search`.
4. Terra checks the aggregated evidence for gaps, attachment corroboration, and
   conflicts without searching.
5. Material gaps trigger one bounded second round of search workers.
6. Terra writes one report using `[S#]` for independent web evidence and `[F#]` for
   untrusted file provenance.

Every stage is a provider-independent subtask with its own response ID, status,
output, sources, citations, and tool usage. DeepSeek Chat is not part of this
workflow.

Research SSE frames are ordered but not every type occurs exactly once:

```text
data: {"type":"research_started","job_id":"...","conversation_id":"...","status":"queued","progress":0}

data: {"type":"status","job_id":"...","status":"collecting","provider_status":"in_progress","progress":0.42,"search_round":1,"max_search_rounds":2,"completed_subtasks":3,"total_subtasks":5,"total_tool_calls":4,"max_total_tool_calls":24,"max_tool_call_overrun":3,"hard_max_total_tool_calls":27,"budget_exceeded":false,"hard_budget_reached":false,"soft_deadline_reached":false,"recovery_state":"retrying","retry_after_seconds":2,"degraded_reasons":[],"citation_coverage":null}

data: {"type":"source","job_id":"...","source":{"id":"S1","title":"...","url":"https://..."}}

data: {"type":"delta","job_id":"...","delta":"## Findings"}

data: {"type":"done","job_id":"...","conversation_id":"...","status":"completed","progress":1,"source_count":8,"citation_coverage":0.92,"web_citation_coverage":0.75,"file_corroboration_coverage":0.5,"quality_warning":"One file-derived claim is not independently corroborated.","citations":[{"source_id":"S1","kind":"web","url":"https://...","start_index":41,"end_index":45},{"source_id":"F1","kind":"file","file_id":"...","verification_status":"unverified","start_index":46,"end_index":50}]}
```

OpenAI `queued`, `in_progress`, `completed`, `failed`/`incomplete`, and
`cancelled` states map onto persisted Mind subtasks and the enclosing phase.
Response IDs are saved per subtask before further polling, so a browser
disconnect or page reload retrieves existing Responses instead of starting
duplicates. User cancellation calls the OpenAI cancel endpoint for every active
subtask. Restarting a cancelled job begins a fresh Harness run and archives all
previous response IDs.

Transient retrieval and service failures retry the same saved response ID with
bounded exponential backoff. Rate limiting pauses the whole job and emits the
provider-neutral `rate_limited` recovery state plus a rounded retry countdown.
Stage-shape, context-window, and incomplete-output failures may restart only that
stage, at most once by default; the retry uses a smaller evidence packet and a
more concise writing instruction. Search starts are limited to two concurrent
workers. After the soft deadline, Mind cancels unfinished searches and continues
with partial evidence when at least 60% of that round completed; the hard deadline
cancels the remaining Responses and fails the job. Every retry timestamp, attempt
counter, degraded reason, and response ID is persisted for refresh recovery.

## Streaming response

Text is sent as ordered SSE frames:

```text
data: {"type":"delta","delta":"I’m "}

data: {"type":"delta","delta":"Mind’s "}

data: {"type":"done","conversation_id":"...","memory_ids":["..."],"memory_candidate_count":1,"memory_candidates":[{"id":"...","type":"project","status":"candidate","review_reason":"update"}],"memory_saved_count":0,"request_id":"..."}
```

`memory_candidate_count` counts inferred, sensitive, conflicting, stale, or
Research-derived changes that need review. `memory_saved_count` counts explicit
non-sensitive “remember this” statements saved immediately. Questions and
ordinary requests produce neither. `memory_candidates` contains the authenticated
user's review-item IDs and bounded classification metadata so the UI can open and
focus the corresponding Memory card without exposing internal embeddings.

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

`MemoryProvider` extracts bounded structured `create`, `update`, `conflict`, or
`ignore` memory groups. The production `OpenAIMemoryProvider` uses strict Responses
API JSON Schema output and first partitions durable facts by specific subject and
shared update/expiry/delete lifecycle. Facts are not grouped merely because they
appear in one message, conversation, or broad category. Each group has one stable
`canonical_key`, one display summary, and bounded facets retained for semantic
retrieval; duplicate model output for the same key is consolidated by the backend.
Tests and zero-cost local development use deterministic rules. Questions, ordinary
requests, credentials, and exact duplicates are discarded. Inferred, sensitive,
Research-derived, update, and conflict groups stay disabled until review. Explicit
non-sensitive “remember this” statements activate immediately. A user-owned resume
or professional-profile summary is one atomic `fact:professional-profile` group;
jobs, education, and skills are facets rather than separate ledger entries, and a
later profile replaces it as one update.

`MemoryRepository` owns the complete tenant-scoped Memory Ledger. Entries record
provenance, confidence, sensitivity, canonical identity, revision, related and
superseded IDs, extraction/embedding model, verification time, stale time, and
expiry. Confirming an update or conflict activates the selected version and
keeps the prior version as disabled `superseded` provenance. Stale information is
disabled for revalidation and nothing is silently deleted.

`MemoryRetriever` embeds the group summary together with its facets, combines
semantic and lexical relevance, and selects only
active, enabled, unexpired, non-stale entries. Production generates normalized
OpenAI `text-embedding-3-small` vectors and uses Firestore nearest-neighbor
search; existing entries are backfilled lazily. A bounded scan/lexical fallback
keeps context available during embedding outages or while the vector index is
building. Selected memory IDs are exposed in Chat completion frames and
persisted on Research Jobs. Disabling, superseding, deleting, expiring, or
staling a memory prevents future retrieval.

The upstream contracts are documented in OpenAI's official
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
guides and Google's official
[Firestore vector search](https://firebase.google.com/docs/firestore/vector-search)
guide.

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

`AttachmentRepository` stores private attachment metadata locally or below the
same Firestore user subtree. `FileStorage` stores originals in an ignored local
directory during development and in a private Cloud Storage bucket in staging.
Public responses never expose storage URIs or extracted text. Research jobs save
`input_file_ids`, a sanitized file-claim review, and file citation provenance;
account deletion removes both metadata and original bytes. File citations prove
where a statement came from, not that it is true. Independent corroboration and
conflict status remain separate from citation coverage.

Milestone-one local JSON records are normalized in memory when read, so older
conversations that predate typed message IDs and tenant fields remain openable.
The compatibility read does not rewrite the local data file.

Deletion is permanent and atomically rewrites the local repository only after
ownership is verified. Missing and cross-tenant IDs both return
`conversation_not_found`; the frontend requires an explicit confirmation before
calling the endpoint.

The shared Pydantic models define `User`, `Conversation`, `Message`,
`Attachment`, typed research jobs/checkpoints/sources/citations, `Memory`,
`Routine`, and `ToolCall`. Routine and voice repositories and endpoints remain
future work.
