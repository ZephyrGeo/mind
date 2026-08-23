"use strict";

const React = require("react");

const h = React.createElement;
const BLOCK_PATTERN = /^(?:#{1,6}\s+|```|>\s?|\s*(?:[-+*]|\d+\.)\s+)/;
const ORDERED_LIST_ITEM_PATTERN = /^\s*\d+\.\s+(.+)$/;
const UNORDERED_LIST_ITEM_PATTERN = /^\s*[-+*]\s+(.+)$/;
const INLINE_PATTERN = /(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|<https?:\/\/[^>\s]+>|https?:\/\/[^\s<]+|`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*| {2,}\n)/g;
const ADJACENT_LINK_PATTERN = /<(https?:\/\/[^>\s]+)>\s+\(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)\)/g;
const SOURCE_MARKER_PATTERN = /\[((?:S|F)\d+)\]/g;
const SOURCE_SECTION_PATTERN =
  /^#{1,6}\s*(?:sources?|references|来源|参考资料|参考文献)\s*$/i;

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
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) {
    if (
      key.toLowerCase().startsWith("utm_") ||
      ["fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"].includes(
        key.toLowerCase(),
      )
    ) {
      url.searchParams.delete(key);
    }
  }
  url.searchParams.sort();

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

function stripTrailingSourceSection(markdown) {
  if (!markdown) return "";
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const sourceHeading = lines.findIndex((line) =>
    SOURCE_SECTION_PATTERN.test(line.trim()),
  );
  return (sourceHeading < 0 ? lines : lines.slice(0, sourceHeading))
    .join("\n")
    .trimEnd();
}

function buildCitationView(content, sources = [], citations = []) {
  const report = stripTrailingSourceSection(content);
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const citationById = new Map();
  for (const citation of citations) {
    if (!citationById.has(citation.source_id)) {
      citationById.set(citation.source_id, citation);
    }
  }

  const idMap = new Map();
  const canonicalIds = new Map();
  const displayRecords = new Map();
  let webIndex = 0;
  let fileIndex = 0;

  function assign(sourceId) {
    if (idMap.has(sourceId)) return idMap.get(sourceId);
    const source = sourceById.get(sourceId);
    const citation = citationById.get(sourceId);
    const isFile = citation?.kind === "file" || sourceId.startsWith("F");
    const url = source?.url ?? citation?.url ?? null;
    const canonical = !isFile && url ? comparableUrl(url) : null;
    if (canonical && canonicalIds.has(canonical)) {
      const existing = canonicalIds.get(canonical);
      idMap.set(sourceId, existing);
      return existing;
    }

    const displayId = isFile ? `F${++fileIndex}` : `S${++webIndex}`;
    idMap.set(sourceId, displayId);
    if (canonical) canonicalIds.set(canonical, displayId);
    displayRecords.set(displayId, {
      ...(source ?? {}),
      id: displayId,
      source_id: displayId,
      title: source?.title ?? citation?.title ?? sourceId,
      url,
      kind: isFile ? "file" : "web",
      file_id: citation?.file_id,
      verification_status: citation?.verification_status,
    });
    return displayId;
  }

  const reportMarkers = [
    ...report.matchAll(new RegExp(SOURCE_MARKER_PATTERN.source, "g")),
  ];
  for (const match of reportMarkers) {
    assign(match[1]);
  }
  if (!reportMarkers.length) {
    for (const citation of [...citations].sort(
      (left, right) => (left.start_index ?? 0) - (right.start_index ?? 0),
    )) {
      assign(citation.source_id);
    }
  }

  const displayContent = report.replace(
    new RegExp(SOURCE_MARKER_PATTERN.source, "g"),
    (_marker, sourceId) => `[${assign(sourceId)}]`,
  );
  const displayCitations = [];
  const markerMatches = [
    ...displayContent.matchAll(new RegExp(SOURCE_MARKER_PATTERN.source, "g")),
  ];
  if (markerMatches.length) {
    for (const match of markerMatches) {
      const record = displayRecords.get(match[1]);
      if (!record) continue;
      displayCitations.push({
        source_id: match[1],
        title: record.title,
        url: record.url,
        file_id: record.file_id,
        kind: record.kind,
        verification_status: record.verification_status,
        start_index: match.index,
        end_index: match.index + match[0].length,
      });
    }
  } else {
    for (const citation of citations) {
      const displayId = idMap.get(citation.source_id);
      if (!displayId) continue;
      displayCitations.push({ ...citation, source_id: displayId });
    }
  }

  return {
    content: displayContent,
    citations: displayCitations,
    sources: [...displayRecords.values()].filter(
      (source) => source.kind !== "file",
    ),
    idMap,
  };
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
  const marker = ordered
    ? ORDERED_LIST_ITEM_PATTERN
    : UNORDERED_LIST_ITEM_PATTERN;
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

function normalizeHeading(value) {
  return value
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`#]/g, "")
    .replace(/^\s*\d+[.)]\s*/, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .toLocaleLowerCase();
}

function renderEvidenceLinks(evidence = [], keyPrefix) {
  if (!evidence.length) return null;
  return h(
    "span",
    { className: "research-claim-evidence" },
    evidence.map((item, index) =>
      item.url
        ? h(
            ExternalLink,
            { href: item.url, key: `${keyPrefix}-${index}` },
            item.source_id,
          )
        : h("span", { key: `${keyPrefix}-${index}` }, item.source_id),
    ),
  );
}

function renderHeadingAnnotation(annotation, key) {
  if (!annotation) return null;
  const confidence = Math.round((annotation.confidence ?? 0) * 100);
  const label = `${annotation.kind[0].toUpperCase()}${annotation.kind.slice(1)}`;
  return h(
    "span",
    {
      className: "research-diff-badge",
      "data-kind": annotation.kind,
      key,
    },
    h("i", { "aria-hidden": "true" }),
    `${label} · ${confidence}%`,
  );
}

function renderClaimComparison(annotation, key) {
  if (
    !annotation ||
    !["changed", "contradicted"].includes(annotation.kind) ||
    !annotation.baseline_claim ||
    !annotation.latest_claim
  ) {
    return null;
  }
  return h(
    "div",
    {
      className: "research-claim-comparison",
      "data-kind": annotation.kind,
      key,
    },
    h(
      "div",
      null,
      h("span", null, "Previously"),
      h("p", null, annotation.baseline_claim),
      renderEvidenceLinks(annotation.baseline_evidence, `${key}-baseline`),
    ),
    h(
      "div",
      null,
      h("span", null, annotation.kind === "contradicted" ? "Current evidence" : "Now"),
      h("p", null, annotation.latest_claim),
      renderEvidenceLinks(annotation.latest_evidence, `${key}-latest`),
    ),
  );
}

function renderBlocks(markdown, options = {}) {
  const headingAnnotations = options.headingAnnotations ?? [];
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;
  let blockIndex = 0;
  let pendingComparison = null;

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
      const normalized = normalizeHeading(heading[2]);
      const annotation = headingAnnotations.find(
        (item) => normalizeHeading(item.section ?? "") === normalized,
      );
      blocks.push(
        h(
          `h${heading[1].length}`,
          {
            className: annotation ? "research-annotated-heading" : undefined,
            key,
          },
          annotation
            ? h("span", null, renderInline(heading[2], key))
            : renderInline(heading[2], key),
          renderHeadingAnnotation(annotation, `${key}-badge`),
        ),
      );
      pendingComparison = annotation;
      index += 1;
      blockIndex += 1;
      continue;
    }

    const orderedItem = line.match(ORDERED_LIST_ITEM_PATTERN);
    const unorderedItem = line.match(UNORDERED_LIST_ITEM_PATTERN);
    if (orderedItem || unorderedItem) {
      const ordered = Boolean(orderedItem);
      const { items, nextIndex } = collectList(lines, index, ordered);
      if (!items.length || nextIndex <= index) {
        blocks.push(h("p", { key }, renderInline(line, key)));
        index += 1;
        blockIndex += 1;
        continue;
      }
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
      blocks.push(
        h(
          "blockquote",
          { key },
          renderBlocks(quoteLines.join("\n"), options),
        ),
      );
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
    const comparison = renderClaimComparison(
      pendingComparison,
      `${key}-comparison`,
    );
    if (comparison) blocks.push(comparison);
    pendingComparison = null;
    blockIndex += 1;
  }
  return blocks;
}

function MarkdownContent({ content, citations = [], headingAnnotations = [] }) {
  const citedMarkdown = applyCitationLinks(content, citations);
  return h(
    "div",
    { className: "markdown-content" },
    renderBlocks(dedupeAdjacentLinks(citedMarkdown), { headingAnnotations }),
  );
}

module.exports = {
  MarkdownContent,
  applyCitationLinks,
  buildCitationView,
  dedupeAdjacentLinks,
  renderBlocks,
  safeWebUrl,
  stripTrailingSourceSection,
};
