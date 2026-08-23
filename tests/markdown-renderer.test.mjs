import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const React = require("react");
const {
  MarkdownContent,
  applyCitationLinks,
  buildCitationView,
  dedupeAdjacentLinks,
  stripTrailingSourceSection,
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

test("streaming Markdown safely renders incomplete list markers", () => {
  for (const content of ["1. ", "24. ", "- ", "+ ", "* "]) {
    const html = renderToStaticMarkup(
      React.createElement(MarkdownContent, { content }),
    );

    assert.match(html, /^<div class="markdown-content"><p>/);
  }
});

test("Markdown separators render as rules instead of raw characters", () => {
  for (const content of ["---", "****", "_____"]) {
    const html = renderToStaticMarkup(
      React.createElement(MarkdownContent, { content }),
    );

    assert.equal(html, '<div class="markdown-content"><hr/></div>');
  }
});

test("every streaming prefix of a structured answer can render", () => {
  const answer = [
    "这份 PDF 是一份个人简历，主要内容如下：",
    "",
    "**基本信息**",
    "- 姓名：测试用户",
    "- 技能：Python、JavaScript",
    "",
    "**项目经历**",
    "1. **RAG 助手**：构建带引用的文档问答流程。",
    "2. **Research Agent**：在综合前核查证据。",
  ].join("\n");

  for (let end = 0; end <= answer.length; end += 1) {
    assert.doesNotThrow(() =>
      renderToStaticMarkup(
        React.createElement(MarkdownContent, {
          content: answer.slice(0, end),
        }),
      ),
    );
  }
});

test("a bare list marker after a completed code fence cannot stall streaming", () => {
  const answer = [
    "## 三、简历结构层面的改进",
    "",
    "建议增加：",
    "",
    "```text",
    "AI Engineer | 专注 LLM 应用开发与 RAG 系统落地",
    "- 3年 AI 应用开发经验",
    "```",
    "",
    "2. 时间线断档需要弥补",
    "",
    "- ",
  ].join("\n");

  for (let end = 0; end <= answer.length; end += 1) {
    assert.doesNotThrow(() =>
      renderToStaticMarkup(
        React.createElement(MarkdownContent, {
          content: answer.slice(0, end),
        }),
      ),
    );
  }
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

test("research change annotations stay attached to matching report sections", () => {
  const html = renderToStaticMarkup(
    React.createElement(MarkdownContent, {
      content: "## Aurora release\n\nThe launch is now planned for Q4.",
      headingAnnotations: [
        {
          id: "change-1",
          kind: "changed",
          section: "Aurora release",
          baseline_claim: "The launch was planned for Q3.",
          latest_claim: "The launch is now planned for Q4.",
          baseline_evidence: [
            {
              source_id: "S4",
              title: "Earlier filing",
              url: "https://example.com/earlier",
            },
          ],
          latest_evidence: [
            {
              source_id: "S18",
              title: "Latest filing",
              url: "https://example.com/latest",
            },
          ],
          confidence: 0.92,
        },
      ],
    }),
  );

  assert.match(html, /research-annotated-heading/);
  assert.match(html, /Changed · 92%/);
  assert.match(html, /Previously/);
  assert.match(html, /The launch was planned for Q3/);
  assert.match(html, /The launch is now planned for Q4/);
  assert.match(html, /https:\/\/example\.com\/earlier/);
  assert.match(html, /https:\/\/example\.com\/latest/);
  assert.doesNotMatch(html, /Aug|2026-08/);
});

test("research source view keeps cited sources only and renumbers them", () => {
  const content = [
    "## Finding",
    "",
    "First fact [S20]. Second fact [S53]. Duplicate [S58].",
    "",
    "## Sources",
    "",
    "- [S20] old generated list",
  ].join("\n");
  const sources = [
    { id: "S1", title: "Unused", url: "https://unused.example.com" },
    { id: "S20", title: "Primary", url: "https://example.com/primary" },
    { id: "S53", title: "Second", url: "https://example.com/second" },
    {
      id: "S58",
      title: "Primary duplicate",
      url: "https://www.example.com/primary?utm_source=search",
    },
  ];
  const citations = [
    { source_id: "S1", title: "Unused", url: sources[0].url },
    { source_id: "S20", title: "Primary", url: sources[1].url },
    { source_id: "S53", title: "Second", url: sources[2].url },
    { source_id: "S58", title: "Primary duplicate", url: sources[3].url },
  ];

  const view = buildCitationView(content, sources, citations);

  assert.equal(view.content, [
    "## Finding",
    "",
    "First fact [S1]. Second fact [S2]. Duplicate [S1].",
  ].join("\n"));
  assert.deepEqual(
    view.sources.map((source) => source.id),
    ["S1", "S2"],
  );
  assert.equal(view.citations.length, 3);
  assert.equal(view.idMap.get("S58"), "S1");
});

test("generated trailing source sections are removed from reports", () => {
  assert.equal(
    stripTrailingSourceSection("## Finding\n\nAnswer.\n\n## Sources\n\n- [S1]"),
    "## Finding\n\nAnswer.",
  );
});
