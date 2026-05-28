from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class HeadPose:
    pan: int = 0
    tilt: int = 0
    speed_dps: int = 60


@dataclass
class SpeechState:
    active: bool = False
    text: str = ""
    voice: str = "local_zh"
    started_at: float | None = None
    until: float | None = None


@dataclass
class VoiceState:
    phase: str = "idle"
    session_id: str | None = None
    conversation_id: str | None = None
    wake_phrase: str = "你好 Luma"
    transcript: str = ""
    reply: str = ""
    tone: str = ""
    pet_behavior: str = ""
    boundary: dict[str, Any] | None = None
    memory_count: int = 0
    audio_bytes: int = 0
    error: dict[str, Any] | None = None
    started_at: float | None = None
    updated_at: float | None = None


@dataclass
class VisionState:
    last_snapshot_at: float | None = None
    last_snapshot_mime: str | None = None
    last_snapshot_base64: str | None = None
    person_detected: bool = False
    target: dict[str, float] | None = None
    description: str = "No frame received yet."


@dataclass
class DeviceState:
    connected: bool = False
    device_id: str | None = None
    role: str | None = None
    capabilities: list[str] = field(default_factory=list)
    last_seen: float | None = None
    telemetry: dict[str, Any] = field(default_factory=dict)
    telemetry_updated_at: float | None = None
    queue_length: int = 0
    estopped: bool = False


class LumaState:
    def __init__(self) -> None:
        self.emotion = "idle"
        self.emotion_expires_at: float | None = None
        self.head = HeadPose()
        self.speech = SpeechState()
        self.voice = VoiceState()
        self.vision = VisionState()
        self.device = DeviceState()

    def apply_command(self, command: dict[str, Any]) -> None:
        command_type = command["type"]
        now = time.time()
        if command_type == "set_emotion":
            self.emotion = command["emotion"]
            duration_ms = command.get("duration_ms")
            self.emotion_expires_at = now + duration_ms / 1000 if duration_ms else None
        elif command_type == "move_head":
            if command["mode"] == "relative":
                self.head.pan += int(command.get("pan", 0))
                self.head.tilt += int(command.get("tilt", 0))
            else:
                self.head.pan = int(command.get("pan", self.head.pan))
                self.head.tilt = int(command.get("tilt", self.head.tilt))
            self.head.pan = max(-60, min(60, self.head.pan))
            self.head.tilt = max(-35, min(35, self.head.tilt))
            self.head.speed_dps = int(command.get("speed_dps", self.head.speed_dps))
        elif command_type == "speak":
            self.speech = SpeechState(
                active=True,
                text=command["text"],
                voice=command.get("voice", "local_zh"),
                started_at=now,
                until=now + min(max(len(command["text"]) * 0.12, 0.6), 6.0),
            )
            self.emotion = command.get("emotion", "speaking")
            self.emotion_expires_at = self.speech.until
        elif command_type == "estop":
            self.mark_estop()
        elif command_type == "reset_estop":
            self.device.estopped = False
        elif command_type == "stop":
            self.device.queue_length = 0
            self.speech.active = False

    def tick(self) -> list[str]:
        now = time.time()
        changed: list[str] = []
        if self.emotion_expires_at and now >= self.emotion_expires_at:
            self.emotion = "idle"
            self.emotion_expires_at = None
            changed.append("emotion_timeout")
        if self.speech.active and self.speech.until and now >= self.speech.until:
            self.speech.active = False
            changed.append("speech_timeout")
        return changed

    def mark_connected(self, device_id: str, role: str, capabilities: list[str]) -> None:
        self.device.connected = True
        self.device.device_id = device_id
        self.device.role = role
        self.device.capabilities = capabilities
        self.device.last_seen = time.time()
        self.device.telemetry = {}
        self.device.telemetry_updated_at = None
        self.device.estopped = False

    def mark_seen(self) -> None:
        self.device.last_seen = time.time()

    def update_telemetry(self, telemetry: dict[str, Any]) -> None:
        now = time.time()
        self.device.last_seen = now
        self.device.telemetry = telemetry
        self.device.telemetry_updated_at = now

    def mark_disconnected(self) -> None:
        self.device.connected = False
        self.device.role = None
        self.device.capabilities = []

    def mark_estop(self) -> None:
        self.device.estopped = True
        self.device.queue_length = 0
        self.speech.active = False
        self.emotion = "idle"
        self.emotion_expires_at = None
        self.head = HeadPose()

    def update_voice(
        self,
        phase: str,
        *,
        session_id: str | None = None,
        transcript: str | None = None,
        reply: str | None = None,
        audio_bytes: int | None = None,
        error: dict[str, Any] | None = None,
        wake_phrase: str | None = None,
        conversation_id: str | None = None,
        tone: str | None = None,
        pet_behavior: str | None = None,
        boundary: dict[str, Any] | None = None,
        memory_count: int | None = None,
    ) -> None:
        now = time.time()
        if phase == "idle":
            self.voice = VoiceState(wake_phrase=wake_phrase or self.voice.wake_phrase, updated_at=now)
            self.speech.active = False
            self.emotion = "idle"
            self.emotion_expires_at = None
            return

        if self.voice.session_id != session_id and session_id is not None:
            self.voice = VoiceState(session_id=session_id, wake_phrase=wake_phrase or self.voice.wake_phrase, started_at=now)

        self.voice.phase = phase
        self.voice.updated_at = now
        if session_id is not None:
            self.voice.session_id = session_id
        if wake_phrase is not None:
            self.voice.wake_phrase = wake_phrase
        if transcript is not None:
            self.voice.transcript = transcript
        if reply is not None:
            self.voice.reply = reply
        if conversation_id is not None:
            self.voice.conversation_id = conversation_id
        if tone is not None:
            self.voice.tone = tone
        if pet_behavior is not None:
            self.voice.pet_behavior = pet_behavior
        if boundary is not None:
            self.voice.boundary = boundary
        if memory_count is not None:
            self.voice.memory_count = memory_count
        if audio_bytes is not None:
            self.voice.audio_bytes = audio_bytes
        self.voice.error = error

        if phase in {"listening", "transcribing", "thinking"}:
            self.speech.active = False
            self.emotion = "listening" if phase == "listening" else "thinking"
            self.emotion_expires_at = None
        elif phase == "speaking":
            self.speech = SpeechState(active=True, text=self.voice.reply, voice="brain_tts", started_at=now, until=None)
            self.emotion = "speaking"
            self.emotion_expires_at = None
        elif phase == "error":
            self.speech.active = False
            self.emotion = "scared"
            self.emotion_expires_at = now + 3

    def update_vision(self, result: dict[str, Any], snapshot_base64: str | None = None) -> None:
        self.vision.last_snapshot_at = time.time()
        self.vision.last_snapshot_mime = result.get("mime", "image/jpeg")
        self.vision.last_snapshot_base64 = snapshot_base64
        self.vision.person_detected = bool(result.get("person_detected", False))
        self.vision.target = result.get("target")
        self.vision.description = result.get("description", "Frame received.")
        if self.vision.person_detected and self.vision.target:
            x = float(self.vision.target.get("x", 0.5))
            y = float(self.vision.target.get("y", 0.5))
            self.emotion = "curious"
            self.emotion_expires_at = time.time() + 3
            self.head.pan = int(max(-60, min(60, (x - 0.5) * 80)))
            self.head.tilt = int(max(-35, min(35, (0.5 - y) * 50)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "emotion": self.emotion,
            "head": {
                "pan": self.head.pan,
                "tilt": self.head.tilt,
                "speed_dps": self.head.speed_dps,
            },
            "speech": {
                "active": self.speech.active,
                "text": self.speech.text,
                "voice": self.speech.voice,
                "started_at": self.speech.started_at,
            },
            "voice": {
                "phase": self.voice.phase,
                "session_id": self.voice.session_id,
                "conversation_id": self.voice.conversation_id,
                "wake_phrase": self.voice.wake_phrase,
                "transcript": self.voice.transcript,
                "reply": self.voice.reply,
                "tone": self.voice.tone,
                "pet_behavior": self.voice.pet_behavior,
                "boundary": self.voice.boundary,
                "memory_count": self.voice.memory_count,
                "audio_bytes": self.voice.audio_bytes,
                "error": self.voice.error,
                "started_at": self.voice.started_at,
                "updated_at": self.voice.updated_at,
            },
            "vision": {
                "last_snapshot_at": self.vision.last_snapshot_at,
                "last_snapshot_mime": self.vision.last_snapshot_mime,
                "last_snapshot_base64": self.vision.last_snapshot_base64,
                "person_detected": self.vision.person_detected,
                "target": self.vision.target,
                "description": self.vision.description,
            },
            "device": {
                "connected": self.device.connected,
                "device_id": self.device.device_id,
                "role": self.device.role,
                "capabilities": self.device.capabilities,
                "last_seen": self.device.last_seen,
                "telemetry": self.device.telemetry,
                "telemetry_updated_at": self.device.telemetry_updated_at,
                "queue_length": self.device.queue_length,
                "estopped": self.device.estopped,
            },
        }
