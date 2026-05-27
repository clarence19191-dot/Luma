# Luma V0 Hardware Notes

## CoreS3 Role

CoreS3 is the realtime voice terminal. It owns:

- LVGL face and simple status text.
- Wake-word entry and touch fallback.
- Microphone capture.
- Speaker playback.
- Safety cancel/stop behavior.

CoreS3 does not run STT, LLM, or TTS in V0. Mac runs those providers now; Raspberry Pi should be able to run the same Brain service later.

## Voice Loop

Default loop:

1. CoreS3 detects "你好 Luma" or receives a touch release.
2. CoreS3 sends `wake_detected`, then `audio_begin`.
3. CoreS3 streams 24 kHz PCM16 mono binary chunks, 40 ms per chunk.
4. CoreS3 sends `audio_end`.
5. Brain runs STT -> LLM -> TTS.
6. Brain sends `play_audio_begin`, PCM16 mono chunks, then `play_audio_end`.
7. CoreS3 plays audio on the local speaker and sends `playback_done`.

## ESP32-S3 Limits

V0 performance rules:

- Do not cache a whole recording on CoreS3.
- Keep only the current capture chunk and at most five playback chunks.
- Capture and playback are mutually exclusive.
- Max utterance length is 8 seconds.
- Silence after speech stops capture after about 1.2 seconds.
- Camera snapshots, GIF overlays, and servo tasks are out of the voice-loop path.

The current CoreS3 board config uses 24 kHz input/output audio. With 16-bit mono PCM, each 40 ms chunk is about 1.9 KB.

## Wake Word

`sdkconfig.defaults` is set for ESP32-S3 + PSRAM, Chinese language, audio processor enabled, and a custom wake phrase:

```text
CONFIG_USE_CUSTOM_WAKE_WORD=y
CONFIG_CUSTOM_WAKE_WORD="ni hao lu ma"
CONFIG_CUSTOM_WAKE_WORD_DISPLAY="你好 Luma"
```

The firmware has the V0 wake entry point and touch fallback. ESP-SR model accuracy and exact callback wiring must be validated after the ESP-IDF dependencies are fetched and the firmware is built on hardware.

## Servos

Servo2/PCA9685 is excluded from this V0:

- `AppLuma` does not initialize `Servo2PanTilt`.
- Head capability does not advertise `motion.pan_tilt`.
- The web console does not show pan/tilt controls.
- `move_head` returns `unsupported_capability` from Brain and command failure from firmware.

Servo files remain in the repository for the later hardware pass.

## Bring-Up Checklist

- Set `OPENAI_API_KEY` and start Brain on the Mac.
- Configure CoreS3 Wi-Fi and `brain_ws_url`.
- Confirm `/ws/head` connects and reports `audio.capture_pcm` and `audio.playback_pcm`.
- Tap the head to trigger the touch fallback wake.
- Confirm Brain logs `wake_detected`, `audio_begin`, binary audio bytes, and `audio_end`.
- Confirm transcript, reply, TTS bytes, CoreS3 playback, and `playback_done`.
- Run a 30 minute loop of repeated wake/cancel/playback without CoreS3 reset.
