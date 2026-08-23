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

## Authenticated reviewer smoke checklist

The following checks require an existing verified Firebase user and intentional
interaction with live model providers:

- [ ] Sign in and sign out.
- [ ] Open and refresh an existing Chat conversation.
- [ ] Send one minimal Chat request.
- [ ] Upload and remove one harmless TXT or PDF fixture.
- [ ] Open Memory, refresh it, and confirm the route remains on Memory.
- [ ] Start one minimal Research Job and observe stage updates.
- [ ] Explicitly stop an active Research Job.
- [ ] Open a completed cited report and its used-source list.
- [ ] Run or inspect the local zero-cost Insight Diff demo.
- [ ] Verify account deletion only with a disposable reviewer account.

Live Chat and Research checks may incur provider cost. Account deletion is not
performed on a persistent user account merely for smoke testing.

## Known limitations and deliberate omissions

- With scale-to-zero enabled, the first API request after inactivity may take
  roughly six seconds; warm p95 was about 65 ms in the bounded check.
- Saved OpenAI background Responses can be reconciled after reopening, but Mind
  does not promise autonomous phase advancement while no client or API request
  is active because Cloud Tasks are intentionally omitted.
- Research depends on server-side OpenAI credit and model access. Quota
  exhaustion fails immediately with a non-retryable safe error.
- Chat depends on the configured DeepSeek key and account balance.
- Daily user quotas, full cost telemetry, custom monitoring dashboards and
  alerts, scheduled Heartbeats, notifications, a separate production project,
  large-scale load testing, long-term Memory decay/cleanup, automatic Research
  refresh, Voice, Google Drive, MCP, multi-agent orchestration, and multiple
  Research providers are outside the submission scope.

## Zero-cost Insight Diff demonstration

For local reviewer screenshots without a model call:

```bash
npm run seed:insight-diff-demo
npm run dev
```

The seeder creates one conversation covering all four change categories and a
second conversation showing the no-material-change state. It modifies only
ignored local demo data.
