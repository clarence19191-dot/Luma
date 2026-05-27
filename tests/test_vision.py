import base64
import unittest

from luma.brain.vision import VisionProvider


class VisionTests(unittest.TestCase):
    def test_accepts_snapshot_without_opencv(self):
        provider = VisionProvider()
        payload = base64.b64encode(b"not really a jpeg").decode("ascii")
        result = provider.analyze_snapshot(payload)
        self.assertIn("person_detected", result)
        self.assertGreater(result["bytes"], 0)


if __name__ == "__main__":
    unittest.main()

