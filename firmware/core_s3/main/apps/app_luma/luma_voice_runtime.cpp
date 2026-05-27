/*
 * Project Luma V0 CoreS3 voice terminal runtime.
 */
#include "luma_voice_runtime.h"

#include <ArduinoJson.hpp>
#include <algorithm>
#include <audio/audio_codec.h>
#include <board.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <hal/hal.h>
#include <mooncake_log.h>
#include <utility>

namespace {

constexpr const char* TAG = "LumaVoice";

std::string make_session_id()
{
    return std::string("voice_") + std::to_string(GetHAL().millis());
}

}  // namespace

namespace luma {

LumaVoiceRuntime::LumaVoiceRuntime(
    JsonSender json_sender, BinarySender binary_sender, UiCallback emotion_callback, UiCallback status_callback)
    : _json_sender(std::move(json_sender)),
      _binary_sender(std::move(binary_sender)),
      _emotion_callback(std::move(emotion_callback)),
      _status_callback(std::move(status_callback))
{
}

LumaVoiceRuntime::~LumaVoiceRuntime()
{
    stop();
}

void LumaVoiceRuntime::init()
{
    _touch_signal_id = GetHAL().onHeadPetGesture.connect([this](HeadPetGesture gesture) {
        if (gesture == HeadPetGesture::Release) {
            requestWake("touch");
        }
    });
    setStatus("Voice ready");
}

void LumaVoiceRuntime::stop()
{
    if (_touch_signal_id >= 0) {
        GetHAL().onHeadPetGesture.disconnect(_touch_signal_id);
        _touch_signal_id = -1;
    }
    stopCapture();
    stopPlayback(false);
    for (int i = 0; i < 100 && (_capture_task != nullptr || _playback_task != nullptr); ++i) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void LumaVoiceRuntime::update()
{
}

bool LumaVoiceRuntime::isBusy() const
{
    return _capture_active.load() || _playback_active.load();
}

void LumaVoiceRuntime::requestWake(std::string_view source)
{
    if (_capture_active.load() || _playback_active.load()) {
        return;
    }
    _session_id = make_session_id();
    sendJsonf(
        "{\"type\":\"wake_detected\",\"session_id\":\"%s\",\"source\":\"%.*s\",\"wake_phrase\":\"你好 Luma\"}",
        _session_id.c_str(),
        static_cast<int>(source.size()),
        source.data());
    startCapture(source);
}

void LumaVoiceRuntime::handleControlJson(std::string_view json)
{
    ArduinoJson::JsonDocument doc;
    auto error = ArduinoJson::deserializeJson(doc, json.data(), json.size());
    if (error) {
        return;
    }

    const char* type = doc["type"] | "";
    if (strcmp(type, "start_listening") == 0) {
        setEmotion("listening");
        setStatus("Listening");
        return;
    }
    if (strcmp(type, "play_audio_begin") == 0) {
        const char* session_id = doc["session_id"] | _session_id.c_str();
        startPlayback(session_id);
        return;
    }
    if (strcmp(type, "play_audio_end") == 0) {
        _playback_finishing = true;
        return;
    }
    if (strcmp(type, "cancel_session") == 0) {
        stopCapture();
        stopPlayback(false);
        setEmotion("idle");
        setStatus("Cancelled");
        return;
    }
}

void LumaVoiceRuntime::handlePlaybackChunk(const uint8_t* data, size_t len)
{
    if (!_playback_active.load() || data == nullptr || len < sizeof(int16_t)) {
        return;
    }

    const size_t samples = len / sizeof(int16_t);
    std::vector<int16_t> chunk(samples);
    std::memcpy(chunk.data(), data, samples * sizeof(int16_t));

    std::lock_guard<std::mutex> lock(_playback_mutex);
    if (_playback_queue.size() >= kMaxPlaybackQueueChunks) {
        _playback_queue.pop();
        mclog::tagWarn(TAG, "playback queue full, dropping oldest chunk");
    }
    _playback_queue.push(std::move(chunk));
}

void LumaVoiceRuntime::startCapture(std::string_view source)
{
    if (_capture_active.exchange(true)) {
        return;
    }
    (void)source;
    setEmotion("listening");
    setStatus("Listening");
    xTaskCreatePinnedToCore(captureTaskThunk, "luma_capture", 8192, this, 4, &_capture_task, 0);
}

void LumaVoiceRuntime::stopCapture()
{
    _capture_active = false;
}

void LumaVoiceRuntime::startPlayback(std::string_view session_id)
{
    stopCapture();
    _session_id.assign(session_id.data(), session_id.size());
    clearPlaybackQueue();
    _playback_finishing = false;
    _playback_notify_done = true;
    if (!_playback_active.exchange(true)) {
        setEmotion("speaking");
        setStatus("Speaking");
        xTaskCreatePinnedToCore(playbackTaskThunk, "luma_playback", 8192, this, 4, &_playback_task, 0);
    }
}

void LumaVoiceRuntime::stopPlayback(bool notify_done)
{
    _playback_active = false;
    _playback_finishing = true;
    _playback_notify_done = notify_done;
    clearPlaybackQueue();
}

void LumaVoiceRuntime::clearPlaybackQueue()
{
    std::lock_guard<std::mutex> lock(_playback_mutex);
    while (!_playback_queue.empty()) {
        _playback_queue.pop();
    }
}

void LumaVoiceRuntime::sendJson(std::string_view json)
{
    if (_json_sender) {
        _json_sender(json);
    }
}

void LumaVoiceRuntime::sendJsonf(const char* fmt, ...)
{
    char buffer[384];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, sizeof(buffer), fmt, args);
    va_end(args);
    sendJson(buffer);
}

void LumaVoiceRuntime::setStatus(std::string_view status)
{
    if (_status_callback) {
        _status_callback(status);
    }
}

void LumaVoiceRuntime::setEmotion(std::string_view emotion)
{
    if (_emotion_callback) {
        _emotion_callback(emotion);
    }
}

void LumaVoiceRuntime::captureTaskThunk(void* arg)
{
    static_cast<LumaVoiceRuntime*>(arg)->captureLoop();
}

void LumaVoiceRuntime::playbackTaskThunk(void* arg)
{
    static_cast<LumaVoiceRuntime*>(arg)->playbackLoop();
}

void LumaVoiceRuntime::captureLoop()
{
    auto audio_codec = Board::GetInstance().GetAudioCodec();
    if (!audio_codec) {
        sendJsonf("{\"type\":\"error\",\"code\":\"audio_codec_unavailable\",\"message\":\"audio codec unavailable\"}");
        _capture_active = false;
        _capture_task   = nullptr;
        vTaskDelete(nullptr);
        return;
    }

    sendJsonf(
        "{\"type\":\"audio_begin\",\"session_id\":\"%s\",\"sample_rate_hz\":%d,\"channels\":%d,\"encoding\":\"pcm_s16le\"}",
        _session_id.c_str(),
        kSampleRateHz,
        kChannels);

    audio_codec->EnableInput(true);

    const int input_channels = std::max(audio_codec->input_channels(), 1);
    const int max_chunks     = kMaxRecordMs / kChunkMs;
    const int silent_limit   = kSilenceStopMs / kChunkMs;
    int silent_chunks        = 0;
    int chunks_read          = 0;
    bool voice_started       = false;

    std::vector<int16_t> input_chunk;
    std::vector<int16_t> mono_chunk;
    input_chunk.resize(kChunkFrames * input_channels);
    mono_chunk.resize(kChunkFrames);

    while (_capture_active.load() && chunks_read < max_chunks) {
        if (!audio_codec->InputData(input_chunk)) {
            mclog::tagWarn(TAG, "audio input chunk failed");
            break;
        }

        uint32_t energy = 0;
        for (int i = 0; i < kChunkFrames; ++i) {
            int16_t sample = input_chunk[i * input_channels];
            mono_chunk[i]  = sample;
            energy += static_cast<uint32_t>(std::abs(sample));
        }
        energy /= kChunkFrames;

        if (_binary_sender) {
            _binary_sender(reinterpret_cast<const uint8_t*>(mono_chunk.data()), mono_chunk.size() * sizeof(int16_t));
        }

        if (energy > 450) {
            voice_started = true;
            silent_chunks = 0;
        } else if (voice_started) {
            silent_chunks += 1;
            if (silent_chunks >= silent_limit) {
                break;
            }
        }

        chunks_read += 1;
    }

    audio_codec->EnableInput(false);
    _capture_active = false;
    setEmotion("thinking");
    setStatus("Thinking");
    sendJsonf("{\"type\":\"audio_end\",\"session_id\":\"%s\",\"chunks\":%d}", _session_id.c_str(), chunks_read);
    _capture_task = nullptr;
    vTaskDelete(nullptr);
}

void LumaVoiceRuntime::playbackLoop()
{
    auto audio_codec = Board::GetInstance().GetAudioCodec();
    if (!audio_codec) {
        sendJsonf("{\"type\":\"error\",\"code\":\"audio_codec_unavailable\",\"message\":\"audio codec unavailable\"}");
        _playback_active = false;
        _playback_task   = nullptr;
        vTaskDelete(nullptr);
        return;
    }

    audio_codec->EnableOutput(true);
    while (_playback_active.load()) {
        std::vector<int16_t> chunk;
        {
            std::lock_guard<std::mutex> lock(_playback_mutex);
            if (!_playback_queue.empty()) {
                chunk = std::move(_playback_queue.front());
                _playback_queue.pop();
            }
        }

        if (!chunk.empty()) {
            audio_codec->OutputData(chunk);
            continue;
        }

        if (_playback_finishing.load()) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    audio_codec->EnableOutput(false);
    _playback_active   = false;
    _playback_finishing = false;
    clearPlaybackQueue();
    if (_playback_notify_done.load()) {
        sendJsonf("{\"type\":\"playback_done\",\"session_id\":\"%s\"}", _session_id.c_str());
    }
    setEmotion("idle");
    setStatus("Ready");
    _playback_task = nullptr;
    vTaskDelete(nullptr);
}

}  // namespace luma
