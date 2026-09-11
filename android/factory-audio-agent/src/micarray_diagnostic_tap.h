#pragma once

#include <stdint.h>

#include <vector>

// Firmware 3448's MicArray ABI processes 256 samples at a time from four
// microphones and two playback-reference channels.  This structure contains
// validation-only copies from one unmodified call through that ABI.
struct MicArrayDiagnosticCall {
  uint64_t sequence = 0;
  int32_t result = 0;
  bool is_waked = false;
  uint32_t samples_per_channel = 0;
  std::vector<uint8_t> raw_mic_pcm_s16le;
  std::vector<uint8_t> echo_reference_pcm_s16le;
  std::vector<uint8_t> asr_pcm_s16le;
  std::vector<uint8_t> vad_pcm_s16le;
};

bool micarray_diagnostic_tap_bind_original(void* vendor_library);
void micarray_diagnostic_tap_unbind_original();
void micarray_diagnostic_tap_set_enabled(bool enabled);
bool micarray_diagnostic_tap_enabled();
uint64_t micarray_diagnostic_tap_dropped();
uint64_t micarray_diagnostic_tap_invalid();
bool micarray_diagnostic_tap_take(MicArrayDiagnosticCall* call);
