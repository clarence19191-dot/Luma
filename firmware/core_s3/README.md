# Luma CoreS3 Firmware

This folder contains Project Luma's standalone CoreS3 firmware application code. Build it from this directory with PlatformIO:

```bash
pio run
```

The qgif expression path is runtime-streamed from Brain:

- Brain sends `qgif_begin`.
- Brain streams qgif bytes as WebSocket binary frames.
- Brain sends `qgif_end`.
- Brain sends the semantic `set_emotion` command with the streamed `asset` name.

CoreS3 keeps only the current streamed qgif in RAM and renders it into a 320x240 RGB565 LVGL image buffer. It does not require bundling the full expression library into firmware assets.

## Local Network Configuration

Luma can preload WiFi and Brain endpoint settings from a private `secrets.h` file:

```bash
cp include/secrets.example.h include/secrets.h
```

Edit `secrets.h`:

```cpp
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"
#define MAC_HOST "192.168.x.x"
#define MAC_PORT 8787
```

`secrets.h` is ignored by git. `MAC_HOST` should be the LAN IP of the Mac running Brain. `MAC_PORT` must match `LUMA_PORT`, which defaults to `8787`.

On boot, the Luma app connects to WiFi and opens:

```text
ws://<MAC_HOST>:<MAC_PORT>/ws/head?device_id=luma-core-s3&role=device
```

Touch wake is wired through the CoreS3 head-touch gesture. Wake-word support is disabled in the lean default build unless custom model assets are explicitly added later.
