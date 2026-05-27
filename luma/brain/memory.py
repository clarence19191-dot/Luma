from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


ALLOWED_MEMORY_TYPES = {
    "user_profile",
    "preference",
    "dislike",
    "pet",
    "life_habit",
    "interaction",
    "emotional_care",
}

REJECTED_MEMORY_TYPES = {
    "one_off",
    "task",
    "work_detail",
    "knowledge",
    "credential",
    "sensitive",
    "secret",
}

SENSITIVE_MEMORY_PATTERNS = [
    "密码",
    "口令",
    "验证码",
    "身份证",
    "银行卡",
    "住址",
    "手机号",
    "电话号码",
    "api key",
    "apikey",
    "access token",
    "secret",
    "private key",
    "token",
]


class MemoryStore:
    def __init__(self, db_path: Path, jsonl_path: Path) -> None:
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    closed_at REAL,
                    summary TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    emotion_tags TEXT NOT NULL DEFAULT '[]',
                    pending_task TEXT
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_device ON conversations(device_id, status, updated_at)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    role TEXT NOT NULL DEFAULT 'exchange',
                    user_text TEXT NOT NULL,
                    luma_text TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    emotion TEXT NOT NULL DEFAULT '',
                    tone TEXT NOT NULL DEFAULT '',
                    pet_behavior TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_conversation ON conversation_turns(conversation_id, ts)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_conversation_id TEXT,
                    source_turn_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'active',
                    deleted_at REAL,
                    FOREIGN KEY(source_conversation_id) REFERENCES conversations(id),
                    FOREIGN KEY(source_turn_id) REFERENCES conversation_turns(id)
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status, updated_at)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_boundaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    device_id TEXT NOT NULL,
                    previous_conversation_id TEXT,
                    conversation_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    signals TEXT NOT NULL,
                    gap_seconds REAL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_boundaries_ts ON conversation_boundaries(ts)")
            self._conn.commit()

    def log(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"ts": time.time(), "kind": kind, "payload": payload}
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(ts, kind, payload) VALUES (?, ?, ?)",
                (event["ts"], kind, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
            with self.jsonl_path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        return event

    def recent(self, *, limit: int, since_seconds: int | None = None) -> list[dict[str, Any]]:
        lower = 0.0 if since_seconds is None else time.time() - since_seconds
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, kind, payload FROM events WHERE ts >= ? ORDER BY id DESC LIMIT ?",
                (lower, limit),
            ).fetchall()
        return [
            {
                "ts": row[0],
                "kind": row[1],
                "payload": json.loads(row[2]),
            }
            for row in rows
        ]

    def current_conversation(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, device_id, status, started_at, updated_at, closed_at, summary, topic, emotion_tags, pending_task
                FROM conversations
                WHERE device_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return self._conversation_from_row(row) if row else None

    def last_conversation(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, device_id, status, started_at, updated_at, closed_at, summary, topic, emotion_tags, pending_task
                FROM conversations
                WHERE device_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return self._conversation_from_row(row) if row else None

    def create_conversation(self, device_id: str, *, now: float | None = None, topic: str = "") -> dict[str, Any]:
        ts = now or time.time()
        conversation_id = f"conv_{uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversations(id, device_id, status, started_at, updated_at, summary, topic, emotion_tags)
                VALUES (?, ?, 'active', ?, ?, '', ?, '[]')
                """,
                (conversation_id, device_id, ts, ts, topic),
            )
            self._conn.commit()
        return self.get_conversation(conversation_id) or {
            "id": conversation_id,
            "device_id": device_id,
            "status": "active",
            "started_at": ts,
            "updated_at": ts,
            "closed_at": None,
            "summary": "",
            "topic": topic,
            "emotion_tags": [],
            "pending_task": None,
        }

    def close_current_conversations(self, device_id: str, *, now: float | None = None) -> None:
        ts = now or time.time()
        with self._lock:
            self._conn.execute(
                """
                UPDATE conversations
                SET status = 'closed', closed_at = ?, updated_at = ?
                WHERE device_id = ? AND status = 'active'
                """,
                (ts, ts, device_id),
            )
            self._conn.commit()

    def reopen_conversation(self, conversation_id: str, *, now: float | None = None) -> dict[str, Any] | None:
        ts = now or time.time()
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None
        with self._lock:
            self._conn.execute(
                """
                UPDATE conversations
                SET status = 'active', closed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (ts, conversation_id),
            )
            self._conn.commit()
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, device_id, status, started_at, updated_at, closed_at, summary, topic, emotion_tags, pending_task
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return self._conversation_from_row(row) if row else None

    def append_turn(
        self,
        conversation_id: str,
        *,
        user_text: str,
        luma_text: str,
        decision: dict[str, Any],
        emotion: str,
        tone: str,
        pet_behavior: str,
        now: float | None = None,
    ) -> int:
        ts = now or time.time()
        summary = self._make_summary(user_text, luma_text)
        topic = self._extract_topic(user_text)
        emotion_tags = self._extract_emotion_tags(user_text, tone, pet_behavior)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO conversation_turns(
                    conversation_id, ts, role, user_text, luma_text, decision_json, emotion, tone, pet_behavior
                )
                VALUES (?, ?, 'exchange', ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    ts,
                    user_text,
                    luma_text,
                    json.dumps(decision, ensure_ascii=False),
                    emotion,
                    tone,
                    pet_behavior,
                ),
            )
            self._conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?, summary = ?, topic = ?, emotion_tags = ?
                WHERE id = ?
                """,
                (ts, summary, topic, json.dumps(emotion_tags, ensure_ascii=False), conversation_id),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def recent_turns(self, conversation_id: str, *, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, conversation_id, ts, user_text, luma_text, decision_json, emotion, tone, pet_behavior
                FROM conversation_turns
                WHERE conversation_id = ?
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [self._turn_from_row(row) for row in reversed(rows)]

    def latest_turns(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, conversation_id, ts, user_text, luma_text, decision_json, emotion, tone, pet_behavior
                FROM conversation_turns
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._turn_from_row(row) for row in rows]

    def record_boundary(
        self,
        *,
        device_id: str,
        previous_conversation_id: str | None,
        conversation_id: str,
        decision: str,
        reason: str,
        signals: dict[str, Any],
        gap_seconds: float | None,
        now: float | None = None,
    ) -> None:
        ts = now or time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversation_boundaries(
                    ts, device_id, previous_conversation_id, conversation_id, decision, reason, signals, gap_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    device_id,
                    previous_conversation_id,
                    conversation_id,
                    decision,
                    reason,
                    json.dumps(signals, ensure_ascii=False),
                    gap_seconds,
                ),
            )
            self._conn.commit()

    def last_boundary(self, device_id: str | None = None) -> dict[str, Any] | None:
        query = """
            SELECT ts, device_id, previous_conversation_id, conversation_id, decision, reason, signals, gap_seconds
            FROM conversation_boundaries
        """
        params: tuple[Any, ...] = ()
        if device_id:
            query += " WHERE device_id = ?"
            params = (device_id,)
        query += " ORDER BY ts DESC, id DESC LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        if not row:
            return None
        return {
            "ts": row[0],
            "device_id": row[1],
            "previous_conversation_id": row[2],
            "conversation_id": row[3],
            "decision": row[4],
            "reason": row[5],
            "signals": json.loads(row[6]),
            "gap_seconds": row[7],
        }

    def save_memory_candidate(
        self,
        candidate: dict[str, Any] | Any,
        *,
        source_conversation_id: str | None,
        source_turn_id: int | None,
        min_confidence: float = 0.68,
    ) -> dict[str, Any] | None:
        memory_type = str(_field(candidate, "type", "")).strip()
        content = _normalize_content(str(_field(candidate, "content", "")).strip())
        try:
            confidence = float(_field(candidate, "confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        if not content or len(content) > 160:
            return None
        if memory_type in REJECTED_MEMORY_TYPES or memory_type not in ALLOWED_MEMORY_TYPES:
            return None
        if confidence < min_confidence:
            return None
        if _is_sensitive(content):
            return None

        now = time.time()
        normalized = _dedupe_key(content)
        with self._lock:
            existing = self._conn.execute(
                """
                SELECT id FROM memories
                WHERE status = 'active' AND lower(content) = lower(?)
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE memories SET updated_at = ?, confidence = max(confidence, ?) WHERE id = ?",
                    (now, confidence, existing[0]),
                )
                self._conn.commit()
                return self.get_memory(int(existing[0]))
            cursor = self._conn.execute(
                """
                INSERT INTO memories(
                    created_at, updated_at, type, content, confidence, source_conversation_id, source_turn_id, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (now, now, memory_type, content, confidence, source_conversation_id, source_turn_id),
            )
            self._conn.commit()
            memory_id = int(cursor.lastrowid)
        return self.get_memory(memory_id)

    def list_memories(self, *, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        where = "WHERE status = 'active'" if active_only else ""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, created_at, updated_at, type, content, confidence, source_conversation_id, source_turn_id, status, deleted_at
                FROM memories
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def relevant_memories(self, text: str, *, limit: int = 8) -> list[dict[str, Any]]:
        memories = self.list_memories(active_only=True, limit=100)
        if not text.strip():
            return memories[:limit]
        text_chars = _content_chars(text)
        scored: list[tuple[float, dict[str, Any]]] = []
        for memory in memories:
            content_chars = _content_chars(memory["content"])
            overlap = len(text_chars & content_chars)
            score = overlap + float(memory["confidence"]) + (0.5 if memory["type"] in {"preference", "dislike", "interaction"} else 0)
            scored.append((score, memory))
        scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        return [memory for score, memory in scored[:limit] if score > 0]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, created_at, updated_at, type, content, confidence, source_conversation_id, source_turn_id, status, deleted_at
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        return self._memory_from_row(row) if row else None

    def soft_delete_memory(self, memory_id: int) -> bool:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE memories SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ? AND status != 'deleted'",
                (now, now, memory_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def soft_delete_matching_memories(self, text: str) -> int:
        target = text.lower()
        for marker in ["别记", "不要记", "别保存", "忘掉", "清除记忆", "删掉记忆", "清除", "删除"]:
            target = target.replace(marker, " ")
        words = [word for word in re.split(r"\s+", target.strip()) if len(word) >= 2]
        target_chars = _content_chars(target)
        if not words and not target_chars:
            return 0
        now = time.time()
        with self._lock:
            rows = self._conn.execute("SELECT id, content FROM memories WHERE status = 'active'").fetchall()
            memory_ids: list[int] = []
            for row in rows:
                content = str(row[1]).lower()
                content_chars = _content_chars(content)
                word_match = any(word in content for word in words)
                char_match = len(target_chars & content_chars) >= 2
                if word_match or char_match:
                    memory_ids.append(int(row[0]))
            for memory_id in memory_ids:
                self._conn.execute(
                    "UPDATE memories SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, memory_id),
                )
            self._conn.commit()
        return len(memory_ids)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _conversation_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "device_id": row[1],
            "status": row[2],
            "started_at": row[3],
            "updated_at": row[4],
            "closed_at": row[5],
            "summary": row[6],
            "topic": row[7],
            "emotion_tags": json.loads(row[8] or "[]"),
            "pending_task": row[9],
        }

    @staticmethod
    def _turn_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "conversation_id": row[1],
            "ts": row[2],
            "user_text": row[3],
            "luma_text": row[4],
            "decision": json.loads(row[5]),
            "emotion": row[6],
            "tone": row[7],
            "pet_behavior": row[8],
        }

    @staticmethod
    def _memory_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "created_at": row[1],
            "updated_at": row[2],
            "type": row[3],
            "content": row[4],
            "confidence": row[5],
            "source_conversation_id": row[6],
            "source_turn_id": row[7],
            "status": row[8],
            "deleted_at": row[9],
        }

    @staticmethod
    def _make_summary(user_text: str, luma_text: str) -> str:
        text = f"用户：{user_text.strip()} / Luma：{luma_text.strip()}"
        return text[:220]

    @staticmethod
    def _extract_topic(text: str) -> str:
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()
        return " ".join(cleaned.split()[:8])

    @staticmethod
    def _extract_emotion_tags(text: str, tone: str, pet_behavior: str) -> list[str]:
        tags: set[str] = set()
        lower = text.lower()
        emotion_terms = {
            "tired": ["累", "困", "疲惫"],
            "sad": ["难过", "伤心", "委屈"],
            "anxious": ["焦虑", "紧张", "害怕"],
            "happy": ["开心", "高兴", "舒服"],
        }
        for tag, terms in emotion_terms.items():
            if any(term in lower for term in terms):
                tags.add(tag)
        if tone:
            tags.add(f"tone:{tone}")
        if pet_behavior in {"comfort", "nudge"}:
            tags.add(pet_behavior)
        return sorted(tags)


def _field(value: dict[str, Any] | Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()


def _dedupe_key(content: str) -> str:
    return _normalize_content(content).lower()


def _is_sensitive(content: str) -> bool:
    lower = content.lower()
    return any(pattern in lower for pattern in SENSITIVE_MEMORY_PATTERNS)


def _content_chars(text: str) -> set[str]:
    return {char for char in text.lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff"}
