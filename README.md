# Mind Personal Agent

Mind is an original personal AI workspace for transparent conversations,
deep research, explainable memory, and guarded autonomous routines.

This repository currently contains milestone 1: a local, zero-model-cost
vertical slice.

## What works now

- Responsive React conversation interface
- Python streaming API using Server-Sent Events
- Deterministic Fake Agent with no external model calls
- Local bearer-token authentication boundary
- Atomic JSON conversation persistence under `work/`
- Frontend and backend automated tests
- One-command local startup

## Run locally

Requirements:

- Node.js 22 or newer
- Python 3.9 or newer

```bash
npm ci
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

## Validate

```bash
npm run test:all
```

## Milestone sequence

1. Local React → Python → Fake Agent streaming slice
2. Firebase Authentication and Gemini provider
3. File and voice inputs
4. Checkpointed Deep Research workflow
5. Memory Ledger, Heartbeats, and Insight Diff
6. Terraform, GCP deployment, CI/CD, monitoring, and report

The Fake Agent and JSON store are deliberately behind small interfaces so they
can be replaced by Gemini and Firestore without rewriting the user experience.
