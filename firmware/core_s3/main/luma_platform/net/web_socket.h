/*
 * SPDX-FileCopyrightText: 2024-2026 78/esp-ml307 contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <functional>
#include <mutex>
#include <string>
#include <vector>

class WebSocket {
public:
    WebSocket();
    ~WebSocket();

    bool IsConnected() const;
    bool Connect(const char* uri);
    bool Send(const std::string& data);
    bool Send(const void* data, size_t len, bool binary = false, bool fin = true);
    void Close();

    void OnConnected(std::function<void()> callback);
    void OnDisconnected(std::function<void()> callback);
    void OnData(std::function<void(const char*, size_t, bool binary)> callback);
    void OnError(std::function<void(int)> callback);
    int GetLastError() const;

private:
    int socket_fd_ = -1;
    bool connected_ = false;
    bool continuation_ = false;
    int last_error_ = 0;
    TaskHandle_t receive_task_ = nullptr;
    std::mutex send_mutex_;
    std::string receive_buffer_;
    std::vector<char> current_message_;
    bool is_fragmented_ = false;
    bool is_binary_ = false;

    std::function<void(const char*, size_t, bool binary)> on_data_;
    std::function<void(int)> on_error_;
    std::function<void()> on_connected_;
    std::function<void()> on_disconnected_;

    static void ReceiveTaskThunk(void* arg);
    void ReceiveTask();
    void HandleIncoming(const char* data, size_t len);
    bool SendControlFrame(uint8_t opcode, const void* data, size_t len);
    void NotifyDisconnected();
};
