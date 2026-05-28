set(LUMA_MAIN_DIR "${CMAKE_CURRENT_LIST_DIR}")
set(LUMA_PROJECT_DIR "${LUMA_MAIN_DIR}/..")

set(LUMA_SOURCES
    "main.cpp"
    "apps/app_luma/app_luma.cpp"
    "apps/app_luma/luma_qgif_player.cpp"
    "apps/app_luma/luma_voice_runtime.cpp"
    "apps/app_luma/luma_ws_client.cpp"
    "hal/audio.cpp"
    "hal/compat_newlib_ctype.c"
    "hal/hal.cpp"
    "hal/hal_head_touch.cpp"
    "hal/hal_io_expander.cpp"
    "hal/hal_network.cpp"
    "hal/hal_rtc.cpp"
    "hal/board/cores3_audio_codec.cc"
    "hal/board/hal_bridge.cc"
    "hal/drivers/PCF8563_Class/PCF8563_Class.cpp"
    "hal/drivers/PY32IOExpander_Class/PY32IOExpander_Class.cpp"
    "hal/drivers/Si12T/Si12T.cpp"
    "luma_platform/audio_codec.cpp"
    "luma_platform/axp2101.cpp"
    "luma_platform/backlight.cpp"
    "luma_platform/board.cpp"
    "luma_platform/i2c_device.cpp"
    "luma_platform/net/network.cpp"
    "luma_platform/net/web_socket.cpp"
    "luma_platform/settings.cpp"
    "luma_platform/system_info.cpp"
)

idf_component_register(
    SRCS ${LUMA_SOURCES}
    INCLUDE_DIRS
        "${LUMA_MAIN_DIR}"
        "${LUMA_PROJECT_DIR}/include"
    PRIV_REQUIRES
        ArduinoJson
        app_update
        esp_app_format
        esp_driver_gpio
        esp_driver_i2c
        esp_driver_i2s
        esp_driver_spi
        esp_event
        esp_lcd
        esp_netif
        esp_pm
        esp_psram
        esp_wifi
        esp-tls
        esp_lvgl_port
        lvgl
        mooncake
        mooncake_log
        nvs_flash
        smooth_ui_toolkit
        esp_audio_codec
        esp_codec_dev
        esp_lcd_ili9341
)

target_compile_definitions(${COMPONENT_LIB}
    PRIVATE
        "BOARD_TYPE=\"luma-core-s3\""
        "BOARD_NAME=\"Project Luma CoreS3\""
)

target_compile_options(${COMPONENT_LIB}
    PRIVATE
        -Wno-error
)
