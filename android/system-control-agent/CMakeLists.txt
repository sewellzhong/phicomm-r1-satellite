cmake_minimum_required(VERSION 3.18)
project(r1_system_control LANGUAGES CXX)

add_library(r1-system-control-core STATIC
  src/system_control.cpp
)
target_include_directories(r1-system-control-core PUBLIC src)
target_compile_features(r1-system-control-core PUBLIC cxx_std_17)
target_compile_options(r1-system-control-core PRIVATE -Wall -Wextra -Werror)

if(NOT ANDROID)
  enable_testing()
  add_executable(r1-system-control-test tests/system_control_test.cpp)
  target_link_libraries(r1-system-control-test PRIVATE r1-system-control-core)
  target_compile_options(r1-system-control-test PRIVATE -Wall -Wextra -Werror)
  add_test(NAME r1-system-control-test COMMAND r1-system-control-test)
endif()

if(ANDROID)
  if(NOT ANDROID_ABI STREQUAL "armeabi-v7a")
    message(FATAL_ERROR "The R1 system-control components require armeabi-v7a")
  endif()
  if(CMAKE_SYSTEM_VERSION VERSION_GREATER "22")
    message(FATAL_ERROR "The R1 system-control components require API 22 compatibility")
  endif()

  add_executable(r1-system-control-agent src/main.cpp)
  target_link_libraries(r1-system-control-agent PRIVATE r1-system-control-core log)
  target_compile_features(r1-system-control-agent PRIVATE cxx_std_17)
  target_compile_options(r1-system-control-agent PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1-system-control-agent PRIVATE "-Wl,--hash-style=both" "-Wl,--gc-sections")

  add_library(r1_system_control_client SHARED src/client_jni.cpp)
  target_link_libraries(r1_system_control_client PRIVATE r1-system-control-core)
  target_compile_features(r1_system_control_client PRIVATE cxx_std_17)
  target_compile_options(r1_system_control_client PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1_system_control_client PRIVATE "-Wl,--hash-style=both" "-Wl,--gc-sections")
endif()
