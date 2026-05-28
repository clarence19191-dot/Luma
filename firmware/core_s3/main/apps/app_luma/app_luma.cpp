/*
 * Project Luma V0 head application.
 */
#include "app_luma.h"
#include "luma_config.h"
#include "luma_qgif_player.h"
#include "luma_voice_runtime.h"
#include "luma_ws_client.h"

#include <ArduinoJson.hpp>
#include <cstring>
#include <hal/hal.h>
#include <luma_platform/board.h>
#include <luma_platform/settings.h>
#include <mooncake_log.h>
#include <smooth_lvgl.hpp>
#include <string>

using namespace mooncake;
using namespace smooth_ui_toolkit::lvgl_cpp;

namespace {

const char* qgif_asset_for_emotion(std::string_view emotion)
{
    struct Entry {
        std::string_view emotion;
        const char* asset;
    };
    static constexpr Entry entries[] = {
        {"idle", "sys_idle.qgif"},
        {"listening", "eye_peek.qgif"},
        {"thinking", "effect_rotate.qgif"},
        {"speaking", "Hello.qgif"},
        {"curious", "eye_peek.qgif"},
        {"happy", "emotion_happy.qgif"},
        {"smile", "emotion_smile.qgif"},
        {"surprised", "emotion_surprised.qgif"},
        {"relaxed", "emotion_relaxed.qgif"},
        {"uwu", "emotion_uwu.qgif"},
        {"love", "emotion_love_01.qgif"},
        {"smirk", "emotion_smirk.qgif"},
        {"angry", "emotion_angry_04.qgif"},
        {"angry_fire", "emotion_angry_fire.qgif"},
        {"scared", "emotion_scared.qgif"},
        {"frustrated", "emotion_frustrated.qgif"},
        {"distracted", "emotion_distracted.qgif"},
        {"dizzy", "emotion_dizzy.qgif"},
        {"cry", "cry.qgif"},
        {"devil", "devil_eyes.qgif"},
        {"sleepy", "action_sleepy.qgif"},
        {"yawn", "action_yawn.qgif"},
        {"wink", "eye_wink.qgif"},
        {"peek", "eye_peek.qgif"},
        {"squint", "eye_squint.qgif"},
        {"look_left", "eye_look_left.qgif"},
        {"look_right", "eye_look_right.qgif"},
    };
    for (const auto& entry : entries) {
        if (emotion == entry.emotion) {
            return entry.asset;
        }
    }
    return nullptr;
}

uint32_t estimate_speech_ms(std::string_view text)
{
    uint32_t duration = static_cast<uint32_t>(text.size()) * 120;
    if (duration < 800) {
        duration = 800;
    }
    if (duration > 6000) {
        duration = 6000;
    }
    return duration;
}

}  // namespace

AppLuma::AppLuma()
{
    setAppInfo().name = "LUMA";
    static uint32_t theme_color = 0x5FB7FF;
    setAppInfo().userData       = (void*)&theme_color;
}

AppLuma::~AppLuma() = default;

void AppLuma::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
}

void AppLuma::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");

    {
        LvglLockGuard lock;

        _title = std::make_unique<Label>(lv_screen_active());
        _title->setText("LUMA");
        _title->setTextColor(lv_color_hex(0x1E252B));
        _title->align(LV_ALIGN_TOP_MID, 0, 8);

        _status = std::make_unique<Label>(lv_screen_active());
        _status->setText("Connecting WiFi");
        _status->setTextColor(lv_color_hex(0x4B5963));
        _status->align(LV_ALIGN_BOTTOM_MID, 0, -8);

        _qgif_player = std::make_unique<luma::LumaQgifPlayer>();
        if (_qgif_player->init(lv_screen_active(), 320, 240)) {
            _qgif_player->play("sys_idle.qgif");
        } else {
            _qgif_player.reset();
        }
    }

    configureNetworkFromSecrets();
    GetHAL().startNetwork([this](std::string_view msg) { queueStatus(msg); });
    _ws_client = std::make_unique<luma::LumaWsClient>(
        [this](std::string_view command) { return applyCommandJson(command); },
        [this](std::string_view control) { applyControlJson(control); },
        [this](const uint8_t* data, size_t len) {
            if (_qgif_rx_active) {
                acceptQgifChunk(data, len);
            } else if (_voice_runtime) {
                _voice_runtime->handlePlaybackChunk(data, len);
            }
        });
    _voice_runtime = std::make_unique<luma::LumaVoiceRuntime>(
        [this](std::string_view json) {
            if (_ws_client) {
                _ws_client->sendJson(json);
            }
        },
        [this](const uint8_t* data, size_t len) {
            if (_ws_client) {
                _ws_client->sendBinary(data, len);
            }
        },
        [this](std::string_view emotion) { queueEmotion(emotion); },
        [this](std::string_view status) { queueStatus(status); });
    _voice_runtime->init();
    _ws_client->init();
}

void AppLuma::configureNetworkFromSecrets()
{
    if (!luma::config::hasWifiCredentials()) {
        if (!luma::config::hasSecretsFile()) {
            mclog::tagWarn(getAppInfo().name, "secrets.h not found; WiFi credentials must already exist in NVS");
        } else {
            mclog::tagWarn(getAppInfo().name, "WIFI_SSID is empty; WiFi credentials must already exist in NVS");
        }
        queueStatus("WiFi setup required");
        return;
    }

    {
        Settings settings("wifi", true);
        settings.SetString("ssid", luma::config::wifiSsid());
        settings.SetString("password", luma::config::wifiPass());
    }
    Board::GetInstance().SetWifiCredentials(luma::config::wifiSsid(), luma::config::wifiPass());
    mclog::tagInfo(getAppInfo().name, "loaded WiFi credentials for {}", luma::config::wifiSsid());
    queueStatus("WiFi configured");
}

void AppLuma::onRunning()
{
    LvglLockGuard lock;
    processPendingUi();
    if (_qgif_player) {
        _qgif_player->update(GetHAL().millis());
    }
    if (_ws_client) {
        _ws_client->update();
    }
    if (_voice_runtime) {
        _voice_runtime->update();
    }

    if (GetHAL().millis() - _last_status_tick > 3000 && (!_voice_runtime || !_voice_runtime->isBusy())) {
        _last_status_tick = GetHAL().millis();
        if (_status) {
            _status->setText(_ws_client && _ws_client->isConnected() ? "Brain connected" : "Waiting for Brain");
        }
    }
}

void AppLuma::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");

    LvglLockGuard lock;
    _voice_runtime.reset();
    _ws_client.reset();
    _qgif_player.reset();
    _title.reset();
    _status.reset();
}

bool AppLuma::applyCommandJson(std::string_view json)
{
    ArduinoJson::JsonDocument doc;
    auto error = ArduinoJson::deserializeJson(doc, json.data(), json.size());
    if (error) {
        setStatus("Bad command");
        return false;
    }

    const char* type = doc["type"] | "";
    if (strcmp(type, "set_emotion") == 0) {
        const char* emotion = doc["emotion"] | "idle";
        const char* asset   = doc["asset"] | "";
        uint32_t duration   = doc["duration_ms"] | 0;
        applyEmotion(emotion, duration, asset);
        return true;
    }

    if (strcmp(type, "move_head") == 0) {
        setStatus("Motion disabled");
        return false;
    }

    if (strcmp(type, "speak") == 0) {
        const char* text = doc["text"] | "";
        applySpeak(text);
        return true;
    }

    if (strcmp(type, "estop") == 0 || strcmp(type, "stop") == 0) {
        if (_voice_runtime) {
            _voice_runtime->handleControlJson("{\"type\":\"cancel_session\"}");
        }
        if (_qgif_player) {
            _qgif_player->stop();
        }
        applyEmotion("idle", 0);
        setStatus("Stopped");
        return true;
    }

    if (strcmp(type, "reset_estop") == 0) {
        setStatus("Ready");
        return true;
    }

    setStatus("Unknown command");
    return false;
}

void AppLuma::applyEmotion(std::string_view emotion, uint32_t duration_ms, std::string_view asset_name)
{
    bool qgif_playing = false;
    if (_qgif_player) {
        if (asset_name.empty()) {
            if (auto asset = qgif_asset_for_emotion(emotion); asset != nullptr) {
                asset_name = asset;
            }
        }
        if (!asset_name.empty()) {
            qgif_playing = _qgif_player->play(asset_name, duration_ms);
        }
        if (!qgif_playing) {
            _qgif_player->stop();
        }
    }

    setStatus(emotion);
}

void AppLuma::applySpeak(std::string_view text)
{
    if (text.empty()) {
        return;
    }

    uint32_t duration = estimate_speech_ms(text);
    if (_qgif_player) {
        _qgif_player->play("Hello.qgif", duration);
    }
    setStatus("Speaking");
}

void AppLuma::queueEmotion(std::string_view emotion)
{
    std::lock_guard<std::mutex> lock(_ui_mutex);
    _pending_emotion.assign(emotion.data(), emotion.size());
    _has_pending_emotion = true;
}

void AppLuma::queueStatus(std::string_view status)
{
    std::lock_guard<std::mutex> lock(_ui_mutex);
    _pending_status.assign(status.data(), status.size());
    _has_pending_status = true;
}

void AppLuma::processPendingUi()
{
    std::string emotion;
    std::string status;
    bool has_emotion = false;
    bool has_status  = false;
    {
        std::lock_guard<std::mutex> lock(_ui_mutex);
        if (_has_pending_emotion) {
            emotion              = _pending_emotion;
            _has_pending_emotion = false;
            has_emotion          = true;
        }
        if (_has_pending_status) {
            status              = _pending_status;
            _has_pending_status = false;
            has_status          = true;
        }
    }
    if (has_emotion) {
        applyEmotion(emotion, 0);
    }
    if (has_status) {
        setStatus(status);
    }
}

void AppLuma::applyControlJson(std::string_view json)
{
    ArduinoJson::JsonDocument doc;
    auto error = ArduinoJson::deserializeJson(doc, json.data(), json.size());
    if (error) {
        return;
    }

    const char* type = doc["type"] | "";
    if (strcmp(type, "qgif_begin") == 0) {
        const char* asset   = doc["asset"] | "";
        const char* emotion = doc["emotion"] | "";
        size_t bytes        = doc["bytes"] | 0;
        uint32_t duration   = doc["duration_ms"] | 0;
        beginQgifTransfer(asset, emotion, bytes, duration);
        return;
    }

    if (strcmp(type, "qgif_end") == 0) {
        finishQgifTransfer();
        return;
    }

    if (strcmp(type, "qgif_cancel") == 0) {
        _qgif_rx_active = false;
        _qgif_rx_buffer.clear();
        return;
    }

    if (strcmp(type, "set_emotion") == 0) {
        const char* emotion = doc["emotion"] | "idle";
        const char* asset   = doc["asset"] | "";
        uint32_t duration   = doc["duration_ms"] | 0;
        applyEmotion(emotion, duration, asset);
        return;
    }

    if (_voice_runtime) {
        _voice_runtime->handleControlJson(json);
    }
}

void AppLuma::beginQgifTransfer(const char* asset, const char* emotion, size_t bytes, uint32_t duration_ms)
{
    _qgif_rx_active         = true;
    _qgif_rx_asset          = asset ? asset : "";
    _qgif_rx_emotion        = emotion ? emotion : "";
    _qgif_rx_expected_bytes = bytes;
    _qgif_rx_duration_ms    = duration_ms;
    _qgif_rx_buffer.clear();
    if (bytes > 0 && bytes <= 512 * 1024) {
        _qgif_rx_buffer.reserve(bytes);
    }
}

void AppLuma::acceptQgifChunk(const uint8_t* data, size_t len)
{
    if (!_qgif_rx_active || !data || len == 0) {
        return;
    }
    if (_qgif_rx_expected_bytes > 0 && _qgif_rx_buffer.size() + len > _qgif_rx_expected_bytes) {
        _qgif_rx_active = false;
        _qgif_rx_buffer.clear();
        setStatus("QGIF overflow");
        return;
    }
    _qgif_rx_buffer.insert(_qgif_rx_buffer.end(), data, data + len);
}

void AppLuma::finishQgifTransfer()
{
    if (!_qgif_rx_active) {
        return;
    }
    _qgif_rx_active = false;
    if (_qgif_rx_expected_bytes > 0 && _qgif_rx_buffer.size() != _qgif_rx_expected_bytes) {
        _qgif_rx_buffer.clear();
        setStatus("QGIF short");
        return;
    }
    if (_qgif_player && !_qgif_rx_buffer.empty()) {
        if (_qgif_player->playBytes(_qgif_rx_asset, _qgif_rx_buffer.data(), _qgif_rx_buffer.size(), _qgif_rx_duration_ms)) {
            _qgif_rx_buffer.clear();
            setStatus(_qgif_rx_emotion.empty() ? _qgif_rx_asset : _qgif_rx_emotion);
            return;
        }
    }
    _qgif_rx_buffer.clear();
}

void AppLuma::setStatus(std::string_view text)
{
    if (_status) {
        _status->setText(std::string(text).c_str());
    }
}
