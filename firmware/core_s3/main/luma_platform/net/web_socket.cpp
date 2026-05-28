/*
 * SPDX-FileCopyrightText: 2024-2026 78/esp-ml307 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include "luma_platform/net/web_socket.h"

#include <esp_log.h>
#include <esp_random.h>

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <lwip/netdb.h>
#include <string>
#include <sys/socket.h>
#include <unistd.h>

namespace {

constexpr const char* TAG = "LumaWebSocket";

struct ParsedUri {
    std::string protocol;
    std::string host;
    int port = 80;
    std::string path = "/";
};

std::string base64_encode(const uint8_t* data, size_t len)
{
    static constexpr char kBase64Chars[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string encoded;
    encoded.reserve(((len + 2) / 3) * 4);

    for (size_t i = 0; i < len; i += 3) {
        const size_t remain = std::min<size_t>(3, len - i);
        uint32_t value = static_cast<uint32_t>(data[i]) << 16;
        if (remain > 1) {
            value |= static_cast<uint32_t>(data[i + 1]) << 8;
        }
        if (remain > 2) {
            value |= data[i + 2];
        }

        encoded.push_back(kBase64Chars[(value >> 18) & 0x3F]);
        encoded.push_back(kBase64Chars[(value >> 12) & 0x3F]);
        encoded.push_back(remain > 1 ? kBase64Chars[(value >> 6) & 0x3F] : '=');
        encoded.push_back(remain > 2 ? kBase64Chars[value & 0x3F] : '=');
    }
    return encoded;
}

bool parse_uri(const char* uri, ParsedUri& out)
{
    if (uri == nullptr) {
        return false;
    }
    std::string value(uri);
    auto scheme_pos = value.find("://");
    if (scheme_pos == std::string::npos) {
        return false;
    }

    out.protocol = value.substr(0, scheme_pos);
    size_t host_start = scheme_pos + 3;
    size_t path_start = value.find('/', host_start);
    std::string host_port = path_start == std::string::npos ? value.substr(host_start)
                                                            : value.substr(host_start, path_start - host_start);
    out.path = path_start == std::string::npos ? "/" : value.substr(path_start);

    auto colon = host_port.rfind(':');
    if (colon != std::string::npos) {
        out.host = host_port.substr(0, colon);
        out.port = std::stoi(host_port.substr(colon + 1));
    } else {
        out.host = host_port;
        out.port = out.protocol == "wss" ? 443 : 80;
    }
    return !out.host.empty() && (out.protocol == "ws");
}

}  // namespace

WebSocket::WebSocket() = default;

WebSocket::~WebSocket()
{
    Close();
}

bool WebSocket::IsConnected() const
{
    return connected_;
}

bool WebSocket::Connect(const char* uri)
{
    Close();

    ParsedUri parsed;
    if (!parse_uri(uri, parsed)) {
        ESP_LOGE(TAG, "invalid or unsupported websocket uri: %s", uri ? uri : "(null)");
        return false;
    }

    struct addrinfo hints = {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo* result = nullptr;
    std::string port = std::to_string(parsed.port);
    int err = getaddrinfo(parsed.host.c_str(), port.c_str(), &hints, &result);
    if (err != 0 || result == nullptr) {
        last_error_ = err;
        ESP_LOGE(TAG, "getaddrinfo failed for %s:%s: %d", parsed.host.c_str(), port.c_str(), err);
        return false;
    }

    socket_fd_ = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    if (socket_fd_ < 0) {
        last_error_ = errno;
        freeaddrinfo(result);
        ESP_LOGE(TAG, "socket create failed: %d", last_error_);
        return false;
    }

    err = connect(socket_fd_, result->ai_addr, result->ai_addrlen);
    freeaddrinfo(result);
    if (err != 0) {
        last_error_ = errno;
        ESP_LOGE(TAG, "connect failed: %d", last_error_);
        Close();
        return false;
    }

    uint8_t key_bytes[16];
    esp_fill_random(key_bytes, sizeof(key_bytes));
    std::string key = base64_encode(key_bytes, sizeof(key_bytes));
    std::string request = "GET " + parsed.path + " HTTP/1.1\r\n";
    request += "Host: " + parsed.host + "\r\n";
    request += "Upgrade: websocket\r\n";
    request += "Connection: Upgrade\r\n";
    request += "Sec-WebSocket-Version: 13\r\n";
    request += "Sec-WebSocket-Key: " + key + "\r\n\r\n";

    if (::send(socket_fd_, request.data(), request.size(), 0) < 0) {
        last_error_ = errno;
        ESP_LOGE(TAG, "handshake send failed: %d", last_error_);
        Close();
        return false;
    }

    std::string response;
    char buffer[512];
    while (response.find("\r\n\r\n") == std::string::npos && response.size() < 4096) {
        int received = recv(socket_fd_, buffer, sizeof(buffer), 0);
        if (received <= 0) {
            last_error_ = errno;
            ESP_LOGE(TAG, "handshake receive failed: %d", last_error_);
            Close();
            return false;
        }
        response.append(buffer, received);
    }

    if (response.find("HTTP/1.1 101") == std::string::npos &&
        response.find("HTTP/1.0 101") == std::string::npos) {
        ESP_LOGE(TAG, "websocket handshake rejected");
        Close();
        return false;
    }

    auto header_end = response.find("\r\n\r\n");
    if (header_end != std::string::npos && header_end + 4 < response.size()) {
        receive_buffer_ = response.substr(header_end + 4);
    }

    connected_ = true;
    xTaskCreatePinnedToCore(ReceiveTaskThunk, "luma_ws_rx", 6144, this, 4, &receive_task_, 0);
    if (on_connected_) {
        on_connected_();
    }
    return true;
}

bool WebSocket::Send(const std::string& data)
{
    return Send(data.data(), data.size(), false);
}

bool WebSocket::Send(const void* data, size_t len, bool binary, bool fin)
{
    if (!connected_ || socket_fd_ < 0 || data == nullptr || len > 65535) {
        return false;
    }

    std::string frame;
    frame.reserve(len + 8);
    uint8_t first_byte = fin ? 0x80 : 0x00;
    if (binary) {
        first_byte |= 0x02;
    } else if (!continuation_) {
        first_byte |= 0x01;
    }
    frame.push_back(static_cast<char>(first_byte));

    if (len < 126) {
        frame.push_back(static_cast<char>(0x80 | len));
    } else {
        frame.push_back(static_cast<char>(0x80 | 126));
        frame.push_back(static_cast<char>((len >> 8) & 0xFF));
        frame.push_back(static_cast<char>(len & 0xFF));
    }

    uint8_t mask[4];
    esp_fill_random(mask, sizeof(mask));
    frame.append(reinterpret_cast<const char*>(mask), sizeof(mask));

    auto* payload = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < len; ++i) {
        frame.push_back(static_cast<char>(payload[i] ^ mask[i % 4]));
    }
    continuation_ = !fin;

    std::lock_guard<std::mutex> lock(send_mutex_);
    size_t sent = 0;
    while (sent < frame.size()) {
        int ret = ::send(socket_fd_, frame.data() + sent, frame.size() - sent, 0);
        if (ret <= 0) {
            last_error_ = errno;
            return false;
        }
        sent += ret;
    }
    return true;
}

void WebSocket::Close()
{
    if (connected_) {
        SendControlFrame(0x8, nullptr, 0);
    }
    connected_ = false;
    if (socket_fd_ >= 0) {
        shutdown(socket_fd_, SHUT_RDWR);
        close(socket_fd_);
        socket_fd_ = -1;
    }
}

void WebSocket::OnConnected(std::function<void()> callback)
{
    on_connected_ = std::move(callback);
}

void WebSocket::OnDisconnected(std::function<void()> callback)
{
    on_disconnected_ = std::move(callback);
}

void WebSocket::OnData(std::function<void(const char*, size_t, bool binary)> callback)
{
    on_data_ = std::move(callback);
}

void WebSocket::OnError(std::function<void(int)> callback)
{
    on_error_ = std::move(callback);
}

int WebSocket::GetLastError() const
{
    return last_error_;
}

void WebSocket::ReceiveTaskThunk(void* arg)
{
    static_cast<WebSocket*>(arg)->ReceiveTask();
    vTaskDelete(nullptr);
}

void WebSocket::ReceiveTask()
{
    if (!receive_buffer_.empty()) {
        std::string pending;
        pending.swap(receive_buffer_);
        HandleIncoming(pending.data(), pending.size());
    }

    char buffer[1500];
    while (connected_ && socket_fd_ >= 0) {
        int received = recv(socket_fd_, buffer, sizeof(buffer), 0);
        if (received <= 0) {
            last_error_ = errno;
            break;
        }
        HandleIncoming(buffer, static_cast<size_t>(received));
    }
    receive_task_ = nullptr;
    NotifyDisconnected();
}

void WebSocket::HandleIncoming(const char* data, size_t len)
{
    receive_buffer_.append(data, len);
    size_t offset = 0;
    const auto* buffer = reinterpret_cast<const uint8_t*>(receive_buffer_.data());
    size_t buffer_size = receive_buffer_.size();

    while (offset < buffer_size) {
        if (buffer_size - offset < 2) {
            break;
        }

        uint8_t opcode = buffer[offset] & 0x0F;
        bool fin = (buffer[offset] & 0x80) != 0;
        uint64_t payload_length = buffer[offset + 1] & 0x7F;
        size_t header_length = 2;

        if (payload_length == 126) {
            if (buffer_size - offset < 4) {
                break;
            }
            payload_length = (static_cast<uint64_t>(buffer[offset + 2]) << 8) | buffer[offset + 3];
            header_length += 2;
        } else if (payload_length == 127) {
            if (buffer_size - offset < 10) {
                break;
            }
            payload_length = 0;
            for (int i = 0; i < 8; ++i) {
                payload_length = (payload_length << 8) | buffer[offset + 2 + i];
            }
            header_length += 8;
        }

        bool masked = (buffer[offset + 1] & 0x80) != 0;
        uint8_t mask_key[4] = {};
        if (masked) {
            if (buffer_size - offset < header_length + 4) {
                break;
            }
            memcpy(mask_key, buffer + offset + header_length, sizeof(mask_key));
            header_length += 4;
        }

        if (payload_length > 512 * 1024 || buffer_size - offset < header_length + payload_length) {
            break;
        }

        std::vector<char> payload(static_cast<size_t>(payload_length));
        if (payload_length > 0) {
            memcpy(payload.data(), buffer + offset + header_length, static_cast<size_t>(payload_length));
            if (masked) {
                for (size_t i = 0; i < payload.size(); ++i) {
                    payload[i] ^= mask_key[i % 4];
                }
            }
        }

        switch (opcode) {
            case 0x0:
            case 0x1:
            case 0x2:
                if (opcode != 0x0) {
                    is_fragmented_ = !fin;
                    is_binary_ = opcode == 0x2;
                    current_message_.clear();
                }
                current_message_.insert(current_message_.end(), payload.begin(), payload.end());
                if (fin) {
                    if (on_data_) {
                        on_data_(current_message_.data(), current_message_.size(), is_binary_);
                    }
                    current_message_.clear();
                    is_fragmented_ = false;
                }
                break;
            case 0x8:
                connected_ = false;
                break;
            case 0x9:
                SendControlFrame(0xA, payload.data(), payload.size());
                break;
            case 0xA:
                break;
            default:
                ESP_LOGW(TAG, "unsupported opcode: %u", opcode);
                break;
        }

        offset += header_length + static_cast<size_t>(payload_length);
    }

    if (offset > 0) {
        receive_buffer_ = receive_buffer_.substr(offset);
    }
}

bool WebSocket::SendControlFrame(uint8_t opcode, const void* data, size_t len)
{
    if (len > 125 || socket_fd_ < 0) {
        return false;
    }

    std::string frame;
    frame.reserve(len + 6);
    frame.push_back(static_cast<char>(0x80 | opcode));
    frame.push_back(static_cast<char>(0x80 | len));

    uint8_t mask[4];
    esp_fill_random(mask, sizeof(mask));
    frame.append(reinterpret_cast<const char*>(mask), sizeof(mask));

    const auto* payload = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < len; ++i) {
        frame.push_back(static_cast<char>(payload[i] ^ mask[i % 4]));
    }

    std::lock_guard<std::mutex> lock(send_mutex_);
    return ::send(socket_fd_, frame.data(), frame.size(), 0) == static_cast<int>(frame.size());
}

void WebSocket::NotifyDisconnected()
{
    const bool was_connected = connected_;
    connected_ = false;
    if (socket_fd_ >= 0) {
        shutdown(socket_fd_, SHUT_RDWR);
        close(socket_fd_);
        socket_fd_ = -1;
    }
    if (was_connected && on_disconnected_) {
        on_disconnected_();
    }
    if (!was_connected && on_error_) {
        on_error_(last_error_);
    }
}
