#include "package_orchestrator.h"

#include <array>
#include <cstdlib>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

using r1_update::Candidate;
using r1_update::Health;
using r1_update::Installed;
using r1_update::PackageManagerBackend;
using r1_update::PackageOrchestrator;
using r1_update::Phase;
using r1_update::StagedArchive;
using r1_update::TransactionController;

namespace {

void require(bool value, const char* message) {
  if (!value) { std::cerr << message << '\n'; std::exit(1); }
}

std::array<uint8_t, 32> digest(uint8_t seed) {
  std::array<uint8_t, 32> value{};
  for (size_t index = 0; index < value.size(); ++index)
    value[index] = static_cast<uint8_t>(seed + index);
  return value;
}

Installed old_package() {
  return {"dev.sewellzhong.r1probe", 117, digest(1), digest(90)};
}

Installed new_package() {
  return {"dev.sewellzhong.r1probe", 118, digest(2), digest(90)};
}

Candidate candidate() {
  return {"0123456789abcdef0123456789abcdef", "dev.sewellzhong.r1probe",
          117, 118, 8192, digest(2), digest(90), 180};
}

std::string temporary_directory() {
  char path[] = "/tmp/r1-update-orchestrator-XXXXXX";
  char* result = mkdtemp(path);
  require(result != nullptr, "mkdtemp failed");
  require(chmod(result, 0700) == 0, "chmod directory failed");
  return result;
}

std::string candidate_path(const std::string& directory) {
  return directory + "/candidate-" + candidate().operation_id + ".apk";
}

std::string previous_path(const std::string& directory) {
  return directory + "/previous-" + candidate().operation_id + ".apk";
}

StagedArchive archive(const std::string& directory) {
  return {candidate_path(directory), candidate().apk_size, candidate().apk_sha256};
}

void cleanup(const std::string& directory) {
  unlink((directory + "/transaction.v1").c_str());
  unlink((directory + "/transaction.v1.tmp").c_str());
  require(rmdir(directory.c_str()) == 0, "temp cleanup failed");
}

class FakeBackend final : public PackageManagerBackend {
 public:
  Installed current = old_package();
  std::map<std::string, Installed> archives;
  std::vector<std::string> calls;
  bool fail_backup = false;
  bool corrupt_backup = false;
  bool fail_upgrade = false;
  bool fail_rollback = false;
  bool expose_store_on_upgrade_failure = false;
  bool corrupt_upgrade = false;
  bool fail_next_installed_read = false;

  bool read_installed(const std::string& package_name, Installed* installed,
                      std::string* error) override {
    calls.push_back("read_installed");
    if (fail_next_installed_read) {
      fail_next_installed_read = false;
      if (error != nullptr) *error = "fake_installed_read_failed";
      return false;
    }
    if (package_name != current.package_name || installed == nullptr) return false;
    *installed = current;
    return true;
  }

  bool read_archive(const std::string& path, Installed* value,
                    std::string* error) override {
    calls.push_back(path.find("candidate-") != std::string::npos
                        ? "read_candidate" : "read_previous");
    auto found = archives.find(path);
    if (found == archives.end() || value == nullptr) {
      if (error != nullptr) *error = "fake_archive_missing";
      return false;
    }
    *value = found->second;
    return true;
  }

  bool backup_installed(const std::string& package_name, const std::string& path,
                        std::string* error) override {
    calls.push_back("backup");
    if (fail_backup || package_name != current.package_name) {
      if (error != nullptr) *error = "fake_backup_failed";
      return false;
    }
    archives[path] = current;
    if (corrupt_backup) archives[path].apk_sha256 = digest(44);
    return true;
  }

  bool install_archive(const std::string& path, bool allow_downgrade,
                       std::string* error) override {
    calls.push_back(allow_downgrade ? "install_downgrade" : "install_upgrade");
    if ((!allow_downgrade && fail_upgrade) || (allow_downgrade && fail_rollback)) {
      if (!allow_downgrade && expose_store_on_upgrade_failure) {
        const size_t separator = path.rfind('/');
        if (separator != std::string::npos) chmod(path.substr(0, separator).c_str(), 0755);
      }
      if (error != nullptr) *error = "fake_install_failed";
      return false;
    }
    auto found = archives.find(path);
    if (found == archives.end()) return false;
    current = found->second;
    if (!allow_downgrade && corrupt_upgrade) current.apk_sha256 = digest(45);
    return true;
  }
};

void prepare(FakeBackend* backend, const std::string& directory) {
  backend->archives[candidate_path(directory)] = new_package();
}

void successful_update_has_strict_order() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory);
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(orchestrator.apply(candidate(), archive(directory), 1000, &error),
          "valid update apply failed");
  require(orchestrator.state().phase == Phase::kAwaitingHealth,
          "update did not await health");
  const std::vector<std::string> apply_calls = {
      "read_installed", "read_candidate", "backup", "read_previous",
      "install_upgrade", "read_installed"};
  require(backend.calls == apply_calls, "package side effects were out of order");
  require(orchestrator.confirm_health({true, true, true, true}, &error),
          "healthy update did not commit");
  require(orchestrator.state().phase == Phase::kIdle
          && backend.current.version == 118, "healthy target was not retained");
  cleanup(directory);
}

void backup_failure_aborts_before_install() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory); backend.corrupt_backup = true;
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(!orchestrator.apply(candidate(), archive(directory), 1000, &error)
          && error == "update_previous_backup_failed", "bad backup was accepted");
  require(orchestrator.state().phase == Phase::kIdle && backend.current.version == 117,
          "backup failure changed installed package");
  require(backend.calls.back() == "read_previous", "install ran after bad backup");
  cleanup(directory);
}

void invalid_identity_never_reaches_backend() {
  std::string directory = temporary_directory();
  FakeBackend backend;
  PackageOrchestrator orchestrator(directory, &backend);
  Candidate invalid = candidate(); invalid.operation_id = "../../client-controlled-path";
  StagedArchive supplied{directory + "/anything.apk", invalid.apk_size,
                         invalid.apk_sha256};
  std::string error;
  require(!orchestrator.apply(invalid, supplied, 1000, &error)
          && error == "update_candidate_identity_invalid",
          "invalid operation id reached package backend");
  require(backend.calls.empty(), "backend was called for invalid operation id");
  cleanup(directory);
}

void install_failure_rolls_back_and_verifies() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory); backend.fail_upgrade = true;
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(!orchestrator.apply(candidate(), archive(directory), 1000, &error)
          && error == "update_package_install_failed", "install failure was hidden");
  require(orchestrator.state().phase == Phase::kIdle && backend.current.version == 117,
          "install failure did not restore old package");
  require(backend.calls[backend.calls.size() - 2] == "install_downgrade"
          && backend.calls.back() == "read_installed", "rollback was not verified");
  cleanup(directory);
}

void identity_or_health_failure_rolls_back() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory); backend.corrupt_upgrade = true;
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(!orchestrator.apply(candidate(), archive(directory), 1000, &error)
          && error == "update_installed_identity_mismatch",
          "post-install identity mismatch was accepted");
  require(backend.current.version == 117, "identity mismatch did not roll back");
  cleanup(directory);

  directory = temporary_directory();
  FakeBackend unhealthy; prepare(&unhealthy, directory);
  PackageOrchestrator second(directory, &unhealthy);
  require(second.apply(candidate(), archive(directory), 2000, &error), "apply failed");
  require(!second.confirm_health({true, true, false, true}, &error)
          && error == "update_health_failed", "partial health was accepted");
  require(unhealthy.current.version == 117, "unhealthy target was not rolled back");
  cleanup(directory);
}

void restart_during_install_resumes_rollback_only() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory);
  backend.archives[previous_path(directory)] = old_package();
  TransactionController controller(directory);
  std::string error;
  require(controller.stage(candidate(), old_package(), new_package(), &error),
          "restart setup stage failed");
  require(controller.begin_install(1000, &error), "restart setup begin failed");

  PackageOrchestrator recovered(directory, &backend);
  bool restored = false;
  require(recovered.recover(&restored, &error) && restored,
          "interrupted install recovery failed");
  require(recovered.state().phase == Phase::kIdle && backend.current.version == 117,
          "interrupted install did not finish rollback");
  require(backend.calls.size() == 2 && backend.calls[0] == "install_downgrade"
          && backend.calls[1] == "read_installed", "recovery retried upgrade");
  cleanup(directory);
}

void rollback_failure_is_fail_closed() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory); backend.fail_upgrade = true;
  backend.fail_rollback = true;
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(!orchestrator.apply(candidate(), archive(directory), 1000, &error)
          && error == "update_package_rollback_failed", "rollback failure was hidden");
  require(orchestrator.state().phase == Phase::kFailed,
          "rollback failure did not remain failed closed");
  cleanup(directory);
}

void rollback_side_effect_requires_durable_transition() {
  std::string directory = temporary_directory();
  FakeBackend backend; prepare(&backend, directory); backend.fail_upgrade = true;
  backend.expose_store_on_upgrade_failure = true;
  PackageOrchestrator orchestrator(directory, &backend);
  std::string error;
  require(!orchestrator.apply(candidate(), archive(directory), 1000, &error)
          && error == "update_store_directory_permissions",
          "rollback proceeded after transition persistence failure");
  require(backend.calls.back() == "install_upgrade",
          "downgrade ran without durable rollback state");
  require(chmod(directory.c_str(), 0700) == 0, "test permission restore failed");
  cleanup(directory);
}

}  // namespace

int main() {
  successful_update_has_strict_order();
  backup_failure_aborts_before_install();
  invalid_identity_never_reaches_backend();
  install_failure_rolls_back_and_verifies();
  identity_or_health_failure_rolls_back();
  restart_during_install_resumes_rollback_only();
  rollback_failure_is_fail_closed();
  rollback_side_effect_requires_durable_transition();
  std::cout << "update orchestrator tests passed\n";
}
