/*
 * SPDX-FileCopyrightText: 2024-2026 78 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include <cstdint>
#include <esp_timer.h>

class Backlight {
public:
    Backlight();
    virtual ~Backlight();

    void RestoreBrightness();
    void SetBrightness(uint8_t brightness, bool permanent = false);
    uint8_t brightness() const { return brightness_; }

protected:
    void OnTransitionTimer();
    virtual void SetBrightnessImpl(uint8_t brightness) = 0;

    esp_timer_handle_t transition_timer_ = nullptr;
    uint8_t brightness_ = 0;
    uint8_t target_brightness_ = 0;
    int8_t step_ = 1;
};
