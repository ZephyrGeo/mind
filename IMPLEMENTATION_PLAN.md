# Mind Personal Agent — Submission-Oriented Harness Implementation Plan

## Product direction

Mind should not compete with OpenAI on the quality of a single research response.
OpenAI provides the core long-running reasoning and web exploration. Mind owns the
personal-agent harness around that capability:

    Conversation or file input
            ↓
    Relevant user-controlled memory
            ↓
    OpenAI background Deep Research
            ↓
    Durable job state, citations, sources, and report
            ↓
    User enables Track this topic
            ↓
    Heartbeat periodically creates a new research snapshot
            ↓
    Insight Diff identifies what is new, changed, contradicted, or stale
            ↓
    Notify the user and update memory with permission

Product statement:

> Mind remembers what matters to you, researches it with traceable evidence, and
> keeps watching for what changes.

The model API is replaceable infrastructure. Mind owns identity, inputs, context,
workflow state, permissions, budgets, recovery, persistence, personalization,
automation, evaluation, and user experience.

## Ownership boundary

### OpenAI owns

- Long-running reasoning.
- Built-in web search and data exploration.
- Search planning and follow-up exploration inside a Response.
- Final research prose.
- Inline URL citations and complete web-source metadata.
- Background Response execution.

### Mind owns

- ResearchProvider abstraction.
- Authenticated user and tenant boundaries.
- Research Job lifecycle and durable state machine.
- OpenAI response ID persistence, retrieval, cancellation, and restart policy.
- Prompt, file, conversation, and memory context assembly.
- Citation and source normalization, validation, persistence, and display.
- Quotas, concurrency, duration, tool-call, and cost controls.
- Browser disconnect recovery and idempotency.
- Report snapshots, Memory Ledger, Research Watch, and Insight Diff.
- Observability, testing, deployment, and security.

Mind will not build a custom search crawler, duplicate OpenAI's internal research
loop, or offer DeepSeek or Tavily as production Research alternatives. Normal
Chat may continue using DeepSeek and is outside the Research provider decision.

## Assignment acceptance map

| Assignment requirement | Mind implementation |
| --- | --- |
| Conversational LLM instructions and responses | Existing Chat experience with the configured Chat ModelProvider |
| Deep Research | OpenAI Responses API plus the Mind Research Harness |
| Registration, login, logout, and account deletion | Firebase Authentication and an account-deletion workflow |
| Non-text input | Bounded TXT and PDF upload through Cloud Storage |
| Original feature 1 | User-controlled Memory Ledger |
| Original feature 2 | Research Watch plus Heartbeat and Insight Diff |
| Web application | React frontend |
| Restricted access | Firebase identity plus production allowlist or active-user status |
| Python backend | FastAPI |
| Google Cloud and IaC | Cloud Run, Firestore, Cloud Storage, Cloud Tasks, Cloud Scheduler, Secret Manager, Firebase Hosting, and Terraform |
| CI and CD | GitHub Actions with staging deployment and controlled production promotion |
| Production assumptions | Explicit capacity, quota, scaling, and load-test targets |
| Deliverables | Production URL, Google Doc report, and GitHub source repository |

## Current foundation to retain

The repository already contains a useful local vertical slice:

- React conversation and Research UI.
- FastAPI streaming API.
- Normal Chat ModelProvider boundary.
- Tenant-scoped conversation and Research repositories.
- Local atomic JSON persistence.
- Research Job, cancel, resume, sources, and progress UI.
- Request IDs, structured errors, and JSON logs.
- Deterministic backend and frontend tests.

The current Research MVP was originally built around DeepSeek planning and
synthesis plus Fake or Tavily search. That path is being replaced by a single
production OpenAIResearchProvider. Fake providers remain test-only.

No broad directory rewrite is required. Existing provider, repository, API,
conversation, SSE, and frontend boundaries should be evolved incrementally.

## Research Harness requirements

### 1. ResearchProvider contract

ResearchService depends only on a small interface covering:

- start a background research Response;
- retrieve the current provider state by response ID;
- cancel an active Response;
- parse the provider result into Mind report, citation, source, and error models.

The only production implementation is OpenAIResearchProvider.

Tests may use mocks or fakes that return representative OpenAI payloads. They
must not be exposed as a production search option.

### 2. Durable Research Job state machine

Use a small, explicit state machine:

    created → queued → running → completed
                     ↘ cancelling → cancelled
                     ↘ failed

A restarted cancelled or terminally failed job creates a new provider attempt.
The new attempt is linked to the previous attempt instead of pretending that the
original OpenAI Response continued.

Each Research Job stores at least:

- job ID;
- user ID and conversation ID;
- provider and model;
- provider response ID;
- status and provider status;
- attempt number and retry-of reference;
- input file and memory references;
- prompt version;
- timestamps;
- normalized error code and safe message;
- report ID when completed.

### 3. Disconnect and cancellation semantics

A browser close, refresh, navigation, network loss, crash, or device sleep means
only that the client detached. It does not cancel background Research.

An active Research task is cancelled only by an explicit authenticated action:

- the user clicks Stop research;
- the user confirms deletion of a conversation and chooses to stop its active
  task;
- account deletion cancels all owned active tasks;
- an administrator or budget policy explicitly terminates the task.

The cancellation flow is:

    POST /api/research/{job_id}/cancel
    → verify ownership and cancellable state
    → call OpenAI cancel
    → persist cancelling
    → retrieve the provider terminal state
    → persist cancelled

Logout alone does not cancel Research.

The server must persist the provider response ID before emitting the first
research-started SSE event. A disconnected browser later retrieves the same
Response by that ID instead of creating a duplicate task.

### 4. Background reconciliation

OpenAI executes the reasoning, but Mind still needs a durable reconciler:

    POST /api/research
    → create Firestore Research Job
    → create OpenAI background Response
    → save response ID
    → enqueue Cloud Task
    → retrieve until terminal
    → save report, citations, and sources

Frontend polling may opportunistically refresh a job, but production completion
must not depend on the browser remaining open.

Cloud Task execution is idempotent. A retry retrieves the existing Response and
does not call start again.

### 5. Context and input assembly

Mind builds the provider request from:

- the current question;
- bounded relevant conversation context;
- user-approved memories;
- bounded extracted file content;
- locale and time context;
- the previous report when running a Research Watch;
- prompt version and research policy;
- reasoning effort and maximum tool calls.

Every injected memory and file remains traceable to its source ID.

### 6. Citation and source ledger

Mind parses and stores:

- final output text;
- inline URL citations and text offsets;
- complete sources returned by web search calls;
- stable source IDs;
- source title, URL, and provider metadata;
- model, prompt version, and completion timestamp.

Deterministic validation covers malformed URLs, invalid citation offsets,
duplicate URLs, missing source mappings, and unsafe link protocols.

Inline citations and source links must be clearly visible and clickable.

### 7. Guardrails and budgets

Enforce:

- maximum active Research jobs per user;
- daily Research quota;
- maximum OpenAI tool calls;
- maximum local reconciliation duration;
- bounded provider polling with backoff;
- file size, type, and extracted-text limits;
- idempotency keys;
- request and job ownership checks;
- server-side secrets only;
- safe error messages and redacted logs.

When exact monetary interruption cannot be guaranteed inside a provider
Response, use tool-call limits, per-user quotas, concurrency limits, and usage
reporting as the enforceable first version.

### 8. Idempotency and recovery

The Harness must prevent:

- duplicate OpenAI Responses from retried start requests;
- duplicate assistant messages;
- concurrent completion writers;
- duplicate scheduled Watch runs;
- a user reading or cancelling another user's job.

Recovery tests cover browser reconnect, API restart, Cloud Task retry, provider
timeout, provider failure, cancellation, and completion racing with cancellation.

## Local-to-production development strategy

### Stage A — Local Research vertical slice

Use the current JSON repositories and a local identity boundary to complete the
Research Harness before Firebase is required.

Local success means:

- start persists a response ID;
- retrieve maps queued, running, completed, failed, and cancelled states;
- refresh and process restart recover the original task;
- explicit stop calls provider cancel;
- citations and complete sources are normalized and clickable;
- completion writes exactly one assistant message;
- mocked tests require no real API key;
- one minimal real smoke test is run when an OpenAI API key is available.

### Stage B — Firebase Emulator Suite

After the local Research vertical slice is stable, add:

- Authentication Emulator;
- Firestore Emulator;
- Cloud Storage Emulator;
- Security Rules tests;
- import and export of deterministic test data.

Use the same repository interfaces in local and production modes. The business
services must not know whether persistence is JSON, an emulator, or production
Firestore.

All domain records include user ID from the beginning so tenant isolation is not
retrofit later.

### Stage C — Google Cloud staging and production

Replace local implementations with:

- Firestore repositories;
- Cloud Storage files;
- Cloud Tasks reconciliation;
- Cloud Scheduler Heartbeats;
- Cloud Run API and workers;
- Secret Manager configuration.

Deploy a thin staging vertical slice early instead of postponing all deployment
work to the final week.

## Vector retrieval policy

A vector database is not required for Research Job, report, citation, source,
conversation, or account persistence.

Vector retrieval is introduced only for the Memory Ledger:

    MemoryRetriever
    ├── LocalMemoryRetriever
    └── FirestoreVectorRetriever

The local retriever may use deterministic fake embeddings, keyword scoring, or
small in-process cosine similarity. Production may use Firestore vector search.

Memory retrieval must not block the initial OpenAI Research integration.

## Focused domain model

### ResearchJob

- id
- user_id
- conversation_id
- provider
- model
- provider_response_id
- status
- provider_status
- attempt
- retry_of
- input_file_ids
- memory_ids
- prompt_version
- error
- report_id
- created_at
- updated_at

### ResearchReport

- id
- job_id
- user_id
- output_text
- citation_ids
- source_ids
- model
- prompt_version
- usage
- completed_at

### ResearchCitation

- id
- report_id
- source_id
- start_index
- end_index
- title
- url

### ResearchSource

- id
- report_id
- title
- url
- source_type
- provider_metadata

### Memory

- id
- user_id
- type
- content
- provenance
- confidence
- sensitivity
- pinned
- enabled
- expires_at

Recommended memory types:

- goal
- preference
- project
- fact
- decision

### ResearchWatch

- id
- user_id
- baseline_report_id
- schedule
- focus
- budget
- enabled
- last_run_at
- next_run_at

### WatchRun and InsightDiff

WatchRun stores the watch, previous report, new report, status, idempotency key,
and retry record.

InsightDiff stores:

- new claims;
- changed claims;
- contradicted claims;
- stale claims;
- unchanged claims;
- recommended actions.

Claims are extracted from completed reports as a post-processing step for
comparison. They do not drive a custom replacement for OpenAI web research.

## Implementation phases

### Phase 0 — Freeze baseline and migrate Research to OpenAI

Estimated effort: 1–2 days

- Preserve the current passing test baseline.
- Define ResearchProvider.
- Implement the sole production OpenAIResearchProvider.
- Use the Responses API with background execution and built-in web search.
- Persist response ID and map provider states.
- Implement retrieve, cancel, parsing, and safe error mapping.
- Parse output text, inline citations, and complete sources.
- Remove Research-specific DeepSeek, Tavily, and Fake production configuration.
- Keep normal Chat DeepSeek configuration unchanged.
- Add mocked unit and API integration tests.

Exit criteria:

- Research runs, reconnects, completes, fails safely, and cancels.
- Browser disconnect does not recreate or cancel the OpenAI Response.
- Every completion produces one persisted assistant message.
- No real API key is needed for the required test suite.

### Phase 1 — Authentication, Firestore foundation, and early staging

Estimated effort: 4–5 days

- Implement Firebase registration, login, logout, and account deletion.
- Verify Firebase ID tokens in FastAPI.
- Add active-user or allowlist authorization for restricted production access.
- Implement Firestore repositories behind existing protocols.
- Add tenant-isolation and Security Rules tests with emulators.
- Create the Terraform skeleton.
- Deploy React, FastAPI, Auth, and Firestore as an early staging slice.
- Start CI with backend tests, frontend tests, lint, type checks, and Terraform
  validation.

Exit criteria:

- Users cannot read, mutate, or cancel one another's resources.
- Registration and restricted service access both work.
- Account deletion has a defined, tested cleanup workflow.
- A staging URL exists before later feature work.

### Phase 2 — Non-text file input

Estimated effort: 2–3 days

- Add bounded TXT and PDF upload.
- Store originals in Cloud Storage.
- Validate MIME type, extension, size, and ownership.
- Extract bounded text server-side.
- Attach files to Chat and Research requests.
- Track provenance from injected text to file ID.
- Delete owned files during account deletion.

Exit criteria:

- At least one real non-text file can affect a Chat or Research result.
- A user cannot access another user's file.
- Oversized, unsupported, or malformed files fail safely.

Voice and Google Drive are deferred until this path is complete.

### Phase 3 — Production Research Harness

Estimated effort: 3–4 days

- Move production Research Job persistence to Firestore.
- Add Cloud Tasks reconciliation.
- Add idempotent start, poll, finalize, cancel, and restart operations.
- Add quotas, concurrency, polling backoff, timeout, and usage reporting.
- Preserve SSE progress while making browser presence optional.
- Add citation and source validation.
- Add structured operational events and metrics.

Exit criteria:

- Research completes after the browser closes.
- API or worker restart does not lose the job.
- Cloud Task retry does not create another OpenAI Response.
- Cancellation and completion races have deterministic outcomes.

### Phase 4 — Memory Ledger

Estimated effort: 3–4 days

Implement the first original feature:

- typed memory candidates from conversations and reports;
- provenance, confidence, and sensitive-data filtering;
- explicit user confirmation for important or sensitive memories;
- inspect, pin, edit, disable, delete, and expire controls;
- relevant-memory retrieval before Chat and Research;
- local MemoryRetriever and production FirestoreVectorRetriever boundaries.

Exit criteria:

- Relevant user goals and preferences can affect a later result.
- Users can see and control everything Mind remembers.
- Deleted or disabled memories are not retrieved.

### Phase 5 — Research Watch, Heartbeat, and Insight Diff

Estimated effort: 3–4 days

Implement the second original feature:

    Open completed report
    → Track this topic
    → Choose schedule, focus, and budget
    → Cloud Scheduler triggers an idempotent Watch run
    → OpenAI creates a new research snapshot
    → Structured claim post-processing compares snapshots
    → Insight Diff presents what changed

Implement:

- Watch create, list, pause, resume, and delete;
- Cloud Scheduler and Cloud Tasks execution;
- run history and retry records;
- new, changed, contradicted, stale, and unchanged categories;
- in-app notification;
- duplicate concurrent-run prevention.

Exit criteria:

- A report can be researched again without the user being online.
- The result emphasizes change instead of repeating the entire report.
- Duplicate scheduled executions are prevented.

### Phase 6 — Production hardening and deliverables

Estimated effort: 3–4 days

Complete:

- automated staging deployment from the main branch;
- controlled production promotion;
- post-deployment smoke tests;
- Python linting, type checks, and tests;
- React build and frontend tests;
- Terraform validation and plan;
- container, dependency, and secret scanning;
- Cloud Logging dashboards and Monitoring alerts;
- load, recovery, and tenant-isolation tests;
- production deployment;
- Google Doc report;
- GitHub submission permissions.

CI, documentation, monitoring, and report evidence are accumulated from Phase 1.
Phase 6 is final validation and packaging rather than the first time they are
considered.

Exit criteria:

- The production URL passes the reviewer journey.
- Infrastructure can be reproduced from Terraform.
- The report includes architecture, quality, monitoring, security, omissions,
  capacity assumptions, and creative decisions.

## Four-week schedule

| Week | Primary outcome |
| --- | --- |
| Week 1 | OpenAI Research local Harness, Firebase Auth and Firestore foundation, Terraform skeleton, first staging deployment |
| Week 2 | Cloud Tasks recovery, file input, citation ledger, account deletion, tenant security |
| Week 3 | Memory Ledger, Research Watch, Heartbeat, Insight Diff |
| Week 4 | CI/CD completion, monitoring, security and load tests, production deployment, Google Doc report |

## Scope control

Prioritize in this order:

1. Complete account lifecycle and restricted access.
2. OpenAI Research with durable state, cancellation, reconnect, and sources.
3. One real non-text input path.
4. Google Cloud staging and Terraform.
5. User-controlled Memory Ledger.
6. Research Watch, Heartbeat, and Insight Diff.
7. CI/CD, monitoring, security, production deployment, and report.

Defer if time is limited:

- custom search, crawling, or Research planning loops;
- Research-specific DeepSeek or Tavily providers;
- multiple production Research providers;
- voice after file upload works;
- Google Drive integration;
- email and mobile push notifications;
- generic tool registry, MCP marketplace, or permissions framework;
- multi-agent orchestration;
- self-hosted models;
- native mobile applications.

## Production assumptions

Use explicit and reviewable initial assumptions:

- 1,000 registered users.
- 100 daily active users.
- 20 concurrent Chat streams at peak.
- 5 concurrent active Deep Research jobs.
- 1 active Research job per user by default.
- Per-user daily Research quota.
- Per-job tool-call and duration controls.
- 20 MB maximum uploaded file before extraction, subject to validation.
- Horizontal Cloud Run scaling with bounded instance and worker concurrency.
- Cloud Tasks retry with idempotent handlers.

Validate these assumptions with load and recovery tests and revise them in the
final report if measured results justify a change.

## Continuous quality strategy

Required deterministic tests:

- ResearchProvider request and payload parsing;
- OpenAI state mapping;
- citation and source normalization;
- Research Job state transitions;
- browser disconnect recovery;
- explicit cancellation;
- cancelled and failed restart behavior;
- idempotent start and finalize;
- duplicate assistant-message prevention;
- tenant isolation;
- account lifecycle and deletion cleanup;
- file ownership and validation;
- memory enable, disable, delete, and retrieval;
- duplicate Heartbeat prevention;
- Insight Diff classification contracts.

Staging tests:

- minimal real OpenAI smoke test when a key is available;
- Auth and restricted-access journey;
- upload-to-Research journey;
- browser close and later recovery;
- Cloud Task retry;
- account deletion;
- load test against documented capacity assumptions.

Track:

- Research success, cancellation, failure, and recovery rates;
- latency and provider-status duration;
- model usage and tool calls;
- citation parsing and source-link validity;
- duplicate-prevention events;
- quota rejections;
- Cloud Task depth, retries, and failures;
- Heartbeat success and diff usefulness;
- memory retrieval relevance.

## Report workstream

Maintain report evidence during implementation:

- service overview and reviewer journey;
- architecture and technology choices;
- OpenAI versus Mind Harness ownership;
- two original features and why they were selected;
- deliberately omitted features and future policy;
- testing and evaluation strategy;
- monitoring and logging design;
- authentication, tenant isolation, secrets, file security, and deletion;
- capacity assumptions and measured load results;
- failure recovery and cost controls;
- architecture diagrams and staging or production screenshots.

The final Google Doc must be shared as Anyone with the link can view.

## Definition of done

The project is submission-ready when a reviewer can:

1. Create an account, sign in, sign out, and delete the account.
2. Pass the production access policy.
3. Chat with a configured LLM.
4. Upload a TXT or PDF file and use it in Chat or Research.
5. Start Deep Research and inspect progress, citations, and sources.
6. Close the browser and later recover the same background Research.
7. Explicitly stop an active Research task.
8. See and control relevant long-term memories.
9. Turn a report into a scheduled Research Watch.
10. Receive an Insight Diff showing what changed.
11. Access the deployed Google Cloud application.
12. Review Terraform, CI/CD, tests, monitoring, security, capacity assumptions,
    and the final report.
13. Access the GitHub repository and view-only Google Doc deliverables.
