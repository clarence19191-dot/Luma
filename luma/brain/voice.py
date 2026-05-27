from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from uuid import uuid4

from .config import settings
from .conversation import ConversationManager
from .local_audio import AudioConversionError, read_wav_as_pcm16_mono, write_pcm16_wav
from .llm import LumaLLMDecision, parse_llm_decision
from .memory import MemoryStore
from .state import LumaState


JsonSender = Callable[[dict[str, Any]], Awaitable[bool]]
BytesSender = Callable[[bytes], Awaitable[bool]]
StateBroadcaster = Callable[[str], Awaitable[None]]


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class AudioFormat:
    sample_rate_hz: int = settings.voice_sample_rate_hz
    channels: int = settings.voice_channels
    encoding: str = "pcm_s16le"

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate_hz * self.channels * 2


@dataclass(frozen=True)
class AudioBuffer:
    pcm: bytes
    format: AudioFormat

    def to_wav_bytes(self) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(self.format.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.format.sample_rate_hz)
            wav.writeframes(self.pcm)
        return output.getvalue()


class STTProvider(Protocol):
    async def transcribe(self, audio: AudioBuffer) -> str:
        ...


class LLMProvider(Protocol):
    async def decide(self, messages: list[dict[str, str]]) -> LumaLLMDecision:
        ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> bytes:
        ...


class OpenAIProviderBase:
    def _client(self, *, api_key: str, base_url: str | None = None, config_name: str = "OPENAI_API_KEY") -> Any:
        if not api_key:
            raise ProviderError("provider_unconfigured", f"{config_name} is not set.", retryable=False)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ProviderError("provider_missing", "Install the openai package to use online providers.", retryable=False) from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return AsyncOpenAI(**kwargs)


class OpenAISTTProvider(OpenAIProviderBase):
    async def transcribe(self, audio: AudioBuffer) -> str:
        client = self._client(api_key=settings.openai_api_key)
        wav = audio.to_wav_bytes()
        try:
            result = await client.audio.transcriptions.create(
                model=settings.openai_stt_model,
                file=("luma.wav", wav, "audio/wav"),
                language="zh",
            )
        except Exception as exc:  # pragma: no cover - exercised with live provider
            raise ProviderError("stt_failed", str(exc), retryable=True) from exc
        return str(getattr(result, "text", "") or "").strip()


class OpenAILLMProvider(OpenAIProviderBase):
    async def decide(self, messages: list[dict[str, str]]) -> LumaLLMDecision:
        client = self._client(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            config_name="LUMA_LLM_API_KEY or OPENAI_API_KEY",
        )
        try:
            kwargs: dict[str, Any] = {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
            }
            if settings.llm_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if settings.llm_thinking:
                kwargs["extra_body"] = {"thinking": {"type": settings.llm_thinking}}
            result = await client.chat.completions.create(**kwargs)
        except Exception as exc:  # pragma: no cover - exercised with live provider
            raise ProviderError("llm_failed", str(exc), retryable=True) from exc

        content = result.choices[0].message.content if result.choices else ""
        return parse_llm_decision(content or "", fallback_on_error=True)


class OpenAITTSProvider(OpenAIProviderBase):
    async def synthesize(self, text: str) -> bytes:
        client = self._client(api_key=settings.openai_api_key)
        try:
            result = await client.audio.speech.create(
                model=settings.openai_tts_model,
                voice=settings.openai_tts_voice,
                input=text,
                response_format="pcm",
            )
        except Exception as exc:  # pragma: no cover - exercised with live provider
            raise ProviderError("tts_failed", str(exc), retryable=True) from exc

        if hasattr(result, "aread"):
            data = await result.aread()
            return bytes(data)
        if hasattr(result, "read"):
            data = result.read()
            if asyncio.iscoroutine(data):
                data = await data
            return bytes(data)
        if isinstance(result, bytes):
            return result
        raise ProviderError("tts_bad_response", "TTS provider did not return PCM bytes.", retryable=True)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHERPA_VENDOR_ROOT = Path.home() / "files/Starest/UTM/AcousticPipelineCore/Vendor"
ZIPVOICE_MODEL_NAME = "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia"
ZIPVOICE_DEFAULT_REFERENCE_TEXT = "那还是三十六年前, 一九八七年. 我呢考上了武汉大学的计算机系."


class LocalSherpaSTTProvider:
    def __init__(self, config: Any = settings) -> None:
        self.config = config
        roots = _sherpa_roots(config)
        self.executable = _resolve_executable(
            _setting(config, "sherpa_asr_bin"),
            "sherpa-onnx",
            roots,
            code="stt_provider_unconfigured",
        )
        self.model = _resolve_asr_model(_setting(config, "sherpa_asr_model_dir"), roots)
        self.timeout_seconds = float(_setting(config, "stt_timeout_seconds", 20))

    async def transcribe(self, audio: AudioBuffer) -> str:
        with tempfile.TemporaryDirectory(prefix="luma-stt-") as temp_dir:
            wav_path = Path(temp_dir) / "utterance.wav"
            try:
                write_pcm16_wav(
                    wav_path,
                    audio.pcm,
                    sample_rate_hz=audio.format.sample_rate_hz,
                    channels=audio.format.channels,
                )
            except AudioConversionError as exc:
                raise ProviderError("stt_bad_audio", str(exc), retryable=False) from exc

            args = [
                str(self.executable),
                f"--tokens={self.model['tokens']}",
                f"--paraformer-encoder={self.model['encoder']}",
                f"--paraformer-decoder={self.model['decoder']}",
                "--num-threads=2",
                str(wav_path),
            ]
            output = await _run_provider_command(
                args,
                timeout_seconds=self.timeout_seconds,
                failed_code="stt_failed",
                timeout_code="stt_timeout",
            )
        return _parse_sherpa_transcript(output)


class LocalSherpaTTSProvider:
    def __init__(self, config: Any = settings) -> None:
        self.config = config
        engine = str(_setting(config, "sherpa_tts_engine", "zipvoice")).strip().lower()
        if engine != "zipvoice":
            raise ProviderError(
                "tts_provider_unconfigured",
                f"Unsupported local sherpa TTS engine: {engine}. Only zipvoice is configured in V0.",
                retryable=False,
            )
        self.engine = engine
        roots = _sherpa_roots(config)
        self.executable = _resolve_executable(
            _setting(config, "sherpa_tts_bin"),
            "sherpa-onnx-offline-tts",
            roots,
            code="tts_provider_unconfigured",
        )
        self.model = _resolve_zipvoice_model(config, roots)
        self.timeout_seconds = float(_setting(config, "tts_timeout_seconds", 45))
        self.target_sample_rate_hz = int(_setting(config, "voice_sample_rate_hz", settings.voice_sample_rate_hz))

    async def synthesize(self, text: str) -> bytes:
        cleaned = text.strip()
        if not cleaned:
            return b""

        with tempfile.TemporaryDirectory(prefix="luma-tts-") as temp_dir:
            output_wav = Path(temp_dir) / "reply.wav"
            args = [
                str(self.executable),
                f"--zipvoice-encoder={self.model['encoder']}",
                f"--zipvoice-decoder={self.model['decoder']}",
                f"--zipvoice-data-dir={self.model['data_dir']}",
                f"--zipvoice-lexicon={self.model['lexicon']}",
                f"--zipvoice-tokens={self.model['tokens']}",
                f"--zipvoice-vocoder={self.model['vocoder']}",
                f"--reference-audio={self.model['reference_audio']}",
                f"--reference-text={self.model['reference_text']}",
                "--num-steps=4",
                f"--output-filename={output_wav}",
                cleaned,
            ]
            await _run_provider_command(
                args,
                timeout_seconds=self.timeout_seconds,
                failed_code="tts_failed",
                timeout_code="tts_timeout",
            )
            try:
                pcm = read_wav_as_pcm16_mono(output_wav, target_sample_rate_hz=self.target_sample_rate_hz)
            except AudioConversionError as exc:
                raise ProviderError("tts_bad_audio", str(exc), retryable=True) from exc
        if not pcm:
            raise ProviderError("empty_tts", "Local sherpa TTS produced empty audio.", retryable=True)
        return pcm


def make_stt_provider(config: Any = settings) -> STTProvider:
    provider = str(_setting(config, "stt_provider", "local_sherpa")).strip().lower()
    if provider in {"local_sherpa", "sherpa", "local"}:
        return LocalSherpaSTTProvider(config)
    if provider in {"openai", "openai_compatible"}:
        return OpenAISTTProvider()
    raise ProviderError("provider_unconfigured", f"Unsupported STT provider: {provider}.", retryable=False)


def make_tts_provider(config: Any = settings) -> TTSProvider:
    provider = str(_setting(config, "tts_provider", "local_sherpa")).strip().lower()
    if provider in {"local_sherpa", "sherpa", "local"}:
        return LocalSherpaTTSProvider(config)
    if provider in {"openai", "openai_compatible"}:
        return OpenAITTSProvider()
    raise ProviderError("provider_unconfigured", f"Unsupported TTS provider: {provider}.", retryable=False)


class LazySTTProvider:
    def __init__(self, factory: Callable[[], STTProvider] = make_stt_provider) -> None:
        self._factory = factory
        self._provider: STTProvider | None = None

    async def transcribe(self, audio: AudioBuffer) -> str:
        if self._provider is None:
            self._provider = self._factory()
        return await self._provider.transcribe(audio)


class LazyTTSProvider:
    def __init__(self, factory: Callable[[], TTSProvider] = make_tts_provider) -> None:
        self._factory = factory
        self._provider: TTSProvider | None = None

    async def synthesize(self, text: str) -> bytes:
        if self._provider is None:
            self._provider = self._factory()
        return await self._provider.synthesize(text)


def _setting(config: Any, name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


def _as_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    path = value if isinstance(value, Path) else Path(str(value))
    path = path.expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sherpa_roots(config: Any) -> list[Path]:
    roots = [
        _as_path(_setting(config, "sherpa_root")),
        PROJECT_ROOT / "models/sherpa",
        PROJECT_ROOT / "models",
        DEFAULT_SHERPA_VENDOR_ROOT,
    ]
    return _deduplicate_paths([root for root in roots if root is not None])


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            output.append(path)
            seen.add(key)
    return output


def _resolve_executable(explicit: Any, name: str, roots: list[Path], *, code: str) -> Path:
    explicit_path = _as_path(explicit)
    if explicit_path is not None:
        if explicit_path.is_file() and os.access(explicit_path, os.X_OK):
            return explicit_path
        raise ProviderError(code, f"{explicit_path} is not an executable file.", retryable=False)

    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / f"sherpa-onnx-v1.13.0-osx-universal2-shared/bin/{name}",
                root / "bin" / name,
                root / name,
            ]
        )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which(name)
    if found:
        return Path(found)
    searched = ", ".join(str(path) for path in candidates[:6])
    raise ProviderError(code, f"Could not find executable {name}. Searched: {searched}", retryable=False)


def _resolve_asr_model(explicit: Any, roots: list[Path]) -> dict[str, Path]:
    explicit_path = _as_path(explicit)
    candidates = [explicit_path] if explicit_path is not None else []
    for root in roots:
        candidates.extend([root / "sherpa-onnx", root / "asr/sherpa-onnx", root])

    for candidate in _deduplicate_paths([path for path in candidates if path is not None]):
        model = _asr_model_files(candidate)
        if model:
            return model
        if explicit_path is not None and candidate == explicit_path:
            break

    raise ProviderError(
        "stt_provider_unconfigured",
        "Could not find sherpa ASR model files: tokens.txt, encoder(.int8).onnx, decoder(.int8).onnx.",
        retryable=False,
    )


def _asr_model_files(directory: Path) -> dict[str, Path] | None:
    tokens = directory / "tokens.txt"
    encoder = _first_existing_file(directory / "encoder.int8.onnx", directory / "encoder.onnx")
    decoder = _first_existing_file(directory / "decoder.int8.onnx", directory / "decoder.onnx")
    if tokens.is_file() and encoder is not None and decoder is not None:
        return {"tokens": tokens, "encoder": encoder, "decoder": decoder}
    return None


def _resolve_zipvoice_model(config: Any, roots: list[Path]) -> dict[str, Any]:
    explicit_path = _as_path(_setting(config, "sherpa_tts_model_dir"))
    candidates = [explicit_path] if explicit_path is not None else []
    for root in roots:
        candidates.extend(
            [
                root / ZIPVOICE_MODEL_NAME,
                root / "tts" / ZIPVOICE_MODEL_NAME,
                root / "zipvoice",
                root,
            ]
        )

    for candidate in _deduplicate_paths([path for path in candidates if path is not None]):
        model = _zipvoice_model_files(candidate, config, roots)
        if model:
            return model
        if explicit_path is not None and candidate == explicit_path:
            break

    raise ProviderError(
        "tts_provider_unconfigured",
        "Could not find ZipVoice TTS model files. Configure LUMA_SHERPA_TTS_MODEL_DIR and LUMA_SHERPA_TTS_VOCODER.",
        retryable=False,
    )


def _zipvoice_model_files(directory: Path, config: Any, roots: list[Path]) -> dict[str, Any] | None:
    tokens = directory / "tokens.txt"
    lexicon = directory / "lexicon.txt"
    data_dir = directory / "espeak-ng-data"
    encoder = _first_existing_file(directory / "encoder.int8.onnx", directory / "encoder.onnx")
    decoder = _first_existing_file(directory / "decoder.int8.onnx", directory / "decoder.onnx")
    vocoder = _resolve_vocoder(_setting(config, "sherpa_tts_vocoder"), directory, roots)
    reference_audio = _resolve_reference_audio(_setting(config, "tts_reference_audio"), directory)
    reference_text = str(_setting(config, "tts_reference_text", "") or "").strip()
    if not reference_text and reference_audio and reference_audio.name == "leijun-1.wav":
        reference_text = ZIPVOICE_DEFAULT_REFERENCE_TEXT
    if (
        tokens.is_file()
        and lexicon.is_file()
        and data_dir.is_dir()
        and encoder is not None
        and decoder is not None
        and vocoder is not None
        and reference_audio is not None
        and reference_text
    ):
        return {
            "tokens": tokens,
            "lexicon": lexicon,
            "data_dir": data_dir,
            "encoder": encoder,
            "decoder": decoder,
            "vocoder": vocoder,
            "reference_audio": reference_audio,
            "reference_text": reference_text,
        }
    return None


def _resolve_vocoder(explicit: Any, model_dir: Path, roots: list[Path]) -> Path | None:
    explicit_path = _as_path(explicit)
    candidates = [explicit_path] if explicit_path is not None else []
    candidates.extend([model_dir / "vocos_24khz.onnx", model_dir.parent / "vocos_24khz.onnx"])
    candidates.extend(root / "vocos_24khz.onnx" for root in roots)
    return _first_existing_file(*[path for path in candidates if path is not None])


def _resolve_reference_audio(explicit: Any, model_dir: Path) -> Path | None:
    explicit_path = _as_path(explicit)
    candidates = [explicit_path] if explicit_path is not None else []
    candidates.extend([model_dir / "test_wavs/leijun-1.wav", model_dir / "reference.wav"])
    return _first_existing_file(*[path for path in candidates if path is not None])


def _first_existing_file(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


async def _run_provider_command(
    args: list[str],
    *,
    timeout_seconds: float,
    failed_code: str,
    timeout_code: str,
) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ProviderError(failed_code, str(exc), retryable=True) from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(0.1, timeout_seconds))
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ProviderError(timeout_code, f"Provider command timed out after {timeout_seconds:.1f}s.", retryable=True) from exc

    output = _decode_command_output(stdout) + "\n" + _decode_command_output(stderr)
    if process.returncode != 0:
        raise ProviderError(failed_code, _trim_provider_output(output), retryable=True)
    return output


def _decode_command_output(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _trim_provider_output(output: str) -> str:
    cleaned = output.strip()
    if not cleaned:
        return "Provider command failed without output."
    return cleaned[-2000:]


def _parse_sherpa_transcript(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = str(decoded.get("text", "") or "").strip()
        if text:
            return text

    for line in reversed(lines):
        if line.startswith("/") or "Recognizer" in line or line.startswith("Started"):
            continue
        if line.startswith("--") or line.startswith("Usage:"):
            continue
        return line
    return ""


class VoiceSessionRuntime:
    def __init__(
        self,
        state: LumaState,
        memory: MemoryStore,
        send_head_json: JsonSender,
        send_head_bytes: BytesSender,
        broadcast_state: StateBroadcaster,
        *,
        stt_provider: STTProvider | None = None,
        llm_provider: LLMProvider | None = None,
        tts_provider: TTSProvider | None = None,
        conversation_manager: ConversationManager | None = None,
    ) -> None:
        self.state = state
        self.memory = memory
        self._send_head_json = send_head_json
        self._send_head_bytes = send_head_bytes
        self._broadcast_state = broadcast_state
        self.stt_provider = stt_provider or LazySTTProvider()
        self.llm_provider = llm_provider or OpenAILLMProvider()
        self.tts_provider = tts_provider or LazyTTSProvider()
        self.conversation = conversation_manager or ConversationManager(memory, self.llm_provider)
        self.format = AudioFormat()
        self._audio = bytearray()
        self._session_id: str | None = None
        self._processing_task: asyncio.Task[Any] | None = None
        self._max_audio_bytes = int(settings.voice_max_record_seconds * self.format.bytes_per_second)
        self._play_chunk_bytes = max(960, int(self.format.bytes_per_second * settings.voice_chunk_ms / 1000))

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def start(
        self,
        *,
        source: str = "wake_word",
        wake_phrase: str = "你好 Luma",
        session_id: str | None = None,
    ) -> str:
        await self.cancel(reason="new_session", notify_head=False)
        self._session_id = session_id or f"voice_{uuid4().hex[:12]}"
        self._audio.clear()
        self.state.update_voice("listening", session_id=self._session_id, wake_phrase=wake_phrase)
        self.memory.log("voice_started", {"session_id": self._session_id, "source": source, "wake_phrase": wake_phrase})
        await self._broadcast_state("voice_started")
        await self._send_head_json(
            {
                "type": "start_listening",
                "session_id": self._session_id,
                "sample_rate_hz": self.format.sample_rate_hz,
                "channels": self.format.channels,
                "encoding": self.format.encoding,
                "max_record_seconds": settings.voice_max_record_seconds,
                "silence_timeout_seconds": settings.voice_silence_timeout_seconds,
            }
        )
        await self._send_head_json({"type": "set_emotion", "emotion": "listening"})
        return self._session_id

    async def begin_audio(self, message: dict[str, Any]) -> None:
        if not self._session_id:
            session_id = message.get("session_id") if isinstance(message.get("session_id"), str) else None
            await self.start(source=str(message.get("source", "audio_begin")), session_id=session_id)
        self._audio.clear()
        self.state.update_voice("listening", session_id=self._session_id, audio_bytes=0)
        self.memory.log("voice_audio_begin", {"session_id": self._session_id, "message": message})
        await self._broadcast_state("voice_audio_begin")

    async def accept_audio_chunk(self, data: bytes) -> None:
        if not data:
            return
        if self.state.voice.phase != "listening" or not self._session_id:
            self.memory.log("voice_audio_ignored", {"bytes": len(data), "phase": self.state.voice.phase})
            return
        if len(self._audio) + len(data) > self._max_audio_bytes:
            await self.fail("audio_too_long", "Recording exceeded the configured V0 limit.", retryable=False)
            await self._send_head_json({"type": "cancel_session", "session_id": self._session_id, "reason": "audio_too_long"})
            return
        self._audio.extend(data)
        self.state.update_voice("listening", session_id=self._session_id, audio_bytes=len(self._audio))

    async def end_audio(self, message: dict[str, Any] | None = None) -> None:
        if not self._session_id:
            await self.fail("no_voice_session", "audio_end arrived before a voice session.", retryable=True)
            return
        if not self._audio:
            await self.fail("empty_audio", "No audio was received from CoreS3.", retryable=True)
            return

        session_id = self._session_id
        pcm = bytes(self._audio)
        self._audio.clear()
        self.state.update_voice("transcribing", session_id=session_id, audio_bytes=len(pcm))
        self.memory.log("voice_audio_end", {"session_id": session_id, "bytes": len(pcm), "message": message or {}})
        await self._broadcast_state("voice_audio_end")
        self._processing_task = asyncio.create_task(self._process_audio(session_id, pcm), name=f"luma-{session_id}")

    async def process_text(self, text: str, *, source: str = "console") -> str:
        await self.cancel(reason="text_session", notify_head=False)
        self._session_id = f"voice_{uuid4().hex[:12]}"
        session_id = self._session_id
        self.state.update_voice("thinking", session_id=session_id, transcript=text)
        self.memory.log("voice_text_started", {"session_id": session_id, "source": source, "text": text})
        await self._broadcast_state("voice_text_started")
        await self._process_text(session_id, text)
        return session_id

    async def playback_done(self, message: dict[str, Any]) -> None:
        session_id = message.get("session_id") or self._session_id
        self.memory.log("voice_playback_done", {"session_id": session_id, "message": message})
        self.state.update_voice("idle", session_id=session_id)
        self._session_id = None
        await self._broadcast_state("voice_playback_done")

    async def cancel(self, *, reason: str = "cancelled", notify_head: bool = True) -> None:
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            await asyncio.gather(self._processing_task, return_exceptions=True)
        self._processing_task = None
        session_id = self._session_id
        self._audio.clear()
        if session_id and notify_head:
            await self._send_head_json({"type": "cancel_session", "session_id": session_id, "reason": reason})
        if session_id:
            self.memory.log("voice_cancelled", {"session_id": session_id, "reason": reason})
        self._session_id = None
        self.state.update_voice("idle", session_id=session_id)
        await self._broadcast_state("voice_cancelled")

    async def fail(self, code: str, message: str, *, retryable: bool = True) -> None:
        error = {"code": code, "message": message, "retryable": retryable}
        session_id = self._session_id
        self.state.update_voice("error", session_id=session_id, error=error)
        self.memory.log("voice_error", {"session_id": session_id, "error": error})
        await self._broadcast_state("voice_error")

    async def _process_audio(self, session_id: str, pcm: bytes) -> None:
        audio = AudioBuffer(pcm=pcm, format=self.format)
        try:
            transcript = await self.stt_provider.transcribe(audio)
            if not transcript:
                transcript = "我没有听清楚。"
            self.state.update_voice("thinking", session_id=session_id, transcript=transcript)
            self.memory.log("voice_transcript", {"session_id": session_id, "text": transcript})
            await self._broadcast_state("voice_transcript")
            await self._process_text(session_id, transcript)
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            await self.fail(exc.code, exc.message, retryable=exc.retryable)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            await self.fail("voice_pipeline_failed", str(exc), retryable=True)

    async def _process_text(self, session_id: str, text: str) -> None:
        started = time.time()
        try:
            result = await self.conversation.process_user_turn(
                text,
                device_id=self.state.device.device_id or "local",
                source="voice",
            )
            decision = result.decision
            reply = decision.reply.text
            self.state.update_voice(
                "thinking",
                session_id=session_id,
                reply=reply,
                conversation_id=result.conversation["id"],
                tone=decision.reply.tone,
                pet_behavior=decision.pet_behavior,
                boundary=result.boundary.to_dict(),
                memory_count=len(result.saved_memories),
            )
            await self._send_head_json(
                {
                    "type": "set_emotion",
                    "emotion": decision.expression.emotion,
                    "duration_ms": decision.expression.duration_ms,
                }
            )
            self.memory.log(
                "voice_reply",
                {
                    "session_id": session_id,
                    "conversation_id": result.conversation["id"],
                    "turn_id": result.turn_id,
                    "text": reply,
                    "tone": decision.reply.tone,
                    "pet_behavior": decision.pet_behavior,
                    "emotion": decision.expression.emotion,
                    "latency_seconds": time.time() - started,
                },
            )
            await self._broadcast_state("voice_reply")

            pcm = await self.tts_provider.synthesize(reply)
            if not pcm:
                raise ProviderError("empty_tts", "TTS provider returned empty audio.", retryable=True)

            self.state.update_voice(
                "speaking",
                session_id=session_id,
                reply=reply,
                audio_bytes=len(pcm),
                conversation_id=result.conversation["id"],
                tone=decision.reply.tone,
                pet_behavior=decision.pet_behavior,
                boundary=result.boundary.to_dict(),
                memory_count=len(result.saved_memories),
            )
            self.memory.log("voice_tts_audio", {"session_id": session_id, "bytes": len(pcm)})
            await self._broadcast_state("voice_speaking")
            await self._stream_audio_to_head(session_id, pcm)
        except ProviderError as exc:
            await self.fail(exc.code, exc.message, retryable=exc.retryable)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            await self.fail("voice_pipeline_failed", str(exc), retryable=True)

    async def _stream_audio_to_head(self, session_id: str, pcm: bytes) -> None:
        await self._send_head_json(
            {
                "type": "play_audio_begin",
                "session_id": session_id,
                "sample_rate_hz": self.format.sample_rate_hz,
                "channels": self.format.channels,
                "encoding": self.format.encoding,
                "bytes": len(pcm),
            }
        )
        for offset in range(0, len(pcm), self._play_chunk_bytes):
            ok = await self._send_head_bytes(pcm[offset : offset + self._play_chunk_bytes])
            if not ok:
                raise ProviderError("head_offline", "CoreS3 is not connected for audio playback.", retryable=True)
            await asyncio.sleep(0)
        await self._send_head_json({"type": "play_audio_end", "session_id": session_id})
