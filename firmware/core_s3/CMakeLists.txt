# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "1.4.1")
add_definitions(-DFIRMWARE_VERSION=\"${PROJECT_VER}\")
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.luma.defaults")
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/compat_components/json")
set(EXCLUDE_COMPONENTS esp-now espressif__bmi270_sensor)

# Add this line to disable the specific warning
add_compile_options(-Wno-missing-field-initializers)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(project-luma-core-s3)
