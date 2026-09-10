#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <grp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include <algorithm>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#include "audio_backend.h"

namespace {

constexpr uint32_t kProtocolVersion = 1;
constexpr size_t kFrameBytes = 640;
constexpr uint32_t kMaximumEnvelope = 1024 * 1024;
constexpr int kIdle = 1;
constexpr int kStreaming = 2;
constexpr int kReferenceUnavailable = 1;
constexpr int kReferenceActive = 2;
constexpr int kReferenceStale = 3;
constexpr uint64_t kDefaultFramePeriodNs = 20000000ULL;

volatile sig_atomic_t g_stop = 0;

void on_signal(int) { g_stop = 1; }

uint64_t monotonic_ns() {
  timespec value{};
  clock_gettime(CLOCK_MONOTONIC, &value);
  return static_cast<uint64_t>(value.tv_sec) * 1000000000ULL + value.tv_nsec;
}

bool parse_bounded_int(const char* text, int minimum, int maximum, int* value) {
  if (text == nullptr || value == nullptr) return false;
  char* end = nullptr;
  errno = 0;
  long parsed = strtol(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || parsed < minimum || parsed > maximum) {
    return false;
  }
  *value = static_cast<int>(parsed);
  return true;
}

void append_varint(std::vector<uint8_t>* out, uint64_t value) {
  while (value >= 0x80) {
    out->push_back(static_cast<uint8_t>(value) | 0x80);
    value >>= 7;
  }
  out->push_back(static_cast<uint8_t>(value));
}

void append_tag(std::vector<uint8_t>* out, uint32_t field, uint32_t wire) {
  append_varint(out, (static_cast<uint64_t>(field) << 3) | wire);
}

void append_uint(std::vector<uint8_t>* out, uint32_t field, uint64_t value) {
  if (value == 0) return;
  append_tag(out, field, 0);
  append_varint(out, value);
}

void append_bool(std::vector<uint8_t>* out, uint32_t field, bool value) {
  if (value) append_uint(out, field, 1);
}

void append_sint32(std::vector<uint8_t>* out, uint32_t field, int32_t value) {
  uint32_t zigzag = (static_cast<uint32_t>(value) << 1)
      ^ static_cast<uint32_t>(value >> 31);
  append_uint(out, field, zigzag);
}

void append_bytes(std::vector<uint8_t>* out, uint32_t field, const uint8_t* data, size_t size) {
  if (size == 0) return;
  append_tag(out, field, 2);
  append_varint(out, size);
  out->insert(out->end(), data, data + size);
}

void append_string(std::vector<uint8_t>* out, uint32_t field, const std::string& value) {
  append_bytes(out, field, reinterpret_cast<const uint8_t*>(value.data()), value.size());
}

void append_message(std::vector<uint8_t>* out, uint32_t field, const std::vector<uint8_t>& value) {
  append_tag(out, field, 2);
  append_varint(out, value.size());
  out->insert(out->end(), value.begin(), value.end());
}

class Reader {
 public:
  Reader(const uint8_t* data, size_t size) : data_(data), size_(size) {}

  bool next(uint32_t* field, uint32_t* wire) {
    if (position_ == size_) return false;
    uint64_t tag;
    if (!varint(&tag) || tag == 0) { failed_ = true; return false; }
    *field = static_cast<uint32_t>(tag >> 3);
    *wire = static_cast<uint32_t>(tag & 7);
    return true;
  }

  bool varint(uint64_t* value) {
    *value = 0;
    for (int shift = 0; shift < 64; shift += 7) {
      if (position_ >= size_) return false;
      uint8_t byte = data_[position_++];
      *value |= static_cast<uint64_t>(byte & 0x7f) << shift;
      if ((byte & 0x80) == 0) return true;
    }
    return false;
  }

  bool bytes(const uint8_t** data, size_t* size) {
    uint64_t length;
    if (!varint(&length) || length > size_ - position_) return false;
    *data = data_ + position_;
    *size = static_cast<size_t>(length);
    position_ += *size;
    return true;
  }

  bool skip(uint32_t wire) {
    uint64_t ignored;
    const uint8_t* bytes_value;
    size_t bytes_size;
    if (wire == 0) return varint(&ignored);
    if (wire == 1 && size_ - position_ >= 8) { position_ += 8; return true; }
    if (wire == 2) return bytes(&bytes_value, &bytes_size);
    if (wire == 5 && size_ - position_ >= 4) { position_ += 4; return true; }
    return false;
  }

  bool ok() const { return !failed_ && position_ <= size_; }
  void fail() { failed_ = true; }

 private:
  const uint8_t* data_;
  size_t size_;
  size_t position_ = 0;
  bool failed_ = false;
};

struct Request {
  uint32_t version = 0;
  uint64_t request_id = 0;
  uint32_t payload_field = 0;
  std::vector<uint8_t> payload;
};

bool parse_envelope(const std::vector<uint8_t>& encoded, Request* request) {
  Reader reader(encoded.data(), encoded.size());
  uint32_t field, wire;
  while (reader.next(&field, &wire)) {
    if ((field == 1 || field == 2) && wire == 0) {
      uint64_t value;
      if (!reader.varint(&value)) return false;
      if (field == 1) request->version = static_cast<uint32_t>(value);
      else request->request_id = value;
    } else if (field >= 10 && field <= 19 && wire == 2) {
      const uint8_t* data;
      size_t size;
      if (!reader.bytes(&data, &size) || request->payload_field != 0) return false;
      request->payload_field = field;
      request->payload.assign(data, data + size);
    } else if (!reader.skip(wire)) {
      return false;
    }
  }
  return reader.ok() && request->payload_field != 0;
}

bool read_uint_field(const std::vector<uint8_t>& encoded, uint32_t wanted, uint64_t* value) {
  Reader reader(encoded.data(), encoded.size());
  uint32_t field, wire;
  while (reader.next(&field, &wire)) {
    if (field == wanted && wire == 0) return reader.varint(value);
    if (!reader.skip(wire)) return false;
  }
  return false;
}

bool read_bytes_field(const std::vector<uint8_t>& encoded, uint32_t wanted,
                      std::vector<uint8_t>* value) {
  Reader reader(encoded.data(), encoded.size());
  uint32_t field, wire;
  while (reader.next(&field, &wire)) {
    if (field == wanted && wire == 2) {
      const uint8_t* data;
      size_t size;
      if (!reader.bytes(&data, &size)) return false;
      value->assign(data, data + size);
      return true;
    }
    if (!reader.skip(wire)) return false;
  }
  return false;
}

std::vector<uint8_t> envelope(uint64_t request_id, uint32_t payload_field,
                              const std::vector<uint8_t>& payload) {
  std::vector<uint8_t> result;
  append_uint(&result, 1, kProtocolVersion);
  append_uint(&result, 2, request_id);
  append_message(&result, payload_field, payload);
  return result;
}

bool send_all(int fd, const uint8_t* data, size_t size) {
  while (size > 0) {
    ssize_t count = send(fd, data, size, MSG_NOSIGNAL);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return false;
    data += count;
    size -= static_cast<size_t>(count);
  }
  return true;
}

bool send_envelope(int fd, const std::vector<uint8_t>& payload) {
  if (payload.empty() || payload.size() > kMaximumEnvelope) return false;
  uint32_t length = htonl(static_cast<uint32_t>(payload.size()));
  return send_all(fd, reinterpret_cast<uint8_t*>(&length), sizeof(length))
      && send_all(fd, payload.data(), payload.size());
}

std::vector<uint8_t> error_message(int code, const std::string& detail) {
  std::vector<uint8_t> result;
  append_uint(&result, 1, code);
  append_string(&result, 2, detail);
  return result;
}

std::vector<uint8_t> health_message(bool streaming, int reference_state,
                                    uint64_t frames, uint64_t dropped,
                                    const AudioBackend& backend,
                                    const std::string& failure = "") {
  std::vector<uint8_t> result;
  append_uint(&result, 1, streaming ? kStreaming : kIdle);
  append_uint(&result, 2, reference_state);
  append_string(&result, 3, backend.name());
  append_uint(&result, 4, frames);
  append_uint(&result, 5, dropped);
  append_string(&result, 6, failure);
  append_string(&result, 7, backend.board_version());
  append_uint(&result, 8, backend.raw_mic_channels());
  append_uint(&result, 9, backend.aec_reference_channels());
  append_bool(&result, 10, backend.array_processing_active());
  append_bool(&result, 11, backend.aec_active());
  return result;
}

bool format_is_supported(const std::vector<uint8_t>& start) {
  std::vector<uint8_t> format;
  if (!read_bytes_field(start, 1, &format)) return false;
  uint64_t rate = 0, channels = 0, width = 0, duration = 0;
  return read_uint_field(format, 1, &rate) && rate == 16000
      && read_uint_field(format, 2, &channels) && channels == 1
      && read_uint_field(format, 3, &width) && width == 2
      && read_uint_field(format, 4, &duration) && duration == 20;
}

struct ClientState {
  bool negotiated = false;
  bool streaming = false;
  uint64_t sequence = 0;
  uint64_t dropped = 0;
  uint64_t next_frame_ns = 0;
  uint64_t last_reference_ns = 0;
  uint64_t frame_period_ns = kDefaultFramePeriodNs;
  std::vector<uint8_t> input;
};

int reference_state(const ClientState& state) {
  if (state.last_reference_ns == 0) return kReferenceUnavailable;
  return monotonic_ns() - state.last_reference_ns <= 500000000ULL
      ? kReferenceActive : kReferenceStale;
}

bool reply_error(int fd, uint64_t id, int code, const std::string& detail) {
  return send_envelope(fd, envelope(id, 19, error_message(code, detail)));
}

bool handle_request(int fd, const Request& request, ClientState* state, AudioBackend* backend) {
  if (request.version != kProtocolVersion) {
    return reply_error(fd, request.request_id, 5, "protocol_version_unsupported");
  }
  if (request.payload_field == 10) {
    uint64_t minimum = 0, maximum = 0;
    if (!read_uint_field(request.payload, 1, &minimum)
        || !read_uint_field(request.payload, 2, &maximum)
        || minimum > kProtocolVersion || maximum < kProtocolVersion) {
      return reply_error(fd, request.request_id, 5, "protocol_range_unsupported");
    }
    std::vector<uint8_t> hello;
    append_uint(&hello, 1, kProtocolVersion);
    append_string(&hello, 2, "host-skeleton-v1");
    append_string(&hello, 3, backend->name());
    state->negotiated = true;
    return send_envelope(fd, envelope(request.request_id, 11, hello));
  }
  if (!state->negotiated) {
    return reply_error(fd, request.request_id, 7, "hello_required");
  }
  if (request.payload_field == 12) {
    if (state->streaming) return reply_error(fd, request.request_id, 6, "capture_busy");
    if (!format_is_supported(request.payload)) {
      return reply_error(fd, request.request_id, 4, "pcm_s16le_16000_mono_20ms_required");
    }
    if (!backend->initialize() || !backend->start()) {
      backend->release();
      return reply_error(fd, request.request_id, 3, "backend_start_failed");
    }
    state->streaming = true;
    state->sequence = 0;
    state->next_frame_ns = monotonic_ns() + state->frame_period_ns;
    return send_envelope(fd, envelope(request.request_id, 15,
        health_message(true, reference_state(*state), state->sequence, state->dropped, *backend)));
  }
  if (request.payload_field == 13) {
    backend->stop();
    backend->release();
    state->streaming = false;
    return send_envelope(fd, envelope(request.request_id, 15,
        health_message(false, reference_state(*state), state->sequence, state->dropped, *backend)));
  }
  if (request.payload_field == 14) {
    return send_envelope(fd, envelope(request.request_id, 15,
        health_message(state->streaming, reference_state(*state), state->sequence, state->dropped,
                       *backend)));
  }
  if (request.payload_field == 17) {
    if (!state->streaming) {
      return reply_error(fd, request.request_id, 7, "capture_not_streaming");
    }
    std::vector<uint8_t> pcm;
    if (!read_bytes_field(request.payload, 3, &pcm) || pcm.size() != kFrameBytes) {
      return reply_error(fd, request.request_id, 4, "playback_reference_must_be_640_bytes");
    }
    if (!backend->submit_playback_reference(pcm)) {
      return reply_error(fd, request.request_id, 3, "backend_reference_failed");
    }
    state->last_reference_ns = monotonic_ns();
    return send_envelope(fd, envelope(request.request_id, 15,
        health_message(state->streaming, kReferenceActive, state->sequence, state->dropped,
                       *backend)));
  }
  return reply_error(fd, request.request_id, 7, "request_not_supported");
}

bool emit_frame(int fd, ClientState* state, AudioBackend* backend) {
  std::vector<uint8_t> audio;
  BackendFrame frame;
  if (!backend->read_frame(&frame) || frame.pcm.size() != kFrameBytes) {
    return reply_error(fd, 0, 3, "backend_read_failed");
  }
  append_uint(&audio, 1, ++state->sequence);
  append_uint(&audio, 2, monotonic_ns());
  append_bytes(&audio, 3, frame.pcm.data(), frame.pcm.size());
  append_uint(&audio, 4, state->dropped);
  if (frame.doa_valid) append_sint32(&audio, 5, frame.doa_degrees);
  append_bool(&audio, 6, frame.doa_valid);
  append_uint(&audio, 7, reference_state(*state));
  return send_envelope(fd, envelope(0, 16, audio));
}

bool consume_requests(int fd, ClientState* state, AudioBackend* backend) {
  uint8_t chunk[8192];
  ssize_t count = recv(fd, chunk, sizeof(chunk), 0);
  if (count < 0 && errno == EINTR) return true;
  if (count <= 0) return false;
  state->input.insert(state->input.end(), chunk, chunk + count);
  while (state->input.size() >= 4) {
    uint32_t network_length;
    memcpy(&network_length, state->input.data(), sizeof(network_length));
    uint32_t length = ntohl(network_length);
    if (length == 0 || length > kMaximumEnvelope) return false;
    if (state->input.size() < 4ULL + length) break;
    std::vector<uint8_t> payload(state->input.begin() + 4, state->input.begin() + 4 + length);
    state->input.erase(state->input.begin(), state->input.begin() + 4 + length);
    Request request;
    if (!parse_envelope(payload, &request)) {
      if (!reply_error(fd, 0, 7, "malformed_envelope")) return false;
      continue;
    }
    if (!handle_request(fd, request, state, backend)) return false;
  }
  return true;
}

void serve_client(int fd, AudioBackend* backend, uint64_t frame_period_ns) {
  ClientState state;
  state.frame_period_ns = frame_period_ns;
  while (!g_stop) {
    int timeout = -1;
    if (state.streaming) {
      uint64_t now = monotonic_ns();
      uint64_t remaining = state.next_frame_ns > now ? state.next_frame_ns - now : 0;
      timeout = remaining < 1000000ULL ? 0
          : static_cast<int>((remaining + 999999ULL) / 1000000ULL);
    }
    pollfd descriptor{fd, POLLIN, 0};
    int result = poll(&descriptor, 1, timeout);
    if (result < 0 && errno == EINTR) continue;
    if (result < 0 || (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL))) break;
    if (result > 0 && (descriptor.revents & POLLIN)
        && !consume_requests(fd, &state, backend)) break;
    if (state.streaming && monotonic_ns() >= state.next_frame_ns) {
      if (!emit_frame(fd, &state, backend)) break;
      state.next_frame_ns += state.frame_period_ns;
      uint64_t now = monotonic_ns();
      if (state.next_frame_ns + state.frame_period_ns < now) {
        uint64_t missed = (now - state.next_frame_ns) / state.frame_period_ns;
        state.dropped += missed;
        state.next_frame_ns += missed * state.frame_period_ns;
      }
    }
  }
  backend->release();
}

bool safe_remove_socket(const std::string& path) {
  struct stat status{};
  if (lstat(path.c_str(), &status) != 0) return errno == ENOENT;
  if (!S_ISSOCK(status.st_mode)) return false;
  return unlink(path.c_str()) == 0;
}

int inherited_control_socket(const std::string& name) {
  if (name.empty() || name.find_first_not_of(
      "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_") != std::string::npos) {
    return -1;
  }
  std::string variable = "ANDROID_SOCKET_" + name;
  int fd = -1;
  if (!parse_bounded_int(getenv(variable.c_str()), 0, std::numeric_limits<int>::max(), &fd)
      || fcntl(fd, F_GETFD) < 0) {
    return -1;
  }
  int type = 0;
  socklen_t type_length = sizeof(type);
  sockaddr_storage address{};
  socklen_t address_length = sizeof(address);
  if (getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_length) != 0 || type != SOCK_STREAM
      || getsockname(fd, reinterpret_cast<sockaddr*>(&address), &address_length) != 0
      || address.ss_family != AF_UNIX) {
    return -1;
  }
  return fd;
}

}  // namespace

int main(int argc, char** argv) {
  std::string socket_path = "/dev/socket/r1_factory_audio";
  std::string init_socket_name;
  long expected_uid = -1;
  long drop_uid = -1;
  long drop_gid = -1;
  bool fake = false;
  VendorBackendOptions vendor_options;
  uint64_t frame_period_ns = kDefaultFramePeriodNs;
  for (int index = 1; index < argc; ++index) {
    std::string argument = argv[index];
    if (argument == "--fake") fake = true;
    else if (argument == "--vendor-library" && index + 1 < argc) {
      vendor_options.library_path = argv[++index];
    } else if (argument == "--vendor-open-channels" && index + 1 < argc) {
      if (!parse_bounded_int(argv[++index], 1, 8, &vendor_options.open_channels)) {
        fprintf(stderr, "invalid_vendor_open_channels\n");
        return 2;
      }
    } else if (argument == "--vendor-output-channels" && index + 1 < argc) {
      if (!parse_bounded_int(argv[++index], 1, 8, &vendor_options.output_channels)) {
        fprintf(stderr, "invalid_vendor_output_channels\n");
        return 2;
      }
    } else if (argument == "--vendor-output-channel" && index + 1 < argc) {
      if (!parse_bounded_int(argv[++index], 0, 7, &vendor_options.output_channel)) {
        fprintf(stderr, "invalid_vendor_output_channel\n");
        return 2;
      }
    }
    else if (argument == "--socket" && index + 1 < argc) socket_path = argv[++index];
    else if (argument == "--init-socket-name" && index + 1 < argc) {
      init_socket_name = argv[++index];
    }
    else if (argument == "--drop-uid" && index + 1 < argc) {
      char* end = nullptr;
      drop_uid = strtol(argv[++index], &end, 10);
      if (!end || *end != '\0' || drop_uid <= 0
          || static_cast<unsigned long>(drop_uid) > std::numeric_limits<uid_t>::max()) {
        fprintf(stderr, "invalid_drop_uid\n");
        return 2;
      }
    } else if (argument == "--drop-gid" && index + 1 < argc) {
      char* end = nullptr;
      drop_gid = strtol(argv[++index], &end, 10);
      if (!end || *end != '\0' || drop_gid <= 0
          || static_cast<unsigned long>(drop_gid) > std::numeric_limits<gid_t>::max()) {
        fprintf(stderr, "invalid_drop_gid\n");
        return 2;
      }
    }
    else if (argument == "--expected-uid" && index + 1 < argc) {
      char* end = nullptr;
      expected_uid = strtol(argv[++index], &end, 10);
      if (!end || *end != '\0' || expected_uid < 0
          || static_cast<unsigned long>(expected_uid) > std::numeric_limits<uid_t>::max()) {
        fprintf(stderr, "invalid_expected_uid\n");
        return 2;
      }
    } else if (argument == "--fake-frame-period-us" && index + 1 < argc) {
      char* end = nullptr;
      unsigned long value = strtoul(argv[++index], &end, 10);
      if (!end || *end != '\0' || value == 0 || value > 20000) {
        fprintf(stderr, "invalid_fake_frame_period_us\n");
        return 2;
      }
      frame_period_ns = static_cast<uint64_t>(value) * 1000ULL;
    } else {
      fprintf(stderr, "usage: r1-factory-audio-agent --expected-uid UID [--fake | "
                      "--vendor-library PATH --vendor-open-channels 2 "
                      "--vendor-output-channels 1|2 --vendor-output-channel N] [--socket PATH]\n");
      return 2;
    }
  }
  bool vendor = !vendor_options.library_path.empty();
  if (fake == vendor) {
    fprintf(stderr, "factory_backend_unimplemented\n");
    return 3;
  }
  if (vendor && (vendor_options.library_path[0] != '/'
      || vendor_options.open_channels != 2
      || (vendor_options.output_channels != 1 && vendor_options.output_channels != 2)
      || vendor_options.output_channel < 0
      || vendor_options.output_channel >= vendor_options.output_channels)) {
    fprintf(stderr, "invalid_vendor_backend_shape\n");
    return 2;
  }
  if (expected_uid < 0 || (init_socket_name.empty()
      && (socket_path.empty() || socket_path[0] != '/'))) {
    fprintf(stderr, "expected_uid_and_absolute_socket_required\n");
    return 2;
  }
  if ((drop_uid < 0) != (drop_gid < 0)) {
    fprintf(stderr, "drop_uid_and_gid_required_together\n");
    return 2;
  }
  bool owns_socket_path = init_socket_name.empty();
  int server = owns_socket_path ? socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0)
                                : inherited_control_socket(init_socket_name);
  if (server < 0) { perror(owns_socket_path ? "socket" : "init_socket"); return 1; }
  if (owns_socket_path) {
    if (!safe_remove_socket(socket_path)) {
      fprintf(stderr, "refusing_to_replace_non_socket\n"); close(server); return 2;
    }
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (socket_path.size() >= sizeof(address.sun_path)) {
      fprintf(stderr, "socket_path_too_long\n"); close(server); return 2;
    }
    memcpy(address.sun_path, socket_path.c_str(), socket_path.size() + 1);
    mode_t old_mask = umask(0007);
    int bind_result = bind(server, reinterpret_cast<sockaddr*>(&address), sizeof(address));
    umask(old_mask);
    if (bind_result != 0 || chmod(socket_path.c_str(), 0660) != 0
        || (drop_uid >= 0 && chown(socket_path.c_str(), static_cast<uid_t>(drop_uid),
                                   static_cast<gid_t>(expected_uid)) != 0)) {
      perror("bind_socket"); close(server); safe_remove_socket(socket_path); return 1;
    }
  }
  if (listen(server, 1) != 0) {
    perror("listen"); close(server);
    if (owns_socket_path) safe_remove_socket(socket_path);
    return 1;
  }
  if (drop_uid >= 0) {
    if (geteuid() != 0 || setgroups(0, nullptr) != 0
        || setgid(static_cast<gid_t>(drop_gid)) != 0
        || setuid(static_cast<uid_t>(drop_uid)) != 0
        || geteuid() != static_cast<uid_t>(drop_uid)
        || getegid() != static_cast<gid_t>(drop_gid)) {
      perror("privilege_drop"); close(server);
      if (owns_socket_path) safe_remove_socket(socket_path);
      return 1;
    }
  }
  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);
  signal(SIGPIPE, SIG_IGN);
  while (!g_stop) {
    pollfd descriptor{server, POLLIN, 0};
    int result = poll(&descriptor, 1, 250);
    if (result < 0 && errno == EINTR) continue;
    if (result <= 0) continue;
    int client = accept4(server, nullptr, nullptr, SOCK_CLOEXEC);
    if (client < 0) continue;
    timeval send_timeout{2, 0};
    if (setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &send_timeout,
                   sizeof(send_timeout)) != 0) {
      close(client);
      continue;
    }
    ucred credentials{};
    socklen_t size = sizeof(credentials);
    if (getsockopt(client, SOL_SOCKET, SO_PEERCRED, &credentials, &size) != 0
        || credentials.uid != static_cast<uid_t>(expected_uid)) {
      reply_error(client, 0, 2, "peer_uid_rejected");
      close(client);
      continue;
    }
    std::unique_ptr<AudioBackend> backend;
    if (fake) backend.reset(new SyntheticBackend());
    else backend.reset(new VendorBackend(vendor_options));
    serve_client(client, backend.get(), frame_period_ns);
    close(client);
  }
  close(server);
  if (owns_socket_path) safe_remove_socket(socket_path);
  return 0;
}
