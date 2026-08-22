#!/usr/bin/env python3
"""Seed deterministic, zero-cost Insight Diff conversations for local UI QA."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models import (  # noqa: E402
    AgentMode,
    ResearchCheckpoint,
    ResearchCitation,
    ResearchDiffClaim,
    ResearchDiffEvidence,
    ResearchInsightDiff,
    ResearchJob,
    ResearchReportSnapshot,
    ResearchSource,
    ResearchStatus,
)
from backend.research_store import JsonResearchRepository  # noqa: E402
from backend.store import (  # noqa: E402
    LOCAL_USER_ID,
    ConversationNotFoundError,
    JsonConversationRepository,
)

DEMO_PROMPT_VERSION = "local-demo-insight-diff-v1"
DEMO_TITLE_PREFIX = "[Demo] Insight Diff"
MARKER_PATTERN = re.compile(r"\[(S\d+)\]")


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def make_sources(
    rows: list[tuple[str, str, str, str]],
    retrieved_at: datetime,
) -> list[ResearchSource]:
    return [
        ResearchSource(
            id=source_id,
            step_id="demo-evidence",
            title=title,
            url=url,
            snippet="Local demonstration evidence; no provider request was made.",
            published_at=published_at,
            retrieved_at=retrieved_at,
        )
        for source_id, title, url, published_at in rows
    ]


def citations_for(
    report: str,
    sources: list[ResearchSource],
) -> list[ResearchCitation]:
    source_by_id = {item.id: item for item in sources}
    return [
        ResearchCitation(
            source_id=source_by_id[match.group(1)].id,
            title=source_by_id[match.group(1)].title,
            url=source_by_id[match.group(1)].url,
            start_index=match.start(),
            end_index=match.end(),
        )
        for match in MARKER_PATTERN.finditer(report)
    ]


def diff_evidence(
    source_ids: list[str],
    sources: dict[str, ResearchSource],
) -> list[ResearchDiffEvidence]:
    return [
        ResearchDiffEvidence(
            source_id=sources[source_id].id,
            title=sources[source_id].title,
            url=sources[source_id].url,
            published_at=sources[source_id].published_at,
        )
        for source_id in source_ids
    ]


def remove_previous_demos(
    conversations: JsonConversationRepository,
    research: JsonResearchRepository,
) -> None:
    conversation_ids = {
        job.conversation_id
        for job in research.list_jobs(LOCAL_USER_ID)
        if job.prompt_version == DEMO_PROMPT_VERSION
    }
    conversation_ids.update(
        summary.id
        for summary in conversations.list_conversations(LOCAL_USER_ID)
        if summary.title.startswith(DEMO_TITLE_PREFIX)
    )
    for conversation_id in conversation_ids:
        research.delete_for_conversation(conversation_id, LOCAL_USER_ID)
        try:
            conversations.delete_conversation(conversation_id, LOCAL_USER_ID)
        except ConversationNotFoundError:
            pass


def save_report_message(
    conversations: JsonConversationRepository,
    research: JsonResearchRepository,
    job: ResearchJob,
) -> None:
    research.create_job(job)
    message_id = conversations.append_assistant_message(
        job.conversation_id,
        job.checkpoint.report,
        user_id=LOCAL_USER_ID,
        research_job_id=job.id,
    )
    job.checkpoint.assistant_message_id = UUID(message_id)
    research.save_job(job, LOCAL_USER_ID)


def seed_demo(
    conversations: JsonConversationRepository,
    research: JsonResearchRepository,
    *,
    title: str,
    baseline_report: str,
    latest_report: str,
    baseline_rows: list[tuple[str, str, str, str]],
    latest_rows: list[tuple[str, str, str, str]],
    claim_rows: list[dict[str, object]],
) -> str:
    baseline_date = utc("2026-04-15T09:00:00")
    latest_date = utc("2026-08-23T09:00:00")
    baseline_sources = make_sources(baseline_rows, baseline_date)
    latest_sources = make_sources(latest_rows, latest_date)
    baseline_by_id = {item.id: item for item in baseline_sources}
    latest_by_id = {item.id: item for item in latest_sources}
    baseline_citations = citations_for(baseline_report, baseline_sources)
    latest_citations = citations_for(latest_report, latest_sources)
    conversation_id = conversations.append_user_message(
        None,
        f"{DEMO_TITLE_PREFIX} — {title}",
        AgentMode.RESEARCH,
        user_id=LOCAL_USER_ID,
    )
    baseline_job = ResearchJob(
        user_id=LOCAL_USER_ID,
        conversation_id=UUID(conversation_id),
        query="Use the April report as an immutable baseline.",
        prompt_version=DEMO_PROMPT_VERSION,
        status=ResearchStatus.COMPLETED,
        progress=1,
        provider_status="completed",
        checkpoint=ResearchCheckpoint(
            report=baseline_report,
            sources=baseline_sources,
            citations=baseline_citations,
        ),
        citation_coverage=1,
        created_at=baseline_date,
        run_started_at=baseline_date,
        updated_at=baseline_date,
    )
    save_report_message(conversations, research, baseline_job)
    conversations.append_user_message(
        conversation_id,
        "Compare this baseline with the latest evidence.",
        AgentMode.RESEARCH,
        user_id=LOCAL_USER_ID,
    )
    claims: list[ResearchDiffClaim] = []
    for item in claim_rows:
        row = dict(item)
        baseline_ids = list(row.pop("baseline_source_ids", []))
        latest_ids = list(row.pop("latest_source_ids", []))
        claims.append(
            ResearchDiffClaim(
                **row,
                baseline_evidence=diff_evidence(
                    baseline_ids,
                    baseline_by_id,
                ),
                latest_evidence=diff_evidence(latest_ids, latest_by_id),
            )
        )
    latest_job = ResearchJob(
        user_id=LOCAL_USER_ID,
        conversation_id=UUID(conversation_id),
        query="Compare the April baseline with the latest evidence.",
        baseline_job_id=baseline_job.id,
        prompt_version=DEMO_PROMPT_VERSION,
        status=ResearchStatus.COMPLETED,
        progress=1,
        provider_status="completed",
        checkpoint=ResearchCheckpoint(
            report=latest_report,
            sources=latest_sources,
            citations=latest_citations,
            baseline_snapshot=ResearchReportSnapshot(
                job_id=baseline_job.id,
                created_at=baseline_date,
                report=baseline_report,
                sources=baseline_sources,
                citations=baseline_citations,
            ),
            insight_diff=ResearchInsightDiff(
                baseline_job_id=baseline_job.id,
                baseline_created_at=baseline_date,
                latest_created_at=latest_date,
                claims=claims,
            ),
        ),
        citation_coverage=1,
        created_at=latest_date,
        run_started_at=latest_date,
        updated_at=latest_date,
    )
    save_report_message(conversations, research, latest_job)
    return conversation_id


def main() -> None:
    conversations = JsonConversationRepository(
        ROOT / "work/local-data/conversations.json"
    )
    research = JsonResearchRepository(ROOT / "work/local-data/research-jobs.json")
    remove_previous_demos(conversations, research)
    changes_id = seed_demo(
        conversations,
        research,
        title="four change types",
        baseline_report="""# Aurora outlook — April baseline

## Launch timing
The public launch was expected in 2026 Q3. [S1]

## Enterprise plan
No enterprise pilot had been announced. [S2]

## Offline mode
Offline mode was included in the initial launch scope. [S3]

## Beta availability
The public beta was open to new participants. [S4]""",
        latest_report="""# Aurora outlook — updated report

## Launch timing
The public launch has moved from 2026 Q3 to Q4. [S1]

## Enterprise plan
A limited enterprise pilot is now scheduled. [S2]

## Offline mode
Offline mode is excluded from the initial release. [S3]

## Current rollout
Enrollment for the earlier public beta has closed. [S4]""",
        baseline_rows=[
            ("S1", "April roadmap", "https://example.com/aurora/april-roadmap", "2026-04-15"),
            ("S2", "April commercial plan", "https://example.com/aurora/april-commercial", "2026-04-15"),
            ("S3", "April technical scope", "https://example.com/aurora/april-scope", "2026-04-15"),
            ("S4", "April beta notice", "https://example.com/aurora/april-beta", "2026-04-15"),
        ],
        latest_rows=[
            ("S1", "August release update", "https://example.com/aurora/august-release", "2026-08-22"),
            ("S2", "Enterprise pilot update", "https://example.com/aurora/enterprise-pilot", "2026-08-20"),
            ("S3", "Current technical scope", "https://example.com/aurora/current-scope", "2026-08-21"),
            ("S4", "Beta enrollment update", "https://example.com/aurora/beta-update", "2026-08-19"),
        ],
        claim_rows=[
            {
                "id": "demo-changed-launch",
                "kind": "changed",
                "section": "Launch timing",
                "baseline_claim": "The public launch was expected in 2026 Q3.",
                "latest_claim": "The public launch has moved to 2026 Q4.",
                "baseline_source_ids": ["S1"],
                "latest_source_ids": ["S1"],
                "confidence": 0.94,
            },
            {
                "id": "demo-new-enterprise",
                "kind": "new",
                "section": "Enterprise plan",
                "latest_claim": "A limited enterprise pilot is now scheduled.",
                "latest_source_ids": ["S2"],
                "confidence": 0.91,
            },
            {
                "id": "demo-contradicted-offline",
                "kind": "contradicted",
                "section": "Offline mode",
                "baseline_claim": "Offline mode was included in the initial launch scope.",
                "latest_claim": "Offline mode is excluded from the initial release.",
                "baseline_source_ids": ["S3"],
                "latest_source_ids": ["S3"],
                "confidence": 0.96,
            },
            {
                "id": "demo-stale-beta",
                "kind": "stale",
                "section": "Beta availability",
                "baseline_claim": "The public beta was open to new participants.",
                "baseline_source_ids": ["S4"],
                "latest_source_ids": ["S4"],
                "confidence": 0.89,
            },
        ],
    )
    unchanged_id = seed_demo(
        conversations,
        research,
        title="no material changes",
        baseline_report="""# Polaris API — April baseline

## Availability
The API is available in the documented production regions. [S1]

## Authentication
Production requests require a scoped bearer token. [S2]""",
        latest_report="""# Polaris API — updated report

## Availability
The API remains available in the same production regions. [S1]

## Authentication
Production requests still require a scoped bearer token. [S2]""",
        baseline_rows=[
            ("S1", "April availability", "https://example.com/polaris/april-availability", "2026-04-15"),
            ("S2", "April authentication", "https://example.com/polaris/april-auth", "2026-04-15"),
        ],
        latest_rows=[
            ("S1", "Current availability", "https://example.com/polaris/current-availability", "2026-08-22"),
            ("S2", "Current authentication", "https://example.com/polaris/current-auth", "2026-08-22"),
        ],
        claim_rows=[],
    )
    print("Seeded local Insight Diff demo conversations:")
    print(f"- Changes: http://127.0.0.1:3000/#/research/{changes_id}")
    print(f"- No changes: http://127.0.0.1:3000/#/research/{unchanged_id}")


if __name__ == "__main__":
    main()
