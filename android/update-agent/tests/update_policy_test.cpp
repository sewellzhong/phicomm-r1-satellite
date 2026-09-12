#include "update_policy.h"

#include <cstdlib>
#include <iostream>

using r1_update::Candidate;
using r1_update::Health;
using r1_update::Installed;
using r1_update::Phase;
using r1_update::Policy;
using r1_update::State;

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

Installed current() {
  return {"dev.sewellzhong.r1probe", 117, digest(1), digest(90)};
}

Candidate candidate() {
  return {"0123456789abcdef0123456789abcdef", "dev.sewellzhong.r1probe",
          117, 118, 8 * 1024 * 1024, digest(2), digest(90), 180};
}

Installed target() {
  return {"dev.sewellzhong.r1probe", 118, digest(2), digest(90)};
}

void successful_update() {
  Policy policy; std::string error;
  require(policy.stage(candidate(), current(), target(), &error), "stage failed");
  require(policy.begin_install(1000, &error), "begin failed");
  require(policy.installed(target(), &error), "installed failed");
  require(policy.confirm_health(target(), {true, true, true, true}, &error),
          "health failed");
  require(policy.state().phase == Phase::kIdle, "success did not commit");
  require(policy.state().last_result == "updated", "success audit result missing");
}

void admission_rejections() {
  std::string error;
  Candidate value = candidate(); value.to_version = value.from_version;
  require(!Policy().stage(value, current(), target(), &error)
          && error == "update_version_not_newer", "same version accepted");
  value = candidate(); value.signer_sha256 = digest(91);
  require(!Policy().stage(value, current(), target(), &error)
          && error == "update_signer_mismatch", "foreign signer accepted");
  value = candidate(); value.apk_sha256 = {};
  require(!Policy().stage(value, current(), target(), &error)
          && error == "update_digest_missing", "missing digest accepted");
  value = candidate(); value.health_timeout_seconds = 601;
  require(!Policy().stage(value, current(), target(), &error)
          && error == "update_health_timeout_invalid", "unbounded health accepted");
  value = candidate(); Installed wrong_hash = target(); wrong_hash.apk_sha256 = digest(3);
  require(!Policy().stage(value, current(), wrong_hash, &error)
          && error == "update_archive_hash_mismatch", "wrong archive hash accepted");
  Installed wrong_version = target(); wrong_version.version = 119;
  require(!Policy().stage(value, current(), wrong_version, &error)
          && error == "update_archive_version_mismatch", "wrong archive version accepted");
}

void timeout_rolls_back() {
  Policy policy; std::string error;
  require(policy.stage(candidate(), current(), target(), &error), "stage failed");
  require(policy.begin_install(1000, &error), "begin failed");
  require(policy.installed(target(), &error), "installed failed");
  require(!policy.tick(1180, true, &error) && policy.state().phase == Phase::kRollingBack,
          "timeout did not roll back");
  require(policy.rollback_finished(current(), &error), "rollback not confirmed");
  require(policy.state().phase == Phase::kIdle, "rollback did not clear state");
  require(policy.state().last_result == "rolled_back"
          && policy.state().failure == "update_health_timeout",
          "rollback audit result missing");
}

void bad_health_and_reboot_roll_back() {
  std::string error;
  Policy unhealthy;
  require(unhealthy.stage(candidate(), current(), target(), &error), "stage failed");
  require(unhealthy.begin_install(1, &error), "begin failed");
  require(unhealthy.installed(target(), &error), "install failed");
  require(!unhealthy.confirm_health(target(), {true, true, false, true}, &error)
          && error == "update_health_failed", "partial health accepted");

  Policy rebooted;
  require(rebooted.stage(candidate(), current(), target(), &error), "stage failed");
  require(rebooted.begin_install(1, &error), "begin failed");
  require(!rebooted.tick(2, false, &error)
          && error == "update_rebooted_before_health", "reboot accepted");
}

void supervisor_restart_and_failed_rollback_are_closed() {
  State state; state.phase = Phase::kInstalling; state.candidate = candidate();
  Policy restored(state); std::string error;
  require(restored.state().phase == Phase::kRollingBack,
          "ambiguous supervisor restart retried install");
  Installed wrong = current(); wrong.version = 116;
  state.previous_apk_sha256 = current().apk_sha256;
  Policy restored_with_hash(state);
  require(!restored_with_hash.rollback_finished(wrong, &error)
          && restored_with_hash.state().phase == Phase::kFailed,
          "bad rollback reported success");
  require(restored_with_hash.state().last_result == "rollback_failed",
          "failed rollback audit result missing");
}

}  // namespace

int main() {
  successful_update();
  admission_rejections();
  timeout_rolls_back();
  bad_health_and_reboot_roll_back();
  supervisor_restart_and_failed_rollback_are_closed();
  std::cout << "update policy tests passed\n";
}
