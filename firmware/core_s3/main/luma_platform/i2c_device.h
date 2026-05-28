/*
 * SPDX-FileCopyrightText: 2024-2026 78 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include <driver/i2c_master.h>

class I2cDevice {
public:
    I2cDevice(i2c_master_bus_handle_t i2c_bus, uint8_t addr);

protected:
    i2c_master_dev_handle_t i2c_device_ = nullptr;

    void WriteReg(uint8_t reg, uint8_t value);
    uint8_t ReadReg(uint8_t reg);
    void ReadRegs(uint8_t reg, uint8_t* buffer, size_t length);
    esp_err_t TryReadRegs(uint8_t reg, uint8_t* buffer, size_t length, int timeout_ms = 100);
};
