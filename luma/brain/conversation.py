from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import settings
from .emotions import ALLOWED_EMOTIONS
from .llm import LumaLLMDecision, decision_to_dict
from .memory import MemoryStore
from .prompt import build_luma_messages


class LLMDecisionProvider(Protocol):
    async def decide(self, messages: list[dict[str, str]]) -> LumaLLMDecision:
        ...


@dataclass(frozen=True)
class BoundaryDecision:
    decision: str
    reason: str
    previous_conversation_id: str | None = None
    conversation_id: str | None = None
    gap_seconds: float | None = None
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "previous_conversation_id": self.previous_conversation_id,
            "conversation_id": self.conversation_id,
            "gap_seconds": self.gap_seconds,
            "signals": self.signals,
        }


@dataclass(frozen=True)
class ConversationTurnResult:
    conversation: dict[str, Any]
    boundary: BoundaryDecision
    decision: LumaLLMDecision
    turn_id: int
    saved_memories: list[dict[str, Any]]
    deleted_memory_count: int = 0


class ConversationManager:
    def __init__(self, memory: MemoryStore, llm_provider: LLMDecisionProvider) -> None:
        self.memory = memory
        self.llm_provider = llm_provider
        self.last_prompt_messages: list[dict[str, str]] = []
        self.last_boundary: BoundaryDecision | None = None
        self.last_result: ConversationTurnResult | None = None

    async def process_user_turn(
        self,
        text: str,
        *,
        device_id: str = "local",
        source: str = "voice",
        now: float | None = None,
    ) -> ConversationTurnResult:
        ts = now or time.time()
        boundary, conversation = self.resolve_conversation(text, device_id=device_id, now=ts)
        active_turns = (
            self.memory.recent_turns(conversation["id"], limit=settings.conversation_recent_turns)
            if boundary.decision in {"same", "resume"}
            else []
        )
        memories = self.memory.relevant_memories(text, limit=settings.conversation_memory_limit)
        prompt_messages = build_luma_messages(
            user_text=text,
            supported_emotions=sorted(ALLOWED_EMOTIONS),
            conversation=conversation,
            boundary=boundary.to_dict(),
            recent_turns=active_turns,
            memories=memories,
        )
        self.last_prompt_messages = prompt_messages

        deleted_count = 0
        allow_memory_write = not _requests_forget(text)
        if not allow_memory_write:
            deleted_count = self.memory.soft_delete_matching_memories(text)

        decision = await self.llm_provider.decide(prompt_messages)
        decision_dict = decision_to_dict(decision)
        turn_id = self.memory.append_turn(
            conversation["id"],
            user_text=text,
            luma_text=decision.reply.text,
            decision=decision_dict,
            emotion=decision.expression.emotion,
            tone=decision.reply.tone,
            pet_behavior=decision.pet_behavior,
            now=ts,
        )

        saved_memories: list[dict[str, Any]] = []
        if allow_memory_write:
            for candidate in decision.memory_candidates:
                saved = self.memory.save_memory_candidate(
                    candidate,
                    source_conversation_id=conversation["id"],
                    source_turn_id=turn_id,
                )
                if saved:
                    saved_memories.append(saved)

        updated = self.memory.get_conversation(conversation["id"]) or conversation
        result = ConversationTurnResult(
            conversation=updated,
            boundary=boundary,
            decision=decision,
            turn_id=turn_id,
            saved_memories=saved_memories,
            deleted_memory_count=deleted_count,
        )
        self.last_result = result
        self.memory.log(
            "conversation_turn",
            {
                "conversation_id": updated["id"],
                "turn_id": turn_id,
                "source": source,
                "boundary": boundary.to_dict(),
                "reply": decision.reply.text,
                "tone": decision.reply.tone,
                "pet_behavior": decision.pet_behavior,
                "emotion": decision.expression.emotion,
                "saved_memory_count": len(saved_memories),
                "deleted_memory_count": deleted_count,
            },
        )
        return result

    def resolve_conversation(self, text: str, *, device_id: str, now: float | None = None) -> tuple[BoundaryDecision, dict[str, Any]]:
        ts = now or time.time()
        previous = self.memory.current_conversation(device_id) or self.memory.last_conversation(device_id)
        boundary = self.decide_boundary(text, previous, now=ts)

        if boundary.decision == "same" and previous:
            conversation = previous if previous["status"] == "active" else self.memory.reopen_conversation(previous["id"], now=ts) or previous
        elif boundary.decision == "resume" and previous:
            self.memory.close_current_conversations(device_id, now=ts)
            conversation = self.memory.reopen_conversation(previous["id"], now=ts) or previous
        else:
            self.memory.close_current_conversations(device_id, now=ts)
            conversation = self.memory.create_conversation(device_id, now=ts, topic=_extract_light_topic(text))

        boundary = BoundaryDecision(
            decision=boundary.decision,
            reason=boundary.reason,
            previous_conversation_id=boundary.previous_conversation_id,
            conversation_id=conversation["id"],
            gap_seconds=boundary.gap_seconds,
            signals=boundary.signals,
        )
        self.memory.record_boundary(
            device_id=device_id,
            previous_conversation_id=boundary.previous_conversation_id,
            conversation_id=conversation["id"],
            decision=boundary.decision,
            reason=boundary.reason,
            signals=boundary.signals,
            gap_seconds=boundary.gap_seconds,
            now=ts,
        )
        self.last_boundary = boundary
        return boundary, conversation

    def decide_boundary(self, text: str, previous: dict[str, Any] | None, *, now: float | None = None) -> BoundaryDecision:
        if previous is None:
            return BoundaryDecision(
                decision="new",
                reason="no_previous_conversation",
                signals=_signals(text, None),
            )

        ts = now or time.time()
        gap = max(0.0, ts - float(previous["updated_at"]))
        signals = _signals(text, previous)
        previous_id = str(previous["id"])

        if signals["explicit_reset"]:
            return BoundaryDecision("new", "explicit_reset", previous_id, gap_seconds=gap, signals=signals)
        if signals["greeting_only"] and gap > settings.conversation_same_seconds:
            return BoundaryDecision("new", "long_gap_greeting_reopens_presence", previous_id, gap_seconds=gap, signals=signals)
        if gap <= settings.conversation_same_seconds:
            return BoundaryDecision("same", "within_short_gap", previous_id, gap_seconds=gap, signals=signals)
        if gap <= settings.conversation_resumable_seconds:
            if signals["explicit_continue"]:
                return BoundaryDecision("same", "explicit_continue_within_resumable_gap", previous_id, gap_seconds=gap, signals=signals)
            if signals["emotion_continuity"]:
                return BoundaryDecision("same", "emotion_continuity_within_resumable_gap", previous_id, gap_seconds=gap, signals=signals)
            if signals["same_topic"] or signals["pronoun_bridge"] or signals["pending_task"]:
                return BoundaryDecision("same", "context_signals_within_resumable_gap", previous_id, gap_seconds=gap, signals=signals)
            return BoundaryDecision("new", "topic_shift_after_short_gap", previous_id, gap_seconds=gap, signals=signals)
        if gap <= settings.conversation_restore_seconds:
            if signals["explicit_continue"] or signals["pending_task"]:
                return BoundaryDecision("resume", "explicit_restore_within_medium_gap", previous_id, gap_seconds=gap, signals=signals)
            if signals["emotion_continuity"]:
                return BoundaryDecision("resume", "emotion_continuity_within_medium_gap", previous_id, gap_seconds=gap, signals=signals)
            return BoundaryDecision("new", "medium_gap_defaults_to_new", previous_id, gap_seconds=gap, signals=signals)
        if signals["explicit_continue"]:
            return BoundaryDecision("resume", "explicit_restore_after_long_gap", previous_id, gap_seconds=gap, signals=signals)
        return BoundaryDecision("new", "long_gap_defaults_to_new", previous_id, gap_seconds=gap, signals=signals)

    def reset(self, *, device_id: str = "local") -> dict[str, Any]:
        now = time.time()
        previous = self.memory.current_conversation(device_id)
        self.memory.close_current_conversations(device_id, now=now)
        conversation = self.memory.create_conversation(device_id, now=now)
        boundary = BoundaryDecision(
            "new",
            "manual_reset",
            previous_conversation_id=previous["id"] if previous else None,
            conversation_id=conversation["id"],
            gap_seconds=None,
            signals={"manual": True},
        )
        self.memory.record_boundary(
            device_id=device_id,
            previous_conversation_id=boundary.previous_conversation_id,
            conversation_id=conversation["id"],
            decision=boundary.decision,
            reason=boundary.reason,
            signals=boundary.signals,
            gap_seconds=None,
            now=now,
        )
        self.last_boundary = boundary
        self.memory.log("conversation_reset", boundary.to_dict())
        return conversation

    def snapshot(self, *, device_id: str = "local") -> dict[str, Any]:
        conversation = self.memory.current_conversation(device_id) or self.memory.last_conversation(device_id)
        turns = self.memory.recent_turns(conversation["id"], limit=settings.conversation_recent_turns) if conversation else []
        return {
            "conversation": conversation,
            "recent_turns": turns,
            "boundary": self.last_boundary.to_dict() if self.last_boundary else self.memory.last_boundary(device_id),
            "last_decision": decision_to_dict(self.last_result.decision) if self.last_result else None,
            "last_turn_id": self.last_result.turn_id if self.last_result else None,
            "saved_memory_count": len(self.last_result.saved_memories) if self.last_result else 0,
            "deleted_memory_count": self.last_result.deleted_memory_count if self.last_result else 0,
        }


def _signals(text: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    normalized = text.strip().lower()
    emotion_tags = set(previous.get("emotion_tags", [])) if previous else set()
    return {
        "explicit_reset": _contains_any(normalized, ["重新开始", "换个话题", "忘掉刚才", "不说这个了", "另说"]),
        "explicit_continue": _contains_any(normalized, ["继续", "接着", "刚才", "上面", "那个", "你刚说", "刚说的", "继续刚才"]),
        "pronoun_bridge": _contains_any(normalized, ["这个", "那个", "它", "这件事", "刚刚", "然后呢"]),
        "greeting_only": _is_greeting_only(normalized),
        "same_topic": _same_topic(normalized, previous),
        "emotion_continuity": _emotion_continuity(normalized, emotion_tags),
        "pending_task": bool(previous and previous.get("pending_task")),
    }


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _is_greeting_only(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?,.、~～]+", "", text)
    return compact in {
        "你好",
        "嗨",
        "哈喽",
        "hello",
        "luma",
        "lumaluma",
        "露玛",
        "露玛在吗",
        "你在吗",
        "在吗",
        "摸摸",
        "摸头",
    }


def _same_topic(text: str, previous: dict[str, Any] | None) -> bool:
    if not previous:
        return False
    topic = str(previous.get("topic", "")).strip().lower()
    if not topic:
        return False
    text_chars = _topic_chars(text)
    topic_chars = _topic_chars(topic)
    if not text_chars or not topic_chars:
        return False
    return len(text_chars & topic_chars) >= 2


def _emotion_continuity(text: str, previous_tags: set[str]) -> bool:
    if not previous_tags:
        return False
    terms = {
        "tired": ["还是好累", "又累", "依然累", "更累", "好累"],
        "sad": ["还是难过", "又难过", "依然难过", "伤心", "委屈"],
        "anxious": ["还是焦虑", "又焦虑", "紧张", "害怕"],
        "happy": ["还是开心", "又开心", "高兴"],
    }
    for tag, words in terms.items():
        if tag in previous_tags and any(word in text for word in words):
            return True
    return False


def _requests_forget(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(lowered, ["别记", "不要记", "别保存", "忘掉", "清除记忆", "删掉记忆"])


def _extract_light_topic(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()
    return " ".join(cleaned.split()[:8])


def _topic_chars(text: str) -> set[str]:
    stop = set("这个那个然后还是就是一下我们你我他她它了吗呢吧啊呀的了和")
    return {char for char in text if ("\u4e00" <= char <= "\u9fff" or char.isalnum()) and char not in stop}
