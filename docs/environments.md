# Environment configuration

Mind keeps configuration separate from source code. Local development can use
the Fake Provider or explicitly opt in to DeepSeek; staging and production
describe the contract that later deployment milestones must implement.

## Environment matrix

| Setting | Development | Test / CI | Staging | Production |
|---|---|---|---|---|
| Purpose | Local product work | Deterministic verification | Integrated pre-release checks | Approved users |
| Agent provider | Fake or opt-in DeepSeek | Fake or mocked DeepSeek only | DeepSeek with a capped evaluation budget | DeepSeek with user quotas |
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
| `MIND_LOCAL_TOKEN` | `local-demo-token` | Shared local-only bearer token; never valid for staging or production |
| `MIND_DATA_PATH` | `work/local-data/conversations.json` | Ignored JSON persistence path |
| `MIND_API_HOST` | `127.0.0.1` | API bind host; the container uses `0.0.0.0` |
| `MIND_API_PORT` | `8000` | API port; the container uses `8080` |
| `MIND_ALLOWED_ORIGINS` | Both local frontend origins | Comma-separated exact CORS origins |
| `MIND_MAX_REQUEST_BYTES` | `64000` | Maximum accepted HTTP request body |
| `MIND_MAX_CONTEXT_CHARACTERS` | `64000` | Total character budget for the new message plus recent complete conversation turns |
| `MIND_MODEL_PROVIDER` | `fake` | `fake` or `deepseek`; DeepSeek is an explicit billable opt-in |
| `DEEPSEEK_API_KEY` | unset | Required only when `MIND_MODEL_PROVIDER=deepseek`; secret environment value |
| `MIND_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | HTTPS API origin; credentials in URLs are rejected |
| `MIND_DEEPSEEK_MODEL` | `deepseek-v4-flash` | Hosted model ID; `deepseek-v4-pro` is the higher-cost option |
| `MIND_DEEPSEEK_TIMEOUT_SECONDS` | `120` | Per-request upstream timeout |
| `MIND_DEEPSEEK_MAX_TOKENS` | `2048` | Maximum generated tokens for one response |
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

Then start normally:

```bash
npm run setup:api
npm run dev
```

Do not place the real key in `.env.example`, source control, frontend code, or
support messages. `Settings` fails at startup when DeepSeek is selected without
a key, and `/api/health` reports `billable_model_calls: true` when it is active.
Only `npm run dev` loads `.env.local`; tests deliberately ignore it so required
CI and local validation cannot accidentally make billable calls.

The frontend currently embeds the same demonstration token, so changing
`MIND_LOCAL_TOKEN` alone will make local chat requests fail. This is an
explicit milestone 1 limitation, not a production authentication design.

## Test and CI guarantees

Required CI runs `npm run test:all` with the Fake Agent and simulated DeepSeek
HTTP streams. Tests must not require model credentials, GCP credentials, search
credentials, OAuth tokens, network access, or a billable model. Any live-model
evaluation must be a separate, explicitly budgeted job and must never replace
the required zero-cost suite.

Tests that write data must use temporary paths rather than
`work/local-data/conversations.json`.

## Staging and production rules

Later deployment code must fail closed when required configuration is missing.
It must not fall back to the local token, Fake Agent, local JSON data, permissive
CORS, or development OAuth credentials.

Runtime secrets belong in Google Secret Manager and must be injected into Cloud
Run by secret reference. Public frontend configuration may contain Firebase web
application identifiers, but no service-account key, OAuth client secret, model
credential, or local conversation data may be committed.

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
