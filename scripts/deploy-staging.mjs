import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { build } from "./build.mjs";
import {
  hasMemoryVectorIndex,
  isAlreadyExistsError,
} from "./firestore-indexes.mjs";

const root = path.resolve(import.meta.dirname, "..");
const projectId = process.env.MIND_FIREBASE_PROJECT_ID ?? "mind-staging-ce427";
const region = process.env.MIND_GCP_REGION ?? "asia-northeast1";
const serviceName = process.env.MIND_CLOUD_RUN_SERVICE ?? "mind-api-staging";
const fileBucket =
  process.env.MIND_FILE_STORAGE_BUCKET ?? `${projectId}-mind-files`;
const serviceAccountName = "mind-api-staging";
const serviceAccount = `${serviceAccountName}@${projectId}.iam.gserviceaccount.com`;
const buildServiceAccountName = "mind-build-staging";
const buildServiceAccount = `${buildServiceAccountName}@${projectId}.iam.gserviceaccount.com`;
const hostingOrigins = [
  `https://${projectId}.web.app`,
  `https://${projectId}.firebaseapp.com`,
].join(",");
const bundledGcloud = "/Users/fuyimin/Documents/Codex/tools/google-cloud-sdk/bin/gcloud";
const gcloud = process.env.GCLOUD ?? (existsSync(bundledGcloud) ? bundledGcloud : "gcloud");

function requireValue(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for staging deployment.`);
  return value;
}

function run(command, args, options = {}) {
  const stdio = options.capture
    ? ["pipe", "pipe", "inherit"]
    : options.input !== undefined
      ? ["pipe", "inherit", "inherit"]
      : "inherit";
  const result = spawnSync(command, args, {
    cwd: root,
    env: process.env,
    encoding: "utf8",
    stdio,
    input: options.input,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} ${args[0]} failed.`);
  }
  return options.capture ? result.stdout.trim() : "";
}

function succeeds(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: process.env,
    stdio: "ignore",
  });
  return result.status === 0;
}

function gcloudDictionary(entries, delimiter = "|") {
  for (const entry of entries) {
    if (entry.includes(delimiter)) {
      throw new Error(
        `Cloud Run environment value contains the reserved ${delimiter} delimiter.`,
      );
    }
  }
  return `^${delimiter}^${entries.join(delimiter)}`;
}

function ensureSecret(secretId, value) {
  if (!succeeds(gcloud, ["secrets", "describe", secretId, "--project", projectId])) {
    run(gcloud, [
      "secrets",
      "create",
      secretId,
      "--project",
      projectId,
      "--replication-policy",
      "user-managed",
      "--locations",
      region,
      "--quiet",
    ]);
  }
  const versions = spawnSync(
    gcloud,
    [
      "secrets",
      "versions",
      "list",
      secretId,
      "--project",
      projectId,
      "--filter=state:ENABLED",
      "--limit=1",
      "--format=value(name)",
    ],
    {
      cwd: root,
      env: process.env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "inherit"],
    },
  );
  if (
    versions.status === 0 &&
    versions.stdout.trim() &&
    process.env.MIND_ROTATE_STAGING_SECRETS !== "1"
  ) {
    console.log(`Reusing the enabled ${secretId} version.`);
    return;
  }
  run(
    gcloud,
    [
      "secrets",
      "versions",
      "add",
      secretId,
      "--project",
      projectId,
      "--data-file=-",
      "--quiet",
    ],
    { input: value },
  );
}

function ensureServiceAccount(accountName, accountEmail, displayName) {
  if (
    succeeds(gcloud, [
      "iam",
      "service-accounts",
      "describe",
      accountEmail,
      "--project",
      projectId,
    ])
  ) {
    return;
  }
  run(gcloud, [
    "iam",
    "service-accounts",
    "create",
    accountName,
    "--project",
    projectId,
    "--display-name",
    displayName,
    "--quiet",
  ]);
}

function ensureMemoryVectorIndex() {
  const dimensions = Number(process.env.MIND_EMBEDDING_DIMENSIONS ?? "256");
  if (!Number.isInteger(dimensions) || dimensions < 32 || dimensions > 2048) {
    throw new Error("MIND_EMBEDDING_DIMENSIONS must be an integer from 32 to 2048.");
  }
  const rawIndexes = run(
    gcloud,
    [
      "firestore",
      "indexes",
      "composite",
      "list",
      "--project",
      projectId,
      "--database",
      "(default)",
      "--format=json",
    ],
    { capture: true },
  );
  const indexes = rawIndexes ? JSON.parse(rawIndexes) : [];
  const exists = hasMemoryVectorIndex(indexes, dimensions);
  if (exists) {
    console.log(`Reusing the ${dimensions}-dimension Memory vector index.`);
    return;
  }
  const result = spawnSync(
    gcloud,
    [
      "firestore",
      "indexes",
      "composite",
      "create",
      "--project",
      projectId,
      "--database",
      "(default)",
      "--collection-group",
      "memories",
      "--query-scope",
      "COLLECTION",
      "--field-config",
      `field-path=embedding,vector-config={dimension=${dimensions},flat}`,
      "--async",
      "--quiet",
    ],
    {
      cwd: root,
      env: process.env,
      encoding: "utf8",
      stdio: ["ignore", "inherit", "pipe"],
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    if (isAlreadyExistsError(result.stderr)) {
      console.log(`Reusing the ${dimensions}-dimension Memory vector index.`);
      return;
    }
    if (result.stderr) process.stderr.write(result.stderr);
    throw new Error(`${path.basename(gcloud)} firestore failed.`);
  }
  console.log(
    "Memory vector index creation started; bounded fallback retrieval remains available while it builds.",
  );
}

function ensureFileBucket() {
  const bucketUri = `gs://${fileBucket}`;
  if (!succeeds(gcloud, ["storage", "buckets", "describe", bucketUri])) {
    run(gcloud, [
      "storage",
      "buckets",
      "create",
      bucketUri,
      "--project",
      projectId,
      "--location",
      region,
      "--uniform-bucket-level-access",
      "--public-access-prevention",
      "--soft-delete-duration=0",
      "--quiet",
    ]);
  }
  run(gcloud, [
    "storage",
    "buckets",
    "update",
    bucketUri,
    "--uniform-bucket-level-access",
    "--public-access-prevention",
    "--soft-delete-duration=0",
    "--quiet",
  ]);
  run(gcloud, [
    "storage",
    "buckets",
    "add-iam-policy-binding",
    bucketUri,
    "--member",
    `serviceAccount:${serviceAccount}`,
    "--role",
    "roles/storage.objectAdmin",
    "--quiet",
  ]);
}

const openaiApiKey = requireValue("OPENAI_API_KEY");
const deepseekApiKey = requireValue("DEEPSEEK_API_KEY");
const allowedEmails = requireValue("MIND_ALLOWED_USER_EMAILS");
requireValue("MIND_PUBLIC_FIREBASE_API_KEY");
requireValue("MIND_PUBLIC_FIREBASE_APP_ID");

console.log(`Deploying Mind staging to ${projectId} (${region})...`);

run(gcloud, ["config", "set", "project", projectId, "--quiet"]);
run(gcloud, [
  "services",
  "enable",
  "artifactregistry.googleapis.com",
  "cloudbuild.googleapis.com",
  "firestore.googleapis.com",
  "firebase.googleapis.com",
  "iam.googleapis.com",
  "identitytoolkit.googleapis.com",
  "run.googleapis.com",
  "secretmanager.googleapis.com",
  "storage.googleapis.com",
  "--project",
  projectId,
  "--quiet",
]);

if (
  !succeeds(gcloud, [
    "artifacts",
    "repositories",
    "describe",
    "cloud-run-source-deploy",
    "--project",
    projectId,
    "--location",
    region,
  ])
) {
  run(gcloud, [
    "artifacts",
    "repositories",
    "create",
    "cloud-run-source-deploy",
    "--project",
    projectId,
    "--location",
    region,
    "--repository-format",
    "docker",
    "--description",
    "Cloud Run source deployments for Mind staging",
    "--quiet",
  ]);
}

ensureServiceAccount(serviceAccountName, serviceAccount, "Mind staging API");
ensureServiceAccount(
  buildServiceAccountName,
  buildServiceAccount,
  "Mind staging image builder",
);
ensureFileBucket();

for (const role of [
  "roles/datastore.user",
  "roles/firebaseauth.admin",
  "roles/logging.logWriter",
  "roles/secretmanager.secretAccessor",
]) {
  run(gcloud, [
    "projects",
    "add-iam-policy-binding",
    projectId,
    "--member",
    `serviceAccount:${serviceAccount}`,
    "--role",
    role,
    "--condition=None",
    "--quiet",
  ]);
}
run(gcloud, [
  "projects",
  "add-iam-policy-binding",
  projectId,
  "--member",
  `serviceAccount:${buildServiceAccount}`,
  "--role",
  "roles/run.builder",
  "--condition=None",
  "--quiet",
]);

const openaiSecret = "mind-openai-api-key-staging";
const deepseekSecret = "mind-deepseek-api-key-staging";
ensureSecret(openaiSecret, openaiApiKey);
ensureSecret(deepseekSecret, deepseekApiKey);

run("firebase", [
  "deploy",
  "--project",
  projectId,
  "--only",
  "firestore:rules,firestore:indexes",
  "--non-interactive",
]);
ensureMemoryVectorIndex();

const envFlag = gcloudDictionary([
  "MIND_ENV=staging",
  "MIND_AUTH_PROVIDER=firebase",
  `MIND_FIREBASE_PROJECT_ID=${projectId}`,
  `MIND_ALLOWED_USER_EMAILS=${allowedEmails}`,
  "MIND_REQUIRE_VERIFIED_EMAIL=1",
  "MIND_FIREBASE_CHECK_REVOKED=1",
  "MIND_PERSISTENCE_PROVIDER=firestore",
  "MIND_FIRESTORE_DATABASE_ID=(default)",
  "MIND_FILE_STORAGE_PROVIDER=gcs",
  `MIND_FILE_STORAGE_BUCKET=${fileBucket}`,
  `MIND_MAX_FILE_BYTES=${process.env.MIND_MAX_FILE_BYTES ?? "20000000"}`,
  `MIND_MAX_FILE_PAGES=${process.env.MIND_MAX_FILE_PAGES ?? "200"}`,
  `MIND_MAX_EXTRACTED_FILE_CHARACTERS=${process.env.MIND_MAX_EXTRACTED_FILE_CHARACTERS ?? "120000"}`,
  `MIND_MAX_FILE_CONTEXT_CHARACTERS=${process.env.MIND_MAX_FILE_CONTEXT_CHARACTERS ?? "24000"}`,
  `MIND_MAX_FILES_PER_REQUEST=${process.env.MIND_MAX_FILES_PER_REQUEST ?? "5"}`,
  `MIND_MEMORY_RETRIEVAL_LIMIT=${process.env.MIND_MEMORY_RETRIEVAL_LIMIT ?? "5"}`,
  `MIND_MEMORY_MAX_CONTEXT_CHARACTERS=${process.env.MIND_MEMORY_MAX_CONTEXT_CHARACTERS ?? "4000"}`,
  "MIND_MEMORY_PROVIDER=openai",
  `MIND_MEMORY_MODEL=${process.env.MIND_MEMORY_MODEL ?? "gpt-5.4-mini"}`,
  `MIND_MEMORY_REASONING_EFFORT=${process.env.MIND_MEMORY_REASONING_EFFORT ?? "low"}`,
  `MIND_MEMORY_TIMEOUT_SECONDS=${process.env.MIND_MEMORY_TIMEOUT_SECONDS ?? "45"}`,
  "MIND_EMBEDDING_PROVIDER=openai",
  `MIND_EMBEDDING_MODEL=${process.env.MIND_EMBEDDING_MODEL ?? "text-embedding-3-small"}`,
  `MIND_EMBEDDING_DIMENSIONS=${process.env.MIND_EMBEDDING_DIMENSIONS ?? "256"}`,
  `MIND_MEMORY_SEMANTIC_THRESHOLD=${process.env.MIND_MEMORY_SEMANTIC_THRESHOLD ?? "0.68"}`,
  `MIND_ALLOWED_ORIGINS=${hostingOrigins}`,
  "MIND_MODEL_PROVIDER=deepseek",
  `MIND_DEEPSEEK_MODEL=${process.env.MIND_DEEPSEEK_MODEL ?? "deepseek-v4-flash"}`,
  "MIND_RESEARCH_PROVIDER=openai",
  `MIND_RESEARCH_MODEL=${process.env.MIND_RESEARCH_MODEL ?? "gpt-5.6-terra"}`,
  `MIND_RESEARCH_REASONING_EFFORT=${process.env.MIND_RESEARCH_REASONING_EFFORT ?? "high"}`,
  `MIND_RESEARCH_MAX_TOOL_CALLS=${process.env.MIND_RESEARCH_MAX_TOOL_CALLS ?? "12"}`,
  `MIND_RESEARCH_MAX_SEARCH_ROUNDS=${process.env.MIND_RESEARCH_MAX_SEARCH_ROUNDS ?? "2"}`,
  `MIND_RESEARCH_MAX_SUBQUESTIONS=${process.env.MIND_RESEARCH_MAX_SUBQUESTIONS ?? "6"}`,
  `MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS=${process.env.MIND_RESEARCH_MAX_TOTAL_TOOL_CALLS ?? "24"}`,
  `MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO=${process.env.MIND_RESEARCH_TOOL_CALL_OVERRUN_RATIO ?? "0.15"}`,
  `MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN=${process.env.MIND_RESEARCH_MAX_TOOL_CALL_OVERRUN ?? "3"}`,
  `MIND_RESEARCH_MIN_CITATION_COVERAGE=${process.env.MIND_RESEARCH_MIN_CITATION_COVERAGE ?? "0.8"}`,
  `MIND_RESEARCH_SOFT_TIMEOUT_SECONDS=${process.env.MIND_RESEARCH_SOFT_TIMEOUT_SECONDS ?? "420"}`,
  `MIND_RESEARCH_JOB_TIMEOUT_SECONDS=${process.env.MIND_RESEARCH_JOB_TIMEOUT_SECONDS ?? "600"}`,
  `MIND_RESEARCH_MAX_CONCURRENT_SEARCHES=${process.env.MIND_RESEARCH_MAX_CONCURRENT_SEARCHES ?? "2"}`,
  `MIND_RESEARCH_MAX_TRANSPORT_RETRIES=${process.env.MIND_RESEARCH_MAX_TRANSPORT_RETRIES ?? "5"}`,
  `MIND_RESEARCH_MAX_RATE_LIMIT_RETRIES=${process.env.MIND_RESEARCH_MAX_RATE_LIMIT_RETRIES ?? "3"}`,
  `MIND_RESEARCH_MAX_STAGE_ATTEMPTS=${process.env.MIND_RESEARCH_MAX_STAGE_ATTEMPTS ?? "2"}`,
  `MIND_RESEARCH_RETRY_BASE_SECONDS=${process.env.MIND_RESEARCH_RETRY_BASE_SECONDS ?? "2"}`,
  `MIND_RESEARCH_MAX_EVIDENCE_CHARACTERS=${process.env.MIND_RESEARCH_MAX_EVIDENCE_CHARACTERS ?? "60000"}`,
]);

run(gcloud, [
  "run",
  "deploy",
  serviceName,
  "--project",
  projectId,
  "--region",
  region,
  "--source",
  ".",
  "--build-service-account",
  `projects/${projectId}/serviceAccounts/${buildServiceAccount}`,
  "--service-account",
  serviceAccount,
  "--allow-unauthenticated",
  "--cpu",
  "1",
  "--memory",
  "512Mi",
  "--min-instances",
  "0",
  "--max-instances",
  "2",
  "--concurrency",
  "20",
  "--timeout",
  "900",
  "--set-env-vars",
  envFlag,
  "--set-secrets",
  `OPENAI_API_KEY=${openaiSecret}:latest,DEEPSEEK_API_KEY=${deepseekSecret}:latest`,
  "--quiet",
]);

const apiUrl = run(
  gcloud,
  [
    "run",
    "services",
    "describe",
    serviceName,
    "--project",
    projectId,
    "--region",
    region,
    "--format=value(status.url)",
  ],
  { capture: true },
);
if (!apiUrl.startsWith("https://")) {
  throw new Error("Cloud Run did not return a valid HTTPS service URL.");
}

process.env.MIND_PUBLIC_API_BASE = apiUrl;
await build();
run("firebase", [
  "deploy",
  "--project",
  projectId,
  "--only",
  "hosting",
  "--non-interactive",
]);

const healthResponse = await fetch(`${apiUrl}/api/health`);
if (!healthResponse.ok) {
  throw new Error(`Staging health check failed with ${healthResponse.status}.`);
}
const health = await healthResponse.json();
if (health.environment !== "staging" || health.status !== "ok") {
  throw new Error("Staging health response did not match the deployment.");
}

console.log("Mind staging deployment completed.");
console.log(`Web: https://${projectId}.web.app`);
console.log(`API: ${apiUrl}`);
