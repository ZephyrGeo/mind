from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app import LOCAL_TOKEN, is_authorized_header, validate_chat_payload
from backend.fake_agent import FakeAgent
from backend.store import ConversationStore


class MindApplicationTest(unittest.TestCase):
    def test_authentication_boundary_accepts_only_the_local_token(self) -> None:
        self.assertTrue(is_authorized_header(f"Bearer {LOCAL_TOKEN}"))
        self.assertFalse(is_authorized_header(None))
        self.assertFalse(is_authorized_header("Bearer wrong-token"))

    def test_chat_payload_validation(self) -> None:
        message, mode, conversation_id = validate_chat_payload(
            {"message": "  Investigate this topic.  ", "mode": "research"}
        )
        self.assertEqual(message, "Investigate this topic.")
        self.assertEqual(mode, "research")
        self.assertIsNone(conversation_id)

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            validate_chat_payload({"message": "   "})

    def test_fake_agent_is_deterministic_and_bill_free(self) -> None:
        agent = FakeAgent(delay_seconds=0)
        reply = agent.create_reply("Explain the local vertical slice.")
        streamed_reply = "".join(
            agent.stream_reply("Explain the local vertical slice.")
        )
        self.assertEqual(reply, streamed_reply)
        self.assertIn("without calling an external model", reply)

    def test_versioned_chat_evaluation_cases(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2] / "evals" / "chat-cases.json"
        )
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
        agent = FakeAgent(delay_seconds=0)

        for case in cases:
            with self.subTest(case=case["id"]):
                reply = agent.create_reply(case["input"], case["mode"])
                for phrase in case["required_phrases"]:
                    self.assertIn(phrase, reply)
                for phrase in case["forbidden_phrases"]:
                    self.assertNotIn(phrase, reply)

    def test_conversation_store_persists_and_summarizes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "conversations.json"
            store = ConversationStore(data_path)
            conversation_id = store.append_exchange(
                None,
                "Explain the local vertical slice.",
                "This is a deterministic reply.",
                "chat",
            )
            store.append_exchange(
                conversation_id,
                "Continue.",
                "This is the second reply.",
                "chat",
            )

            summaries = store.list_conversations()
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["id"], conversation_id)
            self.assertEqual(summaries[0]["message_count"], 4)
            self.assertTrue(data_path.exists())


if __name__ == "__main__":
    unittest.main()
