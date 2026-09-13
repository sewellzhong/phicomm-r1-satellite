#include "package_orchestrator.h"

#include <cerrno>
#include <cstring>
#include <utility>

#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace r1_update {
namespace {

constexpr char kPackageName[] = "dev.sewellzhong.r1probe";

bool reject(const std::string& reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
}

bool valid_operation_id(const std::string& value) {
  if (value.size() != 32) return false;
  for (char byte : value) {
    if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'))) return false;
  }
  return true;
}

bool archive_name(const std::string& value, std::string* operation_id) {
  size_t identity_start = 0;
  if (value.compare(0, 10, "candidate-") == 0) identity_start = 10;
  else if (value.compare(0, 9, "previous-") == 0) identity_start = 9;
  else return false;
  if (value.size() != identity_start + 32 + 4
      || value.compare(value.size() - 4, 4, ".apk") != 0)
    return false;
  const std::string parsed = value.substr(identity_start, 32);
  if (!valid_operation_id(parsed)) return false;
  if (operation_id != nullptr) *operation_id = parsed;
  return true;
}

}  // namespace

PackageOrchestrator::PackageOrchestrator(std::string directory,
                                         std::string boot_id,
                                         PackageManagerBackend* backend)
    : directory_(std::move(directory)), boot_id_(std::move(boot_id)),
      backend_(backend), controller_(directory_) {}

std::string PackageOrchestrator::candidate_path(const std::string& operation_id) const {
  return directory_ + "/candidate-" + operation_id + ".apk";
}

std::string PackageOrchestrator::backup_path(const std::string& operation_id) const {
  return directory_ + "/previous-" + operation_id + ".apk";
}

bool PackageOrchestrator::identities_equal(const Installed& left,
                                           const Installed& right) const {
  return left.package_name == right.package_name && left.version == right.version
      && left.apk_sha256 == right.apk_sha256
      && left.signer_sha256 == right.signer_sha256;
}

bool PackageOrchestrator::cleanup_archives(
    const std::string& retained_operation_id, std::string* error) const {
  DIR* directory = opendir(directory_.c_str());
  if (directory == nullptr) return reject("update_archive_cleanup_open_failed", error);
  bool okay = true;
  bool removed = false;
  errno = 0;
  while (struct dirent* entry = readdir(directory)) {
    std::string operation_id;
    const std::string name(entry->d_name);
    if (!archive_name(name, &operation_id)
        || (!retained_operation_id.empty() && operation_id == retained_operation_id))
      continue;
    const std::string path = directory_ + "/" + name;
    struct stat info {};
    if (lstat(path.c_str(), &info) != 0 || !S_ISREG(info.st_mode)
        || S_ISLNK(info.st_mode) || info.st_uid != geteuid()
        || (info.st_mode & 0077) != 0 || unlink(path.c_str()) != 0) {
      okay = false;
      break;
    }
    removed = true;
    errno = 0;
  }
  if (errno != 0) okay = false;
  closedir(directory);
  if (okay && removed) {
    int fd = open(directory_.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    okay = fd >= 0 && fsync(fd) == 0;
    if (fd >= 0) close(fd);
  }
  return okay || reject("update_archive_cleanup_failed", error);
}

bool PackageOrchestrator::recover(bool* restored, std::string* error) {
  if (backend_ == nullptr) return reject("update_package_backend_missing", error);
  if (!controller_.recover(restored, error)) return false;
  const Phase phase = controller_.state().phase;
  const std::string retained = phase == Phase::kIdle
      ? std::string() : controller_.state().candidate.operation_id;
  if (!cleanup_archives(retained, error)) return false;
  if (controller_.state().phase == Phase::kRollingBack
      || controller_.state().phase == Phase::kFailed) {
    if (!rollback(error)) return false;
    return cleanup_archives("", error);
  }
  return true;
}

bool PackageOrchestrator::apply(const Candidate& candidate, const StagedArchive& archive,
                                uint64_t now, std::string* error) {
  if (backend_ == nullptr) return reject("update_package_backend_missing", error);
  if (controller_.state().phase != Phase::kIdle) return reject("update_busy", error);
  if (!valid_operation_id(candidate.operation_id)
      || candidate.package_name != kPackageName)
    return reject("update_candidate_identity_invalid", error);
  const std::string expected_path = candidate_path(candidate.operation_id);
  if (archive.path != expected_path || archive.size != candidate.apk_size
      || archive.sha256 != candidate.apk_sha256)
    return reject("update_staged_archive_mismatch", error);

  Installed current, target;
  if (!backend_->read_installed(kPackageName, &current, error))
    return reject("update_installed_read_failed", error);
  if (!backend_->read_archive(expected_path, &target, error))
    return reject("update_candidate_read_failed", error);
  if (!controller_.stage(candidate, current, target, error)) return false;

  const std::string previous_path = backup_path(candidate.operation_id);
  Installed previous;
  if (!backend_->backup_installed(kPackageName, previous_path, error)
      || !backend_->read_archive(previous_path, &previous, error)
      || !identities_equal(current, previous)) {
    std::string ignored;
    if (!controller_.abort_staged(&ignored))
      return reject(ignored.empty() ? "update_staging_abort_failed" : ignored, error);
    if (!cleanup_archives("", &ignored)) return reject(ignored, error);
    return reject("update_previous_backup_failed", error);
  }

  if (!controller_.begin_install(now, boot_id_, error)) return false;
  if (!backend_->install_archive(expected_path, false, error))
    return fail_install_and_rollback("update_package_install_failed", error);

  Installed installed;
  if (!backend_->read_installed(kPackageName, &installed, error))
    return fail_install_and_rollback("update_installed_read_failed", error);
  std::string transition_error;
  if (!controller_.installed(installed, &transition_error)) {
    if (transition_error != "update_installed_identity_mismatch")
      return reject(transition_error, error);
    return rollback_after(transition_error, error);
  }
  return true;
}

bool PackageOrchestrator::fail_install_and_rollback(const std::string& failure,
                                                    std::string* error) {
  std::string transition_error;
  if (!controller_.installation_failed(&transition_error))
    return reject(transition_error, error);
  return rollback_after(failure, error);
}

bool PackageOrchestrator::confirm_health(const Health& health, std::string* error) {
  if (controller_.state().phase != Phase::kAwaitingHealth)
    return reject("update_not_awaiting_health", error);
  Installed installed;
  if (!backend_->read_installed(kPackageName, &installed, error)) {
    std::string transition_error;
    if (!controller_.health_probe_failed(&transition_error))
      return reject(transition_error, error);
    return rollback_after("update_health_probe_failed", error);
  }
  std::string transition_error;
  if (!controller_.confirm_health(installed, health, &transition_error)) {
    if (transition_error != "update_health_identity_mismatch"
        && transition_error != "update_health_failed")
      return reject(transition_error, error);
    return rollback_after(transition_error, error);
  }
  return cleanup_archives("", error);
}

bool PackageOrchestrator::tick(uint64_t now, bool same_boot, std::string* error) {
  std::string transition_error;
  if (controller_.tick(now, same_boot, &transition_error)) return true;
  if (transition_error != "update_rebooted_before_health"
      && transition_error != "update_health_timeout")
    return reject(transition_error, error);
  return rollback_after(transition_error, error);
}

bool PackageOrchestrator::rollback_after(const std::string& failure,
                                         std::string* error) {
  std::string rollback_error;
  if (!rollback(&rollback_error)) return reject(rollback_error, error);
  if (!cleanup_archives("", &rollback_error)) return reject(rollback_error, error);
  return reject(failure, error);
}

bool PackageOrchestrator::rollback(std::string* error) {
  if (controller_.state().phase != Phase::kRollingBack
      && controller_.state().phase != Phase::kFailed)
    return reject("update_not_rolling_back", error);
  const std::string previous_path = backup_path(controller_.state().candidate.operation_id);
  Installed installed;
  const Installed expected_previous{
      kPackageName, controller_.state().candidate.from_version,
      controller_.state().previous_apk_sha256,
      controller_.state().candidate.signer_sha256};
  // A failed/timed-out install may leave the exact old package untouched.
  // Verify that state first so recovery never performs an unnecessary
  // downgrade merely because the previous process died after begin_install.
  if (backend_->read_installed(kPackageName, &installed, error)
      && identities_equal(installed, expected_previous))
    return controller_.rollback_finished(installed, error);
  if (!backend_->install_archive(previous_path, true, error)
      || !backend_->read_installed(kPackageName, &installed, error)) {
    Installed invalid;
    std::string ignored;
    controller_.rollback_finished(invalid, &ignored);
    return reject("update_package_rollback_failed", error);
  }
  return controller_.rollback_finished(installed, error);
}

}  // namespace r1_update
