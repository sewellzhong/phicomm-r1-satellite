#include "update_policy.h"

#include <algorithm>
#include <regex>

namespace r1_update {
namespace {

constexpr uint64_t kMinimumApkBytes = 4096;
constexpr uint64_t kMaximumApkBytes = 64ULL * 1024ULL * 1024ULL;
constexpr uint32_t kMinimumHealthSeconds = 30;
constexpr uint32_t kMaximumHealthSeconds = 600;

bool nonzero(const std::array<uint8_t, 32>& value) {
  return std::any_of(value.begin(), value.end(), [](uint8_t byte) { return byte != 0; });
}

bool valid_boot_id(const std::string& value) {
  if (value.size() != 36) return false;
  for (size_t index = 0; index < value.size(); ++index) {
    const char byte = value[index];
    if (index == 8 || index == 13 || index == 18 || index == 23) {
      if (byte != '-') return false;
    } else if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool reject(const char* reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
}

}  // namespace

Policy::Policy(State state) : state_(std::move(state)) {
  if (state_.phase == Phase::kInstalling) {
    // A supervisor restart during package replacement is ambiguous. The old package is
    // already retained, so fail closed into rollback instead of retrying installation.
    state_.phase = Phase::kRollingBack;
    state_.failure = "update_supervisor_restarted_during_install";
  }
}

bool Policy::valid_candidate(const Candidate& candidate, const Installed& installed,
                             const Installed& archive, std::string* error) {
  if (!std::regex_match(candidate.operation_id, std::regex("[a-f0-9]{32}")))
    return reject("update_operation_id_invalid", error);
  if (candidate.package_name != "dev.sewellzhong.r1probe"
      || candidate.package_name != installed.package_name)
    return reject("update_package_mismatch", error);
  if (candidate.from_version != installed.version)
    return reject("update_source_version_mismatch", error);
  if (candidate.to_version <= candidate.from_version)
    return reject("update_version_not_newer", error);
  if (candidate.apk_size < kMinimumApkBytes || candidate.apk_size > kMaximumApkBytes)
    return reject("update_apk_size_invalid", error);
  if (!nonzero(candidate.apk_sha256) || !nonzero(candidate.signer_sha256))
    return reject("update_digest_missing", error);
  if (candidate.signer_sha256 != installed.signer_sha256)
    return reject("update_signer_mismatch", error);
  if (archive.package_name != candidate.package_name)
    return reject("update_archive_package_mismatch", error);
  if (archive.version != candidate.to_version)
    return reject("update_archive_version_mismatch", error);
  if (archive.apk_sha256 != candidate.apk_sha256)
    return reject("update_archive_hash_mismatch", error);
  if (archive.signer_sha256 != candidate.signer_sha256)
    return reject("update_archive_signer_mismatch", error);
  if (candidate.health_timeout_seconds < kMinimumHealthSeconds
      || candidate.health_timeout_seconds > kMaximumHealthSeconds)
    return reject("update_health_timeout_invalid", error);
  return true;
}

bool Policy::stage(const Candidate& candidate, const Installed& installed,
                   const Installed& archive, std::string* error) {
  if (state_.phase != Phase::kIdle) return reject("update_busy", error);
  if (!valid_candidate(candidate, installed, archive, error)) return false;
  state_ = {};
  state_.phase = Phase::kStaged;
  state_.candidate = candidate;
  state_.previous_apk_sha256 = installed.apk_sha256;
  state_.last_result = "pending";
  return true;
}

bool Policy::begin_install(uint64_t now, const std::string& boot_id,
                           std::string* error) {
  if (state_.phase != Phase::kStaged) return reject("update_not_staged", error);
  if (!valid_boot_id(boot_id)) return reject("update_boot_id_invalid", error);
  if (now > UINT64_MAX - state_.candidate.health_timeout_seconds)
    return reject("update_deadline_overflow", error);
  state_.phase = Phase::kInstalling;
  state_.deadline_monotonic_seconds = now + state_.candidate.health_timeout_seconds;
  state_.boot_id = boot_id;
  return true;
}

bool Policy::abort_staged(std::string* error) {
  if (state_.phase != Phase::kStaged) return reject("update_not_staged", error);
  state_.phase = Phase::kIdle;
  state_.last_result = "staging_failed";
  return true;
}

bool Policy::installation_failed(std::string* error) {
  if (state_.phase != Phase::kInstalling) return reject("update_not_installing", error);
  return request_rollback("update_package_install_failed", error);
}

bool Policy::health_probe_failed(std::string* error) {
  if (state_.phase != Phase::kAwaitingHealth)
    return reject("update_not_awaiting_health", error);
  return request_rollback("update_health_probe_failed", error);
}

bool Policy::matches_candidate(const Candidate& candidate, const Installed& installed) {
  return installed.package_name == candidate.package_name
      && installed.version == candidate.to_version
      && installed.apk_sha256 == candidate.apk_sha256
      && installed.signer_sha256 == candidate.signer_sha256;
}

bool Policy::installed(const Installed& installed, std::string* error) {
  if (state_.phase != Phase::kInstalling) return reject("update_not_installing", error);
  if (!matches_candidate(state_.candidate, installed))
    return request_rollback("update_installed_identity_mismatch", error);
  state_.phase = Phase::kAwaitingHealth;
  return true;
}

bool Policy::confirm_health(const Installed& installed, const Health& health,
                            std::string* error) {
  if (state_.phase != Phase::kAwaitingHealth)
    return reject("update_not_awaiting_health", error);
  if (!matches_candidate(state_.candidate, installed))
    return request_rollback("update_health_identity_mismatch", error);
  if (!health.service_ready || !health.state_loaded || !health.audio_agent_reachable
      || !health.isolation_safe)
    return request_rollback("update_health_failed", error);
  state_.phase = Phase::kIdle;
  state_.deadline_monotonic_seconds = 0;
  state_.boot_id.clear();
  state_.failure.clear();
  state_.last_result = "updated";
  return true;
}

bool Policy::request_rollback(const std::string& reason, std::string* error) {
  state_.phase = Phase::kRollingBack;
  state_.failure = reason;
  if (error != nullptr) *error = reason;
  return false;
}

bool Policy::tick(uint64_t now, bool same_boot, std::string* error) {
  if (state_.phase != Phase::kAwaitingHealth && state_.phase != Phase::kInstalling)
    return true;
  if (!same_boot)
    return request_rollback("update_rebooted_before_health", error);
  if (now >= state_.deadline_monotonic_seconds)
    return request_rollback("update_health_timeout", error);
  return true;
}

bool Policy::rollback_finished(const Installed& installed, std::string* error) {
  if (state_.phase != Phase::kRollingBack)
    return reject("update_not_rolling_back", error);
  if (installed.package_name != state_.candidate.package_name
      || installed.version != state_.candidate.from_version
      || installed.apk_sha256 != state_.previous_apk_sha256
      || installed.signer_sha256 != state_.candidate.signer_sha256) {
    state_.phase = Phase::kFailed;
    state_.failure = "update_rollback_verification_failed";
    state_.last_result = "rollback_failed";
    return reject("update_rollback_verification_failed", error);
  }
  state_.phase = Phase::kIdle;
  state_.deadline_monotonic_seconds = 0;
  state_.boot_id.clear();
  state_.last_result = "rolled_back";
  return true;
}

}  // namespace r1_update
