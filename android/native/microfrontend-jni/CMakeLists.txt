cmake_minimum_required(VERSION 3.18)
project(r1_microfrontend LANGUAGES C CXX)

if(NOT DEFINED PYMICRO_FEATURES_DIR)
  message(FATAL_ERROR "PYMICRO_FEATURES_DIR is required")
endif()

set(FRONTEND_DIR "${PYMICRO_FEATURES_DIR}/tensorflow/lite/experimental/microfrontend/lib")
add_library(r1_microfrontend SHARED
  microfrontend_jni.cpp
  "${FRONTEND_DIR}/kiss_fft_int16.cc"
  "${FRONTEND_DIR}/fft.cc"
  "${FRONTEND_DIR}/fft_util.cc"
  "${FRONTEND_DIR}/filterbank.cc"
  "${FRONTEND_DIR}/filterbank_util.cc"
  "${FRONTEND_DIR}/frontend.cc"
  "${FRONTEND_DIR}/frontend_util.cc"
  "${FRONTEND_DIR}/log_lut.cc"
  "${FRONTEND_DIR}/log_scale.cc"
  "${FRONTEND_DIR}/log_scale_util.cc"
  "${FRONTEND_DIR}/noise_reduction.cc"
  "${FRONTEND_DIR}/noise_reduction_util.cc"
  "${FRONTEND_DIR}/pcan_gain_control.cc"
  "${FRONTEND_DIR}/pcan_gain_control_util.cc"
  "${FRONTEND_DIR}/window.cc"
  "${FRONTEND_DIR}/window_util.cc")
target_include_directories(r1_microfrontend PRIVATE
  "${PYMICRO_FEATURES_DIR}"
  "${PYMICRO_FEATURES_DIR}/kissfft")
target_compile_features(r1_microfrontend PRIVATE cxx_std_17)
target_compile_options(r1_microfrontend PRIVATE -Wall -Wextra)
target_link_options(r1_microfrontend PRIVATE "-Wl,--hash-style=both")
