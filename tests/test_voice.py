import tempfile
import unittest
from pathlib import Path

from luma.brain.llm import fallback_decision
from luma.brain.memory import MemoryStore
from luma.brain.state import LumaState
from luma.brain.voice import AudioBuffer, AudioFormat, VoiceSessionRuntime


class FakeSTTProvider:
    async def transcribe(self, audio: AudioBuffer) -> str:
        self.last_audio = audio
        return "你好 Luma"


class FakeLLMProvider:
    async def decide(self, messages):
        self.last_messages = messages
        return fallback_decision("你回来了。", emotion="happy", tone="warm", pet_behavior="greet")


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

    def test_pcm_buffer_can_be_wrapped_as_wav(self):
        audio = AudioBuffer(pcm=b"\x00\x00" * 240, format=AudioFormat(sample_rate_hz=24000, channels=1))
        wav = audio.to_wav_bytes()
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:16])


if __name__ == "__main__":
    unittest.main()
