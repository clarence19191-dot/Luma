from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .emotions import ALLOWED_EMOTIONS, emotion_duration_ms


Tone = Literal["warm", "curious", "playful", "calm", "shy", "sleepy", "apologetic", "neutral"]
PetBehavior = Literal["greet", "nudge", "comfort", "curious", "react", "play_idle", "answer_lightly", "refuse"]
MemoryType = Literal["user_profile", "preference", "dislike", "pet", "life_habit", "interaction", "emotional_care"]


class ReplyDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=120)
    tone: Tone = "warm"

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reply.text is empty")
        return text


class ExpressionDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    emotion: str = "idle"
    duration_ms: int = Field(default_factory=lambda: emotion_duration_ms("idle"), ge=0, le=15000)

    @model_validator(mode="before")
    @classmethod
    def _default_duration_from_emotion(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("duration_ms") is not None:
            return data
        emotion = data.get("emotion", "idle")
        if isinstance(emotion, str):
            data = dict(data)
            data["duration_ms"] = emotion_duration_ms(emotion.strip())
        return data

    @field_validator("emotion")
    @classmethod
    def _supported_emotion(cls, value: str) -> str:
        emotion = value.strip()
        if emotion not in ALLOWED_EMOTIONS:
            raise ValueError(f"Unsupported emotion: {emotion}")
        return emotion


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "note_only"
    params: dict[str, Any] = Field(default_factory=dict)


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: MemoryType
    content: str = Field(min_length=1, max_length=160)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        return value.strip()


class SafetyDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocked: bool = False
    reason: str = ""
    needs_clarification: bool = False


class LumaLLMDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply: ReplyDecision
    expression: ExpressionDecision = Field(default_factory=ExpressionDecision)
    pet_behavior: PetBehavior = "react"
    actions: list[ActionDecision] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    safety: SafetyDecision = Field(default_factory=SafetyDecision)


def fallback_decision(
    text: str = "我刚才有点走神，再说一遍好吗？",
    *,
    emotion: str = "dizzy",
    tone: Tone = "apologetic",
    pet_behavior: PetBehavior = "react",
) -> LumaLLMDecision:
    safe_emotion = emotion if emotion in ALLOWED_EMOTIONS else "dizzy"
    return LumaLLMDecision(
        reply=ReplyDecision(text=text, tone=tone),
        expression=ExpressionDecision(emotion=safe_emotion),
        pet_behavior=pet_behavior,
        actions=[],
        memory_candidates=[],
        safety=SafetyDecision(blocked=False, reason="fallback", needs_clarification=False),
    )


def parse_llm_decision(raw: str, *, fallback_on_error: bool = False) -> LumaLLMDecision:
    try:
        payload = _loads_json_object(raw)
        return LumaLLMDecision.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError, ImportError):
        if fallback_on_error:
            return fallback_decision()
        raise


def decision_to_dict(decision: LumaLLMDecision) -> dict[str, Any]:
    return decision.model_dump(mode="json")


def _loads_json_object(raw: str) -> Any:
    candidate = _extract_json_candidate(raw)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
        except ImportError:
            raise
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, str):
            return json.loads(repaired)
        return repaired


def _extract_json_candidate(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last >= first:
        return text[first : last + 1]
    return text
