# Mind Personal Agent

Mind is an original personal AI workspace for transparent conversations,
deep research, explainable memory, and guarded autonomous routines.

This repository contains the local, zero-model-cost vertical slice and the
milestone 2 FastAPI foundation. It still uses a Fake ModelProvider and makes no
external model calls.

## What works now

- Responsive React conversation interface
- FastAPI streaming API using Server-Sent Events
- Deterministic Fake ModelProvider with no external model calls
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

The current milestone uses safe local defaults. To override them, export values
from `.env.example` before starting the app. The scripts do not automatically
load dotenv files. See [Environment configuration](docs/environments.md) for
the development, test, staging, and production contract.

See [Mind API](docs/api.md) for endpoints, streaming frames, error envelopes,
and the provider/repository boundaries.

## Validate

```bash
npm run test:all
```

The required test suite is deterministic and never calls a model or search
service.

## Run the API container

```bash
docker build -t mind-api .
docker run --rm -p 8000:8080 mind-api
```

Then open <http://127.0.0.1:8000/docs>.

## Milestone sequence

1. Local React → Python → Fake Agent streaming slice — complete
2. FastAPI, typed kernel boundaries, OpenAPI, and container — in progress
3. Firebase Authentication and Gemini provider
4. File and voice inputs
5. Checkpointed Deep Research workflow
6. Memory Ledger, Heartbeats, and Insight Diff
7. Terraform, GCP deployment, CI/CD, monitoring, and report

The Fake Provider and JSON Repository are deliberately behind small interfaces so they
can be replaced by Gemini and Firestore without rewriting the user experience.
