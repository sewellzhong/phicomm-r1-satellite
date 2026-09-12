#include "update_protocol.h"
#include "update_supervisor.h"

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <map>
#include <string>

#include <sys/stat.h>
#include <unistd.h>

namespace {

using r1_update::Installed;
using r1_update::PackageManagerBackend;

bool parse_u32(const std::string& value, uint32_t* output) {
  if (value.empty() || output == nullptr) return false;
  uint64_t parsed = 0;
  for (char byte : value) {
    if (byte < '0' || byte > '9') return false;
    parsed = parsed * 10 + static_cast<uint64_t>(byte - '0');
    if (parsed > UINT32_MAX) return false;
  }
  *output = static_cast<uint32_t>(parsed);
  return true;
}

bool parse_digest(const std::string& value, std::array<uint8_t, 32>* output) {
  if (value.size() != 64 || output == nullptr) return false;
  auto nibble = [](char byte) -> int {
    if (byte >= '0' && byte <= '9') return byte - '0';
    if (byte >= 'a' && byte <= 'f') return byte - 'a' + 10;
    return -1;
  };
  for (size_t index = 0; index < output->size(); ++index) {
    int high = nibble(value[index * 2]);
    int low = nibble(value[index * 2 + 1]);
    if (high < 0 || low < 0) return false;
    (*output)[index] = static_cast<uint8_t>((high << 4) | low);
  }
  return true;
}

class HostFakeBackend final : public PackageManagerBackend {
 public:
  HostFakeBackend(std::string directory, Installed current, Installed target)
      : directory_(std::move(directory)), current_(std::move(current)),
        target_(std::move(target)) {}

  bool read_installed(const std::string& package_name, Installed* installed,
                      std::string*) override {
    if (installed == nullptr || package_name != current_.package_name) return false;
    *installed = current_;
    return true;
  }

  bool read_archive(const std::string& path, Installed* archive,
                    std::string*) override {
    if (archive == nullptr) return false;
    if (path.compare(0, directory_.size() + 11, directory_ + "/candidate-") == 0) {
      *archive = target_;
      return true;
    }
    auto found = backups_.find(path);
    if (found == backups_.end()) return false;
    *archive = found->second;
    return true;
  }

  bool backup_installed(const std::string& package_name, const std::string& path,
                        std::string*) override {
    if (package_name != current_.package_name) return false;
    backups_[path] = current_;
    return true;
  }

  bool install_archive(const std::string& path, bool allow_downgrade,
                       std::string*) override {
    if (!allow_downgrade
        && path.compare(0, directory_.size() + 11, directory_ + "/candidate-") == 0) {
      current_ = target_;
      return true;
    }
    auto found = backups_.find(path);
    if (!allow_downgrade || found == backups_.end()) return false;
    current_ = found->second;
    return true;
  }

 private:
  std::string directory_;
  Installed current_;
  Installed target_;
  std::map<std::string, Installed> backups_;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc != 11) {
    std::cerr << "usage: host-supervisor DIR SOCKET UID BOOT_ID FROM TO OLD_SHA NEW_SHA SIGNER MAX_REQUESTS\n";
    return 2;
  }
  uint32_t uid = 0, from = 0, to = 0, maximum_requests = 0;
  Installed current{"dev.sewellzhong.r1probe"}, target{"dev.sewellzhong.r1probe"};
  if (!parse_u32(argv[3], &uid) || !parse_u32(argv[5], &from)
      || !parse_u32(argv[6], &to) || !parse_digest(argv[7], &current.apk_sha256)
      || !parse_digest(argv[8], &target.apk_sha256)
      || !parse_digest(argv[9], &current.signer_sha256)
      || !parse_u32(argv[10], &maximum_requests)) {
    std::cerr << "invalid host supervisor argument\n";
    return 2;
  }
  target.signer_sha256 = current.signer_sha256;
  current.version = from;
  target.version = to;

  int listener = -1;
  std::string error;
  if (!r1_update::open_private_update_listener(argv[2], static_cast<uid_t>(uid),
                                                &listener, &error)) {
    std::cerr << error << '\n';
    return 1;
  }
  HostFakeBackend backend(argv[1], current, target);
  r1_update::PackageOrchestrator orchestrator(argv[1], argv[4], &backend);
  r1_update::SupervisorConfig config{listener, static_cast<uid_t>(uid), argv[1],
                                     argv[4], maximum_requests};
  const bool okay = r1_update::run_update_supervisor(
      config, &orchestrator, r1_update::monotonic_seconds, [] { return false; },
      [](const std::string& value) { std::cerr << value << '\n'; }, &error);
  close(listener);
  struct stat socket_info {};
  if (lstat(argv[2], &socket_info) == 0 && S_ISSOCK(socket_info.st_mode))
    unlink(argv[2]);
  if (!okay) std::cerr << error << '\n';
  return okay ? 0 : 1;
}
