from __future__ import annotations

from backend.app import create_app
from backend.models import MemoryCreateRequest
from backend.models import MemoryStatus
from backend.models import MemoryType
from fastapi.testclient import TestClient

from backend.tests.api_test_support import (
    MindApiTestCase,
    RecordingModelProvider,
    parse_sse,
)


class ApiMemoryTest(MindApiTestCase):
    def test_memory_ledger_lifecycle_is_tenant_scoped_and_user_controlled(
        self,
    ) -> None:
        created = self.client.post(
            "/api/memories",
            headers=self.auth_headers,
            json={
                "type": "preference",
                "content": "I prefer concise answers with clear next steps.",
                "pinned": True,
            },
        )
        self.assertEqual(created.status_code, 201)
        memory = created.json()
        self.assertEqual(memory["status"], "active")
        self.assertTrue(memory["enabled"])
        self.assertTrue(memory["pinned"])

        listed = self.client.get("/api/memories", headers=self.auth_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [item["id"] for item in listed.json()["memories"]], [memory["id"]]
        )

        updated = self.client.patch(
            f"/api/memories/{memory['id']}",
            headers=self.auth_headers,
            json={"enabled": False, "pinned": False},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["enabled"])
        self.assertFalse(updated.json()["pinned"])

        deleted = self.client.delete(
            f"/api/memories/{memory['id']}",
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get("/api/memories", headers=self.auth_headers).json(),
            {"memories": []},
        )

    def test_chat_creates_disabled_candidate_and_confirmed_memory_is_retrieved(
        self,
    ) -> None:
        first = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "我喜欢简洁的回答。", "mode": "chat"},
        )
        first_events = parse_sse(first.text)
        self.assertEqual(first_events[-1]["memory_candidate_count"], 1)
        candidate = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(
            first_events[-1]["memory_candidates"],
            [
                {
                    "id": str(candidate.id),
                    "type": candidate.type.value,
                    "status": candidate.status.value,
                    "review_reason": (
                        candidate.review_reason.value
                        if candidate.review_reason is not None
                        else None
                    ),
                }
            ],
        )
        self.assertEqual(candidate.type, MemoryType.PREFERENCE)
        self.assertEqual(candidate.status, MemoryStatus.CANDIDATE)
        self.assertFalse(candidate.enabled)

        confirmed = self.client.post(
            f"/api/memories/{candidate.id}/confirm",
            headers=self.auth_headers,
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["status"], "active")

        recording_provider = RecordingModelProvider()
        recording_client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=recording_provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                memory_repository=self.memory_repository,
                memory_service=self.memory_service,
            )
        )
        self.addCleanup(recording_client.close)
        second = recording_client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请简洁说明下一步。", "mode": "chat"},
        )
        second_events = parse_sse(second.text)
        self.assertIn("我喜欢简洁的回答", recording_provider.memory_context_calls[-1])
        self.assertEqual(second_events[-1]["memory_ids"], [str(candidate.id)])

        self.client.patch(
            f"/api/memories/{candidate.id}",
            headers=self.auth_headers,
            json={"enabled": False},
        )
        recording_client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请简洁说明风险。", "mode": "chat"},
        )
        self.assertEqual(recording_provider.memory_context_calls[-1], "")

    def test_memory_filters_credentials_and_marks_sensitive_candidates(self) -> None:
        rejected = self.client.post(
            "/api/memories",
            headers=self.auth_headers,
            json={
                "type": "fact",
                "content": "API key: sk-testcredential1234567890",
            },
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["error"]["code"], "memory_content_rejected")

        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请记住我的医疗诊断需要定期复查。", "mode": "chat"},
        )
        self.assertEqual(parse_sse(response.text)[-1]["memory_candidate_count"], 1)
        candidate = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(candidate.sensitivity.value, "sensitive")
        self.assertFalse(candidate.enabled)

    def test_explicit_non_sensitive_memory_is_saved_without_review(self) -> None:
        response = self.client.post(
            "/api/chat",
            headers=self.auth_headers,
            json={"message": "请记住，我的项目叫 Mind。", "mode": "chat"},
        )

        done = parse_sse(response.text)[-1]
        self.assertEqual(done["memory_candidate_count"], 0)
        self.assertEqual(done["memory_candidates"], [])
        self.assertEqual(done["memory_saved_count"], 1)
        memory = self.memory_repository.list_memories("local-developer")[0]
        self.assertEqual(memory.status, MemoryStatus.ACTIVE)
        self.assertTrue(memory.enabled)

    def test_research_persists_and_uses_relevant_confirmed_memory(self) -> None:
        memory = self.memory_service.create_memory(
            MemoryCreateRequest(
                type=MemoryType.PROJECT,
                content="My project uses Firebase authentication.",
            ),
            "local-developer",
        )
        response = self.client.post(
            "/api/research",
            headers=self.auth_headers,
            json={"query": "Research Firebase authentication patterns."},
        )
        events = parse_sse(response.text)
        job = self.research_repository.get_job(
            str(events[0]["job_id"]),
            "local-developer",
        )

        self.assertEqual(job.memory_ids, [memory.id])
        self.assertIn(
            "My project uses Firebase authentication",
            self.research_provider.start_calls[0].prompt,
        )
