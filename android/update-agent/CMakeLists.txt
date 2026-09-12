cmake_minimum_required(VERSION 3.18)
project(r1_update_agent LANGUAGES CXX)

add_library(r1-update-policy STATIC
  src/package_orchestrator.cpp
  src/update_protocol.cpp
  src/update_policy.cpp
  src/update_runtime.cpp
)
target_include_directories(r1-update-policy PUBLIC src)
target_compile_features(r1-update-policy PUBLIC cxx_std_17)
target_compile_options(r1-update-policy PRIVATE -Wall -Wextra -Werror)

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
endif()

if(ANDROID)
  if(NOT ANDROID_ABI STREQUAL "armeabi-v7a")
    message(FATAL_ERROR "The R1 update supervisor must be built for armeabi-v7a")
  endif()
  if(CMAKE_SYSTEM_VERSION VERSION_GREATER "22")
    message(FATAL_ERROR "The R1 update supervisor must remain compatible with API 22")
  endif()
endif()
