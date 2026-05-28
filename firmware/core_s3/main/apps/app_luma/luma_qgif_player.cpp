/*
 * Project Luma V0 qgif player.
 */
#include "luma_qgif_player.h"

#include <cstring>
#include <esp_heap_caps.h>
#include <mooncake_log.h>

namespace {

constexpr const char* TAG = "LumaQgif";
constexpr uint16_t COLOR_BLACK = 0x0000;
constexpr uint16_t COLOR_WHITE = 0xFFFF;

uint16_t read_u16_le(const uint8_t* ptr)
{
    return static_cast<uint16_t>(ptr[0]) | (static_cast<uint16_t>(ptr[1]) << 8);
}

}  // namespace

namespace luma {

LumaQgifPlayer::~LumaQgifPlayer()
{
    close();
}

bool LumaQgifPlayer::init(lv_obj_t* parent, uint16_t target_width, uint16_t target_height)
{
    close();
    _target_width  = target_width;
    _target_height = target_height;

    const size_t framebuffer_bytes = static_cast<size_t>(_target_width) * _target_height * sizeof(uint16_t);
    _framebuffer = static_cast<uint16_t*>(heap_caps_malloc(framebuffer_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!_framebuffer) {
        _framebuffer = static_cast<uint16_t*>(heap_caps_malloc(framebuffer_bytes, MALLOC_CAP_8BIT));
    }
    if (!_framebuffer) {
        mclog::tagError(TAG, "failed to allocate {} bytes framebuffer", framebuffer_bytes);
        return false;
    }

    std::memset(_framebuffer, 0xFF, framebuffer_bytes);
    _image_dsc.header.cf    = LV_COLOR_FORMAT_RGB565;
    _image_dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    _image_dsc.header.w     = _target_width;
    _image_dsc.header.h     = _target_height;
    _image_dsc.data_size    = framebuffer_bytes;
    _image_dsc.data         = reinterpret_cast<const uint8_t*>(_framebuffer);

    _image = lv_image_create(parent);
    if (!_image) {
        heap_caps_free(_framebuffer);
        _framebuffer = nullptr;
        return false;
    }
    lv_obj_set_size(_image, _target_width, _target_height);
    lv_obj_align(_image, LV_ALIGN_CENTER, 0, 0);
    lv_image_set_src(_image, &_image_dsc);
    lv_obj_add_flag(_image, LV_OBJ_FLAG_HIDDEN);
    return true;
}

void LumaQgifPlayer::close()
{
    if (_image) {
        lv_obj_del(_image);
        _image = nullptr;
    }
    if (_framebuffer) {
        heap_caps_free(_framebuffer);
        _framebuffer = nullptr;
    }
    _asset = {};
    _asset_storage.clear();
    _asset_name.clear();
    _playing = false;
}

bool LumaQgifPlayer::play(std::string_view asset_name, uint32_t duration_ms)
{
    if (!_image || !_framebuffer) {
        return false;
    }
    if (std::string_view(_asset_name.data(), _asset_name.size()) != asset_name || !_asset.data) {
        return false;
    }

    _frame_index   = 0;
    _last_frame_ms = lv_tick_get();
    _expires_at_ms = duration_ms > 0 ? _last_frame_ms + duration_ms : 0;
    _playing       = true;

    renderFrame(_frame_index);
    lv_image_set_src(_image, &_image_dsc);
    lv_obj_remove_flag(_image, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(_image);
    return true;
}

bool LumaQgifPlayer::playBytes(std::string_view asset_name, const uint8_t* data, size_t size, uint32_t duration_ms)
{
    if (!_image || !_framebuffer || !setAsset(asset_name, data, size)) {
        return false;
    }
    return play(asset_name, duration_ms);
}

void LumaQgifPlayer::stop()
{
    _playing = false;
    if (_image) {
        lv_obj_add_flag(_image, LV_OBJ_FLAG_HIDDEN);
    }
}

void LumaQgifPlayer::update(uint32_t now_ms)
{
    if (!_playing || !_asset.data || _asset.frame_count == 0) {
        return;
    }
    if (_expires_at_ms > 0 && static_cast<int32_t>(now_ms - _expires_at_ms) >= 0) {
        stop();
        return;
    }

    const uint16_t delay = frameDelayMs(_frame_index);
    if (static_cast<uint32_t>(now_ms - _last_frame_ms) < delay) {
        return;
    }
    _last_frame_ms = now_ms;
    _frame_index   = static_cast<uint8_t>((_frame_index + 1) % _asset.frame_count);
    renderFrame(_frame_index);
    if (_image) {
        lv_obj_invalidate(_image);
    }
}

bool LumaQgifPlayer::visible() const
{
    return _playing && _image && !lv_obj_has_flag(_image, LV_OBJ_FLAG_HIDDEN);
}

bool LumaQgifPlayer::setAsset(std::string_view asset_name, const uint8_t* data, size_t size)
{
    if (!data || size == 0) {
        return false;
    }
    _asset_storage.assign(data, data + size);

    AssetView parsed;
    if (!parseAsset(_asset_storage.data(), _asset_storage.size(), parsed)) {
        mclog::tagWarn(TAG, "invalid streamed qgif {} size {}", asset_name, size);
        _asset_storage.clear();
        _asset = {};
        return false;
    }
    _asset = parsed;
    _asset_name.assign(asset_name.data(), asset_name.size());
    mclog::tagInfo(TAG, "streamed {}: {}x{} {} frames", asset_name, _asset.width, _asset.height, _asset.frame_count);
    return true;
}

bool LumaQgifPlayer::parseAsset(const uint8_t* data, size_t size, AssetView& out)
{
    if (!data || size < 5) {
        return false;
    }
    const uint8_t frame_count = data[0];
    const uint16_t width      = read_u16_le(data + 1);
    const uint16_t height     = read_u16_le(data + 3);
    if (frame_count == 0 || width == 0 || height == 0) {
        return false;
    }

    const size_t header_bytes = 5 + static_cast<size_t>(frame_count) * 2;
    const size_t row_bytes    = (static_cast<size_t>(width) + 7) / 8;
    const size_t frame_bytes  = row_bytes * height;
    const size_t expected     = header_bytes + static_cast<size_t>(frame_count) * frame_bytes;
    if (size != expected) {
        return false;
    }

    out.data        = data;
    out.size        = size;
    out.frame_count = frame_count;
    out.width       = width;
    out.height      = height;
    out.delays      = data + 5;
    out.frames      = data + header_bytes;
    out.row_bytes   = row_bytes;
    out.frame_bytes = frame_bytes;
    return true;
}

void LumaQgifPlayer::renderFrame(uint8_t frame_index)
{
    if (!_framebuffer || !_asset.data || _asset.width == 0 || _asset.height == 0) {
        return;
    }

    const uint32_t src_w = _asset.width;
    const uint32_t src_h = _asset.height;
    uint32_t draw_w      = _target_width;
    uint32_t draw_h      = (src_h * _target_width) / src_w;
    if (draw_h > _target_height) {
        draw_h = _target_height;
        draw_w = (src_w * _target_height) / src_h;
    }
    if (draw_w == 0 || draw_h == 0) {
        return;
    }

    const uint32_t x_offset = (_target_width - draw_w) / 2;
    const uint32_t y_offset = (_target_height - draw_h) / 2;

    const size_t pixel_count = static_cast<size_t>(_target_width) * _target_height;
    for (size_t i = 0; i < pixel_count; ++i) {
        _framebuffer[i] = COLOR_WHITE;
    }

    for (uint32_t y = 0; y < draw_h; ++y) {
        const uint16_t src_y = static_cast<uint16_t>((y * src_h) / draw_h);
        uint16_t* dst        = _framebuffer + (y + y_offset) * _target_width + x_offset;
        for (uint32_t x = 0; x < draw_w; ++x) {
            const uint16_t src_x = static_cast<uint16_t>((x * src_w) / draw_w);
            dst[x] = sourcePixelOn(frame_index, src_x, src_y) ? COLOR_BLACK : COLOR_WHITE;
        }
    }
}

bool LumaQgifPlayer::sourcePixelOn(uint8_t frame_index, uint16_t x, uint16_t y) const
{
    if (!_asset.frames || frame_index >= _asset.frame_count || x >= _asset.width || y >= _asset.height) {
        return false;
    }
    const uint8_t* frame = _asset.frames + static_cast<size_t>(frame_index) * _asset.frame_bytes;
    const uint8_t byte   = frame[static_cast<size_t>(y) * _asset.row_bytes + x / 8];
    return (byte & (1 << (7 - (x % 8)))) != 0;
}

uint16_t LumaQgifPlayer::frameDelayMs(uint8_t frame_index) const
{
    if (!_asset.delays || frame_index >= _asset.frame_count) {
        return 100;
    }
    const uint16_t delay = read_u16_le(_asset.delays + static_cast<size_t>(frame_index) * 2);
    if (delay < 10) {
        return 10;
    }
    if (delay > 5000) {
        return 5000;
    }
    return delay;
}

}  // namespace luma
