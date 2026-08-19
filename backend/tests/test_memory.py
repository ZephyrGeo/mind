from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.memory_embedding import OpenAIEmbeddingProvider
from backend.memory_provider import (
    MemoryProposal,
    MemoryProposalAction,
    MemoryProviderError,
    OpenAIMemoryProvider,
)
from backend.memory_retrieval import LocalMemoryRetriever
from backend.memory_service import MemoryService
from backend.memory_store import JsonMemoryRepository, MemoryNotFoundError
from backend.models import (
    Memory,
    MemoryCreateRequest,
    MemoryProvenance,
    MemoryReviewReason,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    MemoryUpdateRequest,
)


class MemoryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = JsonMemoryRepository(
            Path(self.temporary_directory.name) / "memories.json"
        )
        self.service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            retrieval_limit=3,
            max_context_characters=800,
        )

    def test_candidates_are_deduplicated_and_require_confirmation(self) -> None:
        conversation_id = uuid.uuid4()
        first = self.service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=conversation_id,
            user_message="我的目标是今年发布 Mind。",
        )
        second = self.service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=conversation_id,
            user_message="我的目标是今年发布 Mind。",
        )

        self.assertEqual(second, [])
        self.assertEqual(len(self.repository.list_memories("owner")), 1)
        self.assertEqual(first[0].status, MemoryStatus.CANDIDATE)
        self.assertEqual(self.service.retrieve("owner", "Mind 发布计划"), [])

        confirmed = self.service.confirm_memory(first[0].id, "owner")
        matches = self.service.retrieve("owner", "Mind 发布计划")
        self.assertTrue(confirmed.enabled)
        self.assertEqual([match.memory.id for match in matches], [confirmed.id])

    def test_candidate_capture_reuses_one_loaded_ledger(self) -> None:
        with patch.object(
            self.repository,
            "list_memories",
            wraps=self.repository.list_memories,
        ) as list_memories:
            captured = self.service.capture_conversation_candidates(
                user_id="owner",
                conversation_id=uuid.uuid4(),
                user_message=(
                    "我的项目叫 Mind。"
                    "我偏好用中文回答。"
                ),
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(list_memories.call_count, 1)

    def test_questions_are_ignored_and_explicit_remember_is_immediately_active(self) -> None:
        conversation_id = uuid.uuid4()
        self.assertEqual(
            self.service.capture_conversation_candidates(
                user_id="owner",
                conversation_id=conversation_id,
                user_message="我的项目叫什么？我偏好怎样的回答方式？",
            ),
            [],
        )

        remembered = self.service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=conversation_id,
            user_message="请记住，我的项目叫 Mind。",
        )

        self.assertEqual(len(remembered), 1)
        self.assertEqual(remembered[0].status, MemoryStatus.ACTIVE)
        self.assertTrue(remembered[0].enabled)
        self.assertIsNone(remembered[0].review_reason)

    def test_resume_summary_is_one_atomic_memory_and_updates_as_a_unit(self) -> None:
        conversation_id = uuid.uuid4()
        first = self.service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=conversation_id,
            user_message=(
                "请记住，我的简历总结如下：\n"
                "- 五年软件工程经验。\n"
                "- 曾负责地图数据平台。\n"
                "- 擅长 Python 和云服务。"
            ),
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].canonical_key, "fact:professional-profile")
        self.assertEqual(first[0].status, MemoryStatus.ACTIVE)
        self.assertIn("地图数据平台", first[0].content)
        self.assertEqual(len(self.repository.list_memories("owner")), 1)

        update = self.service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message=(
                "我的简历总结更新：目前有六年软件工程经验，"
                "主要负责 AI Agent 和地图数据产品。"
            ),
        )

        self.assertEqual(len(update), 1)
        self.assertEqual(update[0].canonical_key, "fact:professional-profile")
        self.assertEqual(update[0].review_reason, MemoryReviewReason.UPDATE)
        self.assertEqual(update[0].supersedes_id, first[0].id)

        self.service.confirm_memory(update[0].id, "owner")
        ledger = self.repository.list_memories("owner")
        self.assertEqual(
            sum(memory.status == MemoryStatus.ACTIVE for memory in ledger),
            1,
        )
        self.assertEqual(
            sum(memory.status == MemoryStatus.SUPERSEDED for memory in ledger),
            1,
        )

    def test_group_facets_are_persisted_and_used_for_retrieval(self) -> None:
        service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            provider=FacetMemoryProvider(),
        )

        changes = service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message="请记住我的职业背景。",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].content, "我的职业档案摘要。")
        self.assertEqual(changes[0].facets, ["我负责量子地图索引系统。"])
        matches = service.retrieve("owner", "量子地图索引")
        self.assertEqual([match.memory.id for match in matches], [changes[0].id])

    def test_legacy_question_candidate_is_archived_without_silent_deletion(self) -> None:
        legacy = Memory(
            user_id="owner",
            type=MemoryType.PREFERENCE,
            content="我偏好怎样的回答方式？",
            status=MemoryStatus.CANDIDATE,
            enabled=False,
        )
        self.repository.create_memory(legacy)

        refreshed = self.service.list_memories("owner")

        self.assertEqual(len(refreshed), 1)
        self.assertEqual(refreshed[0].status, MemoryStatus.SUPERSEDED)
        self.assertFalse(refreshed[0].enabled)

    def test_inferred_update_supersedes_only_after_confirmation(self) -> None:
        existing = self.service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.PREFERENCE,
                content="我偏好使用中文回答。",
            ),
            "owner",
        )
        provider = RelatedUpdateProvider()
        service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            provider=provider,
        )

        changes = service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message="技术问题以后使用英文回答。",
        )

        self.assertEqual(len(changes), 1)
        update = changes[0]
        self.assertEqual(update.status, MemoryStatus.CANDIDATE)
        self.assertEqual(update.review_reason, MemoryReviewReason.UPDATE)
        self.assertEqual(update.supersedes_id, existing.id)
        self.assertEqual(
            self.repository.get_memory(existing.id, "owner").status,
            MemoryStatus.ACTIVE,
        )

        service.confirm_memory(update.id, "owner")
        self.assertEqual(
            self.repository.get_memory(existing.id, "owner").status,
            MemoryStatus.SUPERSEDED,
        )
        self.assertEqual(
            self.repository.get_memory(update.id, "owner").status,
            MemoryStatus.ACTIVE,
        )

    def test_matching_canonical_key_converts_create_into_reviewed_update(self) -> None:
        existing = Memory(
            user_id="owner",
            type=MemoryType.PREFERENCE,
            content="我偏好使用中文回答。",
            status=MemoryStatus.ACTIVE,
            enabled=True,
            canonical_key="preference:answer-language",
        )
        self.repository.create_memory(existing)
        service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            provider=CanonicalCreateProvider(),
        )

        changes = service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message="技术问题使用英文回答。",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].review_reason, MemoryReviewReason.UPDATE)
        self.assertEqual(changes[0].supersedes_id, existing.id)
        self.assertEqual(
            self.repository.get_memory(existing.id, "owner").status,
            MemoryStatus.ACTIVE,
        )

    def test_conflict_keeps_existing_active_until_user_selects_new_version(self) -> None:
        existing = self.service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.PROJECT,
                content="Mind launches on Friday.",
            ),
            "owner",
        )
        service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            provider=RelatedConflictProvider(),
        )

        changes = service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message="Mind launches next Monday instead.",
        )

        self.assertEqual(len(changes), 1)
        conflict = changes[0]
        self.assertEqual(conflict.status, MemoryStatus.CONFLICT)
        self.assertEqual(conflict.review_reason, MemoryReviewReason.CONFLICT)
        self.assertEqual(conflict.supersedes_id, existing.id)
        self.assertEqual(
            self.repository.get_memory(existing.id, "owner").status,
            MemoryStatus.ACTIVE,
        )

        service.confirm_memory(conflict.id, "owner")
        self.assertEqual(
            self.repository.get_memory(existing.id, "owner").status,
            MemoryStatus.SUPERSEDED,
        )
        self.assertEqual(
            self.repository.get_memory(conflict.id, "owner").status,
            MemoryStatus.ACTIVE,
        )

    def test_stale_memory_is_disabled_during_ledger_refresh(self) -> None:
        memory = self.service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.FACT,
                content="The current launch date is Friday.",
            ),
            "owner",
        )
        self.repository.save_memory(
            memory.model_copy(
                update={
                    "stale_after": datetime.now(timezone.utc) - timedelta(seconds=1)
                }
            ),
            "owner",
        )

        refreshed = self.service.list_memories("owner")[0]
        self.assertEqual(refreshed.status, MemoryStatus.STALE)
        self.assertFalse(refreshed.enabled)
        self.assertEqual(self.service.retrieve("owner", "launch date"), [])

        reconfirmed = self.service.confirm_memory(refreshed.id, "owner")
        self.assertEqual(reconfirmed.status, MemoryStatus.ACTIVE)
        self.assertTrue(reconfirmed.enabled)
        self.assertGreater(
            reconfirmed.stale_after or datetime.min.replace(tzinfo=timezone.utc),
            datetime.now(timezone.utc),
        )
        self.assertTrue(self.service.retrieve("owner", "launch date"))

    def test_semantic_provider_failure_does_not_create_rule_fallback_memory(self) -> None:
        service = MemoryService(
            repository=self.repository,
            retriever=LocalMemoryRetriever(self.repository),
            provider=FailingMemoryProvider(),
        )

        changes = service.capture_conversation_candidates(
            user_id="owner",
            conversation_id=uuid.uuid4(),
            user_message="我的目标是周五发布 Mind。",
        )

        self.assertEqual(changes, [])
        self.assertEqual(self.repository.list_memories("owner"), [])

    def test_disabled_expired_and_deleted_memories_are_not_retrieved(self) -> None:
        memory = self.service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.PREFERENCE,
                content="I prefer concise product updates.",
            ),
            "owner",
        )
        self.assertTrue(self.service.retrieve("owner", "concise update"))

        self.service.update_memory(
            memory.id,
            MemoryUpdateRequest(enabled=False),
            "owner",
        )
        self.assertEqual(self.service.retrieve("owner", "concise update"), [])

        self.service.update_memory(
            memory.id,
            MemoryUpdateRequest(
                enabled=True,
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            ),
            "owner",
        )
        self.assertEqual(self.service.retrieve("owner", "concise update"), [])

        self.service.delete_memory(memory.id, "owner")
        with self.assertRaises(MemoryNotFoundError):
            self.repository.get_memory(memory.id, "owner")

    def test_report_candidates_keep_provenance_but_do_not_activate(self) -> None:
        conversation_id = uuid.uuid4()
        job_id = uuid.uuid4()
        candidates = self.service.capture_research_report_candidates(
            user_id="owner",
            conversation_id=conversation_id,
            research_job_id=job_id,
            report=(
                "## Recommendation\n\n"
                "- 工程建议（非来源事实）：建议采用分阶段发布并保留回滚开关。\n"
            ),
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.type, MemoryType.DECISION)
        self.assertEqual(candidate.provenance.research_job_id, job_id)
        self.assertFalse(candidate.enabled)


class RelatedUpdateProvider:
    name = "test"
    model = "test-memory-model"
    billable_calls = False

    def extract(
        self,
        text: str,
        *,
        source_kind: MemorySourceKind,
        related_memories: list[Any],
    ) -> list[MemoryProposal]:
        related = related_memories[0]
        return [
            MemoryProposal(
                action=MemoryProposalAction.UPDATE,
                type=MemoryType.PREFERENCE,
                content="我偏好技术问题使用英文回答。",
                canonical_key="preference:answer-language:technical",
                explicit=False,
                sensitive=False,
                confidence=0.92,
                related_memory_id=related.id,
                rationale="The preference changed for a narrower scope.",
            )
        ]


class FacetMemoryProvider:
    name = "test"
    model = "test-memory-model"
    billable_calls = False

    def extract(
        self,
        text: str,
        *,
        source_kind: MemorySourceKind,
        related_memories: list[Any],
    ) -> list[MemoryProposal]:
        del text, source_kind, related_memories
        return [
            MemoryProposal(
                action=MemoryProposalAction.CREATE,
                type=MemoryType.FACT,
                content="我的职业档案摘要。",
                canonical_key="fact:professional-profile",
                explicit=True,
                sensitive=False,
                confidence=0.95,
                facets=("我负责量子地图索引系统。",),
            )
        ]


class RelatedConflictProvider:
    name = "test"
    model = "test-memory-model"
    billable_calls = False

    def extract(
        self,
        text: str,
        *,
        source_kind: MemorySourceKind,
        related_memories: list[Any],
    ) -> list[MemoryProposal]:
        related = related_memories[0]
        return [
            MemoryProposal(
                action=MemoryProposalAction.CONFLICT,
                type=MemoryType.PROJECT,
                content="Mind launches next Monday.",
                canonical_key="project:mind:launch-date",
                explicit=False,
                sensitive=False,
                confidence=0.95,
                related_memory_id=related.id,
                rationale="The new launch date contradicts the existing date.",
            )
        ]


class CanonicalCreateProvider:
    name = "test"
    model = "test-memory-model"
    billable_calls = False

    def extract(
        self,
        text: str,
        *,
        source_kind: MemorySourceKind,
        related_memories: list[Any],
    ) -> list[MemoryProposal]:
        return [
            MemoryProposal(
                action=MemoryProposalAction.CREATE,
                type=MemoryType.PREFERENCE,
                content="我偏好技术问题使用英文回答。",
                canonical_key="preference:answer-language",
                explicit=False,
                sensitive=False,
                confidence=0.9,
            )
        ]


class FailingMemoryProvider:
    name = "openai"
    model = "test-memory-model"
    billable_calls = True

    def extract(
        self,
        text: str,
        *,
        source_kind: MemorySourceKind,
        related_memories: list[Any],
    ) -> list[MemoryProposal]:
        raise MemoryProviderError("temporary failure")


class StubResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "StubResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int) -> bytes:
        return self.payload


class MemoryProviderTest(unittest.TestCase):
    def test_openai_memory_uses_strict_schema_and_parses_update(self) -> None:
        requests: list[Any] = []
        existing_id = uuid.uuid4()

        def opener(request: Any, *, timeout: float) -> StubResponse:
            requests.append((request, timeout))
            return StubResponse(
                {
                    "id": "resp_memory",
                    "output_text": json.dumps(
                        {
                            "memory_groups": [
                                {
                                    "action": "update",
                                    "type": "preference",
                                    "content": "我偏好技术问题使用英文回答。",
                                    "facets": ["技术问题使用英文回答。"],
                                    "canonical_key": "preference:technical-language",
                                    "explicit": False,
                                    "sensitive": False,
                                    "confidence": 0.94,
                                    "related_memory_id": str(existing_id),
                                    "stale_after_days": None,
                                    "rationale": "A scoped preference update.",
                                }
                            ]
                        }
                    ),
                }
            )

        provider = OpenAIMemoryProvider(
            api_key="test-key",
            opener=opener,
        )
        related = self._memory(existing_id)
        proposals = provider.extract(
            "技术问题以后使用英文回答。",
            source_kind=MemorySourceKind.CONVERSATION,
            related_memories=[related],
        )

        self.assertEqual(proposals[0].action, MemoryProposalAction.UPDATE)
        self.assertEqual(proposals[0].related_memory_id, existing_id)
        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertIn("memory_groups", body["text"]["format"]["schema"]["properties"])
        self.assertIn("same specific subject", body["input"])
        self.assertIn("Do not group facts merely", body["input"])

    def test_openai_memory_keeps_independent_subjects_in_separate_groups(self) -> None:
        def opener(request: Any, *, timeout: float) -> StubResponse:
            del request, timeout
            groups = [
                {
                    "action": "create",
                    "type": memory_type,
                    "content": content,
                    "facets": facets,
                    "canonical_key": key,
                    "explicit": False,
                    "sensitive": False,
                    "confidence": 0.92,
                    "related_memory_id": None,
                    "stale_after_days": None,
                    "rationale": "One subject and lifecycle.",
                }
                for memory_type, content, facets, key in (
                    (
                        "project",
                        "我的产品 Mind 是个人智能助手，计划周五发布。",
                        ["Mind 是个人智能助手。", "Mind 计划周五发布。"],
                        "project:mind:overview",
                    ),
                    (
                        "project",
                        "我的测试项目 Lantern 用于验证记忆检索。",
                        ["Lantern 用于验证记忆检索。"],
                        "project:lantern:overview",
                    ),
                    (
                        "preference",
                        "我偏好使用中文回答。",
                        ["回答语言为中文。"],
                        "preference:response-language",
                    ),
                )
            ]
            return StubResponse(
                {
                    "id": "resp_grouped_memory",
                    "output_text": json.dumps({"memory_groups": groups}),
                }
            )

        provider = OpenAIMemoryProvider(api_key="test-key", opener=opener)
        proposals = provider.extract(
            "Mind 是我的产品且周五发布；Lantern 是测试项目；我偏好中文回答。",
            source_kind=MemorySourceKind.CONVERSATION,
            related_memories=[],
        )

        self.assertEqual(len(proposals), 3)
        self.assertEqual(
            [proposal.canonical_key for proposal in proposals],
            [
                "project:mind:overview",
                "project:lantern:overview",
                "preference:response-language",
            ],
        )
        self.assertEqual(len(proposals[0].facets), 2)

    def test_openai_memory_merges_duplicate_output_for_one_group_key(self) -> None:
        def opener(request: Any, *, timeout: float) -> StubResponse:
            del request, timeout
            groups = [
                {
                    "action": "create",
                    "type": "project",
                    "content": content,
                    "facets": [facet],
                    "canonical_key": "project:mind:overview",
                    "explicit": False,
                    "sensitive": False,
                    "confidence": 0.9,
                    "related_memory_id": None,
                    "stale_after_days": None,
                    "rationale": "Project detail.",
                }
                for content, facet in (
                    ("Mind 是个人智能助手。", "产品名称是 Mind。"),
                    ("Mind 计划周五发布。", "发布时间是周五。"),
                )
            ]
            return StubResponse(
                {
                    "id": "resp_duplicate_groups",
                    "output_text": json.dumps({"memory_groups": groups}),
                }
            )

        provider = OpenAIMemoryProvider(api_key="test-key", opener=opener)
        proposals = provider.extract(
            "我的项目叫 Mind，是个人智能助手，计划周五发布。",
            source_kind=MemorySourceKind.CONVERSATION,
            related_memories=[],
        )

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].canonical_key, "project:mind:overview")
        self.assertIn("个人智能助手", proposals[0].content)
        self.assertIn("周五发布", proposals[0].content)
        self.assertEqual(len(proposals[0].facets), 2)

    def test_openai_memory_consolidates_split_resume_proposals(self) -> None:
        requests: list[Any] = []

        def opener(request: Any, *, timeout: float) -> StubResponse:
            requests.append((request, timeout))
            proposals = [
                {
                    "action": "create",
                    "type": "fact",
                    "content": content,
                    "facets": [content],
                    "canonical_key": key,
                    "explicit": False,
                    "sensitive": False,
                    "confidence": 0.9,
                    "related_memory_id": None,
                    "stale_after_days": None,
                    "rationale": "A resume detail.",
                }
                for content, key in (
                    ("我有五年软件工程经验。", "fact:experience"),
                    ("我曾负责地图数据平台。", "fact:work-history"),
                    ("我擅长 Python 和云服务。", "fact:skills"),
                )
            ]
            return StubResponse(
                {
                    "id": "resp_resume_memory",
                    "output_text": json.dumps({"memory_groups": proposals}),
                }
            )

        provider = OpenAIMemoryProvider(api_key="test-key", opener=opener)
        proposals = provider.extract(
            (
                "我的简历总结如下：五年软件工程经验；曾负责地图数据平台；"
                "擅长 Python 和云服务。"
            ),
            source_kind=MemorySourceKind.CONVERSATION,
            related_memories=[],
        )

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].type, MemoryType.FACT)
        self.assertEqual(proposals[0].canonical_key, "fact:professional-profile")
        self.assertIn("五年软件工程经验", proposals[0].content)
        self.assertIn("地图数据平台", proposals[0].content)
        self.assertIn("Python 和云服务", proposals[0].content)
        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertIn("one atomic group", body["input"])
        self.assertIn("never split jobs", body["input"])

    def test_openai_memory_uses_a_research_specific_extraction_policy(self) -> None:
        requests: list[Any] = []

        def opener(request: Any, *, timeout: float) -> StubResponse:
            requests.append((request, timeout))
            return StubResponse(
                {
                    "id": "resp_research_memory",
                    "output_text": json.dumps({"memory_groups": []}),
                }
            )

        provider = OpenAIMemoryProvider(api_key="test-key", opener=opener)
        self.assertEqual(
            provider.extract(
                "## Recommendation\nUse staged rollout. [S1]",
                source_kind=MemorySourceKind.RESEARCH_REPORT,
                related_memories=[],
            ),
            [],
        )

        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertIn("completed Research report", body["input"])
        self.assertIn("all proposals will require user review", body["input"])

    def test_openai_embedding_preserves_input_order_and_dimensions(self) -> None:
        def opener(request: Any, *, timeout: float) -> StubResponse:
            body = json.loads(request.data.decode("utf-8"))
            dimensions = body["dimensions"]
            return StubResponse(
                {
                    "data": [
                        {"index": 1, "embedding": [0.0] * (dimensions - 1) + [1.0]},
                        {"index": 0, "embedding": [1.0] + [0.0] * (dimensions - 1)},
                    ]
                }
            )

        provider = OpenAIEmbeddingProvider(
            api_key="test-key",
            dimensions=32,
            opener=opener,
        )
        vectors = provider.embed(["first", "second"])

        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[0][0], 1.0)
        self.assertEqual(vectors[1][-1], 1.0)

    @staticmethod
    def _memory(memory_id: uuid.UUID) -> Memory:
        return Memory(
            id=memory_id,
            user_id="owner",
            type=MemoryType.PREFERENCE,
            content="我偏好使用中文回答。",
            provenance=MemoryProvenance(
                source_kind=MemorySourceKind.CONVERSATION,
            ),
            status=MemoryStatus.ACTIVE,
            enabled=True,
        )


if __name__ == "__main__":
    unittest.main()
