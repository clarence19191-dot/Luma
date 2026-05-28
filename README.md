# Project Luma V0

Chinese README: [README.zh-CN.md](README.zh-CN.md)

Project Luma is a CoreS3-based desktop pet prototype. The system is split into:

- **Brain**: a Python FastAPI service that runs the voice loop, WebSocket protocol, LLM decision layer, memory store, local STT/TTS adapters, and web console.
- **CoreS3 head**: firmware for expression playback, touch wake, microphone upload, speaker playback, and device-side safety handling.
- **Browser simulator**: a development head simulator connected to the same `/ws/head` endpoint.

## Quick Start

```bash
python3 -m pip install -r requirements.txt
python3 -m luma.brain
```

Open `http://127.0.0.1:8787` to use the web console and browser simulator.

Brain loads `.env.local` and `.env` from the working directory. `.env.local` is ignored by git.

Example `.env.local`:

```text
LUMA_STT_PROVIDER=local_sherpa
LUMA_TTS_PROVIDER=local_sherpa
LUMA_SHERPA_ROOT=./models/sherpa

LUMA_SHERPA_TTS_MODEL_DIR=./models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia
LUMA_SHERPA_TTS_VOCODER=./models/sherpa/vocos_24khz.onnx
LUMA_TTS_REFERENCE_AUDIO=./models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/test_wavs/leijun-1.wav
LUMA_TTS_REFERENCE_TEXT=reference voice text

LUMA_LLM_BASE_URL=https://api.openai.com/v1
LUMA_LLM_MODEL=gpt-4o-mini
LUMA_LLM_API_KEY=...
LUMA_LLM_JSON_MODE=1

LUMA_VOICE_SAMPLE_RATE_HZ=24000
LUMA_VOICE_CHUNK_MS=40
LUMA_VOICE_MAX_RECORD_SECONDS=8
```

## Local Speech

Local STT uses `sherpa-onnx`; local TTS uses `sherpa-onnx-offline-tts`. The runtime does not download model files automatically and does not silently fall back to cloud speech providers.

Expected ASR/runtime layout:

```text
models/sherpa/
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx-offline-tts
  sherpa-onnx/
    tokens.txt
    encoder.int8.onnx
    decoder.int8.onnx
```

Expected ZipVoice TTS layout:

```text
models/sherpa/
  sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/
    encoder.int8.onnx
    decoder.int8.onnx
    tokens.txt
    lexicon.txt
    espeak-ng-data/
    test_wavs/leijun-1.wav
  vocos_24khz.onnx
```

Generated TTS audio is converted to the CoreS3 playback format: 24 kHz, mono, PCM16.

## Brain Behavior

The realtime LLM decision is constrained to two outputs:

- spoken reply text,
- Luma expression emotion.

The expression is Luma's display state, not the user's emotion. The LLM chooses only the emotion name from the available expression catalog; playback duration is calculated by Brain from the local qgif/gif asset.

Memory reflection runs as a separate asynchronous LLM call after the reply is recorded. Memory rows are categorized as preferences, habits, short-term events, emotional patterns, behavior routines, or relationship context. Short-term memories can expire; long-term memories are reserved for stable interaction value. Credentials, sensitive data, and generic knowledge are rejected.

## Voice Protocol

`/ws/head?device_id=luma-core-s3&role=device` carries JSON control messages and binary PCM frames.

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

Binary frames after `play_audio_begin` are PCM reply audio. Brain closes playback with:

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

`/api/command` is available for expression, stop, and compatibility commands. `move_head` is disabled in this build because the servos are not connected.

## Firmware

CoreS3 firmware lives under `firmware/core_s3/`.

Firmware capabilities:

- WebSocket client for `/ws/head`.
- LVGL expression display.
- Runtime qgif expression streaming with 320x240 contain scaling.
- Touch wake trigger.
- 24 kHz PCM16 mono microphone upload in 40 ms chunks.
- 24 kHz PCM16 mono speaker playback from Brain.
- Semantic expression catalog with qgif asset metadata.

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
