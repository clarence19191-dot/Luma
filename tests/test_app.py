import unittest

from luma.brain.app import HeadLink


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=None):
        self.closed.append({"code": code, "reason": reason})


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


if __name__ == "__main__":
    unittest.main()
