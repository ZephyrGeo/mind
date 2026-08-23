# Small staging concurrency check

Checked: 2026-08-23

## Purpose

This is the deliberately bounded capacity evidence for the Mind submission. It
checks that the public Cloud Run health endpoint and Firebase Hosting frontend
remain available under a small concurrent burst. It does not call Chat,
Research, Memory, OpenAI, or DeepSeek and therefore creates no model spend.

## Method

- Environment: `mind-staging-ce427`
- API target: `https://mind-api-staging-jasp5jgzxq-an.a.run.app/api/health`
- Web target: `https://mind-staging-ce427.web.app/`
- Requests: 20 per target per run
- Concurrent workers: 5
- Timeout: 10 seconds per request
- Success criterion: every response is HTTP 2xx

Reproduce with:

```bash
npm run check:concurrency -- \
  https://mind-api-staging-jasp5jgzxq-an.a.run.app/api/health \
  https://mind-staging-ce427.web.app/
```

## Results

| Run | Target | Success | Failure | p50 | p95 | Maximum |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Scale-from-zero | Cloud Run health | 20 | 0 | 41.9 ms | 6,289.0 ms | 6,299.9 ms |
| Scale-from-zero | Firebase Hosting | 20 | 0 | 15.6 ms | 63.8 ms | 64.9 ms |
| Warm repeat | Cloud Run health | 20 | 0 | 34.2 ms | 65.3 ms | 77.3 ms |
| Warm repeat | Firebase Hosting | 20 | 0 | 15.4 ms | 46.5 ms | 47.3 ms |

All 80 requests succeeded. The first Cloud Run burst exposed the expected
scale-to-zero cold-start cost; the immediate warm repeat returned to a 65.3 ms
p95. The submission retains scale-to-zero to avoid idle cost and documents that
the first API request after inactivity may take roughly six seconds.

## Interpretation and limits

This check supports only a modest reviewer-facing submission workload. It does
not validate the stated upper assumptions of 20 concurrent Chat streams or five
concurrent Research jobs, because exercising those paths would create provider
cost and rate-limit noise. Per-job Research concurrency remains bounded at two
search workers, and only one active Research job is allowed per user.

Large-scale load testing, capacity certification, custom dashboards, and alert
configuration are intentionally outside the submission scope.
