import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const React = require("react");
const {
  MarkdownContent,
  applyCitationLinks,
  dedupeAdjacentLinks,
} = require("../frontend/markdown.cjs");

test("research Markdown renders structure and safe external links", () => {
  const content = [
    "## Research title",
    "",
    "1. **First finding** uses `store=false`.",
    "2. Read [OpenAI Docs](https://developers.openai.com/api/docs/guides/background).",
  ].join("\n");

  const html = renderToStaticMarkup(
    React.createElement(MarkdownContent, { content }),
  );

  assert.match(html, /<h2>Research title<\/h2>/);
  assert.match(html, /<ol>/);
  assert.match(html, /<strong>First finding<\/strong>/);
  assert.match(html, /<code>store=false<\/code>/);
  assert.match(html, /class="message-link"/);
  assert.match(html, /target="_blank"/);
  assert.doesNotMatch(html, /##|\*\*|\[OpenAI Docs\]/);
});

test("adjacent equivalent OpenAI documentation links render once", () => {
  const content =
    "Source: <https://developers.openai.com/api/docs/guides/background> " +
    "([platform.openai.com](https://platform.openai.com/docs/guides/background))";

  const deduped = dedupeAdjacentLinks(content);

  assert.equal(
    deduped,
    "Source: [platform.openai.com](https://developers.openai.com/api/docs/guides/background)",
  );
  const html = renderToStaticMarkup(
    React.createElement(MarkdownContent, { content }),
  );
  assert.equal((html.match(/<a /g) ?? []).length, 1);
});

test("plain citation spans receive a safe clickable marker", () => {
  const content = "The current documentation confirms this limitation.";
  const cited = applyCitationLinks(content, [
    {
      url: "https://developers.openai.com/api/docs/guides/background",
      start_index: 4,
      end_index: 25,
    },
  ]);

  assert.match(cited, /\[↗\]\(https:\/\/developers\.openai\.com/);
  assert.equal(
    applyCitationLinks(content, [
      { url: "javascript:alert(1)", start_index: 4, end_index: 25 },
    ]),
    content,
  );
});
