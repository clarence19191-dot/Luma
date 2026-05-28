/*
 * SPDX-FileCopyrightText: 2024-2026 78 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include "luma_platform/i2c_device.h"

class Axp2101 : public I2cDevice {
public:
    Axp2101(i2c_master_bus_handle_t i2c_bus, uint8_t addr);

    bool IsCharging();
    bool IsDischarging();
    bool IsChargingDone();
    int GetBatteryLevel();
    float GetTemperature();
    void PowerOff();

private:
    int GetBatteryCurrentDirection();
};
