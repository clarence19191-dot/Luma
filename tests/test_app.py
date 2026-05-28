import unittest
import time

from luma.brain.app import HeadLink, LumaRuntime
from luma.brain.commands import normalize_command


class FakeHead:
    def __init__(self):
        self.sent_json = []

    async def send_json(self, message):
        self.sent_json.append(message)
        return True


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = []
        self.json_messages = []
        self.byte_messages = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=None):
        self.closed.append({"code": code, "reason": reason})

    async def send_json(self, message):
        self.json_messages.append(message)

    async def send_bytes(self, payload):
        self.byte_messages.append(payload)


class HeadLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_cannot_replace_connected_device(self):
        head = HeadLink()
        device = FakeWebSocket()
        simulator = FakeWebSocket()

        self.assertTrue(await head.connect(device, "luma-core-s3", "device", []))
        self.assertFalse(await head.connect(simulator, "luma-browser-sim", "simulator", []))

        self.assertIs(head.websocket, device)
        self.assertTrue(device.accepted)
        self.assertFalse(simulator.accepted)
        self.assertEqual(simulator.closed, [{"code": 1008, "reason": "physical device already connected"}])

    async def test_device_replaces_simulator(self):
        head = HeadLink()
        simulator = FakeWebSocket()
        device = FakeWebSocket()

        self.assertTrue(await head.connect(simulator, "luma-browser-sim", "simulator", []))
        self.assertTrue(await head.connect(device, "luma-core-s3", "device", []))

        self.assertIs(head.websocket, device)
        self.assertEqual(head.role, "device")
        self.assertEqual(simulator.closed, [{"code": 1012, "reason": None}])

    async def test_send_json_defaults_set_emotion_to_asset_duration(self):
        head = HeadLink()
        device = FakeWebSocket()
        await head.connect(device, "luma-core-s3", "device", [])

        self.assertTrue(await head.send_json({"type": "set_emotion", "emotion": "happy"}))

        self.assertEqual(device.json_messages[0]["type"], "qgif_begin")
        self.assertEqual(device.json_messages[0]["duration_ms"], 1620)
        self.assertGreater(len(device.byte_messages), 0)
        self.assertEqual(device.json_messages[-1]["type"], "set_emotion")
        self.assertEqual(device.json_messages[-1]["duration_ms"], 1620)

    async def test_send_json_preserves_explicit_persistent_duration(self):
        head = HeadLink()
        device = FakeWebSocket()
        await head.connect(device, "luma-core-s3", "device", [])

        self.assertTrue(await head.send_json({"type": "set_emotion", "emotion": "happy", "duration_ms": 0}))

        self.assertEqual(device.json_messages[0]["duration_ms"], 0)
        self.assertEqual(device.json_messages[-1]["duration_ms"], 0)


class LumaRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_emotion_timeout_syncs_idle_to_head(self):
        runtime = LumaRuntime()
        fake_head = FakeHead()
        runtime.head = fake_head
        self.addCleanup(runtime.memory.close)

        runtime.state.apply_command(
            normalize_command({"type": "set_emotion", "emotion": "happy", "duration_ms": 1})
        )
        runtime.state.emotion_expires_at = time.time() - 1
        changed = runtime.state.tick()

        self.assertIn("emotion_timeout", changed)
        await runtime._sync_head_on_state_changes(changed)

        self.assertEqual(fake_head.sent_json, [{"type": "set_emotion", "emotion": "idle"}])


if __name__ == "__main__":
    unittest.main()
