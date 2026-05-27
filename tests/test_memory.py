import tempfile
import unittest
from pathlib import Path

from luma.brain.memory import MemoryStore


class MemoryTests(unittest.TestCase):
    def test_logs_to_sqlite_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = MemoryStore(root / "state.sqlite3", root / "events.jsonl")
            memory.log("command_queued", {"command_id": "cmd_test"})
            recent = memory.recent(limit=5)
            memory.close()

            self.assertEqual(recent[0]["kind"], "command_queued")
            self.assertTrue((root / "events.jsonl").read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()

