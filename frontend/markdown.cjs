"use strict";

const React = require("react");

const h = React.createElement;
const BLOCK_PATTERN = /^(?:#{1,6}\s+|```|>\s?|\s*(?:[-+*]|\d+\.)\s+)/;
const INLINE_PATTERN = /(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|<https?:\/\/[^>\s]+>|https?:\/\/[^\s<]+|`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*| {2,}\n)/g;
const ADJACENT_LINK_PATTERN = /<(https?:\/\/[^>\s]+)>\s+\(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)\)/g;

function safeWebUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function comparableUrl(value) {
  const safeUrl = safeWebUrl(value);
  if (!safeUrl) return null;
  const url = new URL(safeUrl);
  const hostname = url.hostname.toLowerCase().replace(/^www\./, "");
  let pathname = url.pathname.replace(/\/+$/, "") || "/";

  if (hostname === "developers.openai.com") {
    pathname = pathname.replace(/^\/api\/docs(?=\/|$)/, "/docs");
  }
  if (
    hostname === "developers.openai.com" ||
    hostname === "platform.openai.com"
  ) {
    return `openai-docs:${pathname}${url.search}`;
  }
  return `${hostname}:${pathname}${url.search}`;
}

function dedupeAdjacentLinks(markdown) {
  if (!markdown) return "";
  return markdown.replace(
    ADJACENT_LINK_PATTERN,
    (match, visibleUrl, label, citationUrl) => {
      const first = comparableUrl(visibleUrl);
      const second = comparableUrl(citationUrl);
      if (!first || first !== second) return match;
      return `[${label}](${visibleUrl})`;
    },
  );
}

function applyCitationLinks(markdown, citations = []) {
  const ordered = [...citations]
    .filter(
      (citation) =>
        Number.isInteger(citation.start_index) &&
        Number.isInteger(citation.end_index) &&
        citation.start_index >= 0 &&
        citation.end_index > citation.start_index &&
        citation.end_index <= markdown.length &&
        safeWebUrl(citation.url),
    )
    .sort((left, right) => right.end_index - left.end_index);

  let result = markdown;
  let nextStart = markdown.length;
  for (const citation of ordered) {
    if (citation.end_index > nextStart) continue;
    const citedText = markdown.slice(citation.start_index, citation.end_index);
    const alreadyLinked =
      /\[[^\]]+\]\(https?:\/\//.test(citedText) ||
      /<https?:\/\//.test(citedText) ||
      /^https?:\/\//.test(citedText.trim());
    if (!alreadyLinked) {
      result = `${result.slice(0, citation.end_index)} [↗](${citation.url})${result.slice(citation.end_index)}`;
    }
    nextStart = citation.start_index;
  }
  return result;
}

function ExternalLink({ href, children }) {
  const safeHref = safeWebUrl(href);
  if (!safeHref) return h("span", null, children);
  return h(
    "a",
    {
      className: "message-link",
      href: safeHref,
      target: "_blank",
      rel: "noreferrer noopener",
    },
    children,
  );
}

function trimBareUrl(value) {
  let url = value;
  let suffix = "";
  while (/[.,;:!?，。；：！？]$/.test(url)) {
    suffix = url.at(-1) + suffix;
    url = url.slice(0, -1);
  }
  return { url, suffix };
}

function renderInline(value, keyPrefix = "inline") {
  const parts = [];
  let cursor = 0;
  let match;
  let index = 0;
  const inlinePattern = new RegExp(INLINE_PATTERN.source, "g");

  while ((match = inlinePattern.exec(value)) !== null) {
    if (match.index > cursor) parts.push(value.slice(cursor, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index}`;

    if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
      parts.push(
        linkMatch
          ? h(ExternalLink, { href: linkMatch[2], key }, renderInline(linkMatch[1], key))
          : token,
      );
    } else if (token.startsWith("<")) {
      const href = token.slice(1, -1);
      parts.push(h(ExternalLink, { href, key }, href));
    } else if (token.startsWith("http")) {
      const { url, suffix } = trimBareUrl(token);
      parts.push(h(ExternalLink, { href: url, key }, url));
      if (suffix) parts.push(suffix);
    } else if (token.startsWith("`")) {
      parts.push(h("code", { key }, token.slice(1, -1)));
    } else if (token.startsWith("**")) {
      parts.push(h("strong", { key }, renderInline(token.slice(2, -2), key)));
    } else if (token.startsWith("*")) {
      parts.push(h("em", { key }, renderInline(token.slice(1, -1), key)));
    } else {
      parts.push(h("br", { key }));
    }

    cursor = match.index + token.length;
    index += 1;
  }
  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts;
}

function isBlockStart(line) {
  return BLOCK_PATTERN.test(line);
}

function collectList(lines, startIndex, ordered) {
  const marker = ordered ? /^\s*\d+\.\s+(.+)$/ : /^\s*[-+*]\s+(.+)$/;
  const items = [];
  let index = startIndex;

  while (index < lines.length) {
    const itemMatch = lines[index].match(marker);
    if (!itemMatch) break;
    const itemLines = [itemMatch[1]];
    index += 1;

    while (index < lines.length) {
      const nextLine = lines[index];
      if (nextLine.match(marker)) break;
      if (!nextLine.trim()) {
        const following = lines[index + 1] ?? "";
        if (following.match(marker)) {
          index += 1;
          break;
        }
        if (isBlockStart(following) && !/^\s+/.test(following)) {
          index += 1;
          break;
        }
        itemLines.push("");
        index += 1;
        continue;
      }
      if (isBlockStart(nextLine) && !/^\s+/.test(nextLine)) break;
      itemLines.push(nextLine.trim());
      index += 1;
    }
    items.push(itemLines.join("\n").trim());
  }
  return { items, nextIndex: index };
}

function renderBlocks(markdown) {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;
  let blockIndex = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const key = `block-${blockIndex}`;

    const fence = line.match(/^```([^\s`]*)\s*$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(
        h(
          "pre",
          { key },
          h(
            "code",
            { className: fence[1] ? `language-${fence[1]}` : undefined },
            codeLines.join("\n"),
          ),
        ),
      );
      blockIndex += 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      blocks.push(
        h(`h${heading[1].length}`, { key }, renderInline(heading[2], key)),
      );
      index += 1;
      blockIndex += 1;
      continue;
    }

    const orderedItem = line.match(/^\s*\d+\.\s+/);
    const unorderedItem = line.match(/^\s*[-+*]\s+/);
    if (orderedItem || unorderedItem) {
      const ordered = Boolean(orderedItem);
      const { items, nextIndex } = collectList(lines, index, ordered);
      blocks.push(
        h(
          ordered ? "ol" : "ul",
          { key },
          items.map((item, itemIndex) =>
            h("li", { key: `${key}-${itemIndex}` }, renderInline(item, `${key}-${itemIndex}`)),
          ),
        ),
      );
      index = nextIndex;
      blockIndex += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(h("blockquote", { key }, renderBlocks(quoteLines.join("\n"))));
      blockIndex += 1;
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isBlockStart(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push(
      h("p", { key }, renderInline(paragraphLines.join("\n"), key)),
    );
    blockIndex += 1;
  }
  return blocks;
}

function MarkdownContent({ content, citations = [] }) {
  const citedMarkdown = applyCitationLinks(content, citations);
  return h(
    "div",
    { className: "markdown-content" },
    renderBlocks(dedupeAdjacentLinks(citedMarkdown)),
  );
}

module.exports = {
  MarkdownContent,
  applyCitationLinks,
  dedupeAdjacentLinks,
  renderBlocks,
  safeWebUrl,
};
