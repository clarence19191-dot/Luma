/*
 * SPDX-FileCopyrightText: 2026 Project Luma contributors
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <lvgl.h>

class Display {
public:
    virtual ~Display() = default;

    virtual void SetPowerSaveMode(bool on) = 0;
    virtual bool Lock(int timeout_ms = 0) = 0;
    virtual void Unlock() = 0;
    virtual lv_display_t* GetLvglDisplay() = 0;

    int width() const { return width_; }
    int height() const { return height_; }

protected:
    int width_ = 0;
    int height_ = 0;
};

class DisplayLockGuard {
public:
    explicit DisplayLockGuard(Display* display) : display_(display)
    {
        if (display_ != nullptr) {
            display_->Lock(30000);
        }
    }

    ~DisplayLockGuard()
    {
        if (display_ != nullptr) {
            display_->Unlock();
        }
    }

private:
    Display* display_ = nullptr;
};
