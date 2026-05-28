from pathlib import Path

Import("env")

framework_dir = env.PioPlatform().get_package_dir("framework-espidf")

if framework_dir:
    version_file = Path(framework_dir) / "version.txt"
    if version_file.exists():
        idf_version = version_file.read_text(encoding="utf-8").strip()
        env["ENV"]["IDF_VERSION"] = idf_version
        env["ENV"]["ESP_IDF_VERSION"] = idf_version

    # Keep these include paths explicit for PlatformIO's ESP-IDF wrapper. The
    # script intentionally does not patch managed components or tracked source.
    env.Append(
        CPPPATH=[
            str(Path(framework_dir) / "components" / "esp_driver_dma" / "include"),
            str(Path(framework_dir) / "components" / "esp_driver_i2c" / "include"),
        ]
    )
