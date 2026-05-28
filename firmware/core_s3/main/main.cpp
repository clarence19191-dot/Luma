/*
 * Project Luma CoreS3 firmware entrypoint.
 */
#include <apps/app_luma/app_luma.h>
#include <hal/hal.h>
#include <mooncake.h>
#include <mooncake_log.h>
#include <smooth_ui_toolkit.hpp>
#include <uitk/short_namespace.hpp>

using namespace mooncake;
using namespace smooth_ui_toolkit;

extern "C" void app_main(void)
{
    mclog::set_level(mclog::level_info);
    mclog::set_time_format(mclog::time_format_unix_milliseconds);

    GetHAL().init();

    ui_hal::on_delay([](uint32_t ms) { GetHAL().delay(ms); });
    ui_hal::on_get_tick([]() { return GetHAL().millis(); });

    const int luma_app_id = GetMooncake().installApp(std::make_unique<AppLuma>());
    GetMooncake().openApp(luma_app_id);

    while (true) {
        GetHAL().feedTheDog();
        GetHAL().updateHeapStatusLog();
        GetMooncake().update();
        GetHAL().delay(5);
    }
}
