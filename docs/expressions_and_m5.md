# Expressions And M5 Library Notes

## V0 Expression Catalog

Brain exposes the shared catalog at:

```text
GET /api/emotions
```

The catalog maps semantic emotion names to the prepared `.qgif` assets in the project `gif/` folder. Brain exposes every qgif asset and streams the requested one to CoreS3 on demand. The browser console uses the paired `.gif` files for preview.

Core V0 mapping:

| Emotion | qgif asset | Firmware fallback |
| --- | --- | --- |
| idle | sys_idle.qgif | Neutral |
| listening | eye_peek.qgif | Doubt |
| thinking | effect_rotate.qgif | Doubt |
| speaking | Hello.qgif | Happy |
| happy | emotion_happy.qgif | Happy |
| smile | emotion_smile.qgif | Happy |
| surprised | emotion_surprised.qgif | Doubt |
| relaxed | emotion_relaxed.qgif | Sleepy |
| uwu | emotion_uwu.qgif | Happy |
| love | emotion_love_01.qgif | Happy |
| smirk | emotion_smirk.qgif | Happy |
| angry | emotion_angry_04.qgif | Angry |
| angry_fire | emotion_angry_fire.qgif | Angry |
| scared | emotion_scared.qgif | Sad |
| frustrated | emotion_frustrated.qgif | Angry |
| distracted | emotion_distracted.qgif | Doubt |
| dizzy | emotion_dizzy.qgif | Sad |
| cry | cry.qgif | Sad |
| devil | devil_eyes.qgif | Angry |
| sleepy | action_sleepy.qgif | Sleepy |
| yawn | action_yawn.qgif | Sleepy |
| wink | eye_wink.qgif | Happy |
| peek | eye_peek.qgif | Doubt |
| squint | eye_squint.qgif | Doubt |
| look_left | eye_look_left.qgif | Doubt |
| look_right | eye_look_right.qgif | Doubt |

## qgif Runtime Direction

Each expression asset should have a normal browser preview GIF and a qgif binary with the same stem:

```text
gif/theme_bee.gif
gif/theme_bee.qgif
```

Brain sends qgif files to CoreS3 over the existing `/ws/head` connection:

- `qgif_begin` JSON with `emotion`, `asset`, `bytes`, and `duration_ms`.
- qgif binary chunks.
- `qgif_end` JSON.
- `set_emotion` JSON with the same `asset` name.

CoreS3 stores only the current qgif in RAM and renders it into a 320x240 LVGL image buffer. The full expression library is not stored in firmware.

## M5Unified / M5GFX Assessment

Current firmware does not use M5Unified or M5GFX directly. The V0 app code under `firmware/core_s3/` is currently designed as a small overlay for the StackChan/xiaozhi ESP-IDF stack:

- `Board::GetInstance().GetAudioCodec()` for CoreS3 audio.
- LVGL + StackChan avatar primitives for display.
- HAL signals for touch, Wi-Fi, audio tests, and device state.

M5Unified is useful and official, but it should not be introduced into this V0 stack as a broad replacement yet:

- It would duplicate display, touch, microphone, speaker, power, and IMU initialization that the current board/HAL layer already owns.
- V0's highest-risk path is real-time audio. Replacing the HAL now increases bring-up risk without improving the Brain protocol.
- M5Unified can be evaluated later for a thinner firmware rewrite if we decide to move away from StackChan/xiaozhi internals.

Recommended near-term use: do not migrate this V0 firmware to M5Unified. Borrow examples and pin maps when needed, but keep the current HAL as the owner of hardware resources until the voice loop is stable on CoreS3.
