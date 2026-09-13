cmake_minimum_required(VERSION 3.18)
project(r1_update_agent LANGUAGES CXX)

add_library(r1-update-policy STATIC
  src/android_package_manager_backend.cpp
  src/package_orchestrator.cpp
  src/update_protocol.cpp
  src/update_policy.cpp
  src/update_runtime.cpp
  src/update_supervisor.cpp
)
target_include_directories(r1-update-policy PUBLIC src)
target_compile_features(r1-update-policy PUBLIC cxx_std_17)
target_compile_options(r1-update-policy PRIVATE -Wall -Wextra -Werror)
if(ANDROID)
  target_compile_options(r1-update-policy PRIVATE -ffunction-sections -fdata-sections)
  set_target_properties(r1-update-policy PROPERTIES
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)
endif()

if(NOT ANDROID)
  enable_testing()
  add_executable(r1-update-policy-test tests/update_policy_test.cpp)
  target_link_libraries(r1-update-policy-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-policy-test PRIVATE -Wall -Wextra -Werror)
  add_test(NAME r1-update-policy-test COMMAND r1-update-policy-test)

  add_executable(r1-update-runtime-test tests/update_runtime_test.cpp)
  target_link_libraries(r1-update-runtime-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-runtime-test PRIVATE -Wall -Wextra -Werror)
  add_test(NAME r1-update-runtime-test COMMAND r1-update-runtime-test)

  add_executable(r1-update-orchestrator-test tests/package_orchestrator_test.cpp)
  target_link_libraries(r1-update-orchestrator-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-orchestrator-test PRIVATE -Wall -Wextra -Werror)
  add_test(NAME r1-update-orchestrator-test COMMAND r1-update-orchestrator-test)

  add_executable(r1-update-protocol-test tests/update_protocol_test.cpp)
  target_link_libraries(r1-update-protocol-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-protocol-test PRIVATE -Wall -Wextra -Werror)
  add_test(NAME r1-update-protocol-test COMMAND r1-update-protocol-test)

  add_executable(r1-update-supervisor-host tests/host_supervisor_main.cpp)
  target_link_libraries(r1-update-supervisor-host PRIVATE r1-update-policy)
  target_compile_options(r1-update-supervisor-host PRIVATE -Wall -Wextra -Werror)

  add_executable(r1-update-supervisor-test tests/update_supervisor_test.cpp)
  target_link_libraries(r1-update-supervisor-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-supervisor-test PRIVATE -Wall -Wextra -Werror)
  add_dependencies(r1-update-supervisor-test r1-update-supervisor-host)
  add_test(NAME r1-update-supervisor-test COMMAND r1-update-supervisor-test)

  add_executable(r1-update-android-backend-test
    tests/android_package_manager_backend_test.cpp)
  target_link_libraries(r1-update-android-backend-test PRIVATE r1-update-policy)
  target_compile_options(r1-update-android-backend-test PRIVATE
    -Wall -Wextra -Werror)
  add_test(NAME r1-update-android-backend-test
    COMMAND r1-update-android-backend-test)
endif()

if(ANDROID)
  if(NOT ANDROID_ABI STREQUAL "armeabi-v7a")
    message(FATAL_ERROR "The R1 update supervisor must be built for armeabi-v7a")
  endif()
  if(CMAKE_SYSTEM_VERSION VERSION_GREATER "22")
    message(FATAL_ERROR "The R1 update supervisor must remain compatible with API 22")
  endif()
  add_library(r1_update_client SHARED src/update_client_jni.cpp)
  target_link_libraries(r1_update_client PRIVATE r1-update-policy)
  target_compile_features(r1_update_client PRIVATE cxx_std_17)
  target_compile_options(r1_update_client PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1_update_client PRIVATE "-Wl,--hash-style=both" "-Wl,--gc-sections")
  set_target_properties(r1_update_client PROPERTIES
    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)

  add_executable(r1-update-supervisor src/supervisor_main.cpp)
  target_link_libraries(r1-update-supervisor PRIVATE r1-update-policy log)
  target_compile_features(r1-update-supervisor PRIVATE cxx_std_17)
  target_compile_options(r1-update-supervisor PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1-update-supervisor PRIVATE
    "-Wl,--hash-style=both" "-Wl,--gc-sections")

  add_executable(r1-update-backend-probe tests/android_backend_probe_main.cpp)
  target_link_libraries(r1-update-backend-probe PRIVATE r1-update-policy log)
  target_compile_features(r1-update-backend-probe PRIVATE cxx_std_17)
  target_compile_options(r1-update-backend-probe PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1-update-backend-probe PRIVATE
    "-Wl,--hash-style=both" "-Wl,--gc-sections")

  # Validation-only helper. It is never included by the production update boot
  # builder and accepts only operation ids fixed into a temporary test boot.
  add_executable(r1-update-fault-helper tests/device_fault_helper_main.cpp)
  target_link_libraries(r1-update-fault-helper PRIVATE log)
  target_compile_features(r1-update-fault-helper PRIVATE cxx_std_17)
  target_compile_options(r1-update-fault-helper PRIVATE -Wall -Wextra -Werror)
  target_link_options(r1-update-fault-helper PRIVATE
    "-Wl,--hash-style=both" "-Wl,--gc-sections")
endif()
