cmake_minimum_required(VERSION 3.18)
project(r1_factory_audio_agent LANGUAGES CXX)

add_executable(r1-factory-audio-agent
  src/main.cpp
  src/audio_backend.cpp
  src/safe_vendor_system.cpp
)
target_compile_features(r1-factory-audio-agent PRIVATE cxx_std_17)
target_compile_options(r1-factory-audio-agent PRIVATE -Wall -Wextra -Werror)
target_link_options(r1-factory-audio-agent PRIVATE
  "-Wl,--hash-style=both"
  "-Wl,--export-dynamic"
)
target_link_libraries(r1-factory-audio-agent PRIVATE dl)

if(NOT ANDROID)
  target_compile_definitions(r1-factory-audio-agent PRIVATE R1_FACTORY_AUDIO_HOST_TEST=1)
  add_library(r1-factory-audio-vendor-mock SHARED tests/vendor_mock.cpp)
endif()

if(ANDROID)
  if(NOT ANDROID_ABI STREQUAL "armeabi-v7a")
    message(FATAL_ERROR "The R1 agent must be built for armeabi-v7a")
  endif()
  if(CMAKE_SYSTEM_VERSION VERSION_GREATER "22")
    message(FATAL_ERROR "The R1 agent must remain compatible with API 22")
  endif()
endif()
