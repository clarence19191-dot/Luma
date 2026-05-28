/*
 * SPDX-FileCopyrightText: 2026 Project Luma contributors
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "luma_platform/net/web_socket.h"

#include <esp_wifi_types.h>

#include <functional>
#include <memory>
#include <string>

enum class NetworkEvent {
    Scanning,
    Connecting,
    Connected,
    Disconnected,
    WifiConfigModeEnter,
    WifiConfigModeExit,
};

using NetworkEventCallback = std::function<void(NetworkEvent event, const std::string& data)>;

class LumaNetwork {
public:
    LumaNetwork();

    void SetEventCallback(NetworkEventCallback callback);
    void SetCredentials(std::string ssid, std::string password);
    void Start();
    bool IsConnected() const;
    bool IsConfigMode() const;
    int GetRssi() const;
    std::string GetSsid() const;
    std::unique_ptr<WebSocket> CreateWebSocket(int connect_id = -1);

private:
    std::string ssid_;
    std::string password_;
    NetworkEventCallback callback_;
    bool initialized_ = false;
    bool connected_ = false;
    bool config_mode_ = false;
    int rssi_ = -127;

    void Initialize();
    void Emit(NetworkEvent event, const std::string& data = "");
    static void EventHandler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data);
};
