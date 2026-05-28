import unittest

from luma.brain.commands import CommandValidationError, normalize_command, normalize_command_batch
from luma.brain.emotions import emotion_duration_ms


class CommandTests(unittest.TestCase):
    def test_normalizes_basic_commands(self):
        command = normalize_command({"type": "move_head", "pan": 20, "tilt": -10})
        self.assertEqual(command["type"], "move_head")
        self.assertEqual(command["pan"], 20)
        self.assertEqual(command["tilt"], -10)
        self.assertEqual(command["speed_dps"], 60)
        self.assertIn("command_id", command)

    def test_rejects_out_of_range_motion(self):
        with self.assertRaises(CommandValidationError) as ctx:
            normalize_command({"type": "move_head", "pan": 200})
        self.assertEqual(ctx.exception.code, "out_of_range")

    def test_normalizes_sequence(self):
        commands = normalize_command_batch(
            {
                "type": "sequence",
                "steps": [
                    {"type": "set_emotion", "emotion": "thinking"},
                    {"type": "speak", "text": "hello"},
                ],
            }
        )
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["steps"][0]["emotion"], "thinking")

    def test_accepts_extended_emotions(self):
        command = normalize_command({"type": "set_emotion", "emotion": "angry_fire"})
        self.assertEqual(command["emotion"], "angry_fire")
        speak = normalize_command({"type": "speak", "text": "hello", "emotion": "uwu"})
        self.assertEqual(speak["emotion"], "uwu")

    def test_set_emotion_defaults_to_timed_playback(self):
        command = normalize_command({"type": "set_emotion", "emotion": "happy"})
        self.assertEqual(command["duration_ms"], emotion_duration_ms("happy"))
        self.assertNotEqual(command["duration_ms"], 3000)

    def test_set_emotion_preserves_explicit_persistent_duration(self):
        command = normalize_command({"type": "set_emotion", "emotion": "happy", "duration_ms": 0})
        self.assertEqual(command["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
