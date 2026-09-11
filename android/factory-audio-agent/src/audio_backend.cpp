#include "audio_backend.h"

#include <dlfcn.h>
#include <string.h>

#include <utility>

namespace {
constexpr size_t kMonoFrameBytes = 640;

template <typename T>
bool load_symbol(void* library, const char* name, T* destination) {
  dlerror();
  *destination = reinterpret_cast<T>(dlsym(library, name));
  return *destination != nullptr && dlerror() == nullptr;
}
}  // namespace

bool SyntheticBackend::initialize() {
  initialized_ = true;
  return true;
}

bool SyntheticBackend::start() {
  streaming_ = initialized_;
  return streaming_;
}

bool SyntheticBackend::read_frame(BackendFrame* frame) {
  if (!streaming_ || frame == nullptr) return false;
  frame->pcm.assign(kMonoFrameBytes, 0);
  frame->diagnostic_interleaved_pcm.clear();
  frame->diagnostic_output_channels = 0;
  frame->diagnostic_selected_output_channel = 0;
  frame->doa_degrees = 0;
  frame->doa_valid = false;
  return true;
}

bool SyntheticBackend::submit_playback_reference(const std::vector<uint8_t>& pcm) {
  return initialized_ && pcm.size() == kMonoFrameBytes;
}

void SyntheticBackend::stop() { streaming_ = false; }

void SyntheticBackend::release() {
  streaming_ = false;
  initialized_ = false;
}

VendorBackend::VendorBackend(VendorBackendOptions options) : options_(std::move(options)) {}

VendorBackend::~VendorBackend() { release(); }

bool VendorBackend::resolve_symbols() {
  return load_symbol(library_, "uni_4mic_hal_init", &hal_init_)
      && load_symbol(library_, "uni_4mic_hal_release", &hal_release_)
      && load_symbol(library_, "uni_4mic_pcm_open", &pcm_open_)
      && load_symbol(library_, "uni_4mic_pcm_start", &pcm_start_)
      && load_symbol(library_, "uni_4mic_pcm_read", &pcm_read_)
      && load_symbol(library_, "uni_4mic_pcm_stop", &pcm_stop_)
      && load_symbol(library_, "uni_4mic_pcm_close", &pcm_close_)
      && load_symbol(library_, "get4MicDoaResult", &get_doa_)
      && load_symbol(library_, "get4MicBoardVersion", &get_board_version_)
      && load_symbol(library_, "set4MicDebugMode", &set_debug_mode_)
      && load_symbol(library_, "close4MicAlgorithm", &close_algorithm_);
}

bool VendorBackend::initialize() {
  if (initialized_ || library_ != nullptr || options_.library_path.empty()
      || options_.open_channels != 2
      || (options_.output_channels != 1 && options_.output_channels != 2)
      || options_.output_channel < 0
      || options_.output_channel >= options_.output_channels) {
    return false;
  }
  library_ = dlopen(options_.library_path.c_str(), RTLD_NOW | RTLD_LOCAL);
  if (library_ == nullptr || !resolve_symbols() || hal_init_(1) != 0) {
    release();
    return false;
  }
  initialized_ = true;
  // Never let the proprietary backend write diagnostic household audio in production.
  if (set_debug_mode_(0) != 0 || close_algorithm_(0) != 0) {
    release();
    return false;
  }
  const char* version = get_board_version_();
  if (version != nullptr) board_version_ = version;
  input_buffer_.resize(kMonoFrameBytes * static_cast<size_t>(options_.output_channels));
  return true;
}

bool VendorBackend::start() {
  if (!initialized_ || streaming_) return false;
  handle_ = pcm_open_(options_.open_channels);
  if (handle_ == 0 || pcm_start_(handle_) != 0) {
    if (handle_ != 0) pcm_close_(handle_);
    handle_ = 0;
    return false;
  }
  streaming_ = true;
  return true;
}

bool VendorBackend::read_frame(BackendFrame* frame) {
  if (!streaming_ || frame == nullptr) return false;
  // Firmware 3448's wrapper returns tinyalsa pcm_read's status: 0 on success,
  // a negative value on failure. It does not return the byte count.
  int read_status = pcm_read_(
      handle_, input_buffer_.data(), static_cast<int>(input_buffer_.size()));
  if (read_status < 0) return false;
  frame->diagnostic_interleaved_pcm = input_buffer_;
  frame->diagnostic_output_channels = static_cast<uint32_t>(options_.output_channels);
  frame->diagnostic_selected_output_channel = static_cast<uint32_t>(options_.output_channel);
  frame->pcm.resize(kMonoFrameBytes);
  if (options_.output_channels == 1) {
    memcpy(frame->pcm.data(), input_buffer_.data(), kMonoFrameBytes);
  } else {
    for (size_t sample = 0; sample < kMonoFrameBytes / 2; ++sample) {
      size_t source = (sample * 2 + static_cast<size_t>(options_.output_channel)) * 2;
      frame->pcm[sample * 2] = input_buffer_[source];
      frame->pcm[sample * 2 + 1] = input_buffer_[source + 1];
    }
  }
  int doa = get_doa_();
  frame->doa_valid = doa >= 0 && doa < 360;
  frame->doa_degrees = frame->doa_valid ? doa : 0;
  return true;
}

bool VendorBackend::submit_playback_reference(const std::vector<uint8_t>&) {
  // The device exposes two hardware AEC reference channels. Until coverage is proven on
  // r1-sample01, neither claim them active nor mix a second software reference into the chain.
  return false;
}

bool VendorBackend::set_vendor_debug_files(bool enabled) {
  if (!initialized_ || streaming_ || set_debug_mode_ == nullptr) return false;
  if (set_debug_mode_(enabled ? 1 : 0) != 0) return false;
  debug_files_active_ = enabled;
  return true;
}

void VendorBackend::stop() {
  if (streaming_ && handle_ != 0) pcm_stop_(handle_);
  streaming_ = false;
}

void VendorBackend::release() {
  stop();
  if (handle_ != 0 && pcm_close_ != nullptr) pcm_close_(handle_);
  handle_ = 0;
  if (initialized_ && set_debug_mode_ != nullptr) set_debug_mode_(0);
  debug_files_active_ = false;
  if (initialized_ && hal_release_ != nullptr) hal_release_();
  initialized_ = false;
  board_version_.clear();
  input_buffer_.clear();
  if (library_ != nullptr) dlclose(library_);
  library_ = nullptr;
  hal_init_ = nullptr;
  hal_release_ = nullptr;
  pcm_open_ = nullptr;
  pcm_start_ = nullptr;
  pcm_read_ = nullptr;
  pcm_stop_ = nullptr;
  pcm_close_ = nullptr;
  get_doa_ = nullptr;
  get_board_version_ = nullptr;
  set_debug_mode_ = nullptr;
  close_algorithm_ = nullptr;
}
