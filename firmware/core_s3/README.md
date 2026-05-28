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

## Local Network Configuration

Luma can preload WiFi and Brain endpoint settings from a private `secrets.h` file:

```bash
cp main/apps/app_luma/secrets.example.h main/apps/app_luma/secrets.h
```

Edit `secrets.h`:

```cpp
#define WIFI_SSID "Xiaomi 14"
#define WIFI_PASS "123456789"
#define MAC_HOST "192.168.31.10"
#define MAC_PORT 8787
```

`secrets.h` is ignored by git. `MAC_HOST` should be the LAN IP of the Mac running Brain. `MAC_PORT` must match `LUMA_PORT`, which defaults to `8787`.

On boot, the Luma app shows the default `sys_idle.qgif` expression, preloads the WiFi credential into the StackChan/Xiaozhi-compatible SSID store when `secrets.h` exists, connects to WiFi, and then opens:

```text
ws://<MAC_HOST>:<MAC_PORT>/ws/head?device_id=luma-core-s3&role=device
```

Touch wake is always wired through the CoreS3 head-touch gesture. Wake-word support uses the existing ESP-SR custom wake-word config in `sdkconfig.luma.defaults` (`ni hao lu ma` / `你好 Luma`) when the target firmware includes the required model assets; if model initialization fails, touch wake remains available.
