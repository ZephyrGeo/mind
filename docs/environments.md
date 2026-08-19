# Environment configuration

Mind keeps configuration separate from source code. Chat can use the Fake
Provider or explicitly opt in to DeepSeek. Deep Research uses OpenAI through a
separate provider boundary.

## Environment matrix

| Setting | Development | Test / CI | Staging | Production |
|---|---|---|---|---|
| Purpose | Local product work | Deterministic verification | Integrated pre-release checks | Approved users |
| Chat provider | Fake or opt-in DeepSeek | Fake or mocked DeepSeek only | DeepSeek with a capped evaluation budget | DeepSeek with user quotas |
| Research provider | OpenAI when configured | Mock OpenAI only | OpenAI with a capped evaluation budget | OpenAI with user quotas |
| Authentication | Local bearer token | In-process test token | Firebase Authentication plus allowlist | Firebase Authentication plus allowlist |
| Conversation store | Ignored local JSON | Temporary test directory | Firestore staging database | Firestore production database |
| File store | Not implemented | Temporary fixtures | Dedicated staging bucket | Dedicated production bucket |
| Frontend | Local Node server | Built artifact | Firebase Hosting preview/staging site | Firebase Hosting production site |
| API | Local Python server | In-process tests | Dedicated Cloud Run service | Dedicated Cloud Run service |
| Secrets | Shell environment only | CI secret store when required | Secret Manager | Secret Manager |
| Model spend | None by default; user-funded opt-in | None in required CI | Hard daily cap and kill switch | Per-user and global caps |

Staging and production must use separate GCP resources, service accounts,
databases, storage buckets, OAuth credentials, and budgets. Production data must
never be copied into local development or test fixtures.

## Current local variables

Copy `.env.example` to the ignored `.env.local` file and edit the local values.
`npm run dev` loads this file automatically. An environment variable explicitly
exported in the terminal takes precedence over the same variable in the file.

| Variable | Default | Scope |
|---|---|---|
| `MIND_ENV` | `development` in the example | Environment label reserved for upcoming configuration validation |
| `MIND_AUTH_PROVIDER` | `local` | `local` or `firebase`; staging/production require Firebase |
| `MIND_LOCAL_TOKEN` | `local-demo-token` | Shared local-only bearer token; never valid for staging or production |
| `MIND_FIREBASE_PROJECT_ID` | unset | Firebase/GCP project used for token verification and Firestore |
| `MIND_ALLOWED_USER_EMAILS` | unset | Comma-separated restricted-access allowlist |
| `MIND_REQUIRE_VERIFIED_EMAIL` | `0` | Require Firebase email verification when set to `1` |
| `MIND_PERSISTENCE_PROVIDER` | `json` | `json` or `firestore`; staging/production require Firestore |
| `MIND_FIRESTORE_DATABASE_ID` | `(default)` | Firestore database ID |
| `MIND_DATA_PATH` | `work/local-data/conversations.json` | Ignored JSON persistence path |
| `MIND_RESEARCH_DATA_PATH` | `work/local-data/research-jobs.json` | Ignored, atomic research checkpoint path |
| `MIND_MEMORY_DATA_PATH` | `work/local-data/memories.json` | Ignored, atomic local Memory Ledger path |
| `MIND_API_HOST` | `127.0.0.1` | API bind host; the container uses `0.0.0.0` |
| `MIND_API_PORT` | `8000` | API port; the container uses `8080` |
| `MIND_ALLOWED_ORIGINS` | Both local frontend origins | Comma-separated exact CORS origins |
| `MIND_MAX_REQUEST_BYTES` | `64000` | Maximum accepted HTTP request body |
| `MIND_MAX_CONTEXT_CHARACTERS` | `64000` | Total character budget for the new message plus recent complete conversation turns |
| `MIND_MEMORY_RETRIEVAL_LIMIT` | `5` | Maximum relevant confirmed memories selected for one Chat or Research request |
| `MIND_MEMORY_MAX_CONTEXT_CHARACTERS` | `4000` | Maximum Memory Ledger context added to one model request |
| `MIND_MEMORY_PROVIDER` | `rules` | `rules` for zero-cost local development or `openai`; staging/production require `openai` |
| `MIND_MEMORY_MODEL` | `gpt-5.4-mini` | OpenAI model used for strict durable-memory extraction and reconciliation |
| `MIND_MEMORY_REASONING_EFFORT` | `low` | Reasoning effort for Memory extraction |
| `MIND_MEMORY_TIMEOUT_SECONDS` | `45` | Timeout for one Memory extraction or embedding request |
| `MIND_EMBEDDING_PROVIDER` | `local` | Deterministic local fallback or `openai`; staging/production require `openai` |
| `MIND_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model for multilingual semantic retrieval |
| `MIND_EMBEDDING_DIMENSIONS` | `256` | Vector dimensions; must match the Firestore Memory vector index |
| `MIND_MEMORY_SEMANTIC_THRESHOLD` | `0.68` | Minimum cosine similarity for semantic retrieval before lexical bonuses |
| `MIND_MODEL_PROVIDER` | `fake` | `fake` or `deepseek`; DeepSeek is an explicit billable opt-in |
| `DEEPSEEK_API_KEY` | unset | Required only when `MIND_MODEL_PROVIDER=deepseek`; secret environment value |
| `MIND_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | HTTPS API origin; credentials in URLs are rejected |
| `MIND_DEEPSEEK_MODEL` | `deepseek-v4-flash` | Hosted model ID; `deepseek-v4-pro` is the higher-cost option |
| `MIND_DEEPSEEK_TIMEOUT_SECONDS` | `120` | Per-request upstream timeout |
| `MIND_DEEPSEEK_MAX_TOKENS` | `2048` | Maximum generated tokens for one response |
| `MIND_RESEARCH_PROVIDER` | `openai` | Provider selector retained as an abstraction boundary; `openai` is the only production value |
| `OPENAI_API_KEY` | unset | Required to start local Research and required at startup in staging/production |
| `MIND_OPENAI_BASE_URL` | `https://api.openai.com/v1` | HTTPS Responses API origin; credentials in URLs are rejected |
| `MIND_RESEARCH_MODEL` | `gpt-5.6-terra` | OpenAI model used for background Research |
| `MIND_RESEARCH_REASONING_EFFORT` | `high` | Reasoning effort sent with the Responses API request |
| `MIND_RESEARCH_MAX_TOOL_CALLS` | `12` | Per-Response ceiling; each search worker also receives a fair share of the overall budget |
| `MIND_RESEARCH_MAX_SEARCH_ROUNDS` | `2` | Maximum evidence-search rounds; accepted range is 1–2 |
| `MIND_RESEARCH_MAX_SUBQUESTIONS` | `6` | Maximum initial Research Brief subquestions; accepted range is 4–8 |
| `MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS` | `24` | Whole-job soft web-search tool-call budget across every worker and round |
| `MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO` | `0.15` | Maximum proportional overrun considered when computing the hard search limit |
| `MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN` | `3` | Absolute cap on extra tool calls above the soft budget; the lower ratio-derived value wins |
| `MIND_RESEARCH_MIN_CITATION_COVERAGE` | `0.8` | Minimum sentence-level factual claim coverage; up to two citation-repair Responses run before a low-coverage report may complete |
| `MIND_RESEARCH_JOB_TIMEOUT_SECONDS` | `600` | Whole Harness deadline; active Responses are cancelled when exceeded |
| `MIND_RESEARCH_POLL_INTERVAL_SECONDS` | `2` | Delay between background Response status checks |
| `MIND_OPENAI_TIMEOUT_SECONDS` | `120` | Timeout for each OpenAI HTTP request |
| `MIND_LOG_LEVEL` | `INFO` | Structured API log level |
| `PORT` | `3000` | Local frontend port |
| `PYTHON` | `python3` | Optional Python executable used by the local launcher |
| `MIND_QUIET` | unset | Set to `1` to suppress local API request logs |

One-time local setup:

```bash
cp .env.example .env.local
```

For DeepSeek, edit `.env.local` to contain:

```dotenv
DEEPSEEK_API_KEY=<your DeepSeek API key>
MIND_MODEL_PROVIDER=deepseek
MIND_DEEPSEEK_MODEL=deepseek-v4-flash
```

For live Deep Research, add the independent OpenAI provider:

```dotenv
MIND_RESEARCH_PROVIDER=openai
OPENAI_API_KEY=<your OpenAI API key>
MIND_RESEARCH_MODEL=gpt-5.6-terra
```

For live intelligent Memory extraction and semantic retrieval, add:

```dotenv
MIND_MEMORY_PROVIDER=openai
MIND_MEMORY_MODEL=gpt-5.4-mini
MIND_EMBEDDING_PROVIDER=openai
MIND_EMBEDDING_MODEL=text-embedding-3-small
MIND_EMBEDDING_DIMENSIONS=256
```

The same server-side `OPENAI_API_KEY` is used, but the Memory and Research
provider boundaries remain independent. Existing memories are embedded lazily
in bounded batches on first retrieval; new and edited memories are embedded
when saved.

Research does not use the Chat DeepSeek key and has no alternate production
search provider. In development, the API can still start without an OpenAI key
so Chat remains usable, but health reports Research as unavailable and a
Research request fails closed.

Then start normally:

```bash
npm run setup:api
npm run dev
```

Firebase development options:

```bash
# Deterministic local Auth + Firestore (two terminals)
npm run emulators
npm run dev:emulator

# Real Firebase Auth using the ignored project config
gcloud auth application-default login
npm run dev:firebase
```

Do not place real keys in `.env.example`, source control, frontend code, or
support messages. `Settings` fails at startup when DeepSeek Chat is selected
without its key; staging and production also require OpenAI Memory extraction,
OpenAI embeddings, and the OpenAI Research key.
`/api/health` separately reports Chat and Research billing/readiness. Only
`npm run dev` loads `.env.local`; tests deliberately ignore it so required CI
and local validation cannot accidentally make billable calls.

The local frontend uses the demonstration token only in local auth mode. In
Firebase mode it obtains and refreshes the signed-in user's ID token.

## Test and CI guarantees

Required CI runs `npm run test:all` with the Fake Agent, simulated DeepSeek HTTP
streams, and mock OpenAI Research, Memory, and Embedding responses. Tests must not require model
credentials, GCP credentials, OAuth tokens, network access, or a billable model.
Any live-model evaluation must be a separate, explicitly budgeted job and must
never replace the required zero-cost suite.

Tests that write data must use temporary paths rather than
`work/local-data/conversations.json` or
`work/local-data/research-jobs.json`.

## Staging and production rules

Later deployment code must fail closed when required configuration is missing.
It must not fall back to the local token, Fake Agent, local JSON data, permissive
CORS, or development OAuth credentials.

Runtime secrets belong in Google Secret Manager and must be injected into Cloud
Run by secret reference. Public frontend configuration may contain Firebase web
application identifiers, but no service-account key, OAuth client secret, model
credential, or local conversation data may be committed.

Staging deployment also ensures a 256-dimension flat vector index for the
`memories.embedding` field. The API uses a bounded vector/lexical fallback while
the index builds, then automatically uses Firestore nearest-neighbor queries
when it becomes ready.

Git ignores `.env` and every `.env.*` file except the redacted
`.env.example`. Terraform state, generated credentials, and provider cache files
will be ignored when Terraform is introduced.

## Promotion contract

The intended release path is:

1. Pull requests run the zero-cost build and test suite.
2. Merges to `main` deploy immutable artifacts to staging.
3. Staging smoke tests verify authentication, API health, and tenant isolation.
4. Production promotion requires approval and reuses the tested artifacts.
5. A failed production health check rolls back to the previous Cloud Run
   revision and Firebase Hosting release.

The exact GCP project IDs, regions, allowed identities, budgets, and public URLs
will be supplied through Terraform variables or the deployment environment and
must not be hard-coded in application source.
