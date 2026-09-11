#include <stdint.h>

extern "C" int Unisound_MicArray_Process(
    void*, const int16_t* input, int input_length, int16_t* echo_reference,
    int, int16_t** output_asr, int16_t** output_vad, int* output_length) {
  static thread_local int16_t asr[256];
  static thread_local int16_t vad[256];
  if (input == nullptr || echo_reference == nullptr || input_length != 256
      || output_asr == nullptr || output_vad == nullptr || output_length == nullptr) {
    return -31;
  }
  for (int sample = 0; sample < input_length; ++sample) {
    asr[sample] = static_cast<int16_t>(input[sample * 4] - echo_reference[sample * 2]);
    vad[sample] = static_cast<int16_t>(asr[sample] + 7);
  }
  *output_asr = asr;
  *output_vad = vad;
  *output_length = input_length;
  return 73;
}
