#pragma once

#include <stdint.h>

#include <string>
#include <vector>

struct BackendFrame {
  std::vector<uint8_t> pcm;
  int32_t doa_degrees = 0;
  bool doa_valid = false;
};

class AudioBackend {
 public:
  virtual ~AudioBackend() = default;
  virtual const char* name() const = 0;
  virtual bool initialize() = 0;
  virtual bool start() = 0;
  virtual bool read_frame(BackendFrame* frame) = 0;
  virtual bool submit_playback_reference(const std::vector<uint8_t>& pcm) = 0;
  virtual void stop() = 0;
  virtual void release() = 0;
  virtual std::string board_version() const { return {}; }
  virtual uint32_t raw_mic_channels() const { return 0; }
  virtual uint32_t aec_reference_channels() const { return 0; }
  virtual bool array_processing_active() const { return false; }
  virtual bool aec_active() const { return false; }
};

class SyntheticBackend final : public AudioBackend {
 public:
  const char* name() const override { return "synthetic-fake"; }
  bool initialize() override;
  bool start() override;
  bool read_frame(BackendFrame* frame) override;
  bool submit_playback_reference(const std::vector<uint8_t>& pcm) override;
  void stop() override;
  void release() override;

 private:
  bool initialized_ = false;
  bool streaming_ = false;
};

struct VendorBackendOptions {
  std::string library_path;
  int open_channels = 0;
  int output_channels = 0;
  int output_channel = -1;
};

class VendorBackend final : public AudioBackend {
 public:
  explicit VendorBackend(VendorBackendOptions options);
  ~VendorBackend() override;
  const char* name() const override { return "unisound_uni4mic_3448"; }
  bool initialize() override;
  bool start() override;
  bool read_frame(BackendFrame* frame) override;
  bool submit_playback_reference(const std::vector<uint8_t>& pcm) override;
  void stop() override;
  void release() override;
  std::string board_version() const override { return board_version_; }
  uint32_t raw_mic_channels() const override { return initialized_ ? 4 : 0; }
  uint32_t aec_reference_channels() const override { return 0; }
  bool array_processing_active() const override { return initialized_; }
  bool aec_active() const override { return false; }

 private:
  bool resolve_symbols();
  VendorBackendOptions options_;
  void* library_ = nullptr;
  intptr_t handle_ = 0;
  bool initialized_ = false;
  bool streaming_ = false;
  std::string board_version_;
  std::vector<uint8_t> input_buffer_;

  int (*hal_init_)(int) = nullptr;
  int (*hal_release_)() = nullptr;
  intptr_t (*pcm_open_)(int) = nullptr;
  int (*pcm_start_)(intptr_t) = nullptr;
  int (*pcm_read_)(intptr_t, void*, int) = nullptr;
  int (*pcm_stop_)(intptr_t) = nullptr;
  int (*pcm_close_)(intptr_t) = nullptr;
  int (*get_doa_)() = nullptr;
  const char* (*get_board_version_)() = nullptr;
  int (*set_debug_mode_)(int) = nullptr;
  int (*close_algorithm_)(int) = nullptr;
};
