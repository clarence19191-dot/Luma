import unittest

from luma.brain.commands import normalize_command
from luma.brain.state import LumaState


class StateTests(unittest.TestCase):
    def test_applies_head_and_emotion(self):
        state = LumaState()
        state.apply_command(normalize_command({"type": "set_emotion", "emotion": "happy"}))
        state.apply_command(normalize_command({"type": "move_head", "pan": 20, "tilt": -10}))
        snapshot = state.snapshot()
        self.assertEqual(snapshot["emotion"], "happy")
        self.assertEqual(snapshot["head"]["pan"], 20)
        self.assertEqual(snapshot["head"]["tilt"], -10)

    def test_speak_sets_speech_and_speaking_emotion(self):
        state = LumaState()
        state.apply_command(normalize_command({"type": "speak", "text": "hello"}))
        snapshot = state.snapshot()
        self.assertTrue(snapshot["speech"]["active"])
        self.assertEqual(snapshot["emotion"], "speaking")

    def test_estop_resets_safe_state(self):
        state = LumaState()
        state.apply_command(normalize_command({"type": "move_head", "pan": 20, "tilt": -10}))
        state.apply_command(normalize_command({"type": "estop"}))
        snapshot = state.snapshot()
        self.assertTrue(snapshot["device"]["estopped"])
        self.assertEqual(snapshot["head"]["pan"], 0)
        self.assertEqual(snapshot["head"]["tilt"], 0)

    def test_reset_estop_rearms_device(self):
        state = LumaState()
        state.apply_command(normalize_command({"type": "estop"}))
        state.apply_command(normalize_command({"type": "reset_estop"}))
        self.assertFalse(state.snapshot()["device"]["estopped"])


if __name__ == "__main__":
    unittest.main()
