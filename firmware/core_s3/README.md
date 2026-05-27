# Luma CoreS3 Firmware

This folder contains Project Luma's own CoreS3 firmware application code.

`StackChan/` at the repository root is only a reference checkout. Do not develop Luma code inside it. Until the firmware becomes a fully standalone ESP-IDF project, integrate this app into a clean StackChan firmware checkout as an overlay:

1. Copy `main/apps/app_luma/` into the target firmware's `main/apps/`.
2. Add `#include "app_luma/app_luma.h"` to the target `main/apps/apps.h`.
3. Install `AppLuma` from the target `main/main.cpp`.
4. Apply the Luma sdkconfig values from `sdkconfig.luma.defaults`.

The qgif expression path is runtime-streamed from Brain:

- Brain sends `qgif_begin`.
- Brain streams qgif bytes as WebSocket binary frames.
- Brain sends `qgif_end`.
- Brain sends the semantic `set_emotion` command with the streamed `asset` name.

CoreS3 keeps only the current streamed qgif in RAM and renders it into a 320x240 RGB565 LVGL image buffer. It does not require bundling the full expression library into firmware assets.
