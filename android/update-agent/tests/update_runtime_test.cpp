#include "update_runtime.h"

#include <array>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

using r1_update::Phase;
using r1_update::StagedArchive;
using r1_update::State;
using r1_update::TransactionStore;
using r1_update::TransactionController;

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
    output[i] = static_cast<uint8_t>((nibble(value[i * 2]) << 4) | nibble(value[i * 2 + 1]));
  return output;
}

std::string temporary_directory() {
  char path[] = "/tmp/r1-update-runtime-XXXXXX";
  char* result = mkdtemp(path);
  require(result != nullptr, "mkdtemp failed");
  require(chmod(result, 0700) == 0, "chmod directory failed");
  return result;
}

bool write_all(int fd, const std::string& payload) {
  size_t offset = 0;
  while (offset < payload.size()) {
    ssize_t count = write(fd, payload.data() + offset, payload.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return false;
    offset += static_cast<size_t>(count);
  }
  return true;
}

int input_file(const std::string& directory, const std::string& payload) {
  std::string path = directory + "/input";
  int output = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  require(output >= 0 && write_all(output, payload) && close(output) == 0,
          "input write failed");
  int input = open(path.c_str(), O_RDONLY | O_CLOEXEC);
  require(input >= 0, "input open failed");
  return input;
}

State installing_state() {
  State state;
  state.phase = Phase::kInstalling;
  state.candidate.operation_id = "0123456789abcdef0123456789abcdef";
  state.candidate.package_name = "dev.sewellzhong.r1probe";
  state.candidate.from_version = 117;
  state.candidate.to_version = 118;
  state.candidate.apk_size = 4096;
  state.candidate.apk_sha256 = from_hex("c93eee2d0db02f10acc7460d9576e122dcf8cd53c4bf8dfcae1b3e74ebcfff5a");
  state.candidate.signer_sha256 = from_hex("5389688abf55bc46639385085bfaf1fda3552f63303e4d4a55d664d0f515d6ac");
  state.candidate.health_timeout_seconds = 180;
  state.previous_apk_sha256 = from_hex("5389688abf55bc46639385085bfaf1fda3552f63303e4d4a55d664d0f515d6ac");
  state.deadline_monotonic_seconds = 1180;
  state.last_result = "pending";
  return state;
}

void cleanup(const std::string& directory) {
  const char* names[] = {"input", "transaction.v1", "transaction.v1.tmp",
                         "candidate-0123456789abcdef0123456789abcdef.apk",
                         "candidate-0123456789abcdef0123456789abcdef.apk.tmp"};
  for (const char* name : names) unlink((directory + "/" + name).c_str());
  require(rmdir(directory.c_str()) == 0, "temp cleanup failed");
}

void peer_identity_is_exact() {
  std::string error;
  require(r1_update::authorized_peer(10042, 10042, &error), "matching uid rejected");
  require(!r1_update::authorized_peer(0, 10042, &error)
          && error == "update_peer_uid_rejected", "root peer implicitly accepted");
  require(!r1_update::authorized_peer(10042, static_cast<uid_t>(-1), &error)
          && error == "update_satellite_uid_invalid", "invalid configured uid accepted");
}

void state_round_trip_and_recovery() {
  std::string directory = temporary_directory();
  TransactionStore store(directory);
  State expected = installing_state(), actual;
  std::string error;
  require(store.save(expected, &error), "state save failed");
  struct stat info {};
  require(lstat(store.state_path().c_str(), &info) == 0 && S_ISREG(info.st_mode)
          && (info.st_mode & 0777) == 0600, "state permissions are not private");
  require(store.load(&actual, &error), "state load failed");
  require(actual.phase == Phase::kInstalling
          && actual.candidate.operation_id == expected.candidate.operation_id
          && actual.candidate.apk_sha256 == expected.candidate.apk_sha256
          && actual.previous_apk_sha256 == expected.previous_apk_sha256
          && actual.deadline_monotonic_seconds == 1180, "state round trip changed data");
  r1_update::Policy restored(actual);
  require(restored.state().phase == Phase::kRollingBack
          && restored.state().failure == "update_supervisor_restarted_during_install",
          "install crash did not recover into rollback");
  require(store.remove(&error), "state remove failed");
  require(!store.load(&actual, &error) && error == "update_state_missing",
          "removed transaction remained visible");
  cleanup(directory);
}

void controller_persists_every_transition() {
  std::string directory = temporary_directory();
  TransactionController controller(directory);
  State value = installing_state();
  r1_update::Installed current{"dev.sewellzhong.r1probe", 117,
      value.previous_apk_sha256, value.candidate.signer_sha256};
  r1_update::Installed target{"dev.sewellzhong.r1probe", 118,
      value.candidate.apk_sha256, value.candidate.signer_sha256};
  std::string error;
  require(controller.stage(value.candidate, current, target, &error), "controller stage failed");
  require(controller.begin_install(1000, &error), "controller begin failed");

  TransactionController recovered(directory);
  bool restored = false;
  require(recovered.recover(&restored, &error) && restored,
          "controller transaction recovery failed");
  require(recovered.state().phase == Phase::kRollingBack
          && recovered.state().failure == "update_supervisor_restarted_during_install",
          "controller recovered install unsafely");
  require(recovered.rollback_finished(current, &error), "controller rollback failed");

  TransactionController empty(directory);
  require(empty.recover(&restored, &error) && !restored,
          "completed controller left active transaction");

  require(empty.stage(value.candidate, current, target, &error), "success stage failed");
  require(empty.begin_install(2000, &error), "success begin failed");
  require(empty.installed(target, &error), "success install verification failed");
  require(empty.confirm_health(target, {true, true, true, true}, &error),
          "success health confirmation failed");
  TransactionController committed(directory);
  require(committed.recover(&restored, &error) && !restored,
          "successful update left active transaction");
  cleanup(directory);
}

void state_rejects_unsafe_storage() {
  std::string directory = temporary_directory();
  TransactionStore store(directory);
  std::string error;
  require(chmod(directory.c_str(), 0755) == 0, "test chmod failed");
  require(!store.save(installing_state(), &error)
          && error == "update_store_directory_permissions", "public directory accepted");
  require(chmod(directory.c_str(), 0700) == 0, "test chmod restore failed");
  int fd = open((store.state_path() + ".tmp").c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
  require(fd >= 0 && close(fd) == 0, "temp collision setup failed");
  require(store.save(installing_state(), &error), "safe stale temp was not recovered");
  require(store.remove(&error), "state cleanup failed");
  require(symlink("/dev/null", (store.state_path() + ".tmp").c_str()) == 0,
          "unsafe temp setup failed");
  require(!store.save(installing_state(), &error)
          && error == "update_temp_file_unsafe", "unsafe stale temp accepted");
  cleanup(directory);
}

void archive_is_bounded_and_verified() {
  std::string directory = temporary_directory();
  std::string payload(4096, 'a');
  auto expected = from_hex("c93eee2d0db02f10acc7460d9576e122dcf8cd53c4bf8dfcae1b3e74ebcfff5a");
  const std::string operation = "0123456789abcdef0123456789abcdef";
  std::string error;
  StagedArchive archive;
  int input = input_file(directory, payload);
  require(r1_update::stage_archive_from_fd(input, directory, operation, payload.size(),
                                           expected, &archive, &error),
          "valid archive rejected");
  close(input);
  struct stat info {};
  require(archive.size == payload.size() && archive.sha256 == expected
          && lstat(archive.path.c_str(), &info) == 0 && info.st_size == 4096
          && (info.st_mode & 0777) == 0600, "staged archive metadata invalid");
  unlink((directory + "/input").c_str());
  input = input_file(directory, payload);
  require(!r1_update::stage_archive_from_fd(input, directory, operation, payload.size(),
                                            expected, &archive, &error)
          && error == "update_archive_publish_failed", "existing archive was replaced");
  require(unlink(archive.path.c_str()) == 0 && unlink((directory + "/input").c_str()) == 0,
          "valid archive cleanup failed");
  close(input);

  input = input_file(directory, payload + "x");
  require(!r1_update::stage_archive_from_fd(input, directory, operation, payload.size(),
                                            expected, &archive, &error)
          && error == "update_archive_size_mismatch", "trailing archive byte accepted");
  close(input); unlink((directory + "/input").c_str());

  input = input_file(directory, payload);
  auto wrong = from_hex("5389688abf55bc46639385085bfaf1fda3552f63303e4d4a55d664d0f515d6ac");
  require(!r1_update::stage_archive_from_fd(input, directory, operation, payload.size(),
                                            wrong, &archive, &error)
          && error == "update_archive_hash_mismatch", "wrong archive digest accepted");
  close(input);
  cleanup(directory);
}

}  // namespace

int main() {
  peer_identity_is_exact();
  state_round_trip_and_recovery();
  controller_persists_every_transition();
  state_rejects_unsafe_storage();
  archive_is_bounded_and_verified();
  std::cout << "update runtime tests passed\n";
}
