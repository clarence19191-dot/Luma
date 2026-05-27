/*
 * Project Luma V0 text WebSocket client for Brain.
 */
#pragma once

#include <functional>
#include <cstdint>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <string_view>
#include <vector>

class WebSocket;

namespace luma {

class LumaWsClient {
public:
    using CommandHandler = std::function<bool(std::string_view)>;
    using ControlHandler = std::function<void(std::string_view)>;
    using BinaryHandler  = std::function<void(const uint8_t*, size_t)>;

    LumaWsClient(CommandHandler command_handler, ControlHandler control_handler, BinaryHandler binary_handler);

    void init();
    void update();
    bool isConnected() const;
    void sendJson(std::string_view payload);
    void sendBinary(const uint8_t* data, size_t len);

private:
    struct ReceivedMessage {
        bool binary = false;
        std::string text;
        std::vector<uint8_t> data;
    };

    CommandHandler _command_handler;
    ControlHandler _control_handler;
    BinaryHandler _binary_handler;
    std::unique_ptr<WebSocket> _websocket;
    std::string _url;
    std::mutex _mutex;
    std::queue<ReceivedMessage> _messages;
    uint32_t _last_reconnect_attempt = 0;
    uint32_t _last_telemetry_tick     = 0;

    void connect();
    void handleMessage(std::string_view payload);
    void sendStatus(std::string_view type, std::string_view command_id, std::string_view error = "");
    std::string getBrainUrl() const;
};

}  // namespace luma
