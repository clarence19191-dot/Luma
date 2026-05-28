import unittest

from luma.brain.emotions import emotion_duration_ms
from luma.brain.llm import fallback_decision, parse_llm_decision, parse_memory_reflection
from luma.brain.prompt import LUMA_SYSTEM_PROMPT, build_luma_messages


class LLMContractTests(unittest.TestCase):
    def test_system_prompt_is_desktop_pet_not_productivity_agent(self):
        self.assertIn("桌面 AI 宠物", LUMA_SYSTEM_PROMPT)
        self.assertIn("不是生产力 AI", LUMA_SYSTEM_PROMPT)
        self.assertIn("必须只输出 JSON", LUMA_SYSTEM_PROMPT)
        self.assertIn("V0 暂时没有舵机", LUMA_SYSTEM_PROMPT)
        self.assertIn("不是用户的情绪", LUMA_SYSTEM_PROMPT)
        self.assertIn("不要输出 expression.duration_ms", LUMA_SYSTEM_PROMPT)

    def test_prompt_builder_injects_relationship_context_not_event_log(self):
        messages = build_luma_messages(
            user_text="我还是好累",
            supported_emotions=["idle", "happy"],
            conversation={"id": "conv_a", "status": "active", "summary": "用户说累", "topic": "累", "emotion_tags": ["tired"]},
            boundary={"decision": "same", "reason": "emotion_continuity"},
            recent_turns=[{"user_text": "我好累", "luma_text": "靠一下，我在。", "tone": "warm", "pet_behavior": "comfort"}],
            memories=[{"id": 1, "type": "preference", "content": "用户喜欢被叫小星。", "confidence": 0.9}],
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("清醒陪伴型", LUMA_SYSTEM_PROMPT)
        self.assertIn("默认 1 句，最多 2 句", LUMA_SYSTEM_PROMPT)
        self.assertIn("V0 暂时没有舵机", LUMA_SYSTEM_PROMPT)
        self.assertIn('"available_luma_expressions":["idle","happy"]', messages[1]["content"])
        self.assertIn("memories", messages[1]["content"])
        self.assertNotIn("memory_candidates", messages[0]["content"])
        self.assertNotIn("duration_ms", messages[1]["content"])
        self.assertNotIn("command_queued", messages[1]["content"])

    def test_parses_valid_json_decision(self):
        decision = parse_llm_decision(
            """
            {
              "reply": {"text": "我在这儿。", "tone": "warm"},
              "expression": {"emotion": "happy", "duration_ms": 3000},
              "pet_behavior": "greet",
              "actions": [],
              "memory_candidates": [],
              "safety": {"blocked": false, "reason": "", "needs_clarification": false}
            }
            """
        )
        self.assertEqual(decision.reply.text, "我在这儿。")
        self.assertEqual(decision.expression.emotion, "happy")
        self.assertEqual(decision.expression.duration_ms, emotion_duration_ms("happy"))
        self.assertFalse(hasattr(decision, "memory_candidates"))

    def test_missing_expression_duration_uses_asset_duration(self):
        decision = parse_llm_decision(
            """
            {
              "reply": {"text": "我在这儿。", "tone": "warm"},
              "expression": {"emotion": "happy"},
              "pet_behavior": "greet",
              "actions": [],
              "memory_candidates": [],
              "safety": {"blocked": false, "reason": "", "needs_clarification": false}
            }
            """
        )
        self.assertEqual(decision.expression.duration_ms, emotion_duration_ms("happy"))

        short_decision = parse_llm_decision(
            """
            {
              "reply": {"text": "啪。", "tone": "playful"},
              "expression": {"emotion": "pop_cat"},
              "pet_behavior": "react",
              "actions": [],
              "memory_candidates": [],
              "safety": {"blocked": false, "reason": "", "needs_clarification": false}
            }
            """
        )
        self.assertEqual(short_decision.expression.duration_ms, emotion_duration_ms("pop_cat"))

    def test_repairs_malformed_json_when_available(self):
        decision = parse_llm_decision(
            """
            ```json
            {
              reply: {text: "刚刚听见你啦。", tone: "playful"},
              expression: {emotion: "smile", duration_ms: 3000},
              pet_behavior: "react",
              actions: [],
              memory_candidates: [],
              safety: {blocked: false, reason: "", needs_clarification: false},
            }
            ```
            """
        )
        self.assertEqual(decision.reply.text, "刚刚听见你啦。")
        self.assertEqual(decision.expression.emotion, "smile")

    def test_invalid_decision_can_fallback(self):
        decision = parse_llm_decision("not json", fallback_on_error=True)
        self.assertEqual(decision.reply.text, fallback_decision().reply.text)
        self.assertEqual(decision.expression.duration_ms, emotion_duration_ms(decision.expression.emotion))

    def test_parses_memory_reflection(self):
        reflection = parse_memory_reflection(
            """
            {
              "memories": [
                {
                  "operation": "upsert",
                  "category": "event",
                  "content": "用户这周在调试 Luma 的语音链路。",
                  "confidence": 0.82,
                  "importance": 0.55,
                  "evidence": "用户说今天继续调语音。"
                }
              ]
            }
            """
        )

        self.assertEqual(reflection.memories[0].category, "event")
        self.assertEqual(reflection.memories[0].horizon, "short_term")

    def test_memory_reflection_fallback_is_empty(self):
        reflection = parse_memory_reflection("not json", fallback_on_error=True)
        self.assertEqual(reflection.memories, [])


if __name__ == "__main__":
    unittest.main()
