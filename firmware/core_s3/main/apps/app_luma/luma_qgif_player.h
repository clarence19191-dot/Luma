/*
 * Project Luma V0 qgif player.
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <lvgl.h>
#include <string>
#include <string_view>
#include <vector>

namespace luma {

class LumaQgifPlayer {
public:
    LumaQgifPlayer() = default;
    ~LumaQgifPlayer();

    bool init(lv_obj_t* parent, uint16_t target_width = 320, uint16_t target_height = 240);
    void close();
    bool play(std::string_view asset_name, uint32_t duration_ms = 0);
    bool playBytes(std::string_view asset_name, const uint8_t* data, size_t size, uint32_t duration_ms = 0);
    void stop();
    void update(uint32_t now_ms);
    bool visible() const;

private:
    struct AssetView {
        const uint8_t* data = nullptr;
        size_t size         = 0;
        uint8_t frame_count = 0;
        uint16_t width      = 0;
        uint16_t height     = 0;
        const uint8_t* delays = nullptr;
        const uint8_t* frames  = nullptr;
        size_t row_bytes       = 0;
        size_t frame_bytes     = 0;
    };

    lv_obj_t* _image = nullptr;
    lv_image_dsc_t _image_dsc = {};
    uint16_t* _framebuffer = nullptr;
    uint16_t _target_width = 320;
    uint16_t _target_height = 240;
    AssetView _asset;
    std::vector<uint8_t> _asset_storage;
    std::string _asset_name;
    uint8_t _frame_index = 0;
    uint32_t _last_frame_ms = 0;
    uint32_t _expires_at_ms = 0;
    bool _playing = false;

    bool setAsset(std::string_view asset_name, const uint8_t* data, size_t size);
    bool parseAsset(const uint8_t* data, size_t size, AssetView& out);
    void renderFrame(uint8_t frame_index);
    bool sourcePixelOn(uint8_t frame_index, uint16_t x, uint16_t y) const;
    uint16_t frameDelayMs(uint8_t frame_index) const;
};

}  // namespace luma
