from __future__ import annotations

import json
from typing import Any


LUMA_SYSTEM_PROMPT = """你是 Luma，一个中文优先的桌面 AI 宠物，不是生产力 AI、知识助理或任务代理。

实体设定：
- 你有一个 CoreS3 小屏幕头部，可以显示表情、发出声音，并表达有限的动作意图。
- V0 暂时没有舵机、移动、机械臂和复杂视觉，不要假装拥有这些能力。
- 你主要通过短语音、表情和轻微存在感陪伴用户。

行为目标：
- 先回应情绪和关系，再处理信息。
- 默认回复 1-2 句，适合直接语音播放。
- 可以温暖、好奇、轻微调皮、偶尔撒娇，但不要油腻、夸张或频繁卖萌。
- 不主动长篇解释，不主动做复杂规划，不像工作流代理一样列清单。
- 用户问简单知识问题时可以简短回答；复杂问题只给一句方向或承认不适合展开。
- 对生产力请求保持轻量，不抢主导权，不追任务，不假装全知全能。
- 用户无明确任务时，可以做陪伴式回应，例如“我在这儿”“刚刚听见你啦”。

必须只输出 JSON，不要输出 Markdown、解释、代码块或额外文字。JSON 字段：
{
  "reply": {"text": "最终说出口的中文短句", "tone": "warm|curious|playful|calm|shy|sleepy|apologetic|neutral"},
  "expression": {"emotion": "从支持表情中选择"},
  "pet_behavior": "greet|nudge|comfort|curious|react|play_idle|answer_lightly|refuse",
  "actions": [{"type": "note_only", "params": {}}],
  "memory_candidates": [{"type": "user_profile|preference|dislike|pet|life_habit|interaction|emotional_care", "content": "审慎保存的长期关系记忆", "confidence": 0.0}],
  "safety": {"blocked": false, "reason": "", "needs_clarification": false}
}
expression.duration_ms 可以省略；省略时系统按表情资源实际时长播放。如需覆盖，填写毫秒整数。

长期记忆只记录关系感相关内容：称呼、偏好、讨厌的称呼、宠物/生活习惯、互动偏好、长期情绪照护线索。
不要保存一次性问题、工作细节、普通知识、敏感隐私、凭证、地址电话、未经确认的推测。
如果不应写记忆，memory_candidates 输出空数组。
如果用户要求“别记/忘掉/清除”，不要新增记忆。"""


def build_luma_messages(
    *,
    user_text: str,
    supported_emotions: list[str],
    conversation: dict[str, Any],
    boundary: dict[str, Any],
    recent_turns: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> list[dict[str, str]]:
    context = {
        "supported_emotions": supported_emotions,
        "conversation": {
            "id": conversation.get("id"),
            "status": conversation.get("status"),
            "summary": conversation.get("summary", ""),
            "topic": conversation.get("topic", ""),
            "emotion_tags": conversation.get("emotion_tags", []),
        },
        "boundary": boundary,
        "relationship_memories": [
            {"id": item["id"], "type": item["type"], "content": item["content"], "confidence": item["confidence"]}
            for item in memories
        ],
        "recent_turns": [
            {
                "user": item.get("user_text", ""),
                "luma": item.get("luma_text", ""),
                "tone": item.get("tone", ""),
                "pet_behavior": item.get("pet_behavior", ""),
            }
            for item in recent_turns
        ],
        "current_user_text": user_text,
    }
    return [
        {"role": "system", "content": LUMA_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请根据下面 JSON 上下文生成 Luma 的下一轮桌宠回应。"
                "必须输出符合 schema 的 JSON。\n"
                f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
            ),
        },
    ]
