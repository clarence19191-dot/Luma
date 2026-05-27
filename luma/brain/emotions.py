from __future__ import annotations

from pathlib import Path
from typing import Any


BASE_EMOTION_PRESETS: list[dict[str, Any]] = [
    {"emotion": "idle", "label": "Idle", "asset": "sys_idle.qgif", "group": "core"},
    {"emotion": "listening", "label": "Listen", "asset": "eye_peek.qgif", "group": "core"},
    {"emotion": "thinking", "label": "Think", "asset": "effect_rotate.qgif", "group": "core"},
    {"emotion": "speaking", "label": "Speak", "asset": "Hello.qgif", "group": "core"},
    {"emotion": "happy", "label": "Happy", "asset": "emotion_happy.qgif", "group": "mood"},
    {"emotion": "smile", "label": "Smile", "asset": "emotion_smile.qgif", "group": "mood"},
    {"emotion": "surprised", "label": "Wow", "asset": "emotion_surprised.qgif", "group": "mood"},
    {"emotion": "relaxed", "label": "Relax", "asset": "emotion_relaxed.qgif", "group": "mood"},
    {"emotion": "uwu", "label": "Uwu", "asset": "emotion_uwu.qgif", "group": "mood"},
    {"emotion": "love", "label": "Love", "asset": "emotion_love_01.qgif", "group": "mood"},
    {"emotion": "smirk", "label": "Smirk", "asset": "emotion_smirk.qgif", "group": "mood"},
    {"emotion": "angry", "label": "Angry", "asset": "emotion_angry_04.qgif", "group": "strong"},
    {"emotion": "angry_fire", "label": "Fire", "asset": "emotion_angry_fire.qgif", "group": "strong"},
    {"emotion": "scared", "label": "Scared", "asset": "emotion_scared.qgif", "group": "strong"},
    {"emotion": "frustrated", "label": "Frustrated", "asset": "emotion_frustrated.qgif", "group": "strong"},
    {"emotion": "distracted", "label": "Distract", "asset": "emotion_distracted.qgif", "group": "strong"},
    {"emotion": "dizzy", "label": "Dizzy", "asset": "emotion_dizzy.qgif", "group": "strong"},
    {"emotion": "cry", "label": "Cry", "asset": "cry.qgif", "group": "strong"},
    {"emotion": "devil", "label": "Devil", "asset": "devil_eyes.qgif", "group": "strong"},
    {"emotion": "sleepy", "label": "Sleepy", "asset": "action_sleepy.qgif", "group": "action"},
    {"emotion": "yawn", "label": "Yawn", "asset": "action_yawn.qgif", "group": "action"},
    {"emotion": "wink", "label": "Wink", "asset": "eye_wink.qgif", "group": "eye"},
    {"emotion": "peek", "label": "Peek", "asset": "eye_peek.qgif", "group": "eye"},
    {"emotion": "squint", "label": "Squint", "asset": "eye_squint.qgif", "group": "eye"},
    {"emotion": "look_left", "label": "Left", "asset": "eye_look_left.qgif", "group": "eye"},
    {"emotion": "look_right", "label": "Right", "asset": "eye_look_right.qgif", "group": "eye"},
]

GIF_DIR = Path(__file__).parents[2] / "gif"


def _label_from_stem(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").title()


def _group_from_stem(stem: str) -> str:
    if stem.startswith("emotion_") or stem in {"cry", "devil_eyes"}:
        return "mood"
    if stem.startswith("action_"):
        return "action"
    if stem.startswith("eye_"):
        return "eye"
    if stem.startswith("theme_"):
        return "theme"
    if stem.startswith("effect_"):
        return "effect"
    return "extra"


def emotion_catalog() -> list[dict[str, Any]]:
    presets = [dict(item) for item in BASE_EMOTION_PRESETS]
    known_assets = {item["asset"] for item in presets}
    if GIF_DIR.exists():
        for path in sorted(GIF_DIR.glob("*.qgif")):
            if path.name in known_assets:
                continue
            emotion = path.stem.replace("-", "_").lower()
            presets.append(
                {
                    "emotion": emotion,
                    "label": _label_from_stem(path.stem),
                    "asset": path.name,
                    "group": _group_from_stem(path.stem),
                }
            )
    return presets


EMOTION_PRESETS = emotion_catalog()
ALLOWED_EMOTIONS = {item["emotion"] for item in EMOTION_PRESETS}


def emotion_asset(emotion: str) -> str | None:
    for item in EMOTION_PRESETS:
        if item["emotion"] == emotion:
            return str(item["asset"])
    return None


def qgif_path_for_emotion(emotion: str) -> Path | None:
    asset = emotion_asset(emotion)
    if not asset:
        return None
    path = GIF_DIR / asset
    if path.exists() and path.suffix == ".qgif":
        return path
    return None
