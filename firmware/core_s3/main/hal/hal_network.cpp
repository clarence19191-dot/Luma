/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "hal.h"
#include <luma_platform/board.h>
#include <mooncake_log.h>
#include <mutex>
#include <queue>
#include <vector>
#include <ctime>
#include <sys/time.h>
#include <esp_sntp.h>
#include <atomic>

static std::string _tag           = "Network";
static bool _is_network_connected = false;

static void time_sync_notification_cb(struct timeval* tv)
{
    mclog::tagInfo(_tag, "SNTP time synchronized");
    GetHAL().syncSystemTimeToRtc();
}

void Hal::startSntp()
{
    mclog::tagInfo(_tag, "SNTP init");

    if (esp_sntp_enabled()) {
    } else {
        esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);

        esp_sntp_setservername(0, "pool.ntp.org");
        esp_sntp_setservername(1, "time.google.com");
        esp_sntp_setservername(2, "cn.pool.ntp.org");

        sntp_set_time_sync_notification_cb(time_sync_notification_cb);

        esp_sntp_init();
    }
}

void Hal::startNetwork(std::function<void(std::string_view)> onLog)
{
    if (_is_network_connected) {
        mclog::tagInfo(_tag, "network already connected");
        return;
    }

    std::atomic<bool> wait_done = false;
    std::atomic<bool> network_connected = false;

    auto& board = Board::GetInstance();
    mclog::tagInfo(_tag, "start and wait for network connected...");

    board.SetNetworkEventCallback([&wait_done, &network_connected, &onLog](NetworkEvent event, const std::string& data) {
        switch (event) {
            case NetworkEvent::Scanning:
                if (onLog) {
                    onLog("WiFi scanning...");
                }
                break;
            case NetworkEvent::Connecting: {
                if (data.empty()) {
                    if (onLog) {
                        onLog("WiFi connecting...");
                    }
                } else {
                    if (onLog) {
                        onLog(fmt::format("Connecting to {} ...", data));
                    }
                }
                break;
            }
            case NetworkEvent::Connected: {
                network_connected = true;
                wait_done = true;
                break;
            }
            case NetworkEvent::Disconnected:
                break;
            case NetworkEvent::WifiConfigModeEnter: {
                if (onLog) {
                    onLog("WiFi credentials required");
                }
                wait_done = true;
                break;
            }
            case NetworkEvent::WifiConfigModeExit:
                break;
        }
    });
    board.StartNetwork();

    while (!wait_done) {
        GetHAL().delay(500);
    }
    board.SetNetworkEventCallback(nullptr);

    if (network_connected) {
        mclog::tagInfo(_tag, "network connected");
        startSntp();
    }

    _is_network_connected = network_connected;
}

WifiStatus Hal::getWifiStatus()
{
    auto* network = Board::GetInstance().GetNetwork();

    if (network->IsConfigMode() || !network->IsConnected()) {
        return WifiStatus::None;
    }

    int rssi = network->GetRssi();
    if (rssi >= -65) {
        return WifiStatus::High;
    } else if (rssi >= -75) {
        return WifiStatus::Medium;
    }
    return WifiStatus::Low;
}
