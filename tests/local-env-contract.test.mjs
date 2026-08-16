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
  }
  assert.match(deployScript, /OPENAI_API_KEY=.*:latest/);
  assert.match(deployScript, /DEEPSEEK_API_KEY=.*:latest/);
});
