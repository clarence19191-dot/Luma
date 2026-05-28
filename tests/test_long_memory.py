import tempfile
import unittest
from pathlib import Path

from luma.brain.memory import MemoryStore


class LongMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = MemoryStore(root / "state.sqlite3", root / "events.jsonl")

    def tearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    def test_saves_relationship_preference(self):
        saved = self.memory.save_memory_candidate(
            {"type": "preference", "content": "用户喜欢被叫小星。", "confidence": 0.9},
            source_conversation_id=None,
            source_turn_id=None,
        )
        self.assertIsNotNone(saved)
        self.assertEqual(self.memory.list_memories()[0]["content"], "用户喜欢被叫小星。")

    def test_rejects_sensitive_but_keeps_short_term_event_memory(self):
        sensitive = self.memory.save_memory_candidate(
            {"type": "preference", "content": "用户的 API key 是 sk-123。", "confidence": 0.99},
            source_conversation_id=None,
            source_turn_id=None,
        )
        event = self.memory.save_memory_candidate(
            {"type": "task", "content": "用户今天要写周报。", "confidence": 0.9},
            source_conversation_id=None,
            source_turn_id=None,
        )
        self.assertIsNone(sensitive)
        self.assertIsNotNone(event)
        self.assertEqual(event["category"], "event")
        self.assertEqual(event["horizon"], "short_term")
        self.assertIsNotNone(event["expires_at"])

    def test_merges_similar_memory_without_overwriting_content(self):
        first = self.memory.save_memory_candidate(
            {
                "category": "preference",
                "content": "用户喜欢被叫小星。",
                "confidence": 0.72,
                "importance": 0.6,
                "evidence": "用户说叫我小星就好。",
            },
            source_conversation_id=None,
            source_turn_id=None,
        )
        second = self.memory.save_memory_candidate(
            {
                "category": "preference",
                "content": "用户很喜欢被叫小星。",
                "confidence": 0.9,
                "importance": 0.8,
                "evidence": "用户再次确认喜欢小星这个称呼。",
            },
            source_conversation_id=None,
            source_turn_id=None,
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["content"], "用户喜欢被叫小星。")
        self.assertEqual(second["confidence"], 0.9)
        self.assertEqual(second["importance"], 0.8)
        self.assertEqual(len(second["evidence"]), 2)

    def test_duplicate_short_term_does_not_downgrade_long_term_memory(self):
        first = self.memory.save_memory_candidate(
            {
                "category": "preference",
                "horizon": "long_term",
                "content": "用户喜欢被叫小星。",
                "confidence": 0.9,
            },
            source_conversation_id=None,
            source_turn_id=None,
        )
        second = self.memory.save_memory_candidate(
            {
                "category": "preference",
                "horizon": "short_term",
                "content": "用户很喜欢被叫小星。",
                "confidence": 0.91,
                "ttl_days": 3,
            },
            source_conversation_id=None,
            source_turn_id=None,
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["horizon"], "long_term")
        self.assertIsNone(second["expires_at"])

    def test_soft_deleted_memory_is_not_injected(self):
        saved = self.memory.save_memory_candidate(
            {"type": "interaction", "content": "用户不喜欢夸张卖萌。", "confidence": 0.9},
            source_conversation_id=None,
            source_turn_id=None,
        )
        self.assertTrue(self.memory.soft_delete_memory(saved["id"]))
        self.assertEqual(self.memory.list_memories(), [])
        self.assertEqual(self.memory.relevant_memories("别卖萌"), [])

    def test_forget_text_soft_deletes_matching_chinese_memory(self):
        self.memory.save_memory_candidate(
            {"type": "preference", "content": "用户喜欢咖啡。", "confidence": 0.9},
            source_conversation_id=None,
            source_turn_id=None,
        )
        self.assertEqual(self.memory.soft_delete_matching_memories("忘掉我喜欢咖啡"), 1)
        self.assertEqual(self.memory.list_memories(), [])


if __name__ == "__main__":
    unittest.main()
