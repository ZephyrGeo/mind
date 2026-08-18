"""Deterministic quality metrics for completed Mind Research reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .models import ResearchCitation, ResearchSource
from .source_urls import canonical_source_url


DEFAULT_AUTHORITATIVE_DOMAINS = frozenset(
    {
        "data.gov",
        "europa.eu",
        "oecd.org",
        "openai.com",
        "un.org",
        "who.int",
        "worldbank.org",
    }
)


@dataclass(frozen=True, slots=True)
class ResearchQualityMetrics:
    source_count: int
    duplicate_source_count: int
    authoritative_source_ratio: float
    citation_coverage: float
    conflict_count: int
    conflict_detection_rate: float
    factual_correctness: float


def evaluate_research_quality(
    *,
    report: str,
    sources: list[ResearchSource],
    citations: list[ResearchCitation],
    detected_conflicts: list[str] | None = None,
    expected_conflicts: list[str] | None = None,
    expected_facts: list[str] | None = None,
    authoritative_domains: frozenset[str] = DEFAULT_AUTHORITATIVE_DOMAINS,
) -> ResearchQualityMetrics:
    """Score evidence breadth, citation use, conflict detection, and facts."""

    canonical_sources = [
        (canonical, source)
        for source in sources
        if (canonical := canonical_source_url(source.url))
    ]
    unique_sources = dict(canonical_sources)
    authoritative_count = sum(
        _is_authoritative(source.url, authoritative_domains)
        for source in unique_sources.values()
    )
    source_count = len(unique_sources)
    source_ratio = authoritative_count / source_count if source_count else 0.0

    claim_ranges = _claim_ranges(report)
    cited_claims = sum(
        _claim_is_cited(report, start, end, citations)
        for start, end in claim_ranges
    )
    citation_coverage = cited_claims / len(claim_ranges) if claim_ranges else 1.0

    actual_conflicts = detected_conflicts or []
    conflict_targets = expected_conflicts or []
    conflict_detection_rate = _expected_item_coverage(
        actual_conflicts,
        conflict_targets,
    )
    factual_correctness = _text_item_coverage(report, expected_facts or [])

    return ResearchQualityMetrics(
        source_count=source_count,
        duplicate_source_count=len(canonical_sources) - source_count,
        authoritative_source_ratio=round(source_ratio, 4),
        citation_coverage=round(citation_coverage, 4),
        conflict_count=len(actual_conflicts),
        conflict_detection_rate=round(conflict_detection_rate, 4),
        factual_correctness=round(factual_correctness, 4),
    )


def _claim_ranges(report: str) -> list[tuple[int, int]]:
    """Return sentence-level factual claim candidates outside source lists.

    Sentence boundaries only count periods followed by whitespace or a source
    marker, so dotted identifiers, decimal numbers, and URLs are not split into
    artificial claims.
    """

    ranges: list[tuple[int, int]] = []
    in_sources_section = False
    in_code_block = False
    offset = 0
    for line in report.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        stripped = content.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            offset += len(line)
            continue
        if in_code_block:
            offset += len(line)
            continue
        heading = re.sub(r"^#+\s*", "", stripped).strip().casefold()
        if stripped.startswith("#") and heading in {
            "sources",
            "source",
            "来源",
            "参考来源",
            "参考资料",
        }:
            in_sources_section = True
            offset += len(line)
            continue
        if in_sources_section or not stripped or stripped.startswith("#"):
            offset += len(line)
            continue
        if re.fullmatch(r"[-:|\s]+", stripped):
            offset += len(line)
            continue

        left_trim = len(content) - len(content.lstrip())
        line_start = offset + left_trim
        candidate = content[left_trim:]
        prefix = re.match(r"(?:[-*+]\s+|\d+[.)]\s+)", candidate)
        if prefix is not None:
            line_start += prefix.end()
            candidate = candidate[prefix.end() :]

        for start, end in _sentence_ranges(candidate):
            text = candidate[start:end].strip()
            if (
                len(text) < 24
                or _source_entry(text)
                or _explicit_engineering_judgment(text)
            ):
                continue
            ranges.append((line_start + start, line_start + end))
        offset += len(line)
    return ranges


def _sentence_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character not in ".!?。！？":
            index += 1
            continue
        if character == "." and index + 1 < len(value):
            following = value[index + 1]
            if not following.isspace() and following != "[":
                index += 1
                continue

        end = index + 1
        while True:
            marker = re.match(r"[ \t]*\[S\d+\]", value[end:])
            if marker is None:
                break
            end += marker.end()
        ranges.append((start, end))
        start = end
        while start < len(value) and value[start].isspace():
            start += 1
        index = start

    if value[start:].strip():
        ranges.append((start, len(value)))
    return ranges


def _source_entry(value: str) -> bool:
    normalized = value.casefold()
    return (
        normalized.startswith(("sources", "source:", "来源", "参考来源"))
        or bool(re.fullmatch(r"\[S\d+\][\s:—-]+.*", value))
        or bool(re.fullmatch(r"https?://\S+", value))
    )


def _explicit_engineering_judgment(value: str) -> bool:
    normalized = re.sub(r"^[*_`\s]+", "", value).casefold()
    return normalized.startswith(
        (
            "工程建议（非来源事实）：",
            "工程建议(非来源事实):",
            "engineering judgment (not a sourced fact):",
        )
    )


def _claim_is_cited(
    report: str,
    start: int,
    end: int,
    citations: list[ResearchCitation],
) -> bool:
    if re.search(r"\[S\d+\]", report[start:end]):
        return True
    return any(
        citation.start_index < end and citation.end_index > start
        for citation in citations
    )


def _is_authoritative(url: str, authoritative_domains: frozenset[str]) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    if not hostname:
        return False
    if hostname.endswith(".gov") or ".gov." in hostname:
        return True
    if hostname.endswith(".edu") or ".edu." in hostname:
        return True
    if hostname.endswith(".ac.uk"):
        return True
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in authoritative_domains
    )


def _expected_item_coverage(actual: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    actual_tokens = [_tokens(item) for item in actual]
    matched = 0
    for target in expected:
        target_tokens = _tokens(target)
        if target_tokens and any(
            len(target_tokens & candidate) / len(target_tokens) >= 0.5
            for candidate in actual_tokens
        ):
            matched += 1
    return matched / len(expected)


def _text_item_coverage(report: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    normalized_report = _normalize(report)
    matched = sum(_normalize(fact) in normalized_report for fact in expected)
    return matched / len(expected)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w-]+", value.casefold()))


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w.-]+", value.casefold()))
