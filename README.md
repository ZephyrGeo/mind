# Mind Personal Agent

Mind is an original personal AI workspace for transparent conversations,
deep research, explainable memory, and guarded autonomous routines.

This repository contains the local vertical slice and FastAPI Agent Kernel.
It defaults to a zero-cost Fake ModelProvider and can opt in to DeepSeek through
environment-only credentials.

## What works now

- Responsive React conversation interface
- FastAPI streaming API using Server-Sent Events
- Deterministic Fake ModelProvider with no external model calls
- Opt-in DeepSeek V4 streaming provider with explicit billing status
- Bounded multi-turn model context from persisted conversation history
- Searchable, time-grouped conversation history with no display cap
- Reopenable conversations after a page reload
- Confirmed, tenant-scoped deletion of conversation history
- Local bearer-token authentication boundary
- Typed Pydantic API and domain models
- Replaceable ModelProvider and ConversationRepository interfaces
- Request IDs, standard error envelopes, and structured JSON logs
- OpenAPI documentation at `/docs`, `/redoc`, and `/openapi.json`
- Atomic, tenant-scoped JSON conversation persistence under `work/`
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
`work/local-data/conversations.json`, which is intentionally ignored by source
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

The required test suite is deterministic and uses simulated DeepSeek SSE
responses; it never calls a model or search service.

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
4. Firebase Authentication and managed deployment
5. File and voice inputs
6. Checkpointed Deep Research workflow
7. Memory Ledger, Heartbeats, and Insight Diff
8. Terraform, GCP deployment, CI/CD, monitoring, and report

The Fake and DeepSeek providers share the same small interface. The JSON
Repository can likewise be replaced by Firestore without rewriting the user
experience.
