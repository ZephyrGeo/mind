# Environment configuration

Mind keeps configuration separate from source code. Milestone 1 runs only in
local development and test environments; staging and production describe the
contract that later GCP and Terraform milestones must implement.

## Environment matrix

| Setting | Development | Test / CI | Staging | Production |
|---|---|---|---|---|
| Purpose | Local product work | Deterministic verification | Integrated pre-release checks | Approved users |
| Agent provider | Fake | Fake or mock only | Gemini with a capped evaluation budget | Gemini with user quotas |
| Authentication | Local bearer token | In-process test token | Firebase Authentication plus allowlist | Firebase Authentication plus allowlist |
| Conversation store | Ignored local JSON | Temporary test directory | Firestore staging database | Firestore production database |
| File store | Not implemented | Temporary fixtures | Dedicated staging bucket | Dedicated production bucket |
| Frontend | Local Node server | Built artifact | Firebase Hosting preview/staging site | Firebase Hosting production site |
| API | Local Python server | In-process tests | Dedicated Cloud Run service | Dedicated Cloud Run service |
| Secrets | Shell environment only | CI secret store when required | Secret Manager | Secret Manager |
| Model spend | None | None in required CI | Hard daily cap and kill switch | Per-user and global caps |

Staging and production must use separate GCP resources, service accounts,
databases, storage buckets, OAuth credentials, and budgets. Production data must
never be copied into local development or test fixtures.

## Current local variables

Copy `.env.example` to an ignored local file as a reference, then export the
values in the shell or process manager before running `npm run dev`. The current
scripts intentionally do not load dotenv files.

| Variable | Default | Scope |
|---|---|---|
| `MIND_ENV` | `development` in the example | Environment label reserved for upcoming configuration validation |
| `MIND_LOCAL_TOKEN` | `local-demo-token` | Shared local-only bearer token; never valid for staging or production |
| `MIND_DATA_PATH` | `work/local-data/conversations.json` | Ignored JSON persistence path |
| `PORT` | `3000` | Local frontend port |
| `PYTHON` | `python3` | Optional Python executable used by the local launcher |
| `MIND_QUIET` | unset | Set to `1` to suppress local API request logs |

Example:

```bash
export MIND_LOCAL_TOKEN="local-demo-token"
export MIND_DATA_PATH="work/local-data/conversations.json"
npm run dev
```

The frontend currently embeds the same demonstration token, so changing
`MIND_LOCAL_TOKEN` alone will make local chat requests fail. This is an
explicit milestone 1 limitation, not a production authentication design.

## Test and CI guarantees

Required CI runs `npm run test:all` with the Fake Agent. Tests must not require
GCP credentials, search credentials, OAuth tokens, network access, or a
billable model. Any future live-model evaluation must be a separate, explicitly
budgeted job and must never replace the required zero-cost suite.

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
