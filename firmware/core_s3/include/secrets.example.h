#pragma once

// Copy this file to include/secrets.h and adjust the values for your LAN.
// include/secrets.h is intentionally ignored by git.

#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"

// Use the LAN IP of the Mac running `python3 -m luma.brain`.
// The default Brain port is 8787 unless LUMA_PORT is changed.
#define MAC_HOST "192.168.x.x"
#define MAC_PORT 8787

// Optional full override. If set, it takes priority over MAC_HOST/MAC_PORT.
// #define LUMA_BRAIN_WS_URL "ws://192.168.x.x:8787/ws/head?device_id=luma-core-s3&role=device"
