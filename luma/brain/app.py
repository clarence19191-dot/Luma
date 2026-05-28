from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .commands import CommandValidationError, command_duration_ms, normalize_command, normalize_command_batch
from .config import settings
from .emotions import EMOTION_PRESETS, qgif_path_for_emotion
from .memory import MemoryStore
from .state import LumaState
from .vision import VisionProvider
from .voice import VoiceSessionRuntime


class ConsoleHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)


class HeadLink:
    def __init__(self) -> None:
        self.websocket: WebSocket | None = None
        self.device_id: str | None = None
        self.role: str | None = None
        self.capabilities: list[str] = []
        self.pending: dict[str, asyncio.Event] = {}
        self.pending_status: dict[str, dict[str, Any]] = {}

    @property
    def connected(self) -> bool:
        return self.websocket is not None

    async def connect(self, websocket: WebSocket, device_id: str, role: str, capabilities: list[str]) -> bool:
        if self.websocket is not None and self.role == "device" and role == "simulator":
            await websocket.close(code=1008, reason="physical device already connected")
            return False
        if self.websocket is not None:
            try:
                await self.websocket.close(code=1012)
            except RuntimeError:
                pass
        await websocket.accept()
        self.websocket = websocket
        self.device_id = device_id
        self.role = role
        self.capabilities = capabilities
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket is self.websocket:
            self.websocket = None
            self.device_id = None
            self.role = None
            self.capabilities = []

    async def send_command(self, command: dict[str, Any]) -> bool:
        return await self.send_json({"type": "command", "command": command})

    async def send_json(self, message: dict[str, Any]) -> bool:
        if self.websocket is None:
            return False
        outgoing = dict(message)
        if message.get("type") == "set_emotion" and isinstance(message.get("emotion"), str):
            path = qgif_path_for_emotion(message["emotion"])
            if path is not None:
                await self.send_qgif_for_emotion(
                    message["emotion"],
                    duration_ms=int(message.get("duration_ms") or 0),
                )
                outgoing.setdefault("asset", path.name)
        await self.websocket.send_json(outgoing)
        return True

    async def send_bytes(self, payload: bytes) -> bool:
        if self.websocket is None:
            return False
        await self.websocket.send_bytes(payload)
        return True

    def mark_pending(self, command_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self.pending[command_id] = event
        return event

    def resolve_pending(self, command_id: str, status: dict[str, Any]) -> None:
        self.pending_status[command_id] = status
        event = self.pending.get(command_id)
        if event:
            event.set()

    def clear_pending(self, command_id: str) -> dict[str, Any] | None:
        self.pending.pop(command_id, None)
        return self.pending_status.pop(command_id, None)

    async def send_qgif_for_emotion(self, emotion: str, *, duration_ms: int = 0) -> bool:
        if self.websocket is None:
            return False
        path = qgif_path_for_emotion(emotion)
        if path is None:
            return False
        data = path.read_bytes()
        await self.websocket.send_json(
            {
                "type": "qgif_begin",
                "emotion": emotion,
                "asset": path.name,
                "bytes": len(data),
                "duration_ms": duration_ms,
            }
        )
        chunk_size = max(512, settings.qgif_stream_chunk_bytes)
        for offset in range(0, len(data), chunk_size):
            await self.websocket.send_bytes(data[offset : offset + chunk_size])
            await asyncio.sleep(0)
        await self.websocket.send_json({"type": "qgif_end", "emotion": emotion, "asset": path.name, "bytes": len(data)})
        return True


class LumaRuntime:
    def __init__(self) -> None:
        self.state = LumaState()
        self.memory = MemoryStore(settings.database_path, settings.log_jsonl_path)
        self.vision = VisionProvider()
        self.console = ConsoleHub()
        self.head = HeadLink()
        self.voice = VoiceSessionRuntime(
            self.state,
            self.memory,
            self.head.send_json,
            self.head.send_bytes,
            self.broadcast_state,
        )
        self.conversation = self.voice.conversation
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self._idle_emotions = [
            "idle",
            "smile",
            "relaxed",
            "wink",
            "peek",
            "squint",
            "look_left",
            "look_right",
            "sleepy",
            "uwu",
        ]
        self._next_idle_expression_at = time.time() + random.uniform(
            settings.idle_expression_min_seconds,
            settings.idle_expression_max_seconds,
        )
        self._last_idle_emotion = "idle"
        self._ignored_voice_sessions: set[str] = set()
        self._last_touch_wake_at = 0.0

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._command_worker(), name="luma-command-worker"),
            asyncio.create_task(self._tick_worker(), name="luma-tick-worker"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.memory.close()

    async def enqueue(self, commands: list[dict[str, Any]]) -> list[str]:
        command_ids = []
        for command in commands:
            await self.queue.put(command)
            command_ids.append(command["command_id"])
            self.memory.log("command_queued", {"command": command})
        self.state.device.queue_length = self.queue.qsize()
        await self.broadcast_state("command_queued")
        return command_ids

    async def estop(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        command = normalize_command({"type": "estop"})
        self.state.mark_estop()
        self.memory.log("estop", {"command": command})
        await self.voice.cancel(reason="estop")
        await self.head.send_command(command)
        await self.broadcast_state("estop")

    async def broadcast_state(self, reason: str) -> None:
        await self.console.broadcast({"type": "state", "reason": reason, "state": self.state.snapshot()})

    def conversation_device_id(self) -> str:
        return self.state.device.device_id or "local"

    def should_accept_wake(self, message: dict[str, Any]) -> tuple[bool, str]:
        source = str(message.get("source", "wake_word"))
        if source in {"touch", "wake_word"} and self.state.voice.phase != "idle":
            return False, "voice_busy"
        if source == "touch":
            now = time.time()
            if now - self._last_touch_wake_at < settings.touch_wake_cooldown_seconds:
                return False, "touch_cooldown"
            self._last_touch_wake_at = now
        return True, ""

    def ignore_voice_session(self, session_id: Any) -> None:
        if isinstance(session_id, str) and session_id:
            self._ignored_voice_sessions.add(session_id)

    def voice_session_is_ignored(self, session_id: Any) -> bool:
        return isinstance(session_id, str) and session_id in self._ignored_voice_sessions

    def clear_ignored_voice_session(self, session_id: Any) -> None:
        if isinstance(session_id, str):
            self._ignored_voice_sessions.discard(session_id)

    async def _command_worker(self) -> None:
        while True:
            command = await self.queue.get()
            self.state.device.queue_length = self.queue.qsize()
            try:
                await self._execute_command(command)
            finally:
                self.queue.task_done()
                self.state.device.queue_length = self.queue.qsize()
                await self.broadcast_state("queue_update")

    async def _execute_command(self, command: dict[str, Any]) -> None:
        if self.state.device.estopped and command["type"] != "estop":
            payload = {
                "command_id": command["command_id"],
                "error": {"code": "estopped", "message": "Device is estopped.", "retryable": False},
            }
            self.memory.log("command_error", payload)
            await self.console.broadcast({"type": "error", **payload})
            return

        if command["type"] == "sequence":
            for index, step in enumerate(command["steps"]):
                step = dict(step)
                step["command_id"] = f"{command['command_id']}_{index}"
                await self._execute_command(step)
            return

        if command["type"] == "move_head":
            status = {
                "type": "error",
                "command_id": command["command_id"],
                "error": {
                    "code": "unsupported_capability",
                    "message": "Pan/tilt servos are excluded from this V0 build.",
                    "retryable": False,
                },
            }
            self.memory.log("command_error", status)
            await self.console.broadcast(status)
            return

        self.state.apply_command(command)
        self.memory.log("command_started", {"command": command})
        await self.broadcast_state("command_started")

        event = self.head.mark_pending(command["command_id"])
        outgoing_command = command
        try:
            if command["type"] == "set_emotion":
                path = qgif_path_for_emotion(command["emotion"])
                if path is not None:
                    await self.head.send_qgif_for_emotion(
                        command["emotion"],
                        duration_ms=int(command.get("duration_ms") or 0),
                    )
                    outgoing_command = dict(command)
                    outgoing_command["asset"] = path.name
            sent = await self.head.send_command(outgoing_command)
        except Exception as exc:
            status = {
                "command_id": command["command_id"],
                "error": {"code": "head_send_failed", "message": str(exc), "retryable": True},
            }
            self.head.clear_pending(command["command_id"])
            self.state.mark_disconnected()
            self.memory.log("command_error", status)
            await self.console.broadcast({"type": "error", **status})
            await self.broadcast_state("head_send_failed")
            return
        if not sent:
            status = {
                "command_id": command["command_id"],
                "error": {"code": "head_offline", "message": "No CoreS3 device is connected.", "retryable": True},
            }
            self.head.resolve_pending(command["command_id"], status)
            self.head.clear_pending(command["command_id"])
            self.memory.log("command_error", status)
            await self.console.broadcast({"type": "error", **status})
            return

        try:
            await asyncio.wait_for(event.wait(), timeout=max(settings.command_timeout_seconds, command_duration_ms(command) / 1000))
        except asyncio.TimeoutError:
            status = {
                "command_id": command["command_id"],
                "error": {"code": "command_timeout", "message": "Head did not return done in time.", "retryable": True},
            }
            self.head.clear_pending(command["command_id"])
            self.memory.log("command_error", status)
            await self.console.broadcast({"type": "error", **status})
        else:
            status = self.head.clear_pending(command["command_id"]) or {"status": "done"}
            kind = "command_error" if status.get("type") == "error" else "command_done"
            self.memory.log(kind, status)
            await self.console.broadcast(status)

    async def _tick_worker(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            changed = self.state.tick()
            if self.state.device.connected and self.state.device.last_seen:
                if time.time() - self.state.device.last_seen > settings.head_timeout_seconds:
                    self.state.mark_disconnected()
                    self.memory.log("head_timeout", {"timeout_seconds": settings.head_timeout_seconds})
                    changed.append("head_timeout")
            if changed:
                await self.broadcast_state(",".join(changed))
            await self._maybe_send_idle_expression()

    async def _maybe_send_idle_expression(self) -> None:
        if not settings.idle_expression_enabled:
            return
        now = time.time()
        if now < self._next_idle_expression_at:
            return
        self._next_idle_expression_at = now + random.uniform(
            settings.idle_expression_min_seconds,
            settings.idle_expression_max_seconds,
        )
        if (
            not self.state.device.connected
            or self.state.device.estopped
            or self.state.emotion != "idle"
            or self.state.emotion_expires_at is not None
            or self.state.voice.phase != "idle"
            or self.state.speech.active
            or self.queue.qsize() > 0
        ):
            return

        choices = [emotion for emotion in self._idle_emotions if emotion != self._last_idle_emotion]
        emotion = random.choice(choices or self._idle_emotions)
        self._last_idle_emotion = emotion
        command = normalize_command(
            {
                "type": "set_emotion",
                "emotion": emotion,
                "duration_ms": settings.idle_expression_duration_ms,
            }
        )
        self.state.apply_command(command)
        try:
            await self.head.send_json(
                {
                    "type": "set_emotion",
                    "emotion": emotion,
                    "duration_ms": settings.idle_expression_duration_ms,
                }
            )
        except Exception as exc:
            self.memory.log("idle_expression_error", {"emotion": emotion, "error": str(exc)})
            self.state.mark_disconnected()
            await self.broadcast_state("idle_expression_error")
            return
        self.memory.log("idle_expression", {"emotion": emotion, "duration_ms": settings.idle_expression_duration_ms})
        await self.broadcast_state("idle_expression")


runtime = LumaRuntime()


def create_app() -> FastAPI:
    app = FastAPI(title="Project Luma Brain", version="0.1.0")
    static_dir = Path(__file__).parent / "static"
    gif_dir = Path(__file__).parents[2] / "gif"

    @app.on_event("startup")
    async def _startup() -> None:
        await runtime.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await runtime.stop()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (static_dir / "index.html").read_text(encoding="utf-8")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    if gif_dir.exists():
        app.mount("/gif", StaticFiles(directory=gif_dir), name="gif")

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return runtime.state.snapshot()

    @app.get("/api/emotions")
    async def get_emotions() -> dict[str, Any]:
        return {"emotions": EMOTION_PRESETS, "asset_base": "/gif"}

    @app.get("/api/events")
    async def get_events(limit: int = 100) -> dict[str, Any]:
        return {
            "events": runtime.memory.recent(
                limit=min(max(limit, 1), settings.max_memory_events),
                since_seconds=settings.memory_window_seconds,
            )
        }

    @app.post("/api/command")
    async def post_command(payload: Any = Body(...)) -> dict[str, Any]:
        try:
            commands = normalize_command_batch(payload)
        except CommandValidationError as exc:
            runtime.memory.log("command_rejected", {"error": exc.to_error(), "payload": payload})
            raise HTTPException(status_code=422, detail=exc.to_error()) from exc
        if any(_contains_command_type(command, "move_head") for command in commands):
            error = {
                "code": "unsupported_capability",
                "message": "Pan/tilt servos are excluded from this V0 build.",
                "retryable": False,
            }
            runtime.memory.log("command_rejected", {"error": error, "payload": payload})
            raise HTTPException(status_code=422, detail=error)
        command_ids = await runtime.enqueue(commands)
        return {"status": "queued", "command_ids": command_ids}

    @app.post("/api/estop")
    async def post_estop() -> dict[str, str]:
        await runtime.estop()
        return {"status": "estopped"}

    @app.post("/api/reset_estop")
    async def post_reset_estop() -> dict[str, str]:
        command = normalize_command({"type": "reset_estop"})
        runtime.state.apply_command(command)
        runtime.memory.log("reset_estop", {"command": command})
        await runtime.broadcast_state("reset_estop")
        return {"status": "ready"}

    @app.post("/api/voice/wake")
    async def post_voice_wake(payload: dict[str, Any] | None = Body(None)) -> dict[str, str]:
        payload = payload or {}
        session_id = await runtime.voice.start(
            source=str(payload.get("source", "console")),
            wake_phrase=str(payload.get("wake_phrase", "你好 Luma")),
            session_id=payload.get("session_id") if isinstance(payload.get("session_id"), str) else None,
        )
        return {"status": "listening", "session_id": session_id}

    @app.post("/api/voice/text")
    async def post_voice_text(payload: dict[str, Any] = Body(...)) -> dict[str, str]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail={"code": "invalid_text", "message": "text is required."})
        session_id = await runtime.voice.process_text(text.strip(), source="console")
        return {"status": "queued", "session_id": session_id}

    @app.post("/api/voice/cancel")
    async def post_voice_cancel() -> dict[str, str]:
        await runtime.voice.cancel(reason="console_cancel")
        return {"status": "cancelled"}

    @app.get("/api/conversation")
    async def get_conversation() -> dict[str, Any]:
        return runtime.conversation.snapshot(device_id=runtime.conversation_device_id())

    @app.post("/api/conversation/reset")
    async def post_conversation_reset() -> dict[str, Any]:
        conversation = runtime.conversation.reset(device_id=runtime.conversation_device_id())
        await runtime.broadcast_state("conversation_reset")
        return {"status": "reset", "conversation": conversation}

    @app.get("/api/memories")
    async def get_memories(limit: int = 100) -> dict[str, Any]:
        return {"memories": runtime.memory.list_memories(active_only=True, limit=min(max(limit, 1), 200))}

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(memory_id: int) -> dict[str, Any]:
        deleted = runtime.memory.soft_delete_memory(memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail={"code": "memory_not_found", "message": "Memory not found."})
        runtime.memory.log("memory_deleted", {"memory_id": memory_id})
        await runtime.broadcast_state("memory_deleted")
        return {"status": "deleted", "memory_id": memory_id}

    @app.get("/api/debug/prompt")
    async def get_debug_prompt() -> dict[str, Any]:
        return {
            "messages": runtime.conversation.last_prompt_messages,
            "boundary": runtime.conversation.last_boundary.to_dict() if runtime.conversation.last_boundary else None,
        }

    @app.websocket("/ws/console")
    async def ws_console(websocket: WebSocket) -> None:
        await runtime.console.connect(websocket)
        await websocket.send_json({"type": "state", "reason": "connected", "state": runtime.state.snapshot()})
        try:
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            runtime.console.disconnect(websocket)

    @app.websocket("/ws/head")
    async def ws_head(
        websocket: WebSocket,
        device_id: str = Query("luma-core-s3"),
        role: str = Query("device"),
    ) -> None:
        default_capabilities = [
            "display.lvgl_face",
            "display.qgif_stream",
            "audio.wake_word",
            "audio.capture_pcm",
            "audio.playback_pcm",
            "input.touch_wake",
            "safety.estop",
        ]
        accepted = await runtime.head.connect(websocket, device_id, role, default_capabilities)
        if not accepted:
            runtime.memory.log("head_rejected", {"device_id": device_id, "role": role, "reason": "physical_device_connected"})
            return
        runtime.state.mark_connected(device_id, role, default_capabilities)
        runtime.memory.log("head_connected", {"device_id": device_id, "role": role, "capabilities": default_capabilities})
        await runtime.broadcast_state("head_connected")
        await websocket.send_json({"type": "hello", "server": "luma-brain", "capabilities": default_capabilities})
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    await _handle_head_message(message["text"])
                elif message.get("bytes") is not None:
                    runtime.state.mark_seen()
                    await runtime.voice.accept_audio_chunk(message["bytes"])
        except WebSocketDisconnect:
            pass
        finally:
            was_current = websocket is runtime.head.websocket
            runtime.head.disconnect(websocket)
            if was_current:
                runtime.state.mark_disconnected()
                runtime.memory.log("head_disconnected", {"device_id": device_id, "role": role})
                await runtime.broadcast_state("head_disconnected")

    return app


async def _handle_head_message(raw: str) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        runtime.memory.log("head_bad_message", {"raw": raw[:500]})
        return

    runtime.state.mark_seen()
    message_type = message.get("type")
    if message_type == "hello":
        capabilities = message.get("capabilities") or runtime.head.capabilities
        runtime.head.capabilities = list(capabilities)
        runtime.state.mark_connected(
            runtime.head.device_id or message.get("device_id", "luma-core-s3"),
            runtime.head.role or message.get("role", "device"),
            runtime.head.capabilities,
        )
        runtime.memory.log("head_hello", message)
    elif message_type == "ack":
        runtime.memory.log("head_ack", message)
        await runtime.console.broadcast(message)
    elif message_type in {"done", "error"}:
        command_id = message.get("command_id")
        if isinstance(command_id, str):
            runtime.head.resolve_pending(command_id, message)
        runtime.memory.log(f"head_{message_type}", message)
    elif message_type == "telemetry":
        runtime.memory.log("head_telemetry", message)
    elif message_type == "wake_detected":
        accepted, reason = runtime.should_accept_wake(message)
        if not accepted:
            session_id = message.get("session_id")
            runtime.ignore_voice_session(session_id)
            runtime.memory.log("voice_wake_ignored", {"reason": reason, "message": message})
            if isinstance(session_id, str):
                await runtime.head.send_json({"type": "cancel_session", "session_id": session_id, "reason": reason})
            await runtime.broadcast_state("voice_wake_ignored")
            return
        await runtime.voice.start(
            source=str(message.get("source", "wake_word")),
            wake_phrase=str(message.get("wake_phrase", "你好 Luma")),
            session_id=message.get("session_id") if isinstance(message.get("session_id"), str) else None,
        )
    elif message_type == "audio_begin":
        if runtime.voice_session_is_ignored(message.get("session_id")):
            runtime.memory.log("voice_audio_ignored", {"reason": "ignored_session", "message": message})
            return
        await runtime.voice.begin_audio(message)
    elif message_type == "audio_end":
        if runtime.voice_session_is_ignored(message.get("session_id")):
            runtime.clear_ignored_voice_session(message.get("session_id"))
            runtime.memory.log("voice_audio_ignored", {"reason": "ignored_session", "message": message})
            return
        await runtime.voice.end_audio(message)
    elif message_type == "playback_done":
        await runtime.voice.playback_done(message)
    elif message_type == "vision_snapshot":
        payload = message.get("image_base64")
        if isinstance(payload, str):
            result = runtime.vision.analyze_snapshot(payload, message.get("mime", "image/jpeg"))
            runtime.state.update_vision(result, payload)
            runtime.memory.log("vision_snapshot", result)
            await runtime.broadcast_state("vision_snapshot")
    else:
        runtime.memory.log("head_message", message)


def _contains_command_type(command: dict[str, Any], command_type: str) -> bool:
    if command.get("type") == command_type:
        return True
    if command.get("type") == "sequence":
        return any(_contains_command_type(step, command_type) for step in command.get("steps", []))
    return False


app = create_app()
