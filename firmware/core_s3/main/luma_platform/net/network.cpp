/*
 * SPDX-FileCopyrightText: 2026 Project Luma contributors
 *
 * SPDX-License-Identifier: MIT
 */
#include "luma_platform/net/network.h"

#include "luma_platform/settings.h"

#include <esp_event.h>
#include <esp_log.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#include <cstring>
#include <utility>

namespace {
constexpr const char* TAG = "LumaNetwork";
}

LumaNetwork::LumaNetwork() = default;

void LumaNetwork::SetEventCallback(NetworkEventCallback callback)
{
    callback_ = std::move(callback);
}

void LumaNetwork::SetCredentials(std::string ssid, std::string password)
{
    ssid_ = std::move(ssid);
    password_ = std::move(password);
}

void LumaNetwork::Start()
{
    Settings settings("wifi", false);
    if (ssid_.empty()) {
        ssid_ = settings.GetString("ssid");
        password_ = settings.GetString("password");
    }

    if (ssid_.empty()) {
        config_mode_ = true;
        Emit(NetworkEvent::WifiConfigModeEnter);
        ESP_LOGW(TAG, "no WiFi credentials configured");
        return;
    }

    Initialize();

    wifi_config_t wifi_config = {};
    strlcpy(reinterpret_cast<char*>(wifi_config.sta.ssid), ssid_.c_str(), sizeof(wifi_config.sta.ssid));
    strlcpy(reinterpret_cast<char*>(wifi_config.sta.password), password_.c_str(), sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    Emit(NetworkEvent::Connecting, ssid_);
    ESP_ERROR_CHECK(esp_wifi_connect());
}

bool LumaNetwork::IsConnected() const
{
    return connected_;
}

bool LumaNetwork::IsConfigMode() const
{
    return config_mode_;
}

int LumaNetwork::GetRssi() const
{
    return rssi_;
}

std::string LumaNetwork::GetSsid() const
{
    return ssid_;
}

std::unique_ptr<WebSocket> LumaNetwork::CreateWebSocket(int connect_id)
{
    (void)connect_id;
    return std::make_unique<WebSocket>();
}

void LumaNetwork::Initialize()
{
    if (initialized_) {
        return;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    esp_err_t err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_ERROR_CHECK(err);
    }
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &LumaNetwork::EventHandler, this, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &LumaNetwork::EventHandler, this, nullptr));
    initialized_ = true;
}

void LumaNetwork::Emit(NetworkEvent event, const std::string& data)
{
    if (callback_) {
        callback_(event, data);
    }
}

void LumaNetwork::EventHandler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data)
{
    auto* self = static_cast<LumaNetwork*>(arg);
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        self->connected_ = false;
        self->rssi_ = -127;
        self->Emit(NetworkEvent::Disconnected);
        ESP_LOGW(TAG, "WiFi disconnected, reconnecting");
        esp_wifi_connect();
        self->Emit(NetworkEvent::Connecting, self->ssid_);
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        self->connected_ = true;
        self->config_mode_ = false;
        wifi_ap_record_t ap_info = {};
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            self->rssi_ = ap_info.rssi;
        }
        self->Emit(NetworkEvent::Connected, self->ssid_);
        return;
    }

    (void)event_data;
}
