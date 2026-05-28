/*
 * Project Luma V0 CoreS3 voice terminal runtime.
 */
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <queue>
#include <string>
#include <string_view>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <hal/hal.h>

namespace luma {

class LumaVoiceRuntime {
public:
    using JsonSender = std::function<void(std::string_view)>;
    using BinarySender = std::function<void(const uint8_t*, size_t)>;
    using UiCallback = std::function<void(std::string_view)>;

    LumaVoiceRuntime(JsonSender json_sender, BinarySender binary_sender, UiCallback emotion_callback, UiCallback status_callback);
    ~LumaVoiceRuntime();

    void init();
    void stop();
    void update();
    void requestWake(std::string_view source);
    void handleControlJson(std::string_view json);
    void handlePlaybackChunk(const uint8_t* data, size_t len);
    bool isBusy() const;

private:
    static constexpr int kSampleRateHz = 24000;
    static constexpr int kChannels = 1;
    static constexpr int kChunkMs = 40;
    static constexpr int kChunkFrames = kSampleRateHz * kChunkMs / 1000;
    static constexpr int kMaxRecordMs = 8000;
    static constexpr int kSilenceStopMs = 1200;
    static constexpr int kMaxPlaybackQueueChunks = 5;
    static constexpr uint32_t kTouchWakeCooldownMs = 5000;
    static constexpr uint32_t kTouchTapMinPressMs = 50;
    static constexpr uint32_t kTouchTapMaxPressMs = 700;
    static constexpr uint32_t kTouchDoubleTapMinGapMs = 80;
    static constexpr uint32_t kTouchDoubleTapMaxGapMs = 650;

    JsonSender _json_sender;
    BinarySender _binary_sender;
    UiCallback _emotion_callback;
    UiCallback _status_callback;

    std::atomic<bool> _capture_active{false};
    std::atomic<bool> _playback_active{false};
    std::atomic<bool> _playback_finishing{false};
    std::atomic<bool> _playback_notify_done{true};
    std::atomic<bool> _wake_word_active{false};
    std::atomic<bool> _wake_word_paused{false};
    TaskHandle_t _capture_task = nullptr;
    TaskHandle_t _playback_task = nullptr;
    TaskHandle_t _wake_word_task = nullptr;
    int _touch_signal_id = -1;
    bool _touch_pressed = false;
    bool _touch_swiped = false;
    uint32_t _touch_press_ms = 0;
    uint32_t _last_touch_tap_ms = 0;
    uint32_t _last_touch_wake_ms = 0;
    std::string _session_id;

    std::mutex _playback_mutex;
    std::queue<std::vector<int16_t>> _playback_queue;

    void startCapture(std::string_view source);
    void stopCapture();
    void startPlayback(std::string_view session_id);
    void stopPlayback(bool notify_done);
    void clearPlaybackQueue();
    void sendJson(std::string_view json);
    void sendJsonf(const char* fmt, ...);
    void setStatus(std::string_view status);
    void setEmotion(std::string_view emotion);
    void handleTouchGesture(HeadPetGesture gesture);

    static void captureTaskThunk(void* arg);
    static void playbackTaskThunk(void* arg);
    static void wakeWordTaskThunk(void* arg);
    void startWakeWordDetection();
    void stopWakeWordDetection();
    void captureLoop();
    void playbackLoop();
    void wakeWordLoop();
};

}  // namespace luma
