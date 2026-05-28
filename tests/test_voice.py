import stat
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from luma.brain.llm import fallback_decision
from luma.brain.local_audio import AudioConversionError, read_wav_as_pcm16_mono, write_pcm16_wav
from luma.brain.memory import MemoryStore
from luma.brain.state import LumaState
from luma.brain.voice import (
    AudioBuffer,
    AudioFormat,
    LazySTTProvider,
    LazyTTSProvider,
    LocalSherpaSTTProvider,
    LocalSherpaTTSProvider,
    ProviderError,
    VoiceSessionRuntime,
    make_stt_provider,
    make_tts_provider,
    _parse_sherpa_transcript,
)


class FakeSTTProvider:
    async def transcribe(self, audio: AudioBuffer) -> str:
        self.last_audio = audio
        return "你好 Luma"


class EmptySTTProvider:
    async def transcribe(self, audio: AudioBuffer) -> str:
        self.last_audio = audio
        return ""


class FakeLLMProvider:
    async def decide(self, messages):
        self.last_messages = messages
        return fallback_decision("你回来了。", emotion="happy", tone="warm", pet_behavior="greet")


class FailingLLMProvider:
    async def decide(self, messages):
        raise AssertionError("LLM should not run for empty speech")


class FakeTTSProvider:
    async def synthesize(self, text: str) -> bytes:
        self.last_text = text
        return b"\x00\x01" * 1600


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = MemoryStore(root / "state.sqlite3", root / "events.jsonl")
        self.state = LumaState()
        self.sent_json = []
        self.sent_bytes = []
        self.broadcasts = []

    async def asyncTearDown(self):
        self.memory.close()
        self.tmp.cleanup()

    async def send_json(self, message):
        self.sent_json.append(message)
        return True

    async def send_bytes(self, payload):
        self.sent_bytes.append(payload)
        return True

    async def broadcast_state(self, reason):
        self.broadcasts.append(reason)

    def make_runtime(self):
        return VoiceSessionRuntime(
            self.state,
            self.memory,
            self.send_json,
            self.send_bytes,
            self.broadcast_state,
            stt_provider=FakeSTTProvider(),
            llm_provider=FakeLLMProvider(),
            tts_provider=FakeTTSProvider(),
        )

    def test_default_runtime_defers_local_provider_validation(self):
        runtime = VoiceSessionRuntime(
            self.state,
            self.memory,
            self.send_json,
            self.send_bytes,
            self.broadcast_state,
        )
        self.assertIsInstance(runtime.stt_provider, LazySTTProvider)
        self.assertIsInstance(runtime.tts_provider, LazyTTSProvider)

    async def test_audio_session_runs_stt_llm_tts_and_streams_pcm(self):
        runtime = self.make_runtime()
        session_id = await runtime.start(source="test")
        await runtime.begin_audio({"type": "audio_begin", "session_id": session_id})
        await runtime.accept_audio_chunk(b"\x00\x00" * 2400)
        await runtime.end_audio({"type": "audio_end", "session_id": session_id})
        await runtime._processing_task

        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["voice"]["phase"], "speaking")
        self.assertEqual(snapshot["voice"]["transcript"], "你好 Luma")
        self.assertEqual(snapshot["voice"]["reply"], "你回来了。")
        self.assertTrue(any(message["type"] == "play_audio_begin" for message in self.sent_json))
        self.assertTrue(any(message["type"] == "play_audio_end" for message in self.sent_json))
        self.assertGreater(sum(len(chunk) for chunk in self.sent_bytes), 0)

        await runtime.playback_done({"type": "playback_done", "session_id": session_id})
        self.assertEqual(self.state.snapshot()["voice"]["phase"], "idle")

    async def test_empty_audio_sets_retryable_error(self):
        runtime = self.make_runtime()
        await runtime.start(source="test")
        await runtime.end_audio({"type": "audio_end"})

        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["voice"]["phase"], "error")
        self.assertEqual(snapshot["voice"]["error"]["code"], "empty_audio")

    async def test_empty_transcript_does_not_call_llm_or_tts(self):
        runtime = VoiceSessionRuntime(
            self.state,
            self.memory,
            self.send_json,
            self.send_bytes,
            self.broadcast_state,
            stt_provider=EmptySTTProvider(),
            llm_provider=FailingLLMProvider(),
            tts_provider=FakeTTSProvider(),
        )
        session_id = await runtime.start(source="test")
        await runtime.begin_audio({"type": "audio_begin", "session_id": session_id})
        await runtime.accept_audio_chunk(b"\x00\x00" * 2400)
        await runtime.end_audio({"type": "audio_end", "session_id": session_id})
        await runtime._processing_task

        self.assertEqual(self.state.snapshot()["voice"]["phase"], "idle")
        self.assertFalse(self.sent_bytes)
        self.assertTrue(any(message["type"] == "cancel_session" and message["reason"] == "no_speech" for message in self.sent_json))

    def test_pcm_buffer_can_be_wrapped_as_wav(self):
        audio = AudioBuffer(pcm=b"\x00\x00" * 240, format=AudioFormat(sample_rate_hz=24000, channels=1))
        wav = audio.to_wav_bytes()
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:16])

    def test_empty_sherpa_json_does_not_become_transcript(self):
        output = '{ "text": "", "tokens": [], "is_final": false }'
        self.assertEqual(_parse_sherpa_transcript(output), "")


class LocalSpeechProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.asr_model_dir = self.root / "asr"
        self.tts_model_dir = self.root / "tts"
        self.asr_model_dir.mkdir()
        self.tts_model_dir.mkdir()
        for path in [
            self.asr_model_dir / "tokens.txt",
            self.asr_model_dir / "encoder.int8.onnx",
            self.asr_model_dir / "decoder.int8.onnx",
            self.tts_model_dir / "tokens.txt",
            self.tts_model_dir / "lexicon.txt",
            self.tts_model_dir / "encoder.int8.onnx",
            self.tts_model_dir / "decoder.int8.onnx",
        ]:
            path.write_text("fake", encoding="utf-8")
        (self.tts_model_dir / "espeak-ng-data").mkdir()
        self.vocoder = self.root / "vocos_24khz.onnx"
        self.vocoder.write_text("fake", encoding="utf-8")
        self.reference_audio = self.root / "reference.wav"
        write_pcm16_wav(self.reference_audio, b"\x00\x00" * 80, sample_rate_hz=16000, channels=1)
        self.asr_bin = self._write_executable(
            "fake_asr.py",
            """
import json
print(json.dumps({"text": "你好本地", "tokens": ["你", "好"]}, ensure_ascii=False))
""",
        )
        self.tts_bin = self._write_executable(
            "fake_tts.py",
            """
import math
import struct
import sys
import wave
out = None
for arg in sys.argv[1:]:
    if arg.startswith("--output-filename="):
        out = arg.split("=", 1)[1]
if out is None:
    raise SystemExit(2)
with wave.open(out, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    frames = bytearray()
    for index in range(160):
        sample = int(math.sin(index / 8) * 16000)
        frames.extend(struct.pack("<h", sample))
    wav.writeframes(bytes(frames))
""",
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def _config(self, **overrides):
        values = {
            "stt_provider": "local_sherpa",
            "tts_provider": "local_sherpa",
            "sherpa_root": None,
            "sherpa_asr_bin": self.asr_bin,
            "sherpa_asr_model_dir": self.asr_model_dir,
            "sherpa_tts_bin": self.tts_bin,
            "sherpa_tts_model_dir": self.tts_model_dir,
            "sherpa_tts_engine": "zipvoice",
            "sherpa_tts_vocoder": self.vocoder,
            "tts_reference_audio": self.reference_audio,
            "tts_reference_text": "测试参考音频。",
            "stt_timeout_seconds": 5,
            "tts_timeout_seconds": 5,
            "voice_sample_rate_hz": 24000,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _write_executable(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text("#!/usr/bin/env python3\n" + body.lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_provider_factories_default_to_local_sherpa(self):
        self.assertIsInstance(make_stt_provider(self._config()), LocalSherpaSTTProvider)
        self.assertIsInstance(make_tts_provider(self._config()), LocalSherpaTTSProvider)

    def test_missing_local_stt_binary_fails_without_openai_fallback(self):
        with self.assertRaises(ProviderError) as caught:
            make_stt_provider(self._config(sherpa_asr_bin=self.root / "missing-asr"))
        self.assertEqual(caught.exception.code, "stt_provider_unconfigured")
        self.assertFalse(caught.exception.retryable)

    def test_missing_local_tts_model_fails_without_openai_fallback(self):
        empty_model_dir = self.root / "empty-tts"
        empty_model_dir.mkdir()
        with self.assertRaises(ProviderError) as caught:
            make_tts_provider(self._config(sherpa_tts_model_dir=empty_model_dir))
        self.assertEqual(caught.exception.code, "tts_provider_unconfigured")
        self.assertFalse(caught.exception.retryable)

    async def test_local_sherpa_stt_runs_subprocess_and_parses_json(self):
        provider = LocalSherpaSTTProvider(self._config())
        audio = AudioBuffer(pcm=b"\x00\x00" * 240, format=AudioFormat(sample_rate_hz=24000, channels=1))
        self.assertEqual(await provider.transcribe(audio), "你好本地")

    async def test_local_sherpa_tts_runs_subprocess_and_returns_24khz_pcm(self):
        provider = LocalSherpaTTSProvider(self._config())
        pcm = await provider.synthesize("你好。")
        self.assertEqual(len(pcm), 480)
        self.assertNotEqual(pcm, b"\x00" * len(pcm))


class LocalAudioConversionTests(unittest.TestCase):
    def test_wav_to_pcm16_mono_resamples(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "stereo.wav"
            stereo = bytearray()
            for index in range(100):
                stereo.extend(struct.pack("<h", index * 10))
                stereo.extend(struct.pack("<h", -index * 10))
            write_pcm16_wav(wav_path, bytes(stereo), sample_rate_hz=12000, channels=2)
            pcm = read_wav_as_pcm16_mono(wav_path, target_sample_rate_hz=24000)
        self.assertEqual(len(pcm), 400)

    def test_bad_wav_raises_conversion_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "bad.wav"
            wav_path.write_bytes(b"not a wav")
            with self.assertRaises(AudioConversionError):
                read_wav_as_pcm16_mono(wav_path, target_sample_rate_hz=24000)


if __name__ == "__main__":
    unittest.main()
