import tempfile
import unittest
from pathlib import Path

from luma.brain.conversation import ConversationManager
from luma.brain.llm import LumaLLMDecision, fallback_decision
from luma.brain.memory import MemoryStore


class FakeDecisionProvider:
    def __init__(self, decision: LumaLLMDecision | None = None):
        self.decision = decision or fallback_decision("我在这儿。", emotion="happy", tone="warm", pet_behavior="react")
        self.messages = []

    async def decide(self, messages):
        self.messages = messages
        return self.decision


class ConversationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = MemoryStore(root / "state.sqlite3", root / "events.jsonl")
        self.manager = ConversationManager(self.memory, FakeDecisionProvider())

    async def asyncTearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    def seed_conversation(self, *, text="我喜欢咖啡", reply="记住啦。", now=1000.0):
        conversation = self.memory.create_conversation("local", now=now, topic="咖啡")
        self.memory.append_turn(
            conversation["id"],
            user_text=text,
            luma_text=reply,
            decision={},
            emotion="happy",
            tone="warm",
            pet_behavior="react",
            now=now,
        )
        return self.memory.get_conversation(conversation["id"])

    def test_30_seconds_defaults_same_conversation(self):
        previous = self.seed_conversation(now=1000)
        boundary = self.manager.decide_boundary("这个还挺香", previous, now=1030)
        self.assertEqual(boundary.decision, "same")

    def test_60_seconds_same_topic_reuses_but_unrelated_starts_new(self):
        previous = self.seed_conversation(now=1000)
        same = self.manager.decide_boundary("咖啡还有吗", previous, now=1060)
        unrelated = self.manager.decide_boundary("外面天气怎么样", previous, now=1060)
        self.assertEqual(same.decision, "same")
        self.assertEqual(unrelated.decision, "new")

    def test_3_to_5_minutes_defaults_new_but_explicit_continue_restores(self):
        previous = self.seed_conversation(now=1000)
        default = self.manager.decide_boundary("咖啡还有吗", previous, now=1240)
        explicit = self.manager.decide_boundary("继续刚才那个", previous, now=1240)
        self.assertEqual(default.decision, "new")
        self.assertEqual(explicit.decision, "resume")

    def test_long_gap_greeting_defaults_new(self):
        previous = self.seed_conversation(now=1000)
        boundary = self.manager.decide_boundary("露玛在吗", previous, now=1401)
        self.assertEqual(boundary.decision, "new")
        self.assertEqual(boundary.reason, "long_gap_greeting_reopens_presence")

    def test_emotional_continuity_can_restore_medium_gap(self):
        previous = self.seed_conversation(text="我好累", reply="靠一下，我在。", now=1000)
        boundary = self.manager.decide_boundary("还是好累", previous, now=1240)
        self.assertEqual(boundary.decision, "resume")
        self.assertIn("emotion", boundary.reason)

    async def test_process_turn_records_boundary_and_turn(self):
        result = await self.manager.process_user_turn("你好 Luma", device_id="local", now=1000)
        snapshot = self.manager.snapshot(device_id="local")
        self.assertEqual(result.conversation["id"], snapshot["conversation"]["id"])
        self.assertEqual(snapshot["recent_turns"][0]["luma_text"], "我在这儿。")
        self.assertEqual(snapshot["boundary"]["decision"], "new")


if __name__ == "__main__":
    unittest.main()
