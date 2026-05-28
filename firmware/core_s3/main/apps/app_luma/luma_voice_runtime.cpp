/*
 * Project Luma V0 CoreS3 voice terminal runtime.
 */
#include "luma_voice_runtime.h"

#include <ArduinoJson.hpp>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <hal/hal.h>
#include <luma_platform/audio_codec.h>
#include <luma_platform/board.h>
#include <memory>
#include <mooncake_log.h>
#include <sdkconfig.h>
#include <utility>

#if defined(CONFIG_USE_CUSTOM_WAKE_WORD) && __has_include("wake_words/custom_wake_word.h")
#include "wake_words/custom_wake_word.h"
#define LUMA_HAS_CUSTOM_WAKE_WORD 1
#else
#define LUMA_HAS_CUSTOM_WAKE_WORD 0
#endif

namespace {

constexpr const char* TAG = "LumaVoice";
#if LUMA_HAS_CUSTOM_WAKE_WORD
constexpr int kWakeWordSampleRateHz = 16000;
#endif

std::string make_session_id()
{
    return std::string("voice_") + std::to_string(GetHAL().millis());
}

#if LUMA_HAS_CUSTOM_WAKE_WORD
void resample_interleaved(
    const std::vector<int16_t>& input,
    int input_rate_hz,
    int channels,
    int output_frames,
    std::vector<int16_t>& output)
{
    channels = std::max(channels, 1);
    if (output_frames <= 0) {
        output.clear();
        return;
    }

    output.resize(static_cast<size_t>(output_frames) * channels);
    const int input_frames = static_cast<int>(input.size()) / channels;
    if (input_frames <= 0) {
        std::fill(output.begin(), output.end(), 0);
        return;
    }

    if (input_rate_hz == kWakeWordSampleRateHz && input_frames >= output_frames) {
        std::copy_n(input.begin(), output.size(), output.begin());
        return;
    }

    for (int out_i = 0; out_i < output_frames; ++out_i) {
        const uint64_t scaled = static_cast<uint64_t>(out_i) * static_cast<uint64_t>(input_rate_hz);
        int base              = static_cast<int>(scaled / kWakeWordSampleRateHz);
        uint64_t rem          = scaled % kWakeWordSampleRateHz;
        if (base >= input_frames - 1) {
            base = input_frames - 1;
            rem  = 0;
        }
        const int next = std::min(base + 1, input_frames - 1);
        for (int ch = 0; ch < channels; ++ch) {
            const int16_t a = input[static_cast<size_t>(base) * channels + ch];
            const int16_t b = input[static_cast<size_t>(next) * channels + ch];
            const int32_t mixed =
                static_cast<int32_t>((static_cast<int64_t>(a) * (kWakeWordSampleRateHz - rem) +
                                      static_cast<int64_t>(b) * rem) /
                                     kWakeWordSampleRateHz);
            output[static_cast<size_t>(out_i) * channels + ch] = static_cast<int16_t>(mixed);
        }
    }
}
#endif

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
    _touch_signal_id = GetHAL().onHeadPetGesture.connect([this](HeadPetGesture gesture) { handleTouchGesture(gesture); });
    startWakeWordDetection();
    setStatus("Voice ready");
}

void LumaVoiceRuntime::stop()
{
    if (_touch_signal_id >= 0) {
        GetHAL().onHeadPetGesture.disconnect(_touch_signal_id);
        _touch_signal_id = -1;
    }
    stopWakeWordDetection();
    stopCapture();
    stopPlayback(false);
    for (int i = 0; i < 100 && (_capture_task != nullptr || _playback_task != nullptr || _wake_word_task != nullptr);
         ++i) {
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
    if (source != "wake_word") {
        _wake_word_paused = true;
        vTaskDelay(pdMS_TO_TICKS(20));
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
        const uint32_t overflows = ++_playback_overflow_count;
        mclog::tagWarn(TAG, "playback queue full, dropping incoming chunk, overflow_count={}", overflows);
        return;
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
    _playback_overflow_count = 0;
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

void LumaVoiceRuntime::handleTouchGesture(HeadPetGesture gesture)
{
    const uint32_t now = GetHAL().millis();
    if (gesture == HeadPetGesture::Press) {
        _touch_pressed = true;
        _touch_swiped = false;
        _touch_press_ms = now;
        return;
    }
    if (gesture == HeadPetGesture::SwipeForward || gesture == HeadPetGesture::SwipeBackward) {
        _touch_swiped = true;
        return;
    }
    if (gesture != HeadPetGesture::Release) {
        return;
    }

    const bool was_pressed = _touch_pressed;
    const bool was_swiped = _touch_swiped;
    const uint32_t held_ms = now - _touch_press_ms;
    const uint32_t since_last_wake_ms = now - _last_touch_wake_ms;
    _touch_pressed = false;
    _touch_swiped = false;

    if (!was_pressed || was_swiped) {
        _last_touch_tap_ms = 0;
        return;
    }
    if (held_ms < kTouchTapMinPressMs || held_ms > kTouchTapMaxPressMs) {
        _last_touch_tap_ms = 0;
        return;
    }
    if (_capture_active.load() || _playback_active.load()) {
        _last_touch_tap_ms = 0;
        return;
    }
    if (_last_touch_wake_ms != 0 && since_last_wake_ms < kTouchWakeCooldownMs) {
        _last_touch_tap_ms = 0;
        return;
    }

    if (_last_touch_tap_ms != 0) {
        const uint32_t tap_gap_ms = now - _last_touch_tap_ms;
        if (tap_gap_ms >= kTouchDoubleTapMinGapMs && tap_gap_ms <= kTouchDoubleTapMaxGapMs) {
            _last_touch_tap_ms = 0;
            _last_touch_wake_ms = now;
            requestWake("touch");
            return;
        }
        if (tap_gap_ms < kTouchDoubleTapMinGapMs) {
            return;
        }
    }

    _last_touch_tap_ms = now;
    setStatus("Double tap to wake");
}

void LumaVoiceRuntime::captureTaskThunk(void* arg)
{
    static_cast<LumaVoiceRuntime*>(arg)->captureLoop();
}

void LumaVoiceRuntime::playbackTaskThunk(void* arg)
{
    static_cast<LumaVoiceRuntime*>(arg)->playbackLoop();
}

void LumaVoiceRuntime::wakeWordTaskThunk(void* arg)
{
    static_cast<LumaVoiceRuntime*>(arg)->wakeWordLoop();
}

void LumaVoiceRuntime::startWakeWordDetection()
{
#if LUMA_HAS_CUSTOM_WAKE_WORD
    if (_wake_word_active.exchange(true)) {
        return;
    }
    _wake_word_paused = false;
    xTaskCreatePinnedToCore(wakeWordTaskThunk, "luma_wake_word", 8192, this, 3, &_wake_word_task, 0);
#else
    mclog::tagWarn(TAG, "custom wake word support is not compiled in");
#endif
}

void LumaVoiceRuntime::stopWakeWordDetection()
{
    _wake_word_active = false;
    _wake_word_paused = true;
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
    const int max_chunks      = kMaxRecordMs / kChunkMs;
    const int silent_limit    = kSilenceStopMs / kChunkMs;
    const int no_speech_limit = kNoSpeechStopMs / kChunkMs;
    const int preroll_limit   = std::max(1, kVadPrerollMs / kChunkMs);
    int silent_chunks         = 0;
    int chunks_read           = 0;
    int chunks_sent           = 0;
    int start_candidate_chunks = 0;
    bool voice_started        = false;
    float noise_floor         = 180.0f;

    std::vector<int16_t> input_chunk;
    std::vector<int16_t> mono_chunk;
    std::vector<std::vector<int16_t>> preroll_chunks;
    input_chunk.resize(kChunkFrames * input_channels);
    mono_chunk.resize(kChunkFrames);
    preroll_chunks.reserve(preroll_limit);

    while (_capture_active.load() && chunks_read < max_chunks) {
        if (!audio_codec->InputData(input_chunk)) {
            mclog::tagWarn(TAG, "audio input chunk failed");
            break;
        }

        uint32_t energy = 0;
        for (int i = 0; i < kChunkFrames; ++i) {
            int32_t mixed = 0;
            for (int ch = 0; ch < input_channels; ++ch) {
                mixed += input_chunk[i * input_channels + ch];
            }
            mixed /= input_channels;
            mixed = std::clamp<int32_t>(mixed, -32768, 32767);
            int16_t sample = static_cast<int16_t>(mixed);
            mono_chunk[i] = sample;
            energy += static_cast<uint32_t>(std::abs(sample));
        }
        energy /= kChunkFrames;

        const float start_threshold = std::max(450.0f, noise_floor * 3.0f + 200.0f);
        const float stop_threshold  = std::max(320.0f, noise_floor * 1.8f + 120.0f);
        chunks_read += 1;

        if (!voice_started) {
            if (energy < static_cast<uint32_t>(start_threshold)) {
                noise_floor = noise_floor * 0.95f + static_cast<float>(energy) * 0.05f;
            }
            preroll_chunks.push_back(mono_chunk);
            if (static_cast<int>(preroll_chunks.size()) > preroll_limit) {
                preroll_chunks.erase(preroll_chunks.begin());
            }

            if (energy >= static_cast<uint32_t>(start_threshold)) {
                start_candidate_chunks += 1;
            } else {
                start_candidate_chunks = 0;
            }

            if (start_candidate_chunks >= kVadStartChunks) {
                voice_started = true;
                silent_chunks = 0;
                mclog::tagInfo(TAG, "voice detected after {} chunks, energy={}, noise_floor={}", chunks_read, energy, noise_floor);
                for (const auto& chunk : preroll_chunks) {
                    if (_binary_sender) {
                        _binary_sender(reinterpret_cast<const uint8_t*>(chunk.data()), chunk.size() * sizeof(int16_t));
                        chunks_sent += 1;
                    }
                }
                preroll_chunks.clear();
            } else if (chunks_read >= no_speech_limit) {
                mclog::tagInfo(TAG, "no speech detected, chunks={}, noise_floor={}", chunks_read, noise_floor);
                break;
            }
        } else {
            if (_binary_sender) {
                _binary_sender(reinterpret_cast<const uint8_t*>(mono_chunk.data()), mono_chunk.size() * sizeof(int16_t));
                chunks_sent += 1;
            }

            if (energy <= static_cast<uint32_t>(stop_threshold)) {
                silent_chunks += 1;
                if (silent_chunks >= silent_limit) {
                    break;
                }
            } else {
                silent_chunks = 0;
            }
        }
    }

    audio_codec->EnableInput(false);
    _capture_active = false;
    setEmotion("thinking");
    setStatus("Thinking");
    sendJsonf(
        "{\"type\":\"audio_end\",\"session_id\":\"%s\",\"chunks\":%d,\"captured_chunks\":%d,\"vad_started\":%s}",
        _session_id.c_str(),
        chunks_sent,
        chunks_read,
        voice_started ? "true" : "false");
    _capture_task = nullptr;
    vTaskDelete(nullptr);
}

void LumaVoiceRuntime::wakeWordLoop()
{
#if LUMA_HAS_CUSTOM_WAKE_WORD
    auto audio_codec = Board::GetInstance().GetAudioCodec();
    if (!audio_codec) {
        mclog::tagError(TAG, "audio codec unavailable for wake word");
        _wake_word_active = false;
        _wake_word_task   = nullptr;
        vTaskDelete(nullptr);
        return;
    }

    auto wake_word = std::make_unique<CustomWakeWord>();
    if (!wake_word->Initialize(audio_codec, nullptr)) {
        mclog::tagWarn(TAG, "custom wake word initialization failed");
        setStatus("Touch wake ready");
        _wake_word_active = false;
        _wake_word_task   = nullptr;
        vTaskDelete(nullptr);
        return;
    }

    std::atomic<bool> detected = false;
    wake_word->OnWakeWordDetected([&detected](const std::string&) { detected = true; });

    const int input_channels = std::max(audio_codec->input_channels(), 1);
    const int input_rate     = std::max(audio_codec->input_sample_rate(), kWakeWordSampleRateHz);
    const int feed_frames    = static_cast<int>(wake_word->GetFeedSize());
    const int input_frames   = std::max(1, feed_frames * input_rate / kWakeWordSampleRateHz);

    std::vector<int16_t> input_chunk(static_cast<size_t>(input_frames) * input_channels);
    std::vector<int16_t> wake_chunk;
    bool detector_running = false;

    while (_wake_word_active.load()) {
        if (_wake_word_paused.load() || _capture_active.load() || _playback_active.load()) {
            if (detector_running) {
                wake_word->Stop();
                detector_running = false;
                audio_codec->EnableInput(false);
            }
            if (!_capture_active.load() && !_playback_active.load()) {
                _wake_word_paused = false;
            }
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        if (!detector_running) {
            wake_word->Start();
            detector_running = true;
            audio_codec->EnableInput(true);
            setStatus("Voice ready");
        }

        if (!audio_codec->InputData(input_chunk)) {
            mclog::tagWarn(TAG, "wake word input chunk failed");
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        resample_interleaved(input_chunk, input_rate, input_channels, feed_frames, wake_chunk);
        wake_word->Feed(wake_chunk);

        if (detected.exchange(false)) {
            mclog::tagInfo(TAG, "wake word detected");
            wake_word->Stop();
            detector_running = false;
            audio_codec->EnableInput(false);
            _wake_word_paused = true;
            setStatus("Wake word");
            requestWake("wake_word");
        }
    }

    if (detector_running) {
        wake_word->Stop();
        audio_codec->EnableInput(false);
    }
    _wake_word_task = nullptr;
    vTaskDelete(nullptr);
#else
    _wake_word_task = nullptr;
    vTaskDelete(nullptr);
#endif
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
