#include "micarray_diagnostic_tap.h"

#include <dlfcn.h>
#include <sched.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <array>
#include <atomic>

namespace {
constexpr int kSamplesPerChannel = 256;
constexpr size_t kRawMicChannels = 4;
constexpr size_t kEchoReferenceChannels = 2;
constexpr size_t kQueueCapacity = 32;
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
std::atomic<uint64_t> g_generation{0};
std::atomic<uint64_t> g_active_calls{0};
std::atomic<uint64_t> g_outside_window{0};
std::atomic<uint64_t> g_invalid_input_shape{0};
std::atomic<uint64_t> g_invalid_output_length{0};
std::atomic<uint64_t> g_invalid_output_pointer{0};
std::atomic<uint64_t> g_unexpected_producer{0};
std::atomic<uint64_t> g_queue_full{0};
std::atomic<ProcessFunction> g_original{nullptr};
std::array<FixedCall, kQueueCapacity> g_queue{};
std::atomic<uint64_t> g_queue_read{0};
std::atomic<uint64_t> g_queue_write{0};
std::atomic<pid_t> g_producer_tid{0};

void clear_fixed_call(FixedCall* call) {
  if (call != nullptr) *call = FixedCall{};
}

void clear_queue() {
  for (auto& call : g_queue) clear_fixed_call(&call);
  g_queue_read.store(0, std::memory_order_relaxed);
  g_queue_write.store(0, std::memory_order_relaxed);
}

template <size_t N>
std::vector<uint8_t> pcm_bytes(const std::array<int16_t, N>& samples, size_t count) {
  const auto* begin = reinterpret_cast<const uint8_t*>(samples.data());
  return std::vector<uint8_t>(begin, begin + count * sizeof(int16_t));
}

void enqueue(FixedCall* call) {
  const pid_t tid = static_cast<pid_t>(syscall(__NR_gettid));
  pid_t expected = 0;
  if (!g_producer_tid.compare_exchange_strong(expected, tid)
      && expected != tid) {
    ++g_unexpected_producer;
    clear_fixed_call(call);
    return;
  }
  const uint64_t write = g_queue_write.load(std::memory_order_relaxed);
  const uint64_t read = g_queue_read.load(std::memory_order_acquire);
  if (write - read >= kQueueCapacity) {
    ++g_queue_full;
    clear_fixed_call(call);
    return;
  }
  g_queue[write % kQueueCapacity] = *call;
  g_queue_write.store(write + 1, std::memory_order_release);
  clear_fixed_call(call);
}

void finish_active_call() {
  g_active_calls.fetch_sub(1, std::memory_order_release);
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
  g_enabled.store(false, std::memory_order_release);
  g_generation.fetch_add(1, std::memory_order_acq_rel);
  while (g_active_calls.load(std::memory_order_acquire) != 0) sched_yield();
  clear_queue();
  g_sequence = 0;
  g_outside_window = 0;
  g_invalid_input_shape = 0;
  g_invalid_output_length = 0;
  g_invalid_output_pointer = 0;
  g_unexpected_producer = 0;
  g_queue_full = 0;
  g_producer_tid = 0;
  g_enabled.store(enabled, std::memory_order_release);
}

bool micarray_diagnostic_tap_enabled() {
  return g_enabled.load(std::memory_order_acquire);
}

uint64_t micarray_diagnostic_tap_dropped() {
  return g_unexpected_producer.load() + g_queue_full.load();
}
uint64_t micarray_diagnostic_tap_invalid() {
  return g_invalid_input_shape.load() + g_invalid_output_length.load()
      + g_invalid_output_pointer.load();
}
uint64_t micarray_diagnostic_tap_outside_window() { return g_outside_window.load(); }
uint64_t micarray_diagnostic_tap_invalid_input_shape() {
  return g_invalid_input_shape.load();
}
uint64_t micarray_diagnostic_tap_invalid_output_length() {
  return g_invalid_output_length.load();
}
uint64_t micarray_diagnostic_tap_invalid_output_pointer() {
  return g_invalid_output_pointer.load();
}
uint64_t micarray_diagnostic_tap_unexpected_producer() {
  return g_unexpected_producer.load();
}
uint64_t micarray_diagnostic_tap_queue_full() { return g_queue_full.load(); }

bool micarray_diagnostic_tap_take(MicArrayDiagnosticCall* call) {
  if (call == nullptr) return false;
  const uint64_t read = g_queue_read.load(std::memory_order_relaxed);
  if (read == g_queue_write.load(std::memory_order_acquire)) return false;
  FixedCall fixed = g_queue[read % kQueueCapacity];
  clear_fixed_call(&g_queue[read % kQueueCapacity]);
  g_queue_read.store(read + 1, std::memory_order_release);

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

  const bool enabled_at_entry = g_enabled.load(std::memory_order_acquire);
  const uint64_t generation_at_entry = g_generation.load(std::memory_order_acquire);
  if (enabled_at_entry) g_active_calls.fetch_add(1, std::memory_order_acq_rel);
  const bool valid_input = input_length == kSamplesPerChannel && input != nullptr
      && echo_reference != nullptr && output_asr != nullptr
      && output_vad != nullptr && output_length != nullptr;
  const bool capture = enabled_at_entry && valid_input;
  FixedCall call;
  if (capture) {
    memcpy(call.raw.data(), input, sizeof(call.raw));
    memcpy(call.echo.data(), echo_reference, sizeof(call.echo));
    call.is_waked = is_waked != 0;
  }

  const int result = original(handle, input, input_length, echo_reference, is_waked,
                              output_asr, output_vad, output_length);
  if (!enabled_at_entry) {
    if (g_enabled.load(std::memory_order_acquire)) ++g_outside_window;
    return result;
  }
  if (!g_enabled.load(std::memory_order_acquire)
      || generation_at_entry != g_generation.load(std::memory_order_acquire)) {
    finish_active_call();
    return result;
  }
  if (!valid_input) {
    ++g_invalid_input_shape;
    finish_active_call();
    clear_fixed_call(&call);
    return result;
  }
  if (*output_length < 0 || *output_length > kSamplesPerChannel) {
    ++g_invalid_output_length;
    finish_active_call();
    clear_fixed_call(&call);
    return result;
  }
  if (*output_length > 0 && (*output_asr == nullptr || *output_vad == nullptr)) {
    ++g_invalid_output_pointer;
    finish_active_call();
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
  finish_active_call();
  return result;
}
