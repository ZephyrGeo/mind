from __future__ import annotations

import re
import unittest
import uuid

from backend.models import (
    ResearchCitation,
    ResearchCitationKind,
    ResearchEvidenceStatus,
    ResearchSource,
)
from backend.research_quality import evaluate_research_quality


class ResearchQualityTest(unittest.TestCase):
    def test_scores_sources_citations_conflicts_and_expected_facts(self) -> None:
        report = (
            "The official limit is 600 seconds [S1]. "
            "A community post claims the limit is lower [S2]."
        )
        first_marker = report.index("[S1]")
        second_marker = report.index("[S2]")
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Official documentation",
                    url="https://developers.openai.com/example",
                ),
                ResearchSource(
                    id="S2",
                    step_id="search-r1-q1",
                    title="Community post",
                    url="https://example.com/post",
                ),
            ],
            citations=[
                ResearchCitation(
                    source_id="S1",
                    title="Official documentation",
                    url="https://developers.openai.com/example",
                    start_index=first_marker,
                    end_index=first_marker + 4,
                ),
                ResearchCitation(
                    source_id="S2",
                    title="Community post",
                    url="https://example.com/post",
                    start_index=second_marker,
                    end_index=second_marker + 4,
                ),
            ],
            detected_conflicts=[
                "official 600 seconds versus a lower community claim"
            ],
            expected_conflicts=["600 seconds conflicts with lower claim"],
            expected_facts=["official limit is 600 seconds"],
        )

        self.assertEqual(metrics.source_count, 2)
        self.assertEqual(metrics.duplicate_source_count, 0)
        self.assertEqual(metrics.authoritative_source_ratio, 0.5)
        self.assertEqual(metrics.citation_coverage, 1.0)
        self.assertEqual(metrics.conflict_count, 1)
        self.assertGreaterEqual(metrics.conflict_detection_rate, 0.5)
        self.assertEqual(metrics.factual_correctness, 1.0)

    def test_empty_expectations_do_not_penalize_a_report(self) -> None:
        metrics = evaluate_research_quality(
            report="Short answer.",
            sources=[],
            citations=[],
        )

        self.assertEqual(metrics.source_count, 0)
        self.assertEqual(metrics.duplicate_source_count, 0)
        self.assertEqual(metrics.citation_coverage, 1.0)
        self.assertEqual(metrics.conflict_detection_rate, 1.0)
        self.assertEqual(metrics.factual_correctness, 1.0)

    def test_deduplicates_tracking_urls_and_counts_trailing_citations(self) -> None:
        report = "Background requests can be resumed after disconnect. [S1]"
        marker = report.index("[S1]")
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Background mode",
                    url=(
                        "https://developers.openai.com/api/docs/guides/"
                        "background?utm_source=openai"
                    ),
                ),
                ResearchSource(
                    id="S2",
                    step_id="search-r1-q2",
                    title="Background mode",
                    url=(
                        "https://developers.openai.com/api/docs/guides/"
                        "background/"
                    ),
                ),
            ],
            citations=[
                ResearchCitation(
                    source_id="S1",
                    title="Background mode",
                    url=(
                        "https://developers.openai.com/api/docs/guides/"
                        "background"
                    ),
                    start_index=marker,
                    end_index=marker + 4,
                )
            ],
        )

        self.assertEqual(metrics.source_count, 1)
        self.assertEqual(metrics.duplicate_source_count, 1)
        self.assertEqual(metrics.citation_coverage, 1.0)

    def test_measures_sentence_level_coverage_without_splitting_dotted_terms(
        self,
    ) -> None:
        report = (
            "The response.id remains stable across polling [S1]. "
            "A client can reconnect after a network interruption [S1]. "
            "The final retention statement has no citation."
        )
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Background mode",
                    url=(
                        "https://developers.openai.com/api/docs/guides/background"
                    ),
                )
            ],
            citations=[
                ResearchCitation(
                    source_id="S1",
                    title="Background mode",
                    url=(
                        "https://developers.openai.com/api/docs/guides/background"
                    ),
                    start_index=match.start(),
                    end_index=match.end(),
                )
                for match in re.finditer(r"\[S1\]", report)
            ],
        )

        self.assertEqual(metrics.citation_coverage, 0.6667)

    def test_source_section_entries_are_not_counted_as_report_claims(self) -> None:
        report = (
            "Background responses can be polled by response ID [S1].\n\n"
            "## Sources\n"
            "- [S1] Background mode documentation for long-running tasks."
        )
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Background mode",
                    url="https://example.com/background",
                )
            ],
            citations=[
                ResearchCitation(
                    source_id="S1",
                    title="Background mode",
                    url="https://example.com/background",
                    start_index=report.index("[S1]"),
                    end_index=report.index("[S1]") + 4,
                )
            ],
        )

        self.assertEqual(metrics.citation_coverage, 1.0)

    def test_explicit_pure_engineering_judgment_is_not_a_factual_claim(
        self,
    ) -> None:
        report = (
            "Background Responses support polling [S1].\n"
            "工程建议（非来源事实）：为任务表增加一个便于排障的内部备注字段。"
        )
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-q1",
                    title="Background mode",
                    url="https://example.com/background",
                )
            ],
            citations=[
                ResearchCitation(
                    source_id="S1",
                    title="Background mode",
                    url="https://example.com/background",
                    start_index=report.index("[S1]"),
                    end_index=report.index("[S1]") + 4,
                )
            ],
        )

        self.assertEqual(metrics.citation_coverage, 1.0)

    def test_file_provenance_is_not_external_corroboration(self) -> None:
        report = (
            "The attached document states that the event occurred in 2025 [F1]. "
            "A primary record independently confirms the location [F1] [S1]."
        )
        first_file = report.index("[F1]")
        second_file = report.index("[F1]", first_file + 1)
        web = report.index("[S1]")
        metrics = evaluate_research_quality(
            report=report,
            sources=[
                ResearchSource(
                    id="S1",
                    step_id="search-r1-file-claims",
                    title="Primary record",
                    url="https://example.edu/record",
                )
            ],
            citations=[
                ResearchCitation(
                    source_id="F1",
                    title="Uploaded document.pdf",
                    file_id=uuid.UUID(int=1),
                    kind=ResearchCitationKind.FILE,
                    verification_status=ResearchEvidenceStatus.FILE_PROVIDED,
                    start_index=first_file,
                    end_index=first_file + 4,
                ),
                ResearchCitation(
                    source_id="F1",
                    title="Uploaded document.pdf",
                    file_id=uuid.UUID(int=1),
                    kind=ResearchCitationKind.FILE,
                    verification_status=ResearchEvidenceStatus.CORROBORATED,
                    start_index=second_file,
                    end_index=second_file + 4,
                ),
                ResearchCitation(
                    source_id="S1",
                    title="Primary record",
                    url="https://example.edu/record",
                    start_index=web,
                    end_index=web + 4,
                ),
            ],
        )

        self.assertEqual(metrics.citation_coverage, 1.0)
        self.assertEqual(metrics.web_citation_coverage, 0.5)
        self.assertEqual(metrics.file_corroboration_coverage, 0.5)
        self.assertEqual(metrics.unverified_file_claim_count, 1)


if __name__ == "__main__":
    unittest.main()
