/*
 * Project Luma V0 head application.
 */
#pragma once

#include <memory>
#include <mooncake.h>
#include <mutex>
#include <smooth_lvgl.hpp>
#include <string>
#include <string_view>
#include <vector>

namespace luma {
class LumaQgifPlayer;
class LumaWsClient;
class LumaVoiceRuntime;
}

class AppLuma : public mooncake::AppAbility {
public:
    AppLuma();
    ~AppLuma() override;

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;

    bool applyCommandJson(std::string_view json);

private:
    std::unique_ptr<smooth_ui_toolkit::lvgl_cpp::Label> _title;
    std::unique_ptr<smooth_ui_toolkit::lvgl_cpp::Label> _status;
    std::unique_ptr<luma::LumaQgifPlayer> _qgif_player;
    std::unique_ptr<luma::LumaWsClient> _ws_client;
    std::unique_ptr<luma::LumaVoiceRuntime> _voice_runtime;
    std::mutex _ui_mutex;
    std::string _pending_emotion;
    std::string _pending_status;
    std::vector<uint8_t> _qgif_rx_buffer;
    std::string _qgif_rx_asset;
    std::string _qgif_rx_emotion;
    size_t _qgif_rx_expected_bytes = 0;
    uint32_t _qgif_rx_duration_ms = 0;
    bool _qgif_rx_active = false;
    bool _has_pending_emotion = false;
    bool _has_pending_status = false;
    uint32_t _last_status_tick = 0;

    void configureNetworkFromSecrets();
    void applyEmotion(std::string_view emotion, uint32_t duration_ms, std::string_view asset_name = {});
    void applySpeak(std::string_view text);
    void applyControlJson(std::string_view json);
    void beginQgifTransfer(const char* asset, const char* emotion, size_t bytes, uint32_t duration_ms);
    void acceptQgifChunk(const uint8_t* data, size_t len);
    void finishQgifTransfer();
    void queueEmotion(std::string_view emotion);
    void queueStatus(std::string_view status);
    void processPendingUi();
    void setStatus(std::string_view text);
};
