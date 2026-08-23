from __future__ import annotations

from backend.app import create_app
from backend.auth import LocalAccountManager
from backend.models import AgentMode
from backend.models import LocalPrincipal
from backend.models import MemoryCreateRequest
from backend.models import ResearchJob
from backend.models import ResearchStatus
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from fastapi.testclient import TestClient
import uuid

from backend.tests.api_test_support import (
    MindApiTestCase,
)


class ApiAccountTest(MindApiTestCase):
    def test_account_deletion_stops_active_research_and_removes_owned_data(
        self,
    ) -> None:
        conversation_id = self.repository.append_user_message(
            None,
            "Research before deleting my account.",
            AgentMode.RESEARCH,
            user_id="local-developer",
        )
        job = ResearchJob(
            user_id="local-developer",
            conversation_id=uuid.UUID(conversation_id),
            query="Research before deleting my account.",
            status=ResearchStatus.COLLECTING,
            provider_response_id="resp_account_delete",
            provider_status="in_progress",
        )
        self.research_repository.create_job(job)
        self.research_provider.register(
            "resp_account_delete",
            {"id": "resp_account_delete", "status": "in_progress", "output": []},
        )
        self.memory_service.create_memory(
            MemoryCreateRequest(content="Remember this before account deletion."),
            "local-developer",
        )
        attachment = self.file_service.upload(
            user_id="local-developer",
            name="account-data.txt",
            media_type="text/plain",
            content=b"Delete this private file with the account.",
        )
        self.assertTrue(any(self.local_file_path.rglob("account-data.txt")))

        response = self.client.delete(
            "/api/account",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.research_provider.cancel_calls,
            ["resp_account_delete"],
        )
        self.assertEqual(self.repository.list_conversations("local-developer"), [])
        self.assertEqual(self.research_repository.list_jobs("local-developer"), [])
        self.assertEqual(self.memory_repository.list_memories("local-developer"), [])
        self.assertEqual(
            self.attachment_repository.list_attachments("local-developer"),
            [],
        )
        self.assertFalse(any(self.local_file_path.rglob("account-data.txt")))
        self.assertIsNotNone(attachment.id)

    def test_firebase_account_deletion_requires_recent_authentication(self) -> None:
        class OldFirebasePrincipalVerifier:
            method = "firebase"

            def verify(self, _token: str) -> LocalPrincipal:
                return LocalPrincipal(
                    user_id="firebase-user",
                    email="owner@example.com",
                    email_verified=True,
                    authenticated_at=datetime.now(timezone.utc) - timedelta(hours=1),
                    authentication_method="firebase",
                )

        client = TestClient(
            create_app(
                settings=self.settings,
                repository=self.repository,
                provider=self.provider,
                research_repository=self.research_repository,
                research_provider=self.research_provider,
                principal_verifier=OldFirebasePrincipalVerifier(),
                account_manager=LocalAccountManager(),
            )
        )
        self.addCleanup(client.close)

        response = client.delete(
            "/api/account",
            headers={"Authorization": "Bearer firebase-token"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "recent_authentication_required",
        )
