/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "hal_bridge.h"

#include <luma_platform/audio_codec.h>
#include <luma_platform/board.h>
#include <luma_platform/display.h>
#include <luma_platform/settings.h>

#include <mutex>

namespace {

static constexpr std::string_view kConfigNvsNs = "luma";
static constexpr std::string_view kIdleShutdownTimeKey = "idle_sec";
static constexpr std::string_view kAllowShutdownWhenChargingKey = "ext_pwr";
static constexpr std::string_view kIdleRandomMovementKey = "idle_lv";

std::mutex bridge_mutex;
hal_bridge::Data_t bridge_data;

Display* display()
{
    return Board::GetInstance().GetDisplay();
}

}  // namespace

namespace hal_bridge {

void lock()
{
    bridge_mutex.lock();
}

void unlock()
{
    bridge_mutex.unlock();
}

Data_t& get_data()
{
    return bridge_data;
}

void set_touch_point(int num, int x, int y)
{
    std::lock_guard<std::mutex> lock(bridge_mutex);
    bridge_data.touchPoint.num = num;
    bridge_data.touchPoint.x = x;
    bridge_data.touchPoint.y = y;
}

TouchPoint_t get_touch_point()
{
    std::lock_guard<std::mutex> lock(bridge_mutex);
    return bridge_data.touchPoint;
}

bool is_xiaozhi_mode()
{
    return false;
}

void set_xiaozhi_mode(bool mode)
{
    (void)mode;
}

void toggle_xiaozhi_chat_state()
{
}

void disply_lvgl_lock()
{
    display()->Lock(30000);
}

void disply_lvgl_unlock()
{
    display()->Unlock();
}

lv_disp_t* display_get_lvgl_display()
{
    return display()->GetLvglDisplay();
}

void xiaozhi_board_init()
{
    (void)Board::GetInstance();
}

void start_xiaozhi_app()
{
}

bool is_xiaozhi_ready()
{
    return true;
}

bool is_xiaozhi_idle()
{
    return true;
}

XiaozhiConfig_t get_xiaozhi_config()
{
    XiaozhiConfig_t config;
    Settings settings(kConfigNvsNs.data(), false);
    config.idleShutdownTimeSeconds =
        settings.GetInt(kIdleShutdownTimeKey.data(), static_cast<int>(config.idleShutdownTimeSeconds));
    config.allowShutdownWhenCharging =
        settings.GetBool(kAllowShutdownWhenChargingKey.data(), config.allowShutdownWhenCharging);
    config.idleRandomMovementLevel =
        settings.GetInt(kIdleRandomMovementKey.data(), config.idleRandomMovementLevel);
    return config;
}

void set_xiaozhi_config(const XiaozhiConfig_t& config)
{
    Settings settings(kConfigNvsNs.data(), true);
    settings.SetInt(kIdleShutdownTimeKey.data(), config.idleShutdownTimeSeconds);
    settings.SetBool(kAllowShutdownWhenChargingKey.data(), config.allowShutdownWhenCharging);
    settings.SetInt(kIdleRandomMovementKey.data(), config.idleRandomMovementLevel);
}

i2c_master_bus_handle_t board_get_i2c_bus()
{
    return Board::GetInstance().GetI2cBus();
}

int board_get_battery_level()
{
    int level = 0;
    bool charging = false;
    bool discharging = false;
    return Board::GetInstance().GetBatteryLevel(level, charging, discharging) ? level : 100;
}

bool board_is_battery_charging()
{
    int level = 0;
    bool charging = false;
    bool discharging = false;
    return Board::GetInstance().GetBatteryLevel(level, charging, discharging) ? charging : false;
}

void board_set_backlight_brightness(uint8_t brightness, bool permanent)
{
    if (auto* backlight = Board::GetInstance().GetBacklight()) {
        backlight->SetBrightness(brightness, permanent);
    }
}

uint8_t board_get_backlight_brightness()
{
    if (auto* backlight = Board::GetInstance().GetBacklight()) {
        return backlight->brightness();
    }
    return 0;
}

void board_set_speaker_volume(uint8_t volume, bool permanent)
{
    if (auto* codec = Board::GetInstance().GetAudioCodec()) {
        codec->SetOutputVolume(volume);
    }
    (void)permanent;
}

uint8_t board_get_speaker_volume()
{
    if (auto* codec = Board::GetInstance().GetAudioCodec()) {
        return static_cast<uint8_t>(codec->output_volume());
    }
    return 0;
}

void app_play_sound(const std::string_view& sound)
{
    (void)sound;
}

}  // namespace hal_bridge
