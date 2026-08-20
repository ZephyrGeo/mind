import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("built page contains the Mind product shell", async () => {
  const html = await readFile(
    new URL("../dist/index.html", import.meta.url),
    "utf8",
  );
  const bundle = await readFile(
    new URL("../dist/assets/app.js", import.meta.url),
    "utf8",
  );
  const source = await readFile(
    new URL("../frontend/app.js", import.meta.url),
    "utf8",
  );

  assert.match(html, /Mind — Personal AI workspace/);
  assert.match(html, /rel="icon"[^>]+href="\/favicon\.svg"/);
  await access(new URL("../dist/favicon.svg", import.meta.url));
  assert.match(html, /@phosphor-icons\/web@2\.1\.2/);
  assert.match(html, /\/runtime-config\.js/);
  assert.match(bundle, /What should we make sense of/);
  assert.doesNotMatch(bundle, /Fake Provider · no model calls · no cloud cost/);
  assert.doesNotMatch(bundle, /DeepSeek Provider · model calls may incur cost/);
  assert.doesNotMatch(bundle, /OpenAI Research Provider/);
  assert.match(bundle, /\/api\/health/);
  assert.match(bundle, /\/api\/conversations\/\$\{conversation\.id\}/);
  assert.match(bundle, /The conversation could not be opened/);
  assert.match(bundle, /Delete conversation/);
  assert.match(bundle, /Delete account/);
  assert.match(bundle, /\/api\/account/);
  assert.match(bundle, /method:\s*"DELETE"/);
  assert.match(bundle, /This cannot be undone/);
  assert.match(bundle, /Search conversations/);
  assert.match(bundle, /Chats and researches/);
  assert.doesNotMatch(bundle, /conversation\.mode === "research"/);
  assert.match(bundle, /conversationsCollapsed/);
  assert.match(bundle, /name:\s*"caret-down"/);
  assert.match(bundle, /aria-expanded/);
  assert.match(bundle, /No conversations yet/);
  assert.match(bundle, /composer-mode-switch/);
  assert.doesNotMatch(bundle, /conversation-selector/);
  assert.match(bundle, /name:\s*"snowflake"/);
  assert.doesNotMatch(bundle, /className:\s*"message-label"/);
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
  assert.match(bundle, /\/api\/files\?name=/);
  assert.match(bundle, /attachment_ids/);
  assert.match(bundle, /Attach a TXT or PDF file/);
  assert.match(bundle, /Uploading…/);
  assert.doesNotMatch(bundle, /Ingestion arrives in phase 2/);
  assert.match(bundle, /Resume research/);
  assert.match(bundle, /Restart as a new research task/);
  assert.match(bundle, /research_started/);
  assert.match(bundle, /Research complete/);
  assert.match(bundle, /Planning research/);
  assert.match(bundle, /Searching sources/);
  assert.match(bundle, /Checking evidence/);
  assert.match(bundle, /Writing report/);
  assert.match(bundle, /This can take several minutes/);
  assert.match(bundle, /Used extra search budget/);
  assert.match(bundle, /Research budget limit reached/);
  assert.doesNotMatch(bundle, /OpenAI ·/);
  assert.match(bundle, /Too many requests\. Research will continue in/);
  assert.match(bundle, /Research is temporarily delayed/);
  assert.match(bundle, /Research is continuing with partial evidence/);
  assert.match(bundle, /MarkdownContent/);
  assert.match(bundle, /message-link/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML/);
  assert.match(bundle, /target:\s*"_blank"/);
  assert.match(bundle, /\/cancel/);
  assert.match(bundle, /research-sources-toggle/);
  assert.match(bundle, /research-source-row/);
  assert.match(bundle, /sourcesOpen/);
  assert.match(bundle, /Cited in report/);
  assert.match(bundle, /View all.*sources/);
  assert.match(bundle, /Key sources will appear with the report/);
  assert.match(bundle, /not proof of factual accuracy/);
  assert.match(bundle, /quality_warning/);
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
  assert.match(source, /RadixSelect\.Root/);
  assert.match(source, /RadixSwitch\.Root/);
  assert.match(source, /className:\s*"memory-type-content"/);
  assert.match(source, /className:\s*"memory-switch"/);
  assert.doesNotMatch(source, /h\("select"/);
  assert.doesNotMatch(source, /memory-row-caret|memory-more/);
  assert.match(bundle, /method:\s*"PATCH"/);
  assert.match(bundle, /#\/memory/);
  assert.match(bundle, /className:\s*"dialog-backdrop"/);
  assert.doesNotMatch(source, /window\.(?:confirm|prompt|alert)/);
  assert.doesNotMatch(source, /Local API ready/);
  assert.doesNotMatch(
    source,
    /formatConversationTime|dateTime:\s*conversation\.updated_at/,
  );
  assert.doesNotMatch(
    source,
    /conversationGroupLabel|groupConversations|Previous 7 Days/,
  );
});

test("built stylesheet includes responsive and reduced-motion behavior", async () => {
  const css = await readFile(
    new URL("../dist/assets/styles.css", import.meta.url),
    "utf8",
  );
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /\.sidebar-container\.open/);
  assert.match(css, /\.conversation-category-label/);
  assert.match(css, /\.conversation-category\.collapsed \.category-caret/);
  assert.match(css, /\.conversation-category-empty/);
  assert.match(
    css,
    /\.composer-mode-switch button\.selected\s*\{[\s\S]*?background:\s*var\(--ink\)/,
  );
  assert.match(css, /\.composer-mode-switch\s*\{[\s\S]*?background:\s*#e8e8e8/);
  assert.match(css, /\.empty-workspace/);
  assert.match(css, /\.app-shell\.sidebar-collapsed/);
  assert.match(css, /grid-template-columns:\s*280px minmax\(0, 1fr\)/);
  assert.match(css, /overflow-y:\s*auto/);
  assert.match(css, /\.research-progress/);
  assert.match(css, /\.research-source-list/);
  assert.match(css, /\.research-sources-toolbar/);
  assert.match(css, /\.research-sources-view-all/);
  assert.match(css, /max-height:\s*260px/);
  assert.match(css, /grid-template-columns:\s*32px minmax\(0, 1fr\) auto/);
  assert.match(css, /text-overflow:\s*ellipsis/);
  assert.match(css, /\.research-resume/);
  assert.match(css, /\.research-stage-list/);
  assert.match(css, /\.research-progress-meta/);
  assert.match(css, /\.research-recovery-notice/);
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
  assert.match(css, /\.profile-menu/);
  assert.match(css, /\.dialog-card/);
  assert.match(css, /--brand-ice:\s*#62bfe8/);
  assert.match(css, /\.brand-mark\s*\{[\s\S]*?background:\s*transparent/);
  assert.match(css, /\.welcome-mark\s*\{[\s\S]*?background:\s*transparent/);
  assert.doesNotMatch(css, /Georgia|Times New Roman/);
});
