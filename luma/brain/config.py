from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env.local", ".env"):
        path = Path(name)
        if path.exists():
            load_dotenv(path, override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()


_load_env_files()


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("LUMA_HOST", "127.0.0.1")
    port: int = int(os.getenv("LUMA_PORT", "8787"))
    database_path: Path = Path(os.getenv("LUMA_DB", ".luma/luma_state.sqlite3"))
    log_jsonl_path: Path = Path(os.getenv("LUMA_JSONL", ".luma/luma_events.jsonl"))
    head_timeout_seconds: float = float(os.getenv("LUMA_HEAD_TIMEOUT", "10.0"))
    command_timeout_seconds: float = float(os.getenv("LUMA_COMMAND_TIMEOUT", "8.0"))
    max_memory_events: int = int(os.getenv("LUMA_MAX_MEMORY_EVENTS", "200"))
    memory_window_seconds: int = int(os.getenv("LUMA_MEMORY_WINDOW_SECONDS", "1800"))
    voice_sample_rate_hz: int = int(os.getenv("LUMA_VOICE_SAMPLE_RATE_HZ", "24000"))
    voice_channels: int = int(os.getenv("LUMA_VOICE_CHANNELS", "1"))
    voice_chunk_ms: int = int(os.getenv("LUMA_VOICE_CHUNK_MS", "40"))
    voice_max_record_seconds: float = float(os.getenv("LUMA_VOICE_MAX_RECORD_SECONDS", "8.0"))
    voice_silence_timeout_seconds: float = float(os.getenv("LUMA_VOICE_SILENCE_TIMEOUT_SECONDS", "1.2"))
    playback_initial_buffer_chunks: int = int(os.getenv("LUMA_PLAYBACK_INITIAL_BUFFER_CHUNKS", "3"))
    voice_error_recovery_seconds: float = float(os.getenv("LUMA_VOICE_ERROR_RECOVERY_SECONDS", "1.5"))
    telemetry_broadcast_seconds: float = float(os.getenv("LUMA_TELEMETRY_BROADCAST_SECONDS", "5.0"))
    event_log_queue_size: int = int(os.getenv("LUMA_EVENT_LOG_QUEUE_SIZE", "1000"))
    event_log_batch_size: int = int(os.getenv("LUMA_EVENT_LOG_BATCH_SIZE", "50"))
    event_log_flush_seconds: float = float(os.getenv("LUMA_EVENT_LOG_FLUSH_SECONDS", "0.25"))
    server_vad_trim_enabled: bool = _env_bool("LUMA_SERVER_VAD_TRIM_ENABLED", True)
    touch_wake_cooldown_seconds: float = float(os.getenv("LUMA_TOUCH_WAKE_COOLDOWN_SECONDS", "20.0"))
    stt_provider: str = os.getenv("LUMA_STT_PROVIDER", "local_sherpa")
    tts_provider: str = os.getenv("LUMA_TTS_PROVIDER", "local_sherpa")
    sherpa_root: Path | None = _env_path("LUMA_SHERPA_ROOT")
    sherpa_asr_bin: Path | None = _env_path("LUMA_SHERPA_ASR_BIN")
    sherpa_asr_model_dir: Path | None = _env_path("LUMA_SHERPA_ASR_MODEL_DIR")
    sherpa_tts_bin: Path | None = _env_path("LUMA_SHERPA_TTS_BIN")
    sherpa_tts_model_dir: Path | None = _env_path("LUMA_SHERPA_TTS_MODEL_DIR")
    sherpa_tts_engine: str = os.getenv("LUMA_SHERPA_TTS_ENGINE", "zipvoice")
    sherpa_tts_vocoder: Path | None = _env_path("LUMA_SHERPA_TTS_VOCODER")
    tts_reference_audio: Path | None = _env_path("LUMA_TTS_REFERENCE_AUDIO")
    tts_reference_text: str = os.getenv("LUMA_TTS_REFERENCE_TEXT", "")
    stt_timeout_seconds: float = float(os.getenv("LUMA_STT_TIMEOUT_SECONDS", "20"))
    tts_timeout_seconds: float = float(os.getenv("LUMA_TTS_TIMEOUT_SECONDS", "45"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_stt_model: str = os.getenv("LUMA_OPENAI_STT_MODEL", "whisper-1")
    openai_tts_model: str = os.getenv("LUMA_OPENAI_TTS_MODEL", "tts-1")
    openai_tts_voice: str = os.getenv("LUMA_OPENAI_TTS_VOICE", "alloy")
    llm_api_key: str = os.getenv("LUMA_LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    llm_base_url: str = os.getenv("LUMA_LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = os.getenv("LUMA_LLM_MODEL", os.getenv("LUMA_OPENAI_LLM_MODEL", "gpt-4o-mini"))
    llm_temperature: float = float(os.getenv("LUMA_LLM_TEMPERATURE", "0.65"))
    llm_max_tokens: int = int(os.getenv("LUMA_LLM_MAX_TOKENS", "800"))
    llm_json_mode: bool = _env_bool("LUMA_LLM_JSON_MODE", True)
    llm_thinking: str = os.getenv("LUMA_LLM_THINKING", "")
    openai_llm_model: str = llm_model
    conversation_same_seconds: float = float(os.getenv("LUMA_CONVERSATION_SAME_SECONDS", "45"))
    conversation_resumable_seconds: float = float(os.getenv("LUMA_CONVERSATION_RESUMABLE_SECONDS", "180"))
    conversation_restore_seconds: float = float(os.getenv("LUMA_CONVERSATION_RESTORE_SECONDS", "300"))
    conversation_recent_turns: int = int(os.getenv("LUMA_CONVERSATION_RECENT_TURNS", "8"))
    conversation_memory_limit: int = int(os.getenv("LUMA_CONVERSATION_MEMORY_LIMIT", "8"))
    openai_system_prompt: str = os.getenv("LUMA_OPENAI_SYSTEM_PROMPT", "")
    idle_expression_enabled: bool = _env_bool("LUMA_IDLE_EXPRESSION_ENABLED", True)
    idle_expression_min_seconds: float = float(os.getenv("LUMA_IDLE_EXPRESSION_MIN_SECONDS", "60"))
    idle_expression_max_seconds: float = float(os.getenv("LUMA_IDLE_EXPRESSION_MAX_SECONDS", "120"))
    idle_expression_duration_ms: int = int(os.getenv("LUMA_IDLE_EXPRESSION_DURATION_MS", "3000"))
    qgif_stream_chunk_bytes: int = int(os.getenv("LUMA_QGIF_STREAM_CHUNK_BYTES", "4096"))


settings = Settings()
