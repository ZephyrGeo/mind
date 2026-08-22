# Mind Personal Agent

Mind is an original personal AI workspace for transparent conversations,
deep research, explainable memory, and guarded autonomous routines.

This repository contains the local vertical slice and FastAPI Agent Kernel.
Chat defaults to a zero-cost Fake ModelProvider and can opt in to DeepSeek.
Deep Research uses an independent OpenAI ResearchProvider.

## What works now

- Responsive React conversation interface
- FastAPI streaming API using Server-Sent Events
- Deterministic Fake ModelProvider with no external model calls
- Opt-in DeepSeek V4 streaming provider with explicit billing status
- Bounded multi-turn model context from persisted conversation history
- Mind Research Harness with a Research Brief, 4–6 parallel Terra web-search
  workers, evidence-gap and conflict checks, an optional second search round,
  cited synthesis, persisted per-subtask recovery, bounded exponential backoff,
  two-worker search concurrency, soft/hard deadlines, partial-evidence completion,
  context reduction, and cancel-all semantics
- Searchable, time-grouped conversation history with no display cap
- Reopenable conversations after a page reload
- Confirmed, tenant-scoped deletion of conversation history
- Firebase registration, email verification, login, logout, and account deletion
- FastAPI Firebase ID-token verification and restricted-access allowlist
- Typed Pydantic API and domain models
- Replaceable ModelProvider and ConversationRepository interfaces
- Request IDs, standard error envelopes, and structured JSON logs
- OpenAPI documentation at `/docs`, `/redoc`, and `/openapi.json`
- Atomic, tenant-scoped JSON conversation persistence under `work/`
- Replaceable Firestore conversation and Research repositories
- User-controlled intelligent Memory Ledger with structured OpenAI extraction,
  question and credential rejection, provenance, confidence and sensitivity,
  explicit confirmation, semantic deduplication, update/conflict review,
  superseded history, staleness, expiry, pin, edit, disable, and deletion controls
- OpenAI embeddings plus Firestore vector search select relevant confirmed
  memories for later Chat and Research; lexical fallback keeps retrieval available
  while an index builds or the embedding service is temporarily unavailable
- Private, tenant-scoped TXT and PDF upload with bounded server-side extraction,
  Chat/Research provenance, and account-deletion cleanup
- Firebase Emulator and tenant-isolation Security Rules test workflow
- Terraform staging foundation and CI quality gates
- Python 3.12 container image running as a non-root user
- Frontend and backend automated tests
- One-command local startup

## Run locally

Requirements:

- Node.js 22 or newer
- Python 3.10 or newer; Python 3.12 is the production and CI baseline

```bash
npm ci
npm run setup:api
npm run dev
```

Then open <http://127.0.0.1:3000/>.

To add two zero-cost local Insight Diff conversations for visual testing, run:

```bash
npm run seed:insight-diff-demo
```

The command replaces only earlier local demo conversations and never calls a
model or web-search provider. One conversation contains Changed, New,
Contradicted, and Stale claims; the other shows No material changes detected.

The local API runs at <http://127.0.0.1:8000/>. Conversation data is written to
`work/local-data/conversations.json`; research checkpoints are written to
`work/local-data/research-jobs.json`; Memory Ledger entries are written to
`work/local-data/memories.json`; attachment metadata and private originals are
written below `work/local-data/attachments.json` and `work/local-files/`. All are
intentionally ignored by source control.

The current milestone uses safe local defaults. For persistent project-local
DeepSeek configuration, copy the ignored example once:

```bash
cp .env.example .env.local
```

Then edit `.env.local` and set these two values:

```dotenv
DEEPSEEK_API_KEY=<your DeepSeek API key>
MIND_MODEL_PROVIDER=deepseek
```

After that, normal startup automatically loads `.env.local`:

```bash
npm run dev
```

Deep Research has one production provider: OpenAI. To enable it locally, add:

```dotenv
OPENAI_API_KEY=<your OpenAI API key>
MIND_RESEARCH_PROVIDER=openai
MIND_RESEARCH_MODEL=gpt-5.6-terra
```

To test the production Memory path locally with the same OpenAI key, also add:

```dotenv
MIND_MEMORY_PROVIDER=openai
MIND_MEMORY_MODEL=gpt-5.4-mini
MIND_EMBEDDING_PROVIDER=openai
MIND_EMBEDDING_MODEL=text-embedding-3-small
```

Without those Memory overrides, local development intentionally uses the
zero-cost deterministic extractor and embedding fallback. Staging and
production require the OpenAI implementations.

Research runs several bounded background OpenAI Responses. Mind plans and
coordinates the stages. Attached files first pass through an isolated, no-tool
claim-extraction stage; raw file text never enters a web-search worker. Only
evidence-collection workers enable built-in web search. The default budget is two
rounds, at most six initial subquestions, 24
total web-search calls, and ten minutes. Runs can therefore take several minutes
and incur cost. DeepSeek remains the optional Chat provider and is not used by
Research.

Current canonical documentation is preferred over legacy guide URLs. Final
reports must pass an 80% sentence-level citation coverage gate; up to two
persisted citation-repair Responses run automatically when needed. A useful report
that remains below the target completes with an explicit quality warning rather
than being hidden. `[S#]` identifies independent web evidence; `[F#]` attributes a
claim to an untrusted uploaded file and does not by itself establish correctness.
OpenAI Background-mode research also requires both the current canonical
Background and data-controls guides before a report can complete.

The default model is `deepseek-v4-flash`; set `MIND_DEEPSEEK_MODEL` to
`deepseek-v4-pro` when you explicitly want the higher-cost model. Variables
explicitly exported in the terminal take precedence over `.env.local`. See
[Environment configuration](docs/environments.md) for the full contract. Never
commit the API key or paste it into application logs.

See [Mind API](docs/api.md) for endpoints, streaming frames, error envelopes,
and the provider/repository boundaries.

## Validate

```bash
npm run test:all
```

The required test suite is deterministic and uses simulated DeepSeek SSE plus
mock OpenAI Research, Memory, and Embedding responses; it never calls a model or
search service.

For the Firebase Emulator tenant-isolation test, run:

```bash
npm run test:rules
```

For an interactive emulator workspace, start `npm run emulators` in one terminal
and `npm run dev:emulator` in another. Real Firebase Auth can be tested with the
ignored `.env.firebase.local` file and `npm run dev:firebase`.

After Firebase and gcloud login, the early staging slice is deployed with:

```bash
npm run deploy:staging
```

The script keeps model keys server-side in Secret Manager, ensures the Firestore
Memory vector index, deploys the API with scale-to-zero, publishes Firestore
rules and Firebase Hosting, and verifies the Cloud Run health response before
reporting the URLs. See
[Staging infrastructure](infra/README.md) for the Terraform equivalent.

## Run the API container

```bash
docker build -t mind-api .
docker run --rm -p 8000:8080 mind-api
```

Then open <http://127.0.0.1:8000/docs>.

## Milestone sequence

1. Local React → Python → Fake Agent streaming slice — complete
2. FastAPI, typed kernel boundaries, OpenAPI, and container — complete
3. DeepSeek streaming provider and multi-turn conversations — complete
4. Local checkpointed Deep Research MVP — complete
5. Firebase Authentication and Firestore foundation — complete
6. TXT and PDF file input — complete; voice remains deferred
7. Intelligent Memory Ledger — complete MVP; Heartbeats and Insight Diff follow
8. Production research workers, Terraform, CI/CD, monitoring, and report

Fake and DeepSeek Chat providers share `ModelProvider`. OpenAI Research uses the
separate `ResearchProvider` boundary. The JSON repositories can likewise be
replaced by Firestore without rewriting the user experience.
