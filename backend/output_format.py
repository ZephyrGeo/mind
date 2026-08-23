"""Shared model-output rules for Mind's custom Markdown renderer."""

MARKDOWN_OUTPUT_RULES = """Markdown output rules:
- Use headings, paragraphs, ordered or unordered lists, blockquotes, emphasis,
  inline code, links, and citations only when they improve readability.
- Do not output Markdown horizontal rules or decorative separator lines such as
  `---`, `***`, or `___`. Separate sections with one blank line and a heading.
- Use fenced code blocks only for actual code, commands, configuration, or data
  that must preserve whitespace. Never use a code block as a visual callout.
- Indent nested list items correctly. Do not place a child bullet at the same
  indentation level as its numbered parent.
- Do not output Markdown tables; use short lists instead.
- Do not escape decorative punctuation merely to force it to appear literally.
"""
