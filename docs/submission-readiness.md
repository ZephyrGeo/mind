# Mind submission readiness

Updated: 2026-08-23

## Submission environment

- Web: https://mind-staging-ce427.web.app
- API: https://mind-api-staging-jasp5jgzxq-an.a.run.app
- GCP project: `mind-staging-ce427`
- Region: `asia-northeast1`
- Deployed Cloud Run revision: `mind-api-staging-00007-zj7`
- Source revision at deployment: `2163473`

The current staging environment is the final reviewer-facing submission. There
is no separate production promotion in scope.

## Delivered reviewer journey

1. Register, verify an email address, sign in, sign out, and delete the account.
2. Continue tenant-scoped Chat conversations.
3. Upload a private TXT or PDF and use it in Chat or Research.
4. Start a multi-stage Research Job, inspect its current task, and explicitly
   stop or safely restart it.
5. Refresh or reopen a conversation and recover the persisted job by its saved
   provider response IDs.
6. Read a cited report whose source list contains only deduplicated sources used
   by the report.
7. Inspect and control the Memory Ledger.
8. Run **Compare with latest evidence** and view immutable baseline/latest
   reports plus `New`, `Changed`, `Contradicted`, and `Stale` claims.
9. See **No material changes detected** when the comparison finds no meaningful
   difference.

## Automated verification

The zero-cost deterministic suite completed on 2026-08-23:

- Frontend build and contracts: 15 passed.
- Backend: 122 passed.
- Ruff: passed.
- Pyright: 0 errors and 0 warnings.
- Firebase Auth/Firestore Emulator tenant-isolation rule test: passed.
- Terraform 1.14.3 formatting and validation: passed.
- Git diff whitespace validation: passed.

The bounded staging capacity check completed 80/80 requests successfully. See
[Small staging concurrency check](capacity-check.md) for cold-start, warm p50/p95,
method, and limitations.

## Deployment smoke evidence

The 2026-08-23 deployment completed Firestore rules/index publication, reused
the 256-dimension Memory vector index, created Cloud Run revision
`mind-api-staging-00007-zj7`, routed 100% of API traffic to it, and released a new
Firebase Hosting version.

Unauthenticated smoke checks after deployment:

| Check | Result |
| --- | --- |
| Firebase Hosting root | HTTP 200 |
| Runtime Firebase/API configuration | HTTP 200; staging API selected |
| `/api/health` | HTTP 200; staging/live providers ready |
| `/openapi.json` | HTTP 200; Mind API 0.7.0 |
| Conversations without an ID token | HTTP 401 `authentication_required` |
| Allowed staging-origin CORS preflight | HTTP 200 |
| Untrusted-origin CORS preflight | HTTP 400 `Disallowed CORS origin` |
| Refresh on `#/memory` | Route remained `#/memory` |
| Deployed UI bundle | Insight Diff present; deferred Heartbeats/Voice UI absent |

## Authenticated reviewer smoke evidence

Authenticated staging checks used a verified Firebase reviewer account on
2026-08-23. No reviewer email address, token, or tenant identifier is recorded
in the repository.

| Check | Result |
| --- | --- |
| Sign in | Passed; the tenant-scoped workspace and conversation list loaded |
| Minimal Chat request | Passed; `Staging smoke test. Reply only: OK.` returned `OK.` |
| Chat persistence | Passed; reload retained the smoke conversation URL and messages |
| Memory navigation and refresh | Passed; reload retained `#/memory` and the Memory Ledger |
| Persisted Research recovery | Passed; the saved Research conversation reopened as `Research stopped` at `1 / 6 steps` |
| Research route refresh | Passed; reload retained the exact Research URL and stopped state with no browser console error |
| Harmless TXT upload | Not completed through the in-app browser because its file chooser timed out before any file was selected; no file was transmitted |
| New live Research run | Not repeated because the configured OpenAI project has insufficient balance; this avoids a misleading provider failure and additional cost |
| Active-job Stop click | Not repeated without a funded live job; the previously stopped job and deterministic cancellation tests provide recovery evidence |
| Completed used-source report | Covered by deterministic citation/source tests and the local demo; the available staging Research job is stopped before synthesis |
| Insight Diff | Covered by the zero-cost local demo and deterministic frontend/backend tests |
| Sign out | Not performed so the reviewer session remains available for follow-up checks |
| Account deletion | Deliberately not performed on the persistent account; use a disposable reviewer account |

The authenticated browser session produced no console errors during Chat or
Research refresh recovery. Live Chat and Research checks may incur provider
cost. Account deletion is never performed on a persistent user account merely
for smoke testing.

The Chat smoke conversation remains in the reviewer's workspace. Its deletion
requires an explicit confirmation because it removes cloud data.

## Known limitations and deliberate omissions

- With scale-to-zero enabled, the first API request after inactivity may take
  roughly six seconds; warm p95 was about 65 ms in the bounded check.
- Saved OpenAI background Responses can be reconciled after reopening, but Mind
  does not promise autonomous phase advancement while no client or API request
  is active because Cloud Tasks are intentionally omitted.
- Research depends on server-side OpenAI credit and model access. Quota
  exhaustion fails immediately with a non-retryable safe error.
- Chat depends on the configured DeepSeek key and account balance.
- Full cost telemetry, custom monitoring dashboards and alerts, scheduled
  Heartbeats, notifications, a separate production project, large-scale load
  testing, long-term Memory decay/cleanup, automatic Research refresh, Voice,
  Google Drive, MCP, multi-agent orchestration, and multiple Research providers
  are outside the submission scope. Per-user Chat and Research limits are
  enforced server-side.

## Zero-cost Insight Diff demonstration

For local reviewer screenshots without a model call:

```bash
npm run seed:insight-diff-demo
npm run dev
```

The seeder creates one conversation covering all four change categories and a
second conversation showing the no-material-change state. It modifies only
ignored local demo data.
