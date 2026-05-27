/*
 * Project Luma V0 text WebSocket client for Brain.
 */
#include "luma_ws_client.h"

#include <ArduinoJson.hpp>
#include <board.h>
#include <hal/hal.h>
#include <mooncake_log.h>
#include <settings.h>
#include <web_socket.h>

namespace {

constexpr const char* TAG = "LumaWsClient";

}  // namespace

namespace luma {

LumaWsClient::LumaWsClient(CommandHandler command_handler, ControlHandler control_handler, BinaryHandler binary_handler)
    : _command_handler(std::move(command_handler)),
      _control_handler(std::move(control_handler)),
      _binary_handler(std::move(binary_handler))
{
}

void LumaWsClient::init()
{
    _url = getBrainUrl();
    connect();
}

void LumaWsClient::update()
{
    if (!_websocket || !_websocket->IsConnected()) {
        if (GetHAL().millis() - _last_reconnect_attempt > 3000) {
            connect();
        }
        return;
    }

    std::queue<ReceivedMessage> local;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        std::swap(local, _messages);
    }

    while (!local.empty()) {
        auto message = std::move(local.front());
        if (message.binary) {
            if (_binary_handler) {
                _binary_handler(message.data.data(), message.data.size());
            }
        } else {
            handleMessage(message.text);
        }
        local.pop();
    }

    if (GetHAL().millis() - _last_telemetry_tick > 1000) {
        _last_telemetry_tick = GetHAL().millis();
        sendJson("{\"type\":\"telemetry\",\"battery\":100}");
    }
}

bool LumaWsClient::isConnected() const
{
    return _websocket && _websocket->IsConnected();
}

void LumaWsClient::connect()
{
    _last_reconnect_attempt = GetHAL().millis();
    _websocket.reset();

    auto& board  = Board::GetInstance();
    auto network = board.GetNetwork();
    _websocket   = network->CreateWebSocket(1);
    if (!_websocket) {
        mclog::tagError(TAG, "failed to create websocket");
        return;
    }

    _websocket->OnConnected([this]() {
        mclog::tagInfo(TAG, "connected to {}", _url);
        sendJson("{\"type\":\"hello\",\"device_id\":\"luma-core-s3\",\"role\":\"device\",\"capabilities\":[\"display.lvgl_face\",\"display.qgif_stream\",\"audio.wake_word\",\"audio.capture_pcm\",\"audio.playback_pcm\",\"input.touch_wake\",\"safety.estop\"]}");
    });

    _websocket->OnDisconnected([]() { mclog::tagWarn(TAG, "disconnected"); });

    _websocket->OnData([this](const char* data, size_t len, bool binary) {
        std::lock_guard<std::mutex> lock(_mutex);
        ReceivedMessage message;
        message.binary = binary;
        if (binary) {
            message.data.assign(data, data + len);
        } else {
            message.text.assign(data, len);
        }
        _messages.push(std::move(message));
    });

    if (!_websocket->Connect(_url.c_str())) {
        mclog::tagError(TAG, "connect failed: {}", _url);
    }
}

void LumaWsClient::handleMessage(std::string_view payload)
{
    ArduinoJson::JsonDocument doc;
    auto error = ArduinoJson::deserializeJson(doc, payload.data(), payload.size());
    if (error) {
        mclog::tagError(TAG, "bad json: {}", error.c_str());
        return;
    }

    const char* type = doc["type"] | "";
    if (strcmp(type, "command") != 0 || !doc["command"].is<ArduinoJson::JsonObject>()) {
        if (_control_handler) {
            _control_handler(payload);
        }
        return;
    }

    ArduinoJson::JsonObject command = doc["command"];
    const char* command_id          = command["command_id"] | "";

    std::string command_json;
    ArduinoJson::serializeJson(command, command_json);

    sendStatus("ack", command_id);
    bool ok = _command_handler(command_json);
    if (ok) {
        sendStatus("done", command_id);
    } else {
        sendStatus("error", command_id, "command_failed");
    }
}

void LumaWsClient::sendJson(std::string_view payload)
{
    if (!_websocket || !_websocket->IsConnected()) {
        return;
    }
    _websocket->Send(std::string(payload).c_str());
}

void LumaWsClient::sendBinary(const uint8_t* data, size_t len)
{
    if (!_websocket || !_websocket->IsConnected() || data == nullptr || len == 0) {
        return;
    }
    _websocket->Send(data, len, true);
}

void LumaWsClient::sendStatus(std::string_view type, std::string_view command_id, std::string_view error)
{
    ArduinoJson::JsonDocument doc;
    doc["type"]       = type;
    doc["command_id"] = command_id;
    doc["ts"]         = GetHAL().millis() / 1000.0f;
    if (!error.empty()) {
        doc["error"]["code"]      = error;
        doc["error"]["message"]   = error;
        doc["error"]["retryable"] = true;
    }
    std::string output;
    ArduinoJson::serializeJson(doc, output);
    sendJson(output);
}

std::string LumaWsClient::getBrainUrl() const
{
    Settings settings("luma", false);
    return settings.GetString(
        "brain_ws_url",
        "ws://192.168.1.100:8787/ws/head?device_id=luma-core-s3&role=device");
}

}  // namespace luma
