#pragma once

#include "update_runtime.h"

#include <cstdint>
#include <string>

namespace r1_update {

// Device implementations must call PackageManager through a fixed argv/Binder
// contract. The supervisor never accepts a command line or a client path.
class PackageManagerBackend {
 public:
  virtual ~PackageManagerBackend() = default;
  virtual bool read_installed(const std::string& package_name, Installed* installed,
                              std::string* error) = 0;
  virtual bool read_archive(const std::string& archive_path, Installed* archive,
                            std::string* error) = 0;
  virtual bool backup_installed(const std::string& package_name,
                                const std::string& destination_path,
                                std::string* error) = 0;
  virtual bool install_archive(const std::string& archive_path, bool allow_downgrade,
                               std::string* error) = 0;
};

class PackageOrchestrator {
 public:
  PackageOrchestrator(std::string directory, std::string boot_id,
                      PackageManagerBackend* backend);

  const State& state() const { return controller_.state(); }
  bool recover(bool* restored, std::string* error);
  bool apply(const Candidate& candidate, const StagedArchive& archive,
             uint64_t now_monotonic_seconds, std::string* error);
  bool confirm_health(const Health& health, std::string* error);
  bool tick(uint64_t now_monotonic_seconds, bool same_boot, std::string* error);

 private:
  std::string candidate_path(const std::string& operation_id) const;
  std::string backup_path(const std::string& operation_id) const;
  bool rollback(std::string* error);
  bool rollback_after(const std::string& failure, std::string* error);
  bool fail_install_and_rollback(const std::string& failure, std::string* error);
  bool identities_equal(const Installed& left, const Installed& right) const;

  std::string directory_;
  std::string boot_id_;
  PackageManagerBackend* backend_;
  TransactionController controller_;
};

}  // namespace r1_update
