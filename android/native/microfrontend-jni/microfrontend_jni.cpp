#include <jni.h>

#include <algorithm>
#include <cstdint>
#include <cstdlib>

extern "C" {
#include "tensorflow/lite/experimental/microfrontend/lib/frontend.h"
#include "tensorflow/lite/experimental/microfrontend/lib/frontend_util.h"
}

namespace {
constexpr int kSampleRate = 16000;
constexpr int kChunkSamples = 160;
constexpr int kFeatureCount = 40;

struct Handle {
  FrontendConfig config;
  FrontendState state;
};

void InitConfig(FrontendConfig *config) {
  config->window.size_ms = 30;
  config->window.step_size_ms = 10;
  config->filterbank.num_channels = kFeatureCount;
  config->filterbank.lower_band_limit = 125.0f;
  config->filterbank.upper_band_limit = 7500.0f;
  config->noise_reduction.smoothing_bits = 10;
  config->noise_reduction.even_smoothing = 0.025f;
  config->noise_reduction.odd_smoothing = 0.06f;
  config->noise_reduction.min_signal_remaining = 0.05f;
  config->pcan_gain_control.enable_pcan = 1;
  config->pcan_gain_control.strength = 0.95f;
  config->pcan_gain_control.offset = 80.0f;
  config->pcan_gain_control.gain_bits = 21;
  config->log_scale.enable_log = 1;
  config->log_scale.scale_shift = 6;
}
}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_dev_sewellzhong_r1probe_MicroFrontendNative_nativeCreate(JNIEnv *, jclass) {
  auto *handle = static_cast<Handle *>(std::calloc(1, sizeof(Handle)));
  if (handle == nullptr) return 0;
  InitConfig(&handle->config);
  if (!FrontendPopulateState(&handle->config, &handle->state, kSampleRate)) {
    std::free(handle);
    return 0;
  }
  return reinterpret_cast<jlong>(handle);
}

extern "C" JNIEXPORT jint JNICALL
Java_dev_sewellzhong_r1probe_MicroFrontendNative_nativeProcess(
    JNIEnv *env, jclass, jlong pointer, jshortArray audio, jbyteArray features) {
  auto *handle = reinterpret_cast<Handle *>(pointer);
  if (handle == nullptr || env->GetArrayLength(audio) != kChunkSamples ||
      env->GetArrayLength(features) != kFeatureCount) {
    return -1;
  }
  int16_t samples[kChunkSamples];
  env->GetShortArrayRegion(audio, 0, kChunkSamples,
                           reinterpret_cast<jshort *>(samples));
  size_t samples_read = 0;
  FrontendOutput output = FrontendProcessSamples(
      &handle->state, samples, kChunkSamples, &samples_read);
  if (samples_read != kChunkSamples) return -2;
  if (output.size == 0) return 0;
  if (output.size != kFeatureCount) return -3;
  jbyte quantized[kFeatureCount];
  for (int i = 0; i < kFeatureCount; ++i) {
    int32_t value = ((output.values[i] * 256) + 333) / 666 - 128;
    value = std::max<int32_t>(-128, std::min<int32_t>(127, value));
    quantized[i] = static_cast<jbyte>(value);
  }
  env->SetByteArrayRegion(features, 0, kFeatureCount, quantized);
  return kFeatureCount;
}

extern "C" JNIEXPORT void JNICALL
Java_dev_sewellzhong_r1probe_MicroFrontendNative_nativeDestroy(
    JNIEnv *, jclass, jlong pointer) {
  auto *handle = reinterpret_cast<Handle *>(pointer);
  if (handle == nullptr) return;
  FrontendFreeStateContents(&handle->state);
  std::free(handle);
}
