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
