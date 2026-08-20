import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("local development loads an optional ignored environment file", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  const gitignore = await readFile(
    new URL("../.gitignore", import.meta.url),
    "utf8",
  );
  const example = await readFile(
    new URL("../.env.example", import.meta.url),
    "utf8",
  );

  assert.equal(
    packageJson.scripts.dev,
    "node --env-file-if-exists=.env.local scripts/start-local.mjs",
  );
  assert.match(gitignore, /^\.env\.\*$/m);
  assert.match(example, /^DEEPSEEK_API_KEY=$/m);
  assert.doesNotMatch(example, /^DEEPSEEK_API_KEY=.+$/m);
  assert.match(example, /^OPENAI_API_KEY=$/m);
  assert.doesNotMatch(example, /^OPENAI_API_KEY=.+$/m);
  assert.match(example, /^MIND_RESEARCH_PROVIDER=openai$/m);
  assert.match(example, /^MIND_RESEARCH_MODEL=gpt-5\.6-terra$/m);
  assert.match(example, /^MIND_AUTH_PROVIDER=local$/m);
  assert.match(example, /^MIND_PERSISTENCE_PROVIDER=json$/m);
  assert.match(example, /^MIND_FIRESTORE_DATABASE_ID=\(default\)$/m);
  assert.match(example, /^MIND_FILE_STORAGE_PROVIDER=local$/m);
  assert.match(example, /^MIND_MAX_FILE_BYTES=20000000$/m);
  assert.match(example, /^MIND_MEMORY_PROVIDER=rules$/m);
  assert.match(example, /^MIND_MEMORY_MODEL=gpt-5\.4-mini$/m);
  assert.match(example, /^MIND_EMBEDDING_PROVIDER=local$/m);
  assert.match(example, /^MIND_EMBEDDING_MODEL=text-embedding-3-small$/m);
  assert.match(example, /^MIND_EMBEDDING_DIMENSIONS=256$/m);
  assert.doesNotMatch(example, /TAVILY_API_KEY|MIND_SEARCH_PROVIDER/);
});

test("test commands do not load the local billable provider configuration", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );

  assert.doesNotMatch(packageJson.scripts.test, /env-file/);
  assert.doesNotMatch(packageJson.scripts["test:backend"], /env-file/);
  assert.doesNotMatch(packageJson.scripts["test:all"], /env-file/);
});

test("staging grants the API Firebase Auth access and mounts model secrets", async () => {
  const deployScript = await readFile(
    new URL("../scripts/deploy-staging.mjs", import.meta.url),
    "utf8",
  );
  const terraform = await readFile(
    new URL("../infra/terraform/main.tf", import.meta.url),
    "utf8",
  );

  for (const source of [deployScript, terraform]) {
    assert.match(source, /identitytoolkit\.googleapis\.com/);
    assert.match(source, /roles\/firebaseauth\.admin/);
    assert.match(source, /MIND_FIREBASE_CHECK_REVOKED/);
    assert.match(source, /MIND_MEMORY_RETRIEVAL_LIMIT/);
    assert.match(source, /MIND_MEMORY_MAX_CONTEXT_CHARACTERS/);
    assert.match(source, /MIND_MEMORY_PROVIDER/);
    assert.match(source, /MIND_MEMORY_MODEL/);
    assert.match(source, /MIND_EMBEDDING_PROVIDER/);
    assert.match(source, /MIND_EMBEDDING_MODEL/);
    assert.match(source, /MIND_EMBEDDING_DIMENSIONS/);
    assert.match(source, /MIND_FILE_STORAGE_PROVIDER/);
    assert.match(source, /MIND_FILE_STORAGE_BUCKET/);
    assert.match(source, /MIND_MAX_FILE_BYTES/);
  }
  assert.match(deployScript, /ensureFileBucket/);
  assert.match(deployScript, /roles\/storage\.objectAdmin/);
  assert.match(terraform, /google_storage_bucket" "files/);
  assert.match(terraform, /public_access_prevention\s*=\s*"enforced"/);
  assert.match(terraform, /retention_duration_seconds\s*=\s*0/);
  assert.match(deployScript, /--soft-delete-duration=0/);
  assert.match(deployScript, /ensureMemoryVectorIndex/);
  assert.match(deployScript, /collection-group["',\s]+memories/);
  assert.match(terraform, /google_firestore_index" "memory_embedding/);
  assert.match(terraform, /vector_config/);
  assert.match(deployScript, /OPENAI_API_KEY=.*:latest/);
  assert.match(deployScript, /DEEPSEEK_API_KEY=.*:latest/);
});
