const targets = (
  process.argv.slice(2).length
    ? process.argv.slice(2)
    : (process.env.MIND_CONCURRENCY_TARGETS ?? "").split(",")
)
  .map((value) => value.trim())
  .filter(Boolean)
  .map((value) => new URL(value));

if (!targets.length) {
  console.error(
    "Provide one or more HTTP(S) targets as arguments or MIND_CONCURRENCY_TARGETS.",
  );
  process.exit(2);
}

for (const target of targets) {
  if (!new Set(["http:", "https:"]).has(target.protocol)) {
    throw new Error(`Unsupported target protocol: ${target.protocol}`);
  }
}

function boundedInteger(name, fallback, maximum) {
  const value = Number.parseInt(process.env[name] ?? String(fallback), 10);
  if (!Number.isInteger(value) || value < 1 || value > maximum) {
    throw new Error(`${name} must be an integer from 1 to ${maximum}.`);
  }
  return value;
}

const requestsPerTarget = boundedInteger("MIND_CONCURRENCY_REQUESTS", 20, 100);
const concurrency = boundedInteger("MIND_CONCURRENCY_WORKERS", 5, 10);
const timeoutMs = boundedInteger("MIND_CONCURRENCY_TIMEOUT_MS", 10_000, 60_000);

function percentile(values, ratio) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.max(0, Math.ceil(sorted.length * ratio) - 1);
  return Math.round(sorted[index] * 10) / 10;
}

async function checkTarget(target) {
  let nextRequest = 0;
  const observations = [];

  async function worker() {
    while (nextRequest < requestsPerTarget) {
      const requestNumber = nextRequest;
      nextRequest += 1;
      const startedAt = performance.now();
      try {
        const response = await fetch(target, {
          headers: {
            accept: "application/json,text/html;q=0.9,*/*;q=0.8",
            "cache-control": "no-cache",
            "user-agent": "mind-small-concurrency-check/1.0",
          },
          redirect: "follow",
          signal: AbortSignal.timeout(timeoutMs),
        });
        await response.arrayBuffer();
        observations.push({
          requestNumber,
          durationMs: performance.now() - startedAt,
          status: response.status,
          ok: response.ok,
        });
      } catch (error) {
        observations.push({
          requestNumber,
          durationMs: performance.now() - startedAt,
          status: null,
          ok: false,
          error: error instanceof Error ? error.name : "UnknownError",
        });
      }
    }
  }

  const startedAt = performance.now();
  await Promise.all(
    Array.from({ length: Math.min(concurrency, requestsPerTarget) }, worker),
  );

  const durations = observations.map((item) => item.durationMs);
  const statusCounts = {};
  for (const item of observations) {
    const key = item.status == null ? item.error : String(item.status);
    statusCounts[key] = (statusCounts[key] ?? 0) + 1;
  }

  return {
    target: target.toString(),
    requests: observations.length,
    concurrency: Math.min(concurrency, requestsPerTarget),
    successes: observations.filter((item) => item.ok).length,
    failures: observations.filter((item) => !item.ok).length,
    statusCounts,
    p50Ms: percentile(durations, 0.5),
    p95Ms: percentile(durations, 0.95),
    maxMs: percentile(durations, 1),
    wallTimeMs: Math.round((performance.now() - startedAt) * 10) / 10,
  };
}

const results = [];
for (const target of targets) {
  results.push(await checkTarget(target));
}

console.log(
  JSON.stringify(
    {
      checkedAt: new Date().toISOString(),
      requestsPerTarget,
      configuredConcurrency: concurrency,
      timeoutMs,
      results,
    },
    null,
    2,
  ),
);

if (results.some((result) => result.failures > 0)) {
  process.exitCode = 1;
}
