# Evaluation fixtures

These cases define product behavior before a billable model is connected.

- Pull requests use the deterministic Fake Agent and make zero model calls.
- Nightly and pre-release suites may opt into the configured Research model
  using a separate service identity and evaluation budget.
- User-facing chat and research quotas never apply to the internal eval runner.

`research-quality-cases.json` defines deterministic acceptance targets for
Research reports. `backend.research_quality.evaluate_research_quality` compares
source count, authoritative-source ratio, citation coverage, conflict detection,
and expected-fact correctness without making billable model calls. Keep the case
expectations stable when comparing provider models or prompt versions.

Production synthesis uses the same sentence-level claim segmentation. A draft
below `MIND_RESEARCH_MIN_CITATION_COVERAGE` receives one persisted citation-repair
Response and at most one follow-up repair; unresolved low coverage remains a
retryable Research failure.

The Background-mode regression case additionally requires the current canonical
Background and data-controls guides so citation quantity cannot mask stale facts.
