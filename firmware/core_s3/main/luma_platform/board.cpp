/*
 * SPDX-FileCopyrightText: 2024-2026 M5Stack Technology CO LTD
 * SPDX-FileCopyrightText: 2024-2026 78 contributors
 * SPDX-FileCopyrightText: 2026 Project Luma contributors
 *
 * SPDX-License-Identifier: MIT AND Apache-2.0
 */
#include "luma_platform/board.h"

#include "hal/board/config.h"
#include "hal/board/cores3_audio_codec.h"
#include "luma_platform/axp2101.h"
#include "luma_platform/i2c_device.h"
#include "luma_platform/settings.h"

#include <driver/spi_master.h>
#include <esp_check.h>
#include <esp_lcd_ili9341.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_log.h>
#include <esp_lvgl_port.h>
#include <esp_random.h>
#include <esp_wifi.h>

#include <algorithm>
#include <memory>
#include <vector>

namespace {

constexpr const char* TAG = "LumaCoreS3";
constexpr uint8_t kPmicAddr = 0x34;
constexpr uint8_t kAw9523Addr = 0x58;

class Pmic : public Axp2101 {
public:
    enum ChargeCurrent : uint8_t {
        CHG_CUR_700MA = 10,
        CHG_CUR_1000MA = 13,
    };

    Pmic(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : Axp2101(i2c_bus, addr)
    {
        uint8_t data = ReadReg(0x90);
        WriteReg(0x90, data | 0b10110100);
        WriteReg(0x97, 0b11110 - 2);
        WriteReg(0x69, 0b00110101);
        WriteReg(0x30, 0b111111);
        WriteReg(0x90, 0xBF);
        WriteReg(0x94, 33 - 5);
        WriteReg(0x95, 33 - 5);
        WriteReg(0x27, 0x00);
        setChargerConstantCurr(CHG_CUR_700MA);
        SetDisplayBrightness(0);
    }

    void SetDisplayBrightness(uint8_t brightness)
    {
        if (brightness == 0) {
            uint8_t value = ReadReg(0x90);
            WriteReg(0x90, value & 0x7F);
            return;
        }

        brightness = std::min<uint8_t>(brightness, 100);
        uint8_t reg_val = 20 + (static_cast<uint16_t>(brightness) * 8 / 100);
        WriteReg(0x99, reg_val);

        uint8_t value = ReadReg(0x90);
        if ((value & 0x80) == 0) {
            WriteReg(0x90, value | 0x80);
        }
    }

    bool IsExternalPowerConnected()
    {
        const uint8_t power_status = ReadReg(0x01);
        const uint8_t current_direction = (power_status & 0b01100000) >> 5;
        const bool is_charging_done = (power_status & 0b00000111) == 0b00000100;
        return current_direction != 2 || is_charging_done;
    }

private:
    bool setChargerConstantCurr(uint8_t value)
    {
        if (value > CHG_CUR_1000MA) {
            return false;
        }
        int reg = ReadReg(0x62);
        reg &= 0xE0;
        WriteReg(0x62, reg | value);
        return true;
    }
};

class PmicBacklight : public Backlight {
public:
    explicit PmicBacklight(Pmic* pmic) : pmic_(pmic)
    {
    }

private:
    void SetBrightnessImpl(uint8_t brightness) override
    {
        pmic_->SetDisplayBrightness(brightness);
    }

    Pmic* pmic_ = nullptr;
};

class Aw9523 : public I2cDevice {
public:
    Aw9523(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr)
    {
        WriteReg(0x02, 0b00000111);
        WriteReg(0x03, 0b10001111);
        WriteReg(0x04, 0b00011000);
        WriteReg(0x05, 0b00001100);
        WriteReg(0x11, 0b00010000);
        WriteReg(0x12, 0b11111111);
        WriteReg(0x13, 0b11111111);
    }

    void ResetAw88298()
    {
        WriteReg(0x02, 0b00000011);
        vTaskDelay(pdMS_TO_TICKS(10));
        WriteReg(0x02, 0b00000111);
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    void ResetIli9342()
    {
        WriteReg(0x03, 0b10000001);
        vTaskDelay(pdMS_TO_TICKS(20));
        WriteReg(0x03, 0b10000011);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
};

class LumaLvglDisplay : public Display {
public:
    LumaLvglDisplay(esp_lcd_panel_io_handle_t panel_io,
                    esp_lcd_panel_handle_t panel,
                    int width,
                    int height,
                    bool mirror_x,
                    bool mirror_y,
                    bool swap_xy)
        : panel_io_(panel_io), panel_(panel)
    {
        width_ = width;
        height_ = height;

        std::vector<uint16_t> line(width_, 0x0000);
        for (int y = 0; y < height_; ++y) {
            esp_lcd_panel_draw_bitmap(panel_, 0, y, width_, y + 1, line.data());
        }

        esp_err_t err = esp_lcd_panel_disp_on_off(panel_, true);
        if (err != ESP_ERR_NOT_SUPPORTED) {
            ESP_ERROR_CHECK(err);
        }

        lv_init();
        lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
        port_cfg.task_priority = 3;
#if CONFIG_SOC_CPU_CORES_NUM > 1
        port_cfg.task_affinity = 1;
#endif
        ESP_ERROR_CHECK(lvgl_port_init(&port_cfg));

        const lvgl_port_display_cfg_t display_cfg = {
            .io_handle = panel_io_,
            .panel_handle = panel_,
            .control_handle = nullptr,
            .buffer_size = static_cast<uint32_t>(width_ * 20),
            .double_buffer = false,
            .trans_size = 0,
            .hres = static_cast<uint32_t>(width_),
            .vres = static_cast<uint32_t>(height_),
            .monochrome = false,
            .rotation = {
                .swap_xy = swap_xy,
                .mirror_x = mirror_x,
                .mirror_y = mirror_y,
            },
            .color_format = LV_COLOR_FORMAT_RGB565,
            .flags = {
                .buff_dma = 1,
                .buff_spiram = 0,
                .sw_rotate = 0,
                .swap_bytes = 1,
                .full_refresh = 0,
                .direct_mode = 0,
            },
        };

        display_ = lvgl_port_add_disp(&display_cfg);
        ESP_ERROR_CHECK(display_ == nullptr ? ESP_FAIL : ESP_OK);
    }

    void SetPowerSaveMode(bool on) override
    {
        if (panel_ != nullptr) {
            esp_lcd_panel_disp_on_off(panel_, !on);
        }
    }

    bool Lock(int timeout_ms = 0) override
    {
        return lvgl_port_lock(timeout_ms);
    }

    void Unlock() override
    {
        lvgl_port_unlock();
    }

    lv_display_t* GetLvglDisplay() override
    {
        return display_;
    }

private:
    esp_lcd_panel_io_handle_t panel_io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    lv_display_t* display_ = nullptr;
};

class CoreS3Board : public Board {
public:
    CoreS3Board()
    {
        InitializeI2c();
        pmic_ = std::make_unique<Pmic>(i2c_bus_, kPmicAddr);
        backlight_ = std::make_unique<PmicBacklight>(pmic_.get());
        aw9523_ = std::make_unique<Aw9523>(i2c_bus_, kAw9523Addr);
        aw9523_->ResetAw88298();
        InitializeDisplay();
        backlight_->RestoreBrightness();
    }

    std::string GetBoardType() override
    {
        return "luma-core-s3";
    }

    std::string GetUuid() override
    {
        return uuid_;
    }

    Backlight* GetBacklight() override
    {
        return backlight_.get();
    }

    AudioCodec* GetAudioCodec() override
    {
        static CoreS3AudioCodec audio_codec(i2c_bus_,
                                            AUDIO_INPUT_SAMPLE_RATE,
                                            AUDIO_OUTPUT_SAMPLE_RATE,
                                            AUDIO_I2S_GPIO_MCLK,
                                            AUDIO_I2S_GPIO_BCLK,
                                            AUDIO_I2S_GPIO_WS,
                                            AUDIO_I2S_GPIO_DOUT,
                                            AUDIO_I2S_GPIO_DIN,
                                            AUDIO_CODEC_AW88298_ADDR,
                                            AUDIO_CODEC_ES7210_ADDR,
                                            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    Display* GetDisplay() override
    {
        return display_.get();
    }

    LumaNetwork* GetNetwork() override
    {
        return &network_;
    }

    void StartNetwork() override
    {
        network_.Start();
    }

    void SetNetworkEventCallback(NetworkEventCallback callback) override
    {
        network_.SetEventCallback(std::move(callback));
    }

    const char* GetNetworkStateIcon() override
    {
        if (network_.IsConfigMode() || !network_.IsConnected()) {
            return "none";
        }
        if (network_.GetRssi() >= -65) {
            return "high";
        }
        if (network_.GetRssi() >= -75) {
            return "medium";
        }
        return "low";
    }

    bool GetBatteryLevel(int& level, bool& charging, bool& discharging) override
    {
        charging = pmic_->IsCharging();
        discharging = pmic_->IsDischarging();
        level = pmic_->GetBatteryLevel();
        return true;
    }

    void SetPowerSaveLevel(PowerSaveLevel level) override
    {
        wifi_ps_type_t ps = WIFI_PS_NONE;
        if (level == PowerSaveLevel::LOW_POWER) {
            ps = WIFI_PS_MAX_MODEM;
        } else if (level == PowerSaveLevel::BALANCED) {
            ps = WIFI_PS_MIN_MODEM;
        }
        esp_wifi_set_ps(ps);
    }

    i2c_master_bus_handle_t GetI2cBus() override
    {
        return i2c_bus_;
    }

    void SetWifiCredentials(std::string ssid, std::string password) override
    {
        network_.SetCredentials(std::move(ssid), std::move(password));
    }

private:
    i2c_master_bus_handle_t i2c_bus_ = nullptr;
    std::unique_ptr<Pmic> pmic_;
    std::unique_ptr<PmicBacklight> backlight_;
    std::unique_ptr<Aw9523> aw9523_;
    std::unique_ptr<LumaLvglDisplay> display_;
    LumaNetwork network_;

    void InitializeI2c()
    {
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = static_cast<i2c_port_t>(1),
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {
                .enable_internal_pullup = 1,
            },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));
    }

    void InitializeDisplay()
    {
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = GPIO_NUM_37;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = GPIO_NUM_36;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));

        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = GPIO_NUM_3;
        io_config.dc_gpio_num = GPIO_NUM_35;
        io_config.spi_mode = 2;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &panel_io));

        esp_lcd_panel_handle_t panel = nullptr;
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR;
        panel_config.bits_per_pixel = 16;
        ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(panel_io, &panel_config, &panel));

        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        aw9523_->ResetIli9342();
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, true));
        ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y));

        display_ = std::make_unique<LumaLvglDisplay>(panel_io,
                                                     panel,
                                                     DISPLAY_WIDTH,
                                                     DISPLAY_HEIGHT,
                                                     DISPLAY_MIRROR_X,
                                                     DISPLAY_MIRROR_Y,
                                                     DISPLAY_SWAP_XY);
    }
};

}  // namespace

Board::Board()
{
    Settings settings("board", true);
    uuid_ = settings.GetString("uuid");
    if (uuid_.empty()) {
        uuid_ = GenerateUuid();
        settings.SetString("uuid", uuid_);
    }
    ESP_LOGI(TAG, "UUID=%s", uuid_.c_str());
}

std::string Board::GenerateUuid()
{
    uint8_t uuid[16];
    esp_fill_random(uuid, sizeof(uuid));
    uuid[6] = (uuid[6] & 0x0F) | 0x40;
    uuid[8] = (uuid[8] & 0x3F) | 0x80;

    char uuid_str[37];
    snprintf(uuid_str,
             sizeof(uuid_str),
             "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
             uuid[0],
             uuid[1],
             uuid[2],
             uuid[3],
             uuid[4],
             uuid[5],
             uuid[6],
             uuid[7],
             uuid[8],
             uuid[9],
             uuid[10],
             uuid[11],
             uuid[12],
             uuid[13],
             uuid[14],
             uuid[15]);
    return std::string(uuid_str);
}

Board& Board::GetInstance()
{
    static CoreS3Board board;
    return board;
}
