import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { build } from "./build.mjs";

const root = path.resolve(import.meta.dirname, "..");
const projectId = process.env.MIND_FIREBASE_PROJECT_ID ?? "mind-staging-ce427";
const region = process.env.MIND_GCP_REGION ?? "asia-northeast1";
const serviceName = process.env.MIND_CLOUD_RUN_SERVICE ?? "mind-api-staging";
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

const envFlag = gcloudDictionary([
  "MIND_ENV=staging",
  "MIND_AUTH_PROVIDER=firebase",
  `MIND_FIREBASE_PROJECT_ID=${projectId}`,
  `MIND_ALLOWED_USER_EMAILS=${allowedEmails}`,
  "MIND_REQUIRE_VERIFIED_EMAIL=1",
  "MIND_FIREBASE_CHECK_REVOKED=1",
  "MIND_PERSISTENCE_PROVIDER=firestore",
  "MIND_FIRESTORE_DATABASE_ID=(default)",
  `MIND_ALLOWED_ORIGINS=${hostingOrigins}`,
  "MIND_MODEL_PROVIDER=deepseek",
  `MIND_DEEPSEEK_MODEL=${process.env.MIND_DEEPSEEK_MODEL ?? "deepseek-v4-flash"}`,
  "MIND_RESEARCH_PROVIDER=openai",
  `MIND_RESEARCH_MODEL=${process.env.MIND_RESEARCH_MODEL ?? "gpt-5.6-terra"}`,
  `MIND_RESEARCH_REASONING_EFFORT=${process.env.MIND_RESEARCH_REASONING_EFFORT ?? "high"}`,
  `MIND_RESEARCH_MAX_TOOL_CALLS=${process.env.MIND_RESEARCH_MAX_TOOL_CALLS ?? "12"}`,
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
  "300",
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
