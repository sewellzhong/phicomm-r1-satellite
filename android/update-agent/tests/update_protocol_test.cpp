#include "update_protocol.h"

#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

using r1_update::Candidate;
using r1_update::Health;
using r1_update::Installed;
using r1_update::PackageManagerBackend;
using r1_update::PackageOrchestrator;
using r1_update::Phase;
using r1_update::ProtocolRequest;
using r1_update::ProtocolRequestType;
using r1_update::ProtocolResponse;

namespace {

void require(bool value, const char* message) {
  if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

std::array<uint8_t, 32> from_hex(const std::string& value) {
  std::array<uint8_t, 32> output{};
  auto nibble = [](char byte) -> uint8_t {
    return static_cast<uint8_t>(byte <= '9' ? byte - '0' : byte - 'a' + 10);
  };
  for (size_t i = 0; i < output.size(); ++i)
    output[i] = static_cast<uint8_t>((nibble(value[i * 2]) << 4)
                                     | nibble(value[i * 2 + 1]));
  return output;
}

std::array<uint8_t, 32> digest(uint8_t seed) {
  std::array<uint8_t, 32> value{};
  for (size_t i = 0; i < value.size(); ++i) value[i] = seed + i;
  return value;
}

std::string temporary_directory() {
  char path[] = "/tmp/r1-update-protocol-XXXXXX";
  char* result = mkdtemp(path);
  require(result != nullptr && chmod(result, 0700) == 0, "mkdtemp failed");
  return result;
}

Candidate candidate() {
  return {"0123456789abcdef0123456789abcdef", "dev.sewellzhong.r1probe",
          117, 118, 4096,
          from_hex("c93eee2d0db02f10acc7460d9576e122dcf8cd53c4bf8dfcae1b3e74ebcfff5a"),
          digest(90), 180};
}

Installed old_package() {
  return {"dev.sewellzhong.r1probe", 117, digest(1), digest(90)};
}

Installed new_package() {
  Candidate value = candidate();
  return {value.package_name, value.to_version, value.apk_sha256,
          value.signer_sha256};
}

bool write_all(int fd, const std::string& payload) {
  size_t offset = 0;
  while (offset < payload.size()) {
    ssize_t written = write(fd, payload.data() + offset, payload.size() - offset);
    if (written < 0 && errno == EINTR) continue;
    if (written <= 0) return false;
    offset += static_cast<size_t>(written);
  }
  return true;
}

int create_archive(const std::string& directory) {
  std::string path = directory + "/incoming.apk";
  int output = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  require(output >= 0 && write_all(output, std::string(4096, 'a'))
          && close(output) == 0, "archive creation failed");
  int input = open(path.c_str(), O_RDONLY | O_CLOEXEC);
  require(input >= 0, "archive open failed");
  return input;
}

std::string candidate_path(const std::string& directory) {
  return directory + "/candidate-" + candidate().operation_id + ".apk";
}

std::string previous_path(const std::string& directory) {
  return directory + "/previous-" + candidate().operation_id + ".apk";
}

class FakeBackend final : public PackageManagerBackend {
 public:
  explicit FakeBackend(std::string directory) : directory_(std::move(directory)) {}
  Installed current = old_package();
  std::map<std::string, Installed> archives;

  bool read_installed(const std::string& package_name, Installed* output,
                      std::string*) override {
    if (output == nullptr || package_name != current.package_name) return false;
    *output = current;
    return true;
  }
  bool read_archive(const std::string& path, Installed* output,
                    std::string*) override {
    if (path == candidate_path(directory_)) {
      *output = new_package();
      return true;
    }
    auto found = archives.find(path);
    if (found == archives.end() || output == nullptr) return false;
    *output = found->second;
    return true;
  }
  bool backup_installed(const std::string& package_name, const std::string& path,
                        std::string*) override {
    if (package_name != current.package_name) return false;
    archives[path] = current;
    return true;
  }
  bool install_archive(const std::string& path, bool allow_downgrade,
                       std::string*) override {
    if (!allow_downgrade && path == candidate_path(directory_)) {
      current = new_package();
      return true;
    }
    auto found = archives.find(path);
    if (!allow_downgrade || found == archives.end()) return false;
    current = found->second;
    return true;
  }

 private:
  std::string directory_;
};

void cleanup(const std::string& directory) {
  const std::string paths[] = {
      directory + "/incoming.apk", candidate_path(directory),
      previous_path(directory), directory + "/transaction.v1",
      directory + "/update.sock"};
  for (const auto& path : paths) unlink(path.c_str());
  require(rmdir(directory.c_str()) == 0, "cleanup failed");
}

void apply_packet_round_trip_and_dispatch() {
  std::string directory = temporary_directory();
  int archive = create_archive(directory);
  int pair[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) == 0,
          "socketpair failed");
  std::string error;
  require(r1_update::send_apply_request(pair[0], candidate(), archive, &error),
          "apply send failed");
  ProtocolRequest request;
  require(r1_update::receive_protocol_request(pair[1], &request, &error),
          "apply receive failed");
  require(request.type == ProtocolRequestType::kApply && request.archive_fd >= 0
          && request.candidate.operation_id == candidate().operation_id
          && request.candidate.apk_sha256 == candidate().apk_sha256,
          "apply packet changed fields");
  close(archive); close(pair[0]); close(pair[1]);

  FakeBackend backend(directory);
  PackageOrchestrator orchestrator(directory, &backend);
  require(r1_update::dispatch_protocol_request(&request, directory, &orchestrator,
                                                1000, &error),
          "apply dispatch failed");
  require(request.archive_fd == -1
          && orchestrator.state().phase == Phase::kAwaitingHealth
          && backend.current.version == 118, "apply was not orchestrated");

  ProtocolRequest health;
  health.type = ProtocolRequestType::kHealth;
  health.health = {true, true, true, true};
  require(r1_update::dispatch_protocol_request(&health, directory, &orchestrator,
                                                1001, &error),
          "health dispatch failed");
  require(orchestrator.state().phase == Phase::kIdle,
          "healthy update did not commit");
  cleanup(directory);
}

void health_packet_has_no_descriptor() {
  int pair[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) == 0,
          "health socketpair failed");
  std::string error;
  Health expected{true, false, true, false};
  require(r1_update::send_health_request(pair[0], expected, &error),
          "health send failed");
  ProtocolRequest actual;
  require(r1_update::receive_protocol_request(pair[1], &actual, &error),
          "health receive failed");
  require(actual.type == ProtocolRequestType::kHealth && actual.archive_fd == -1
          && actual.health.service_ready && !actual.health.state_loaded
          && actual.health.audio_agent_reachable && !actual.health.isolation_safe,
          "health packet changed fields");
  close(pair[0]); close(pair[1]);
}

void listener_is_private_and_checks_kernel_peer() {
  std::string directory = temporary_directory();
  std::string path = directory + "/update.sock";
  int listener = -1;
  std::string error;
  require(r1_update::open_private_update_listener(path, geteuid(), &listener, &error),
          "private listener creation failed");
  struct stat info {};
  require(lstat(path.c_str(), &info) == 0 && S_ISSOCK(info.st_mode)
          && info.st_uid == geteuid() && (info.st_mode & 0777) == 0600,
          "listener path is not private");
  int client = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  require(client >= 0, "listener client create failed");
  struct sockaddr_un address {};
  address.sun_family = AF_UNIX;
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  require(connect(client, reinterpret_cast<struct sockaddr*>(&address),
                  sizeof(address)) == 0, "listener connect failed");
  require(r1_update::send_health_request(client, {true, true, true, true}, &error),
          "listener health send failed");
  ProtocolRequest request;
  require(r1_update::accept_protocol_request(listener, geteuid(), &request, &error)
          && request.type == ProtocolRequestType::kHealth,
          "listener did not accept matching kernel UID");
  require(!r1_update::open_private_update_listener(path, geteuid(), &client, &error)
          && error == "update_socket_path_exists",
          "listener replaced an existing socket path");
  close(client); close(listener);
  cleanup(directory);
}

void listener_rejects_replaceable_parent() {
  std::string directory = temporary_directory();
  require(chmod(directory.c_str(), 0770) == 0, "unsafe parent setup failed");
  int listener = -1;
  std::string error;
  require(!r1_update::open_private_update_listener(directory + "/update.sock",
                                                    geteuid(), &listener, &error)
          && error == "update_socket_parent_permissions" && listener == -1,
          "replaceable socket parent was accepted");
  require(chmod(directory.c_str(), 0700) == 0, "unsafe parent restore failed");
  cleanup(directory);
}

void listener_dispatches_and_returns_fixed_response() {
  std::string directory = temporary_directory();
  std::string path = directory + "/update.sock";
  int listener = -1;
  std::string error;
  require(r1_update::open_private_update_listener(path, geteuid(), &listener, &error),
          "serve listener creation failed");
  int client = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  require(client >= 0, "serve client create failed");
  struct sockaddr_un address {};
  address.sun_family = AF_UNIX;
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  require(connect(client, reinterpret_cast<struct sockaddr*>(&address),
                  sizeof(address)) == 0, "serve connect failed");
  int archive = create_archive(directory);
  require(r1_update::send_apply_request(client, candidate(), archive, &error),
          "serve apply send failed");

  FakeBackend backend(directory);
  PackageOrchestrator orchestrator(directory, &backend);
  bool operation_succeeded = false;
  require(r1_update::serve_protocol_request_once(listener, geteuid(), directory,
                                                  &orchestrator, 1000,
                                                  &operation_succeeded, &error)
          && operation_succeeded, "serve apply dispatch failed");
  ProtocolResponse response;
  require(r1_update::receive_protocol_response(client, &response, &error)
          && response.request_type == ProtocolRequestType::kApply
          && response.success && response.phase == Phase::kAwaitingHealth
          && response.error.empty(), "serve response was invalid");
  close(archive); close(client); close(listener);
  cleanup(directory);
}

void apply_requires_descriptor_and_exact_uid() {
  int pair[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) == 0,
          "negative socketpair failed");
  std::string error;
  require(r1_update::send_health_request(pair[0], {true, true, true, true}, &error),
          "negative health send failed");
  ProtocolRequest request;
  require(r1_update::receive_protocol_request(pair[1], &request, &error),
          "valid negative setup failed");
  require(!r1_update::authorized_peer(geteuid(), geteuid() + 1, &error)
          && error == "update_peer_uid_rejected", "wrong peer UID was accepted");
  close(pair[0]); close(pair[1]);

  Candidate invalid = candidate();
  invalid.operation_id[0] = 'G';
  require(!r1_update::send_apply_request(-1, invalid, -1, &error)
          && error == "update_protocol_apply_invalid",
          "invalid apply framing was accepted");
}

}  // namespace

int main() {
  apply_packet_round_trip_and_dispatch();
  health_packet_has_no_descriptor();
  listener_is_private_and_checks_kernel_peer();
  listener_rejects_replaceable_parent();
  listener_dispatches_and_returns_fixed_response();
  apply_requires_descriptor_and_exact_uid();
  std::cout << "update protocol tests passed\n";
}
