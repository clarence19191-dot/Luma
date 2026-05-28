/*
 * Project Luma local firmware configuration.
 *
 * Copy include/secrets.example.h to include/secrets.h for a private build.
 */
#pragma once

#include <string>

#if __has_include("secrets.h")
#include "secrets.h"
#define LUMA_HAS_SECRETS_FILE 1
#elif __has_include(<secrets.h>)
#include <secrets.h>
#define LUMA_HAS_SECRETS_FILE 1
#else
#define LUMA_HAS_SECRETS_FILE 0
#endif

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif

#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif

#ifndef MAC_HOST
#define MAC_HOST ""
#endif

#ifndef MAC_PORT
#define MAC_PORT 8787
#endif

namespace luma::config {

inline constexpr bool hasSecretsFile()
{
    return LUMA_HAS_SECRETS_FILE != 0;
}

inline constexpr const char* wifiSsid()
{
    return WIFI_SSID;
}

inline constexpr const char* wifiPass()
{
    return WIFI_PASS;
}

inline bool hasWifiCredentials()
{
    return wifiSsid()[0] != '\0';
}

inline constexpr const char* brainHost()
{
    return MAC_HOST;
}

inline constexpr int brainPort()
{
    return MAC_PORT;
}

inline bool hasBrainHost()
{
    return brainHost()[0] != '\0';
}

inline std::string brainWsUrl()
{
#ifdef LUMA_BRAIN_WS_URL
    std::string explicit_url = LUMA_BRAIN_WS_URL;
    if (!explicit_url.empty()) {
        return explicit_url;
    }
#endif
    if (!hasBrainHost()) {
        return {};
    }
    return std::string("ws://") + brainHost() + ":" + std::to_string(brainPort()) +
           "/ws/head?device_id=luma-core-s3&role=device";
}

}  // namespace luma::config
