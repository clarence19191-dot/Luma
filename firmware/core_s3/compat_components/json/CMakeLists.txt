# Compatibility component for older third-party dependencies that still
# require ESP-IDF's pre-v6 "json" component name.
idf_component_register(REQUIRES espressif__cjson)
