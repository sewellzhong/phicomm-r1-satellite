#pragma once

#include "package_orchestrator.h"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace r1_update {

struct CommandResult {
  int exit_code = -1;
  std::string stdout_text;
  std::string stderr_text;
};

using CommandRunner = std::function<bool(
    const std::vector<std::string>& arguments,
    const std::vector<std::string>& environment,
    uint32_t timeout_seconds, CommandResult* result, std::string* error)>;

// Executes one fixed argv without a shell. Output is bounded and a timeout
// kills the entire direct child before returning.
bool run_fixed_command(const std::vector<std::string>& arguments,
                       const std::vector<std::string>& environment,
                       uint32_t timeout_seconds, CommandResult* result,
                       std::string* error);

class AndroidPackageManagerBackend final : public PackageManagerBackend {
 public:
  AndroidPackageManagerBackend(std::string transaction_directory,
                               std::string helper_jar,
                               CommandRunner runner = run_fixed_command);

  bool read_installed(const std::string& package_name, Installed* installed,
                      std::string* error) override;
  bool read_archive(const std::string& archive_path, Installed* archive,
                    std::string* error) override;
  bool backup_installed(const std::string& package_name,
                        const std::string& destination_path,
                        std::string* error) override;
  bool install_archive(const std::string& archive_path, bool allow_downgrade,
                       std::string* error) override;

 private:
  bool read_identity(const std::string& mode, const std::string& value,
                     Installed* installed, std::string* apk_path,
                     std::string* error);
  bool transaction_archive_path(const std::string& path) const;

  std::string transaction_directory_;
  std::string helper_jar_;
  CommandRunner runner_;
};

}  // namespace r1_update
