/*
 * SPDX-FileCopyrightText: 2026 Project Luma contributors
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "luma_platform/backlight.h"
#include "luma_platform/display.h"
#include "luma_platform/net/network.h"

#include <driver/i2c_master.h>

#include <functional>
#include <string>

class AudioCodec;

enum class PowerSaveLevel {
    LOW_POWER,
    BALANCED,
    PERFORMANCE,
};

class Board {
public:
    static Board& GetInstance();
    virtual ~Board() = default;

    virtual std::string GetBoardType() = 0;
    virtual std::string GetUuid() = 0;
    virtual Backlight* GetBacklight() = 0;
    virtual AudioCodec* GetAudioCodec() = 0;
    virtual Display* GetDisplay() = 0;
    virtual LumaNetwork* GetNetwork() = 0;
    virtual void StartNetwork() = 0;
    virtual void SetNetworkEventCallback(NetworkEventCallback callback) = 0;
    virtual const char* GetNetworkStateIcon() = 0;
    virtual bool GetBatteryLevel(int& level, bool& charging, bool& discharging) = 0;
    virtual void SetPowerSaveLevel(PowerSaveLevel level) = 0;
    virtual i2c_master_bus_handle_t GetI2cBus() = 0;
    virtual void SetWifiCredentials(std::string ssid, std::string password) = 0;

protected:
    Board();
    std::string GenerateUuid();

    std::string uuid_;
};
