#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <thread>
#include <vector>

namespace {
bool initialized = false;
bool streaming = false;
intptr_t expected_handle = 0x1234;
int wake_status = 0;
}

extern "C" int Unisound_MicArray_Process(
    void*, const int16_t*, int, int16_t*, int, int16_t**, int16_t**, int*);

static bool run_micarray_process() {
  int16_t raw[256 * 4];
  int16_t echo[256 * 2];
  for (int index = 0; index < 256 * 4; ++index) raw[index] = static_cast<int16_t>(1000 + index);
  for (int index = 0; index < 256 * 2; ++index) echo[index] = static_cast<int16_t>(200 + index);
  int16_t* asr = nullptr;
  int16_t* vad = nullptr;
  int output_length = 0;
  return Unisound_MicArray_Process(reinterpret_cast<void*>(expected_handle), raw, 256,
                                   echo, wake_status, &asr, &vad, &output_length) == 73
      && asr != nullptr && vad != nullptr && output_length == 256;
}

extern "C" int uni_4mic_hal_init(int use_four_mic) {
  initialized = use_four_mic == 1;
  return initialized ? 0 : -1;
}
extern "C" int uni_4mic_hal_release() { initialized = false; return 0; }
extern "C" intptr_t uni_4mic_pcm_open(int channels) {
  return initialized && channels == 2 ? expected_handle : 0;
}
extern "C" int uni_4mic_pcm_start(intptr_t handle) {
  streaming = handle == expected_handle;
  return streaming ? 0 : -1;
}
extern "C" int uni_4mic_pcm_read(intptr_t handle, void* output, int size) {
  if (!streaming || handle != expected_handle || size != 2400) return -1;
  auto* bytes = static_cast<uint8_t*>(output);
  for (int index = 0; index < size / 2; ++index) {
    int16_t sample = static_cast<int16_t>(index);
    memcpy(bytes + index * 2, &sample, sizeof(sample));
  }
  if (getenv("R1_VENDOR_MOCK_CONCURRENT_TAP") != nullptr) {
    std::vector<std::thread> workers;
    int results[4] = {};
    for (size_t index = 0; index < 4; ++index) {
      workers.emplace_back([index, &results]() { results[index] = run_micarray_process() ? 1 : 0; });
    }
    for (auto& worker : workers) worker.join();
    for (int result : results) if (result == 0) return -1;
  } else if (!run_micarray_process()) {
    return -1;
  }
  return 0;
}
extern "C" int uni_4mic_pcm_stop(intptr_t handle) {
  if (handle != expected_handle) return -1;
  streaming = false;
  return 0;
}
extern "C" int uni_4mic_pcm_close(intptr_t handle) { return handle == expected_handle ? 0 : -1; }
extern "C" int get4MicDoaResult() { return 145; }
extern "C" const char* get4MicBoardVersion() { return "MOCK_UNI_4MIC_V1.1"; }
extern "C" int set4MicWakeUpStatus(int status) {
  if (status != 0 && status != 1) return -1;
  wake_status = status;
  const char* trace = getenv("R1_VENDOR_MOCK_WAKE_STATUS_FILE");
  if (trace != nullptr) {
    FILE* output = fopen(trace, "a");
    if (output == nullptr || fputc('0' + status, output) == EOF) {
      if (output != nullptr) fclose(output);
      return -1;
    }
    fclose(output);
  }
  return 0;
}
extern "C" int set4MicDebugMode(int mode) {
  if (mode != 0 && mode != 1) return -1;
  const char* command = getenv("R1_VENDOR_MOCK_SYSTEM_COMMAND");
  if (mode == 1 && command != nullptr && system(command) != 0) return -1;
  return 0;
}
extern "C" int close4MicAlgorithm(int closed) { return closed == 0 ? 0 : -1; }
