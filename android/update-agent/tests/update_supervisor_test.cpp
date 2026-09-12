#include "update_protocol.h"
#include "update_supervisor.h"

#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

constexpr char kBootId[] = "11111111-2222-3333-4444-555555555555";
constexpr char kOldSha[] =
    "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20";
constexpr char kNewSha[] =
    "c93eee2d0db02f10acc7460d9576e122dcf8cd53c4bf8dfcae1b3e74ebcfff5a";
constexpr char kSigner[] =
    "5a5b5c5d5e5f606162636465666768696a6b6c6d6e6f70717273747576777879";

void require(bool value, const char* message) {
  if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

std::array<uint8_t, 32> parse_digest(const std::string& value) {
  std::array<uint8_t, 32> output{};
  auto nibble = [](char byte) -> uint8_t {
    return static_cast<uint8_t>(byte <= '9' ? byte - '0' : byte - 'a' + 10);
  };
  for (size_t index = 0; index < output.size(); ++index)
    output[index] = static_cast<uint8_t>((nibble(value[index * 2]) << 4)
                                         | nibble(value[index * 2 + 1]));
  return output;
}

std::string temporary_directory() {
  char path[] = "/tmp/r1-update-supervisor-XXXXXX";
  char* result = mkdtemp(path);
  require(result != nullptr && chmod(result, 0700) == 0, "mkdtemp failed");
  return result;
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

std::string sibling_executable(const char* name) {
  char path[4096];
  ssize_t size = readlink("/proc/self/exe", path, sizeof(path) - 1);
  require(size > 0, "cannot locate test executable");
  path[size] = '\0';
  std::string current(path);
  return current.substr(0, current.rfind('/') + 1) + name;
}

void wait_for_socket(const std::string& path) {
  for (int attempt = 0; attempt < 200; ++attempt) {
    struct stat info {};
    if (lstat(path.c_str(), &info) == 0 && S_ISSOCK(info.st_mode)) return;
    usleep(10000);
  }
  require(false, "supervisor socket did not appear");
}

void cross_process_apply_and_health() {
  const std::string directory = temporary_directory();
  const std::string socket_path = directory + "/update.sock";
  const std::string uid = std::to_string(static_cast<uint64_t>(geteuid()));
  const std::string executable = sibling_executable("r1-update-supervisor-host");
  pid_t child = fork();
  require(child >= 0, "fork failed");
  if (child == 0) {
    execl(executable.c_str(), executable.c_str(), directory.c_str(),
          socket_path.c_str(), uid.c_str(), kBootId, "117", "118", kOldSha,
          kNewSha, kSigner, "3", static_cast<char*>(nullptr));
    _exit(127);
  }
  wait_for_socket(socket_path);

  // A malformed peer is confined to one connection and cannot terminate the
  // long-running supervisor before a later valid client arrives.
  std::string error;
  int malformed = -1;
  require(r1_update::connect_private_update_socket(socket_path, &malformed, &error)
          && send(malformed, "x", 1, MSG_NOSIGNAL) == 1,
          "malformed client setup failed");
  close(malformed);

  const std::string incoming = directory + "/incoming.apk";
  int output = open(incoming.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  require(output >= 0 && write_all(output, std::string(4096, 'a'))
          && close(output) == 0, "candidate creation failed");
  int archive = open(incoming.c_str(), O_RDONLY | O_CLOEXEC);
  require(archive >= 0, "candidate open failed");
  r1_update::Candidate candidate{
      "0123456789abcdef0123456789abcdef", "dev.sewellzhong.r1probe", 117, 118,
      4096, parse_digest(kNewSha), parse_digest(kSigner), 180};
  int client = -1;
  require(r1_update::connect_private_update_socket(socket_path, &client, &error)
          && r1_update::send_apply_request(client, candidate, archive, &error),
          "cross-process apply send failed");
  r1_update::ProtocolResponse response;
  require(r1_update::receive_protocol_response(client, &response, &error)
          && response.success && response.phase == r1_update::Phase::kAwaitingHealth,
          "cross-process apply response failed");
  close(archive);
  close(client);

  require(r1_update::connect_private_update_socket(socket_path, &client, &error)
          && r1_update::send_health_request(client, {true, true, true, true}, &error)
          && r1_update::receive_protocol_response(client, &response, &error)
          && response.success && response.phase == r1_update::Phase::kIdle,
          "cross-process health confirmation failed");
  close(client);

  int status = 0;
  require(waitpid(child, &status, 0) == child && WIFEXITED(status)
          && WEXITSTATUS(status) == 0, "host supervisor did not exit cleanly");
  unlink(incoming.c_str());
  unlink((directory + "/candidate-0123456789abcdef0123456789abcdef.apk").c_str());
  unlink((directory + "/previous-0123456789abcdef0123456789abcdef.apk").c_str());
  unlink((directory + "/transaction.v1").c_str());
  unlink(socket_path.c_str());
  require(rmdir(directory.c_str()) == 0, "supervisor cleanup failed");
}

class RecoveryBackend final : public r1_update::PackageManagerBackend {
 public:
  r1_update::Installed current{
      "dev.sewellzhong.r1probe", 118, parse_digest(kNewSha), parse_digest(kSigner)};
  std::map<std::string, r1_update::Installed> archives;

  bool read_installed(const std::string& package_name,
                      r1_update::Installed* installed, std::string*) override {
    if (installed == nullptr || package_name != current.package_name) return false;
    *installed = current;
    return true;
  }
  bool read_archive(const std::string& path, r1_update::Installed* archive,
                    std::string*) override {
    auto found = archives.find(path);
    if (archive == nullptr || found == archives.end()) return false;
    *archive = found->second;
    return true;
  }
  bool backup_installed(const std::string&, const std::string&, std::string*) override {
    return false;
  }
  bool install_archive(const std::string& path, bool allow_downgrade,
                       std::string*) override {
    auto found = archives.find(path);
    if (!allow_downgrade || found == archives.end()) return false;
    current = found->second;
    return true;
  }
};

void recovered_health_window_rejects_another_boot() {
  const std::string directory = temporary_directory();
  const std::string operation = "0123456789abcdef0123456789abcdef";
  const r1_update::Installed old_package{
      "dev.sewellzhong.r1probe", 117, parse_digest(kOldSha), parse_digest(kSigner)};
  const r1_update::Installed new_package{
      "dev.sewellzhong.r1probe", 118, parse_digest(kNewSha), parse_digest(kSigner)};
  const r1_update::Candidate candidate{
      operation, "dev.sewellzhong.r1probe", 117, 118, 4096,
      parse_digest(kNewSha), parse_digest(kSigner), 180};
  r1_update::TransactionController controller(directory);
  std::string error;
  require(controller.stage(candidate, old_package, new_package, &error)
          && controller.begin_install(1000, kBootId, &error)
          && controller.installed(new_package, &error),
          "reboot recovery setup failed");

  RecoveryBackend backend;
  backend.archives[directory + "/previous-" + operation + ".apk"] = old_package;
  constexpr char kNextBoot[] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
  r1_update::PackageOrchestrator orchestrator(directory, kNextBoot, &backend);
  int pair[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) == 0,
          "recovery socketpair failed");
  r1_update::SupervisorConfig config{pair[0], geteuid(), directory, kNextBoot, 0};
  require(r1_update::run_update_supervisor(
              config, &orchestrator, [] { return 1001; }, [] { return true; },
              [](const std::string&) {}, &error),
          "recovered supervisor failed");
  require(orchestrator.state().phase == r1_update::Phase::kIdle
          && backend.current.version == 117,
          "another boot retained an unconfirmed package");
  close(pair[0]);
  close(pair[1]);
  unlink((directory + "/transaction.v1").c_str());
  require(rmdir(directory.c_str()) == 0, "recovery cleanup failed");
}

}  // namespace

int main() {
  cross_process_apply_and_health();
  recovered_health_window_rejects_another_boot();
  std::cout << "update supervisor tests passed\n";
}
