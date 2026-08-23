from __future__ import annotations

from backend.config import Settings
from backend.conversation_context import select_recent_history
from backend.fake_agent import FakeAgentProvider
from backend.models import AgentMode
from backend.models import Message
from backend.models import MessageRole
from backend.models import ResearchBudget
from backend.store import ConversationNotFoundError
from backend.store import JsonConversationRepository
from pathlib import Path
import json
import tempfile
import unittest
import uuid


class MindDomainAndRepositoryTest(unittest.TestCase):
    def test_versioned_chat_evaluation_cases(self) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "evals" / "chat-cases.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
        provider = FakeAgentProvider(delay_seconds=0)

        for case in cases:
            with self.subTest(case=case["id"]):
                reply = provider.create_reply(case["input"], case["mode"])
                streamed_reply = "".join(
                    provider.stream_reply(case["input"], case["mode"])
                )
                self.assertEqual(reply, streamed_reply)
                for phrase in case["required_phrases"]:
                    self.assertIn(phrase, reply)
                for phrase in case["forbidden_phrases"]:
                    self.assertNotIn(phrase, reply)
        self.assertFalse(provider.billable_model_calls)

    def test_json_repository_persists_and_enforces_tenant_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            repository = JsonConversationRepository(data_path)
            conversation_id = repository.append_exchange(
                None,
                "Explain the local vertical slice.",
                "This is a deterministic reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )
            repository.append_exchange(
                conversation_id,
                "Continue.",
                "This is the second reply.",
                AgentMode.CHAT,
                user_id="user-a",
            )

            summaries = repository.list_conversations("user-a")
            self.assertEqual(len(summaries), 1)
            self.assertEqual(str(summaries[0].id), conversation_id)
            self.assertEqual(summaries[0].message_count, 4)
            self.assertEqual(repository.list_conversations("user-b"), [])
            conversation = repository.get_conversation(
                conversation_id,
                "user-a",
            )
            self.assertEqual(len(conversation.messages), 4)
            self.assertEqual(conversation.messages[0].role, MessageRole.USER)
            with self.assertRaises(ConversationNotFoundError):
                repository.get_conversation(conversation_id, "user-b")
            with self.assertRaises(ConversationNotFoundError):
                repository.append_exchange(
                    conversation_id,
                    "Cross-tenant access.",
                    "This must not be written.",
                    AgentMode.CHAT,
                    user_id="user-b",
                )
            repository.delete_conversation(conversation_id, "user-a")
            self.assertEqual(repository.list_conversations("user-a"), [])
            with self.assertRaises(ConversationNotFoundError):
                repository.delete_conversation(conversation_id, "user-a")
            self.assertTrue(data_path.exists())

    def test_repository_reads_legacy_conversations_without_rewriting_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            conversation_id = str(uuid.uuid4())
            timestamp = "2026-01-01T00:00:00+00:00"
            legacy_payload = {
                "conversations": [
                    {
                        "id": conversation_id,
                        "title": "Legacy conversation",
                        "mode": "chat",
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Legacy question",
                                "created_at": timestamp,
                            },
                            {
                                "role": "assistant",
                                "content": "Legacy answer",
                                "created_at": timestamp,
                            },
                        ],
                    }
                ]
            }
            original_json = json.dumps(legacy_payload, ensure_ascii=False)
            data_path.write_text(original_json, encoding="utf-8")
            repository = JsonConversationRepository(data_path)

            first_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )
            second_read = repository.get_conversation(
                conversation_id,
                "local-developer",
            )

            self.assertEqual(first_read.user_id, "local-developer")
            self.assertEqual(len(first_read.messages), 2)
            self.assertEqual(
                first_read.messages[0].conversation_id,
                first_read.id,
            )
            self.assertEqual(
                first_read.messages[0].id,
                second_read.messages[0].id,
            )
            self.assertEqual(
                data_path.read_text(encoding="utf-8"),
                original_json,
            )

    def test_context_selection_keeps_only_recent_complete_turns(self) -> None:
        conversation_id = uuid.uuid4()
        messages = [
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="old question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="old answer",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="new question",
            ),
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="new answer",
            ),
        ]

        history = select_recent_history(
            messages,
            max_characters=len("new questionnew answer"),
        )

        self.assertEqual(
            [message.content for message in history],
            ["new question", "new answer"],
        )
        self.assertEqual(select_recent_history(messages, max_characters=1), [])

    def test_legacy_research_budget_without_soft_timeout_still_loads(self) -> None:
        budget = ResearchBudget.model_validate({"timeout_seconds": 600})

        self.assertIsNone(budget.soft_timeout_seconds)

    def test_production_requires_firebase_and_restricted_access(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Firebase authentication",
        ):
            Settings(environment="production")

        with self.assertRaisesRegex(ValueError, "MIND_ALLOWED_USER_EMAILS"):
            Settings(
                environment="production",
                auth_provider="firebase",
                firebase_project_id="mind-production",
                openai_api_key="test-key",
                allowed_origins=("https://mind.example",),
            )

        with self.assertRaisesRegex(
            ValueError,
            "MIND_MAX_CONTEXT_CHARACTERS",
        ):
            Settings(max_context_characters=0)
        with self.assertRaisesRegex(ValueError, "MIND_FILE_STORAGE_BUCKET"):
            Settings(file_storage_provider="gcs")
        with self.assertRaisesRegex(ValueError, "MIND_MAX_FILE_BYTES"):
            Settings(max_file_bytes=20_000_001)
        with self.assertRaisesRegex(ValueError, "MIND_CHAT_DAILY_LIMIT"):
            Settings(chat_daily_limit=0)
        with self.assertRaisesRegex(ValueError, "MIND_RESEARCH_DAILY_LIMIT"):
            Settings(research_daily_limit=0)
        with self.assertRaisesRegex(
            ValueError,
            "MIND_RESEARCH_MAX_ACTIVE_PER_USER",
        ):
            Settings(research_max_active_per_user=0)
