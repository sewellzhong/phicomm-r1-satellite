#include "audio_backend.h"

#include <dlfcn.h>
#include <string.h>

#include <utility>

namespace {
constexpr size_t kMonoFrameBytes = 640;
// Firmware 3448's FourMicAudioManager allocates 1200 S16 samples and passes
// all 2400 bytes to readData on every proprietary HAL read.
constexpr size_t kOriginalManagerReadBytes = 2400;
constexpr size_t kPostWakePrimeFrames = 50;

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
  frame->micarray_diagnostic_calls.clear();
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
      && load_symbol(library_, "set4MicWakeUpStatus", &set_wakeup_status_)
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
  if (library_ == nullptr || !resolve_symbols()
      || !micarray_diagnostic_tap_bind_original(library_) || hal_init_(1) != 0) {
    release();
    return false;
  }
  initialized_ = true;
  // Never let the proprietary backend write diagnostic household audio in production.
  if (set_debug_mode_(0) != 0 || close_algorithm_(0) != 0
      || set_wakeup_status_(0) != 0) {
    release();
    return false;
  }
  const char* version = get_board_version_();
  if (version != nullptr) board_version_ = version;
  input_buffer_.resize(kOriginalManagerReadBytes);
  pending_output_.clear();
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
  // The HAL start resets the proprietary wake state on firmware 3448. Enter
  // post-wake after the original chain has processed one second of unsaved
  // warm-up audio, but before enabling the tap or emitting the first frame.
  // Transition-internal calls therefore cannot create sidecar sequence gaps.
  if (tap_active_) {
    const size_t output_frame_bytes =
        kMonoFrameBytes * static_cast<size_t>(options_.output_channels);
    const size_t prime_bytes = kPostWakePrimeFrames * output_frame_bytes;
    size_t consumed = 0;
    while (consumed < prime_bytes) {
      if (pcm_read_(handle_, input_buffer_.data(),
                    static_cast<int>(input_buffer_.size())) < 0) {
        pcm_stop_(handle_);
        pcm_close_(handle_);
        handle_ = 0;
        return false;
      }
      consumed += input_buffer_.size();
    }
    if (set_wakeup_status_(1) != 0) {
      pcm_stop_(handle_);
      pcm_close_(handle_);
      handle_ = 0;
      return false;
    }
    // The first vendor call after the wake transition can expose an empty
    // output pointer set. Consume one unsaved HAL block before arming the tap
    // so the captured sequence begins only after the proprietary chain settles.
    if (pcm_read_(handle_, input_buffer_.data(),
                  static_cast<int>(input_buffer_.size())) < 0) {
      pcm_stop_(handle_);
      pcm_close_(handle_);
      handle_ = 0;
      return false;
    }
    micarray_diagnostic_tap_set_enabled(true);
  }
  streaming_ = true;
  pending_output_.clear();
  return true;
}

bool VendorBackend::read_frame(BackendFrame* frame) {
  if (!streaming_ || frame == nullptr) return false;
  // Match firmware 3448's original manager lifecycle for its debug-file path.
  // The first second is the pre-wake (waking) window; subsequent frames are
  // marked waked. The MicArray tap performs the same unsaved warm-up before
  // entering post-wake, with the tap disabled throughout that transition.
  // Production capture never enters either validation state.
  if (debug_files_active_ && validation_frames_ == 50
      && set_wakeup_status_(1) != 0) {
    return false;
  }
  const size_t output_frame_bytes =
      kMonoFrameBytes * static_cast<size_t>(options_.output_channels);
  frame->micarray_diagnostic_calls.clear();
  if (pending_output_.size() < output_frame_bytes) {
    // Match the original Java manager's 2400-byte request exactly. Preserve
    // every returned byte locally and packetize it into the satellite's fixed
    // 20 ms frames without changing the proprietary call boundary.
    int read_status = pcm_read_(
        handle_, input_buffer_.data(), static_cast<int>(input_buffer_.size()));
    if (read_status < 0) return false;
    pending_output_.insert(
        pending_output_.end(), input_buffer_.begin(), input_buffer_.end());
    if (tap_active_) {
      MicArrayDiagnosticCall call;
      while (frame->micarray_diagnostic_calls.size() < 8
             && micarray_diagnostic_tap_take(&call)) {
        frame->micarray_diagnostic_calls.push_back(std::move(call));
        call = MicArrayDiagnosticCall{};
      }
    }
  }
  if (pending_output_.size() < output_frame_bytes) return false;
  frame->diagnostic_interleaved_pcm.assign(
      pending_output_.begin(), pending_output_.begin() + output_frame_bytes);
  pending_output_.erase(
      pending_output_.begin(), pending_output_.begin() + output_frame_bytes);
  frame->diagnostic_output_channels = static_cast<uint32_t>(options_.output_channels);
  frame->diagnostic_selected_output_channel = static_cast<uint32_t>(options_.output_channel);
  frame->pcm.resize(kMonoFrameBytes);
  if (options_.output_channels == 1) {
    memcpy(frame->pcm.data(), frame->diagnostic_interleaved_pcm.data(), kMonoFrameBytes);
  } else {
    for (size_t sample = 0; sample < kMonoFrameBytes / 2; ++sample) {
      size_t source = (sample * 2 + static_cast<size_t>(options_.output_channel)) * 2;
      frame->pcm[sample * 2] = frame->diagnostic_interleaved_pcm[source];
      frame->pcm[sample * 2 + 1] = frame->diagnostic_interleaved_pcm[source + 1];
    }
  }
  int doa = get_doa_();
  frame->doa_valid = doa >= 0 && doa < 360;
  frame->doa_degrees = frame->doa_valid ? doa : 0;
  if (debug_files_active_) ++validation_frames_;
  return true;
}

bool VendorBackend::submit_playback_reference(const std::vector<uint8_t>&) {
  // The device exposes two hardware AEC reference channels. Until coverage is proven on
  // r1-sample01, neither claim them active nor mix a second software reference into the chain.
  return false;
}

bool VendorBackend::set_vendor_debug_files(bool enabled) {
  if (!initialized_ || streaming_ || set_debug_mode_ == nullptr
      || set_wakeup_status_ == nullptr) return false;
  if (enabled) {
    if (set_debug_mode_(1) != 0) return false;
    if (set_wakeup_status_(0) != 0) {
      set_debug_mode_(0);
      return false;
    }
    validation_frames_ = 0;
    debug_files_active_ = true;
    return true;
  }
  const bool wake_reset = set_wakeup_status_(0) == 0;
  const bool debug_reset = set_debug_mode_(0) == 0;
  validation_frames_ = 0;
  debug_files_active_ = false;
  return wake_reset && debug_reset;
}

bool VendorBackend::set_micarray_diagnostic_tap(bool enabled) {
  if (!initialized_ || streaming_) return false;
  if (enabled) {
    if (set_wakeup_status_(0) != 0) return false;
    micarray_diagnostic_tap_set_enabled(false);
    tap_active_ = true;
    validation_frames_ = 0;
    return !micarray_diagnostic_tap_enabled();
  }
  micarray_diagnostic_tap_set_enabled(false);
  tap_active_ = false;
  validation_frames_ = 0;
  return !micarray_diagnostic_tap_enabled() && set_wakeup_status_(0) == 0;
}

uint64_t VendorBackend::micarray_diagnostic_tap_dropped() const {
  return tap_active_ ? ::micarray_diagnostic_tap_dropped() : 0;
}

uint64_t VendorBackend::micarray_diagnostic_tap_invalid() const {
  return tap_active_ ? ::micarray_diagnostic_tap_invalid() : 0;
}

void VendorBackend::stop() {
  if (streaming_ && handle_ != 0) pcm_stop_(handle_);
  streaming_ = false;
  pending_output_.clear();
}

void VendorBackend::release() {
  stop();
  micarray_diagnostic_tap_set_enabled(false);
  tap_active_ = false;
  if (handle_ != 0 && pcm_close_ != nullptr) pcm_close_(handle_);
  handle_ = 0;
  if (initialized_ && set_wakeup_status_ != nullptr) set_wakeup_status_(0);
  if (initialized_ && set_debug_mode_ != nullptr) set_debug_mode_(0);
  validation_frames_ = 0;
  debug_files_active_ = false;
  if (initialized_ && hal_release_ != nullptr) hal_release_();
  initialized_ = false;
  board_version_.clear();
  input_buffer_.clear();
  pending_output_.clear();
  micarray_diagnostic_tap_unbind_original();
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
  set_wakeup_status_ = nullptr;
  close_algorithm_ = nullptr;
}
