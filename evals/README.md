# Evaluation fixtures

These cases define product behavior before a billable model is connected.

- Pull requests use the deterministic Fake Agent and make zero model calls.
- Nightly and pre-release suites will later opt into Gemini using a separate
  service identity and evaluation budget.
- User-facing chat and research quotas never apply to the internal eval runner.
