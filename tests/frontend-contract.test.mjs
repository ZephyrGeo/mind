import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("built page contains the Mind product shell", async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  const bundle = await readFile(
    new URL("../dist/assets/app.js", import.meta.url),
    "utf8",
  );

  assert.match(html, /Mind — Personal AI workspace/);
  assert.match(bundle, /What should we make sense of/);
  assert.match(bundle, /Fake Provider · no model calls · no cloud cost/);
  assert.match(bundle, /DeepSeek Provider · model calls may incur cost/);
  assert.match(bundle, /\/api\/health/);
  assert.match(bundle, /Authorization/);
  assert.match(bundle, /text\/event-stream/);
});

test("built stylesheet includes responsive and reduced-motion behavior", async () => {
  const css = await readFile(
    new URL("../dist/assets/styles.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /\.sidebar-container\.open/);
});
