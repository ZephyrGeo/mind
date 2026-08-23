# Mind Personal Agent — Final Submission Plan

Updated: 2026-08-23

## Product direction

Mind is a personal AI workspace for conversations, evidence-backed research,
user-controlled memory, and structured tracking of how research conclusions
change over time.

OpenAI supplies replaceable model inference, background Responses, and built-in
web search. Mind owns the Research Harness: planning, bounded parallel search,
evidence verification, conflict checks, synthesis, persistence, recovery,
cancellation, source normalization, report snapshots, and Insight Diff.

The submission focuses on a complete reviewer journey instead of expanding the
system with additional automation or infrastructure.

## Final scope decision

The current stable Firebase Hosting and Cloud Run staging deployment is the
submission environment. It will not be promoted to a separate production
project for this submission.

### Included

- Firebase registration, verification, login, logout, and account deletion.
- Tenant-scoped Chat conversations with the configured Chat provider.
- TXT and PDF upload with private storage, bounded extraction, and provenance.
- The OpenAI-backed multi-stage Research Harness.
- Persisted Research Jobs and provider response IDs.
- Refresh recovery, explicit stop, safe restart, and duplicate-message guards.
- Per-job search-round, tool-call, concurrency, retry, and duration limits.
- Used-source-only reports with stable, clickable citation numbering.
- User-controlled Memory Ledger with semantic retrieval and conflict review.
- Manual **Compare with latest evidence** from a completed Research report.
- Immutable baseline and latest report snapshots.
- Claim-level `New`, `Changed`, `Contradicted`, and `Stale` Insight Diff with
  evidence preserved on both sides.
- Deterministic CI, Terraform validation, one-command staging deployment, a
  reviewer smoke test, and one small concurrency test.

### Deliberately omitted

- Cloud Tasks background reconciliation or automatic offline advancement.
- Cloud Scheduler and scheduled Heartbeats.
- Email, mobile push, or other background notifications.
- Daily user quotas; existing per-job Research budgets remain.
- Full usage telemetry, a cost dashboard, or custom Cloud Monitoring dashboards
  and alerts.
- A separate production project or GitHub Actions production release.
- Large-scale load testing.
- Long-term Memory decay, full-ledger cleanup, and automatic Research refresh.
- Voice, Google Drive, MCP, multi-agent orchestration, and multiple Research
  providers.
- Further non-blocking visual polish after the reviewer journey is stable.

These are explicit product decisions, not incomplete acceptance criteria.

## Acceptance map

| Requirement | Submission implementation |
| --- | --- |
| Conversational LLM | Existing Chat experience and `ModelProvider` boundary |
| Deep Research | OpenAI Responses API plus the Mind Research Harness |
| Identity | Firebase Authentication and account deletion |
| Non-text input | Bounded TXT and PDF upload through private Cloud Storage |
| Original feature 1 | User-controlled Memory Ledger |
| Original feature 2 | Manual Insight Diff between immutable Research snapshots |
| Web application | React frontend with FastAPI backend |
| Restricted access | Firebase identity plus configured allowlist |
| Persistence | Firestore for submission staging; JSON for local development |
| Google Cloud | Firebase Hosting, Cloud Run, Firestore, Cloud Storage, Secret Manager |
| IaC and CI | Terraform validation and deterministic GitHub Actions checks |
| Deployment | Deliberate `npm run deploy:staging` release and smoke test |
| Capacity evidence | Documented assumptions and one small concurrency test |

## Research Harness

### Ownership boundary

OpenAI owns model inference, web search, background Response execution,
retrieval, and cancellation. Mind owns:

- the `ResearchProvider` interface and provider-neutral job model;
- Research Brief generation and 4–6 bounded subquestions;
- parallel search scheduling within the per-job concurrency limit;
- evidence aggregation, gap analysis, and conflict detection;
- at most one bounded follow-up search round;
- cited synthesis and citation-repair attempts;
- response-ID persistence, status mapping, recovery, and cancellation;
- source deduplication, stable report citation numbering, and safe links;
- report snapshots and claim-level Insight Diff;
- tenant isolation, budgets, tests, and user experience.

OpenAI is the only Research provider enabled in the submission. The abstraction
is retained so a future model can replace it without rewriting
`ResearchService`; no alternative provider is exposed now.

### Job lifecycle

    queued → planning → collecting → verifying → comparing → synthesizing
                                                                  ↓
                                                              completed

Any active stage may become `failed` or `cancelled`. A retryable transport or
rate-limit failure uses bounded exponential backoff. Provider retry hints are
clamped to 30 seconds, and automatic rate-limit waiting is capped at 90 seconds
for the whole job. Quota exhaustion fails immediately and does not enter a
misleading retry loop.

Each Research Job stores its user and conversation, model, prompt version,
budget, stage, Research Brief, subtasks, response IDs, provider states, retry
state, sources, citations, report snapshots, Insight Diff, errors, and
timestamps.

### Recovery boundary

Refreshing or reopening a conversation retrieves the persisted job and existing
OpenAI Responses by saved ID; it does not create another job. Explicit Stop
cancels every active Response belonging to that job.

Without Cloud Tasks, Mind does not promise autonomous stage advancement while
no client or API request is active. OpenAI background Responses can continue,
and reopening the conversation reconciles their saved IDs and resumes the Mind
Harness. This limitation must be stated in the final report.

### Per-job guardrails

- At most two search rounds.
- Four to six initial subquestions by default.
- Whole-job soft and hard web-search call limits.
- Maximum two concurrent search workers by default.
- Soft search deadline and hard whole-job timeout.
- Bounded transport and rate-limit retries.
- Maximum active Research jobs per user.
- File type, size, page, and extracted-text limits.
- Request ownership and idempotency checks.
- Server-side secrets, redacted logs, and provider-neutral error messages.

No daily user quota is required for submission.

## Manual Insight Diff

The second original feature is a user-triggered evidence comparison, not an
update report that overwrites the previous result.

    Open completed Research report
            ↓
    Compare with latest evidence
            ↓
    Freeze current report as immutable baseline
            ↓
    Run the same Research Brief against current evidence
            ↓
    Save a separate latest report snapshot
            ↓
    Compare claims and evidence
            ↓
    Show New / Changed / Contradicted / Stale or
    No material changes detected

Required behavior:

- Baseline and latest reports remain independently viewable.
- The latest report never mutates the baseline.
- Changed and contradicted claims retain old and new evidence.
- Report citations show only sources used by the article, deduplicated by
  canonical URL and renumbered in order of first use.
- A completed comparison is persisted in the Research conversation.
- The user can continue the conversation after reviewing the report or Diff.
- Local zero-cost demo data covers all change categories and the no-change state.

Scheduled tracking, Watch records, Heartbeats, and notifications are out of
scope.

## Memory boundary

The Memory Ledger stores typed, user-visible entries with provenance,
confidence, sensitivity, enabled state, pinning, expiry, and superseded history.
It supports structured extraction, exact and semantic deduplication,
LLM-assisted update/conflict classification, OpenAI embeddings in staging, and
Firestore vector retrieval with lexical fallback.

Users can inspect, confirm, edit, enable, disable, pin, expire, and delete
memories. Disabled, unresolved, stale, or deleted memories do not enter model
context.

Periodic full-ledger consolidation, importance decay, and automatic refreshing
of Research-derived facts are explicitly omitted.

## Submission work remaining

### 1. Scope cleanup

Status: completed on 2026-08-23.

- Remove Heartbeats and Voice placeholder controls from the frontend.
- Remove claims of scheduled automation, production promotion, and daily quotas
  from canonical documentation.
- Keep local/demo files and unrelated user work out of commits.

### 2. Deterministic verification

Status: completed on 2026-08-23.

- Run frontend build and contract tests.
- Run backend lint, type checks, and tests.
- Run Terraform formatting and validation.
- Verify Research failure mappings, cancellation, refresh recovery, citation
  normalization, Insight Diff classification, tenant isolation, file ownership,
  and Memory controls.

Recorded result:

- `ruff check backend`: passed.
- CI-scoped Pyright check: 0 errors and 0 warnings.
- Frontend build/contracts: 15 passed; the emulator-only test was then run
  separately.
- Backend suite: 122 passed.
- Firebase Auth/Firestore Emulator tenant-isolation rules: 1 passed.
- Terraform 1.14.3 formatting and validation: passed.

### 3. Small concurrency check

Status: completed on 2026-08-23.

Run one bounded staging check that exercises a small number of simultaneous
read-only/low-cost requests. Record:

- tested concurrency and request mix;
- success and error counts;
- p50 and p95 latency;
- any Cloud Run scaling or provider-limit observation;
- the capacity assumptions below.

This is evidence for the submission, not a large load test.

Recorded result: two runs sent 20 requests per target with five concurrent
workers to the public Cloud Run health endpoint and Firebase Hosting. All 80
requests returned HTTP 200. The first Cloud Run burst recorded a 6,289.0 ms p95
from scale-to-zero; the immediate warm repeat recorded a 65.3 ms p95. See
`docs/capacity-check.md` for the complete method, results, and limitations.

### 4. Staging release and reviewer smoke test

Status: deployed on 2026-08-23; public/security checks and the available
authenticated checks passed. Provider-cost and destructive checks retain the
explicit limitations recorded in `docs/submission-readiness.md`.

- Deploy the selected revision with `npm run deploy:staging`.
- Verify API health and Firebase Hosting.
- Create and authenticate a reviewer account.
- Test Chat, TXT/PDF input, Research start/progress/stop, refresh recovery,
  sources, Memory, manual Insight Diff, and account deletion.
- Confirm secrets and private files are not exposed to the browser or repository.

Recorded authenticated result: Firebase sign-in, minimal Chat, Chat refresh
recovery, Memory refresh recovery, and persisted stopped-Research recovery
passed. A new paid Research run was not started after the OpenAI project balance
was found insufficient. The in-app browser file chooser timed out before any
fixture was selected, and account deletion remains reserved for a disposable
reviewer account.

### 5. Final documentation

Status: completed on 2026-08-23. The deployment, automated verification,
capacity evidence, known limitations, and authenticated reviewer evidence are
recorded in `docs/submission-readiness.md`.

- Record the staging URL and reviewer journey.
- Explain OpenAI versus Mind Harness ownership.
- Describe architecture, security, tenant isolation, testing, resilience,
  capacity assumptions, deliberate omissions, and known limitations.
- Include representative screenshots and local Insight Diff demo instructions.
- Confirm repository access and submission links.

## Capacity assumptions

- 1,000 registered users.
- 100 daily active users.
- 20 concurrent Chat streams at peak.
- 5 concurrent Research jobs across the service.
- 1 active Research job per user.
- 2 concurrent search workers inside one Research job.
- 20 MB maximum raw uploaded file.
- Cloud Run scale-to-zero with bounded instance concurrency.

Per-job budgets protect Research cost and duration. These assumptions are not a
promise of validated large-scale capacity; only the documented small
concurrency check is required before submission.

## Definition of done

Mind is submission-ready when a reviewer can:

1. Create an account, sign in, sign out, and delete the account.
2. Chat with the configured model.
3. Upload a TXT or PDF and use it in Chat or Research.
4. Start Research and inspect its current stage, report, citations, and sources.
5. Refresh or reopen the page and recover the same persisted Research Job.
6. Explicitly stop an active Research task.
7. Inspect and control everything Mind remembers.
8. Compare a completed report with latest evidence.
9. View immutable baseline/latest reports and structured, dual-evidence changes.
10. See a clear no-change result when no material change is found.
11. Use the current staging URL successfully.
12. Review passing CI, Terraform, tests, capacity notes, security decisions,
    deliberate omissions, and final documentation.
