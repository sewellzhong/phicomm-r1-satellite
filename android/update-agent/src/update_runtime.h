#pragma once

#include "update_policy.h"

#include <array>
#include <cstdint>
#include <string>

#include <sys/types.h>

namespace r1_update {

// The socket listener must obtain this value from SO_PEERCRED. Root and other
// privileged callers are deliberately not treated as equivalent to the app.
bool authorized_peer(uid_t peer_uid, uid_t satellite_uid, std::string* error);

// Stores only supervisor-owned metadata. APK bytes are staged separately and
// are always addressed by the policy-validated operation id.
class TransactionStore {
 public:
  explicit TransactionStore(std::string directory);

  bool save(const State& state, std::string* error) const;
  bool load(State* state, std::string* error) const;
  bool remove(std::string* error) const;
  std::string state_path() const;

 private:
  std::string directory_;
};

// Couples every policy transition to durable state. begin_install() persists
// kInstalling before the caller may invoke PackageManager; all rollback
// transitions are likewise durable before the caller performs a downgrade.
class TransactionController {
 public:
  explicit TransactionController(std::string directory);

  const State& state() const { return policy_.state(); }
  bool recover(bool* restored, std::string* error);
  bool stage(const Candidate& candidate, const Installed& installed,
             const Installed& archive, std::string* error);
  bool begin_install(uint64_t now_monotonic_seconds, std::string* error);
  bool installed(const Installed& installed, std::string* error);
  bool confirm_health(const Installed& installed, const Health& health,
                      std::string* error);
  bool tick(uint64_t now_monotonic_seconds, bool same_boot, std::string* error);
  bool rollback_finished(const Installed& installed, std::string* error);

 private:
  bool persist(std::string* error);
  TransactionStore store_;
  Policy policy_;
};

struct StagedArchive {
  std::string path;
  uint64_t size = 0;
  std::array<uint8_t, 32> sha256{};
};

// Copies exactly expected_size bytes from an already received regular-file
// descriptor (for example via SCM_RIGHTS). Pipes and sockets are rejected.
// No client-provided path is opened by the supervisor. The final name derives
// only from the validated operation id and is published with an atomic rename.
bool stage_archive_from_fd(int source_fd, const std::string& directory,
                           const std::string& operation_id,
                           uint64_t expected_size,
                           const std::array<uint8_t, 32>& expected_sha256,
                           StagedArchive* result, std::string* error);

}  // namespace r1_update
