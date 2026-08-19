import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("built page contains the Mind product shell", async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  const bundle = await readFile(
    new URL("../dist/assets/app.js", import.meta.url),
    "utf8",
  );
  const source = await readFile(
    new URL("../frontend/app.js", import.meta.url),
    "utf8",
  );

  assert.match(html, /Mind — Personal AI workspace/);
  assert.match(html, /@phosphor-icons\/web@2\.1\.2/);
  assert.match(html, /\/runtime-config\.js/);
  assert.match(bundle, /What should we make sense of/);
  assert.match(bundle, /Fake Provider · no model calls · no cloud cost/);
  assert.match(bundle, /DeepSeek Provider · model calls may incur cost/);
  assert.match(bundle, /OpenAI Research Provider/);
  assert.match(bundle, /\/api\/health/);
  assert.match(bundle, /\/api\/conversations\/\$\{conversation\.id\}/);
  assert.match(bundle, /The conversation could not be opened/);
  assert.match(bundle, /Delete conversation/);
  assert.match(bundle, /Delete account/);
  assert.match(bundle, /\/api\/account/);
  assert.match(bundle, /method:\s*"DELETE"/);
  assert.match(bundle, /This cannot be undone/);
  assert.match(bundle, /Search conversations/);
  assert.match(bundle, /Previous 7 Days/);
  assert.match(bundle, /Previous 30 Days/);
  assert.match(bundle, /composer-mode-switch/);
  assert.match(bundle, /conversation-selector/);
  assert.match(bundle, /name:\s*"star-four"/);
  assert.match(bundle, /Collapse sidebar/);
  assert.match(bundle, /sidebarCollapsed/);
  assert.doesNotMatch(source, /conversations\.slice\(0,\s*5\)/);
  assert.match(bundle, /Authorization/);
  assert.match(bundle, /Create your workspace/);
  assert.match(bundle, /Verify your email/);
  assert.match(bundle, /Password reset email sent/);
  assert.match(bundle, /text\/event-stream/);
  assert.match(bundle, /error\.isApiError/);
  assert.match(bundle, /payload\?\.error\?\.message/);
  assert.match(bundle, /\/api\/research/);
  assert.match(bundle, /Resume OpenAI research/);
  assert.match(bundle, /Restart as a new OpenAI task/);
  assert.match(bundle, /research_started/);
  assert.match(bundle, /Research complete/);
  assert.match(bundle, /Planning research/);
  assert.match(bundle, /Searching sources/);
  assert.match(bundle, /Checking evidence/);
  assert.match(bundle, /Writing report/);
  assert.match(bundle, /This can take several minutes/);
  assert.match(bundle, /Used extra search budget/);
  assert.match(bundle, /Research budget limit reached/);
  assert.match(bundle, /OpenAI ·/);
  assert.match(bundle, /MarkdownContent/);
  assert.match(bundle, /message-link/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML/);
  assert.match(bundle, /target:\s*"_blank"/);
  assert.match(bundle, /\/cancel/);
  assert.match(bundle, /sources collected/);
  assert.match(bundle, /Search memories/);
  assert.match(bundle, /\/api\/memories/);
  assert.match(bundle, /Confirm memory/);
  assert.match(bundle, /Needs attention/);
  assert.match(bundle, /Update suggested/);
  assert.match(bundle, /Use this version/);
  assert.match(bundle, /Needs revalidation/);
  assert.match(bundle, /replaced memories/);
  assert.match(bundle, /Memory update needs review/);
  assert.match(bundle, /Review memory/);
  assert.match(bundle, /memories need review/);
  assert.match(bundle, /memory_candidates/);
  assert.match(bundle, /scrollIntoView/);
  assert.match(bundle, /Research job:/);
  assert.match(bundle, /Conversation:/);
  assert.match(bundle, /Sensitive credentials are rejected and never saved/);
  assert.match(bundle, /method:\s*"PATCH"/);
});

test("built stylesheet includes responsive and reduced-motion behavior", async () => {
  const css = await readFile(
    new URL("../dist/assets/styles.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /\.sidebar-container\.open/);
  assert.match(css, /\.conversation-group-label/);
  assert.match(css, /\.empty-workspace/);
  assert.match(css, /\.app-shell\.sidebar-collapsed/);
  assert.match(css, /grid-template-columns:\s*300px minmax\(0, 1fr\)/);
  assert.match(css, /overflow-y:\s*auto/);
  assert.match(css, /\.research-progress/);
  assert.match(css, /\.research-source-list/);
  assert.match(css, /\.research-resume/);
  assert.match(css, /\.research-stage-list/);
  assert.match(css, /\.research-progress-meta/);
  assert.match(css, /\.markdown-content/);
  assert.match(css, /\.message-link/);
  assert.match(css, /\.memory-ledger/);
  assert.match(css, /PingFang SC/);
  assert.match(css, /\.memory-list/);
  assert.match(css, /\.memory-row-detail/);
  assert.match(css, /\.memory-row\.review/);
  assert.match(css, /\.memory-row\.status-conflict/);
  assert.match(css, /\.memory-previous/);
  assert.match(css, /\.memory-actions/);
  assert.match(css, /\.memory-review-notice/);
  assert.match(css, /\.nav-badge/);
  assert.match(css, /\.memory-row\.focused/);
});
