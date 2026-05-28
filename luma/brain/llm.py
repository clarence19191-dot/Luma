from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .emotions import ALLOWED_EMOTIONS, emotion_duration_ms


MemoryCategory = Literal[
    "preference",
    "habit",
    "event",
    "emotional_pattern",
    "behavior_routine",
    "relationship",
]
MemoryHorizon = Literal["short_term", "long_term"]
MemoryOperation = Literal["upsert", "ignore"]

LEGACY_MEMORY_CATEGORY_MAP = {
    "user_profile": "relationship",
    "preference": "preference",
    "dislike": "preference",
    "pet": "relationship",
    "life_habit": "habit",
    "interaction": "behavior_routine",
    "emotional_care": "emotional_pattern",
    "one_off": "event",
    "task": "event",
    "work_detail": "event",
}


class ReplyDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=120)

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
        if not isinstance(data, dict):
            return data
        emotion = data.get("emotion", "idle")
        if isinstance(emotion, str):
            data = dict(data)
            # The LLM chooses only the expression. Playback duration is always
            # derived from the local asset catalog.
            data["duration_ms"] = emotion_duration_ms(emotion.strip())
        return data

    @field_validator("emotion")
    @classmethod
    def _supported_emotion(cls, value: str) -> str:
        emotion = value.strip()
        if emotion not in ALLOWED_EMOTIONS:
            raise ValueError(f"Unsupported emotion: {emotion}")
        return emotion


class LumaLLMDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply: ReplyDecision
    expression: ExpressionDecision = Field(default_factory=ExpressionDecision)


class MemoryReflectionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    operation: MemoryOperation = "upsert"
    category: MemoryCategory = "event"
    horizon: MemoryHorizon | None = None
    content: str = Field(default="", max_length=220)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    ttl_days: int | None = Field(default=None, ge=1, le=90)
    evidence: str = Field(default="", max_length=220)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_type(cls, data: Any) -> Any:
        if isinstance(data, dict) and "category" not in data and "type" in data:
            data = dict(data)
            data["category"] = LEGACY_MEMORY_CATEGORY_MAP.get(str(data.get("type", "")), data.get("type"))
        return data

    @model_validator(mode="after")
    def _default_horizon(self) -> "MemoryReflectionItem":
        if self.horizon is None:
            self.horizon = "short_term" if self.category == "event" else "long_term"
        return self

    @field_validator("content", "evidence")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


class MemoryReflectionDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    memories: list[MemoryReflectionItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_common_shapes(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"memories": data}
        if isinstance(data, dict):
            for key in ("memory_updates", "operations", "items"):
                if key in data and "memories" not in data:
                    data = dict(data)
                    data["memories"] = data[key]
                    break
        return data


def fallback_decision(
    text: str = "我刚才有点走神，再说一遍好吗？",
    *,
    emotion: str = "dizzy",
    tone: str | None = None,
    pet_behavior: str | None = None,
) -> LumaLLMDecision:
    _ = tone, pet_behavior
    safe_emotion = emotion if emotion in ALLOWED_EMOTIONS else "dizzy"
    return LumaLLMDecision(
        reply=ReplyDecision(text=text),
        expression=ExpressionDecision(emotion=safe_emotion),
    )


def parse_llm_decision(raw: str, *, fallback_on_error: bool = False) -> LumaLLMDecision:
    try:
        payload = _loads_json_object(raw)
        return LumaLLMDecision.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError, ImportError):
        if fallback_on_error:
            return fallback_decision()
        raise


def parse_memory_reflection(raw: str, *, fallback_on_error: bool = False) -> MemoryReflectionDecision:
    try:
        payload = _loads_json_object(raw)
        return MemoryReflectionDecision.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError, ImportError):
        if fallback_on_error:
            return MemoryReflectionDecision()
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
    if text.startswith("[") and text.endswith("]"):
        return text
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last >= first:
        return text[first : last + 1]
    return text
