/*
 * SPDX-FileCopyrightText: 2024-2026 78 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include "luma_platform/backlight.h"

#include "luma_platform/settings.h"

#include <esp_log.h>

namespace {
constexpr const char* TAG = "Backlight";
}

Backlight::Backlight()
{
    const esp_timer_create_args_t timer_args = {
        .callback = [](void* arg) { static_cast<Backlight*>(arg)->OnTransitionTimer(); },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "backlight_timer",
        .skip_unhandled_events = true,
    };
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &transition_timer_));
}

Backlight::~Backlight()
{
    if (transition_timer_ != nullptr) {
        esp_timer_stop(transition_timer_);
        esp_timer_delete(transition_timer_);
    }
}

void Backlight::RestoreBrightness()
{
    Settings settings("display", false);
    int saved_brightness = settings.GetInt("brightness", 75);
    if (saved_brightness <= 0) {
        ESP_LOGW(TAG, "Brightness value (%d) is too small, setting to default (10)", saved_brightness);
        saved_brightness = 10;
    }
    SetBrightness(static_cast<uint8_t>(saved_brightness));
}

void Backlight::SetBrightness(uint8_t brightness, bool permanent)
{
    if (brightness > 100) {
        brightness = 100;
    }
    if (brightness_ == brightness) {
        return;
    }

    if (permanent) {
        Settings settings("display", true);
        settings.SetInt("brightness", brightness);
    }

    target_brightness_ = brightness;
    step_ = target_brightness_ > brightness_ ? 1 : -1;
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_timer_stop(transition_timer_));
    ESP_ERROR_CHECK(esp_timer_start_periodic(transition_timer_, 5 * 1000));
}

void Backlight::OnTransitionTimer()
{
    if (brightness_ == target_brightness_) {
        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_timer_stop(transition_timer_));
        return;
    }

    brightness_ = static_cast<uint8_t>(brightness_ + step_);
    SetBrightnessImpl(brightness_);

    if (brightness_ == target_brightness_) {
        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_timer_stop(transition_timer_));
    }
}
