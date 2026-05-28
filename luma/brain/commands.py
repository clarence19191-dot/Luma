from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from .emotions import ALLOWED_EMOTIONS as CATALOG_EMOTIONS
from .emotions import emotion_duration_ms

ALLOWED_EMOTIONS = set(CATALOG_EMOTIONS) | {"curious", "error"}

DEFAULT_LIMITS = {
    "pan_min": -60,
    "pan_max": 60,
    "tilt_min": -35,
    "tilt_max": 35,
    "speed_min": 1,
    "speed_max": 90,
}


class CommandValidationError(ValueError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


def make_command_id() -> str:
    return f"cmd_{uuid4().hex[:12]}"


def normalize_command(raw: dict[str, Any], *, command_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CommandValidationError("invalid_command", "Command must be a JSON object.")

    command = deepcopy(raw)
    command_type = command.get("type")
    if not isinstance(command_type, str):
        raise CommandValidationError("missing_type", "Command field 'type' is required.")

    if command_type == "set_emotion":
        emotion = command.get("emotion")
        if emotion not in ALLOWED_EMOTIONS:
            raise CommandValidationError("invalid_emotion", f"Unsupported emotion: {emotion!r}.")
        duration_ms = command.get("duration_ms")
        command["duration_ms"] = (
            emotion_duration_ms(emotion)
            if duration_ms is None
            else _int_in_range(duration_ms, 0, 60_000, "duration_ms")
        )

    elif command_type == "move_head":
        mode = command.get("mode", "absolute")
        if mode not in {"absolute", "relative"}:
            raise CommandValidationError("invalid_mode", "move_head mode must be absolute or relative.")
        command["mode"] = mode
        if "pan" not in command and "tilt" not in command:
            raise CommandValidationError("missing_angles", "move_head requires pan or tilt.")
        if "pan" in command:
            command["pan"] = _int_in_range(command["pan"], DEFAULT_LIMITS["pan_min"], DEFAULT_LIMITS["pan_max"], "pan")
        if "tilt" in command:
            command["tilt"] = _int_in_range(command["tilt"], DEFAULT_LIMITS["tilt_min"], DEFAULT_LIMITS["tilt_max"], "tilt")
        command["speed_dps"] = _int_in_range(
            command.get("speed_dps", 60),
            DEFAULT_LIMITS["speed_min"],
            DEFAULT_LIMITS["speed_max"],
            "speed_dps",
        )

    elif command_type == "speak":
        text = command.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CommandValidationError("invalid_text", "speak requires non-empty text.")
        command["text"] = text.strip()
        command["voice"] = str(command.get("voice", "local_zh"))
        if "emotion" in command and command["emotion"] not in ALLOWED_EMOTIONS:
            raise CommandValidationError("invalid_emotion", f"Unsupported emotion: {command['emotion']!r}.")

    elif command_type == "sequence":
        steps = command.get("steps")
        if not isinstance(steps, list) or not steps:
            raise CommandValidationError("invalid_sequence", "sequence requires a non-empty steps list.")
        if len(steps) > 32:
            raise CommandValidationError("sequence_too_long", "sequence can contain at most 32 steps.")
        command["steps"] = [normalize_command(step) for step in steps]

    elif command_type in {"stop", "estop", "reset_estop"}:
        pass

    else:
        raise CommandValidationError("unknown_command", f"Unsupported command type: {command_type}.")

    command["command_id"] = command.get("command_id") or command_id or make_command_id()
    return command


def normalize_command_batch(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [normalize_command(item) for item in payload]
    return [normalize_command(payload)]


def command_duration_ms(command: dict[str, Any]) -> int:
    command_type = command["type"]
    if command_type == "set_emotion":
        return int(command.get("duration_ms") or 300)
    if command_type == "move_head":
        return 500
    if command_type == "speak":
        # Rough local TTS estimate: enough for queue pacing without blocking long phrases.
        return min(max(len(command.get("text", "")) * 120, 600), 6000)
    if command_type == "sequence":
        return sum(command_duration_ms(step) for step in command["steps"])
    return 100


def _int_in_range(value: Any, lower: int, upper: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandValidationError("invalid_number", f"{field} must be a number.") from exc
    if parsed < lower or parsed > upper:
        raise CommandValidationError("out_of_range", f"{field} must be in [{lower}, {upper}].")
    return parsed
