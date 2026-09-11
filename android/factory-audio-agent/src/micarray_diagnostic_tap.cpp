#include "micarray_diagnostic_tap.h"

#include <dlfcn.h>
#include <pthread.h>
#include <string.h>

#include <array>
#include <atomic>

namespace {
constexpr int kSamplesPerChannel = 256;
constexpr size_t kRawMicChannels = 4;
constexpr size_t kEchoReferenceChannels = 2;
constexpr size_t kQueueCapacity = 8;
constexpr size_t kRawSamples = kSamplesPerChannel * kRawMicChannels;
constexpr size_t kEchoSamples = kSamplesPerChannel * kEchoReferenceChannels;

using ProcessFunction = int (*)(void*, const int16_t*, int, int16_t*, int,
                                int16_t**, int16_t**, int*);

struct FixedCall {
  uint64_t sequence = 0;
  int32_t result = 0;
  bool is_waked = false;
  uint32_t output_samples = 0;
  std::array<int16_t, kRawSamples> raw{};
  std::array<int16_t, kEchoSamples> echo{};
  std::array<int16_t, kSamplesPerChannel> asr{};
  std::array<int16_t, kSamplesPerChannel> vad{};
};

std::atomic<bool> g_enabled{false};
std::atomic<uint64_t> g_sequence{0};
std::atomic<uint64_t> g_dropped{0};
std::atomic<uint64_t> g_invalid{0};
std::atomic<ProcessFunction> g_original{nullptr};
pthread_mutex_t g_queue_mutex = PTHREAD_MUTEX_INITIALIZER;
std::array<FixedCall, kQueueCapacity> g_queue{};
size_t g_queue_head = 0;
size_t g_queue_size = 0;

void clear_fixed_call(FixedCall* call) {
  if (call != nullptr) *call = FixedCall{};
}

void clear_queue_locked() {
  for (auto& call : g_queue) clear_fixed_call(&call);
  g_queue_head = 0;
  g_queue_size = 0;
}

template <size_t N>
std::vector<uint8_t> pcm_bytes(const std::array<int16_t, N>& samples, size_t count) {
  const auto* begin = reinterpret_cast<const uint8_t*>(samples.data());
  return std::vector<uint8_t>(begin, begin + count * sizeof(int16_t));
}

void enqueue(FixedCall* call) {
  if (pthread_mutex_trylock(&g_queue_mutex) != 0) {
    ++g_dropped;
    clear_fixed_call(call);
    return;
  }
  if (!g_enabled.load(std::memory_order_relaxed) || g_queue_size == kQueueCapacity) {
    ++g_dropped;
  } else {
    const size_t tail = (g_queue_head + g_queue_size) % kQueueCapacity;
    g_queue[tail] = *call;
    ++g_queue_size;
  }
  pthread_mutex_unlock(&g_queue_mutex);
  clear_fixed_call(call);
}
}  // namespace

extern "C" int Unisound_MicArray_Process(
    void*, const int16_t*, int, int16_t*, int, int16_t**, int16_t**, int*);

bool micarray_diagnostic_tap_bind_original(void* vendor_library) {
  if (vendor_library == nullptr || g_enabled.load()) return false;
  dlerror();
  void* symbol = dlsym(vendor_library, "Unisound_MicArray_Process");
  const char* error = dlerror();
  if (error != nullptr || symbol == nullptr
      || symbol == reinterpret_cast<void*>(&Unisound_MicArray_Process)) return false;
  g_original.store(reinterpret_cast<ProcessFunction>(symbol), std::memory_order_release);
  return true;
}

void micarray_diagnostic_tap_unbind_original() {
  micarray_diagnostic_tap_set_enabled(false);
  g_original.store(nullptr, std::memory_order_release);
}

void micarray_diagnostic_tap_set_enabled(bool enabled) {
  pthread_mutex_lock(&g_queue_mutex);
  clear_queue_locked();
  g_sequence = 0;
  g_dropped = 0;
  g_invalid = 0;
  g_enabled.store(enabled, std::memory_order_release);
  pthread_mutex_unlock(&g_queue_mutex);
}

bool micarray_diagnostic_tap_enabled() {
  return g_enabled.load(std::memory_order_acquire);
}

uint64_t micarray_diagnostic_tap_dropped() { return g_dropped.load(); }
uint64_t micarray_diagnostic_tap_invalid() { return g_invalid.load(); }

bool micarray_diagnostic_tap_take(MicArrayDiagnosticCall* call) {
  if (call == nullptr) return false;
  pthread_mutex_lock(&g_queue_mutex);
  if (g_queue_size == 0) {
    pthread_mutex_unlock(&g_queue_mutex);
    return false;
  }
  FixedCall fixed = g_queue[g_queue_head];
  clear_fixed_call(&g_queue[g_queue_head]);
  g_queue_head = (g_queue_head + 1) % kQueueCapacity;
  --g_queue_size;
  pthread_mutex_unlock(&g_queue_mutex);

  call->sequence = fixed.sequence;
  call->result = fixed.result;
  call->is_waked = fixed.is_waked;
  call->samples_per_channel = kSamplesPerChannel;
  call->raw_mic_pcm_s16le = pcm_bytes(fixed.raw, fixed.raw.size());
  call->echo_reference_pcm_s16le = pcm_bytes(fixed.echo, fixed.echo.size());
  call->asr_pcm_s16le = pcm_bytes(fixed.asr, fixed.output_samples);
  call->vad_pcm_s16le = pcm_bytes(fixed.vad, fixed.output_samples);
  clear_fixed_call(&fixed);
  return true;
}

extern "C" __attribute__((visibility("default")))
int Unisound_MicArray_Process(void* handle, const int16_t* input, int input_length,
                             int16_t* echo_reference, int is_waked,
                             int16_t** output_asr, int16_t** output_vad,
                             int* output_length) {
  ProcessFunction original = g_original.load(std::memory_order_acquire);
  if (original == nullptr) return -1;

  const bool capture = g_enabled.load(std::memory_order_acquire)
      && input_length == kSamplesPerChannel && input != nullptr
      && echo_reference != nullptr && output_asr != nullptr
      && output_vad != nullptr && output_length != nullptr;
  FixedCall call;
  if (capture) {
    memcpy(call.raw.data(), input, sizeof(call.raw));
    memcpy(call.echo.data(), echo_reference, sizeof(call.echo));
    call.is_waked = is_waked != 0;
  }

  const int result = original(handle, input, input_length, echo_reference, is_waked,
                              output_asr, output_vad, output_length);
  if (!g_enabled.load(std::memory_order_acquire)) return result;
  if (!capture || *output_length < 0 || *output_length > kSamplesPerChannel
      || (*output_length > 0 && (*output_asr == nullptr || *output_vad == nullptr))) {
    ++g_invalid;
    clear_fixed_call(&call);
    return result;
  }
  call.sequence = ++g_sequence;
  call.result = result;
  call.output_samples = static_cast<uint32_t>(*output_length);
  if (call.output_samples > 0) {
    memcpy(call.asr.data(), *output_asr, call.output_samples * sizeof(int16_t));
    memcpy(call.vad.data(), *output_vad, call.output_samples * sizeof(int16_t));
  }
  enqueue(&call);
  return result;
}
