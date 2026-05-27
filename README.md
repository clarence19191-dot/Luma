# Project Luma V0

Project Luma V0 is now a voice-loop CoreS3 robot terminal:

- CoreS3 Head: expression display, wake/touch trigger, microphone PCM capture, speaker PCM playback, device safety.
- Luma Brain: Python FastAPI, WebSocket, SQLite logs, voice session runtime, desktop-pet personality, conversation boundary, relationship memory, OpenAI-compatible STT/LLM/TTS providers, web console.
- Browser simulator: development-only head device connected to the same `/ws/head` endpoint.

The Mac runs Brain during development. The same Brain process is designed to move to Raspberry Pi later without changing the CoreS3 wire protocol.

## Run The Brain

```bash
python3 -m pip install -r requirements.txt
export OPENAI_API_KEY=...
python3 -m luma.brain
```

Open `http://127.0.0.1:8787`. The page starts a browser simulator automatically.

Useful environment variables:

```text
LUMA_OPENAI_STT_MODEL=whisper-1
LUMA_LLM_BASE_URL=https://api.openai.com/v1
LUMA_LLM_MODEL=gpt-4o-mini
LUMA_LLM_API_KEY=...
LUMA_LLM_JSON_MODE=1
LUMA_OPENAI_TTS_MODEL=tts-1
LUMA_OPENAI_TTS_VOICE=alloy
LUMA_VOICE_SAMPLE_RATE_HZ=24000
LUMA_VOICE_CHUNK_MS=40
LUMA_VOICE_MAX_RECORD_SECONDS=8
```

For DeepSeek or another OpenAI-compatible provider, set `LUMA_LLM_BASE_URL`, `LUMA_LLM_MODEL`, and `LUMA_LLM_API_KEY`. STT/TTS still use `OPENAI_API_KEY` in the current V0 unless those providers are replaced later.

Local `.env.local` is loaded automatically by Brain and is ignored by git.

## Desktop Pet Brain

The LLM layer is intentionally constrained as a desktop pet. It outputs validated JSON with:

- short spoken reply text,
- tone,
- expression emotion,
- pet behavior tag,
- note-only action intent,
- cautious relationship memory candidates,
- safety/boundary metadata.

Brain decides whether an utterance continues the same conversation, resumes a recent one, or starts a new one. The decision uses time gap, topic overlap, pronoun bridges, explicit continuation/reset phrases, greeting-only wakeups, pending context, and emotional continuity. Long-gap wakeups default to a fresh “re-met” interaction instead of forcing old task context.

Relationship memories are SQLite rows, not a knowledge base. They are for stable preferences, disliked interaction styles, names, pets, habits, and emotional care cues. One-off tasks, work details, credentials, sensitive data, and generic knowledge are rejected.

## Voice Protocol

`/ws/head?device_id=luma-core-s3&role=device` carries JSON control messages plus binary PCM frames.

CoreS3 to Brain:

```json
{"type":"wake_detected","wake_phrase":"你好 Luma","source":"touch"}
{"type":"audio_begin","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le"}
```

Binary frames after `audio_begin` are 24 kHz, 16-bit, mono PCM chunks. CoreS3 closes the utterance with:

```json
{"type":"audio_end"}
{"type":"playback_done"}
```

Brain to CoreS3:

```json
{"type":"start_listening","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le"}
{"type":"play_audio_begin","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le","bytes":12345}
```

Binary frames after `play_audio_begin` are PCM reply audio for the CoreS3 speaker. Brain closes playback with:

```json
{"type":"play_audio_end"}
```

## HTTP API

```bash
curl -X POST http://127.0.0.1:8787/api/voice/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"你回来了。"}'

curl -X POST http://127.0.0.1:8787/api/voice/wake \
  -H 'Content-Type: application/json' \
  -d '{"source":"console","wake_phrase":"你好 Luma"}'

curl http://127.0.0.1:8787/api/conversation
curl http://127.0.0.1:8787/api/memories
curl http://127.0.0.1:8787/api/debug/prompt
```

The old `/api/command` path remains for expression, stop, and compatibility commands. `move_head` is intentionally disabled in this V0 because the servos are not connected.

## Firmware

Luma's CoreS3 firmware code lives under `firmware/core_s3/`. `StackChan/` is kept only as a local reference checkout and is ignored by git.

Current V0 firmware behavior:

- Text and binary WebSocket client to `/ws/head`.
- LVGL face expression display.
- Runtime-streamed qgif expression playback with 320x240 contain scaling.
- Touch fallback wake trigger.
- 24 kHz PCM16 mono microphone upload in 40 ms chunks.
- 24 kHz PCM16 mono speaker playback from Brain.
- Expanded semantic expression catalog with qgif asset metadata.
- No Servo2/PCA9685 initialization in this build.

Brain streams the requested qgif asset on demand. CoreS3 keeps only the current streamed qgif in RAM, scales each 1-bit frame into a 320x240 RGB565 buffer, and presents it through LVGL. If no streamed qgif is available, firmware falls back to the LVGL StackChan face.

ESP-SR configuration values for the Chinese custom wake phrase are in `firmware/core_s3/sdkconfig.luma.defaults`. Final wake-word accuracy needs ESP-IDF dependencies fetched and hardware calibration on the CoreS3.

Expression mapping and the M5Unified/M5GFX assessment are documented in `docs/expressions_and_m5.md`.

Default Brain URL:

```text
ws://192.168.1.100:8787/ws/head?device_id=luma-core-s3&role=device
```

The firmware reads an override from NVS namespace `luma`, key `brain_ws_url`.

## Tests

```bash
python3 -m unittest discover -s tests
```

With dev dependencies installed:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```
