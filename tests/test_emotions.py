from pathlib import Path
import unittest

from luma.brain.emotions import EMOTION_PRESETS, GIF_DIR, qgif_path_for_emotion


class EmotionCatalogTests(unittest.TestCase):
    def test_exposes_all_qgif_assets(self):
        qgif_assets = {path.name for path in Path(GIF_DIR).glob("*.qgif")}
        exposed_assets = {item["asset"] for item in EMOTION_PRESETS}

        self.assertTrue(qgif_assets)
        self.assertTrue(qgif_assets.issubset(exposed_assets))

    def test_dynamic_emotion_ids_are_lowercase_and_streamable(self):
        discord = next(item for item in EMOTION_PRESETS if item["asset"] == "Discord.qgif")
        action_eat = next(item for item in EMOTION_PRESETS if item["asset"] == "action_eat.qgif")

        self.assertEqual(discord["emotion"], "discord")
        self.assertEqual(qgif_path_for_emotion("discord").name, "Discord.qgif")
        self.assertEqual(action_eat["emotion"], "action_eat")
        self.assertEqual(qgif_path_for_emotion("action_eat").name, "action_eat.qgif")


if __name__ == "__main__":
    unittest.main()
