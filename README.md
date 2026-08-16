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
- OpenAI Responses API Deep Research with background execution, built-in web
  search, inline citations, complete source lists, cancel, and refresh recovery
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

The local API runs at <http://127.0.0.1:8000/>. Conversation data is written to
`work/local-data/conversations.json`; research checkpoints are written to
`work/local-data/research-jobs.json`. Both are intentionally ignored by source
control.

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

Research starts a background OpenAI Response with built-in web search and can
incur cost. The header reports whether Research is ready before a run starts.
DeepSeek remains the optional Chat provider and is not used by Research.

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

The required test suite is deterministic and uses simulated DeepSeek SSE plus a
mock OpenAI ResearchProvider; it never calls a model or search service.

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

The script keeps model keys server-side in Secret Manager, deploys the API with
scale-to-zero, publishes Firestore rules and Firebase Hosting, and verifies the
Cloud Run health response before reporting the URLs. See
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
5. Firebase Authentication and Firestore foundation — in progress
6. File and voice inputs
7. Memory Ledger, Heartbeats, and Insight Diff
8. Production research workers, Terraform, CI/CD, monitoring, and report

Fake and DeepSeek Chat providers share `ModelProvider`. OpenAI Research uses the
separate `ResearchProvider` boundary. The JSON repositories can likewise be
replaced by Firestore without rewriting the user experience.
