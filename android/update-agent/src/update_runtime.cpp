#include "update_runtime.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace r1_update {
namespace {

constexpr uint64_t kMinimumApkBytes = 4096;
constexpr uint64_t kMaximumApkBytes = 64ULL * 1024ULL * 1024ULL;
constexpr size_t kMaximumStateBytes = 16 * 1024;
constexpr char kStateName[] = "transaction.v1";

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

std::string hex(const std::array<uint8_t, 32>& value) {
  static constexpr char digits[] = "0123456789abcdef";
  std::string output(64, '0');
  for (size_t i = 0; i < value.size(); ++i) {
    output[i * 2] = digits[value[i] >> 4];
    output[i * 2 + 1] = digits[value[i] & 15];
  }
  return output;
}

bool parse_hex(const std::string& value, std::array<uint8_t, 32>* output) {
  if (value.size() != 64 || output == nullptr) return false;
  auto nibble = [](char byte) -> int {
    if (byte >= '0' && byte <= '9') return byte - '0';
    if (byte >= 'a' && byte <= 'f') return byte - 'a' + 10;
    return -1;
  };
  for (size_t i = 0; i < output->size(); ++i) {
    int high = nibble(value[i * 2]);
    int low = nibble(value[i * 2 + 1]);
    if (high < 0 || low < 0) return false;
    (*output)[i] = static_cast<uint8_t>((high << 4) | low);
  }
  return true;
}

bool write_all(int fd, const uint8_t* data, size_t size) {
  while (size > 0) {
    ssize_t written = write(fd, data, size);
    if (written < 0 && errno == EINTR) continue;
    if (written <= 0) return false;
    data += written;
    size -= static_cast<size_t>(written);
  }
  return true;
}

bool sync_directory(const std::string& directory) {
  int fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (fd < 0) return false;
  bool okay = fsync(fd) == 0;
  close(fd);
  return okay;
}

bool ensure_private_directory(const std::string& directory, std::string* error) {
  struct stat info {};
  if (lstat(directory.c_str(), &info) != 0)
    return reject("update_store_directory_missing", error);
  if (!S_ISDIR(info.st_mode) || S_ISLNK(info.st_mode))
    return reject("update_store_directory_unsafe", error);
  if (info.st_uid != geteuid()) return reject("update_store_directory_owner", error);
  if ((info.st_mode & 0077) != 0)
    return reject("update_store_directory_permissions", error);
  return true;
}

bool remove_stale_temp(const std::string& path, std::string* error) {
  struct stat info {};
  if (lstat(path.c_str(), &info) != 0)
    return errno == ENOENT || reject("update_temp_stat_failed", error);
  if (!S_ISREG(info.st_mode) || info.st_uid != geteuid() || (info.st_mode & 0077) != 0)
    return reject("update_temp_file_unsafe", error);
  if (unlink(path.c_str()) != 0) return reject("update_temp_remove_failed", error);
  return true;
}

bool parse_u64(const std::string& value, uint64_t* output) {
  if (value.empty() || output == nullptr) return false;
  uint64_t result = 0;
  for (char byte : value) {
    if (byte < '0' || byte > '9') return false;
    uint64_t digit = static_cast<uint64_t>(byte - '0');
    if (result > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
    result = result * 10 + digit;
  }
  *output = result;
  return true;
}

std::string encode(const State& state) {
  std::ostringstream out;
  out << "R1_UPDATE_TRANSACTION_V1\n"
      << "phase=" << static_cast<uint32_t>(state.phase) << '\n'
      << "operation_id=" << state.candidate.operation_id << '\n'
      << "package_name=" << state.candidate.package_name << '\n'
      << "from_version=" << state.candidate.from_version << '\n'
      << "to_version=" << state.candidate.to_version << '\n'
      << "apk_size=" << state.candidate.apk_size << '\n'
      << "apk_sha256=" << hex(state.candidate.apk_sha256) << '\n'
      << "signer_sha256=" << hex(state.candidate.signer_sha256) << '\n'
      << "health_timeout_seconds=" << state.candidate.health_timeout_seconds << '\n'
      << "previous_apk_sha256=" << hex(state.previous_apk_sha256) << '\n'
      << "deadline_monotonic_seconds=" << state.deadline_monotonic_seconds << '\n'
      << "failure=" << state.failure << '\n'
      << "last_result=" << state.last_result << '\n';
  return out.str();
}

bool safe_text(const std::string& value) {
  for (char byte : value) {
    if (byte == '\n' || byte == '\r' || byte == '\0' || byte == '=') return false;
  }
  return value.size() <= 256;
}

bool decode(const std::string& payload, State* state, std::string* error) {
  if (state == nullptr) return reject("update_state_output_missing", error);
  std::istringstream input(payload);
  std::string line;
  if (!std::getline(input, line) || line != "R1_UPDATE_TRANSACTION_V1")
    return reject("update_state_header_invalid", error);
  std::vector<std::string> values;
  static constexpr const char* names[] = {
      "phase", "operation_id", "package_name", "from_version", "to_version",
      "apk_size", "apk_sha256", "signer_sha256", "health_timeout_seconds",
      "previous_apk_sha256", "deadline_monotonic_seconds", "failure", "last_result"};
  for (const char* name : names) {
    if (!std::getline(input, line)) return reject("update_state_truncated", error);
    std::string prefix = std::string(name) + "=";
    if (line.compare(0, prefix.size(), prefix) != 0)
      return reject("update_state_field_invalid", error);
    values.push_back(line.substr(prefix.size()));
  }
  if (std::getline(input, line)) return reject("update_state_trailing_data", error);

  uint64_t phase = 0, from = 0, to = 0, timeout = 0;
  State decoded;
  if (!parse_u64(values[0], &phase) || phase < static_cast<uint32_t>(Phase::kIdle)
      || phase > static_cast<uint32_t>(Phase::kFailed)
      || !valid_operation_id(values[1]) || values[2] != "dev.sewellzhong.r1probe"
      || !parse_u64(values[3], &from) || from > UINT32_MAX
      || !parse_u64(values[4], &to) || to > UINT32_MAX
      || !parse_u64(values[5], &decoded.candidate.apk_size)
      || !parse_hex(values[6], &decoded.candidate.apk_sha256)
      || !parse_hex(values[7], &decoded.candidate.signer_sha256)
      || !parse_u64(values[8], &timeout) || timeout > UINT32_MAX
      || !parse_hex(values[9], &decoded.previous_apk_sha256)
      || !parse_u64(values[10], &decoded.deadline_monotonic_seconds)
      || !safe_text(values[11]) || !safe_text(values[12]))
    return reject("update_state_value_invalid", error);
  decoded.phase = static_cast<Phase>(phase);
  decoded.candidate.operation_id = values[1];
  decoded.candidate.package_name = values[2];
  decoded.candidate.from_version = static_cast<uint32_t>(from);
  decoded.candidate.to_version = static_cast<uint32_t>(to);
  decoded.candidate.health_timeout_seconds = static_cast<uint32_t>(timeout);
  decoded.failure = values[11];
  decoded.last_result = values[12];
  *state = decoded;
  return true;
}

// Compact SHA-256 implementation used to avoid depending on a firmware crypto
// provider. It is used only for artifact integrity, not secret material.
class Sha256 {
 public:
  void update(const uint8_t* data, size_t size) {
    total_ += size;
    while (size > 0) {
      size_t take = std::min(size, block_.size() - used_);
      std::memcpy(block_.data() + used_, data, take);
      used_ += take; data += take; size -= take;
      if (used_ == block_.size()) { compress(block_.data()); used_ = 0; }
    }
  }

  std::array<uint8_t, 32> finish() {
    uint64_t bits = total_ * 8;
    block_[used_++] = 0x80;
    if (used_ > 56) {
      std::fill(block_.begin() + used_, block_.end(), 0); compress(block_.data()); used_ = 0;
    }
    std::fill(block_.begin() + used_, block_.begin() + 56, 0);
    for (size_t i = 0; i < 8; ++i) block_[63 - i] = static_cast<uint8_t>(bits >> (i * 8));
    compress(block_.data());
    std::array<uint8_t, 32> output{};
    for (size_t i = 0; i < words_.size(); ++i)
      for (size_t j = 0; j < 4; ++j) output[i * 4 + j] = static_cast<uint8_t>(words_[i] >> (24 - j * 8));
    return output;
  }

 private:
  static uint32_t rotate(uint32_t value, uint32_t bits) { return (value >> bits) | (value << (32 - bits)); }
  void compress(const uint8_t* data) {
    static constexpr uint32_t constants[64] = {
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    uint32_t w[64]{};
    for (size_t i = 0; i < 16; ++i)
      w[i] = (static_cast<uint32_t>(data[i*4]) << 24) | (static_cast<uint32_t>(data[i*4+1]) << 16)
          | (static_cast<uint32_t>(data[i*4+2]) << 8) | data[i*4+3];
    for (size_t i = 16; i < 64; ++i) {
      uint32_t s0 = rotate(w[i-15],7) ^ rotate(w[i-15],18) ^ (w[i-15] >> 3);
      uint32_t s1 = rotate(w[i-2],17) ^ rotate(w[i-2],19) ^ (w[i-2] >> 10);
      w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=words_[0],b=words_[1],c=words_[2],d=words_[3],e=words_[4],f=words_[5],g=words_[6],h=words_[7];
    for (size_t i = 0; i < 64; ++i) {
      uint32_t s1=rotate(e,6)^rotate(e,11)^rotate(e,25), ch=(e&f)^((~e)&g);
      uint32_t t1=h+s1+ch+constants[i]+w[i], s0=rotate(a,2)^rotate(a,13)^rotate(a,22);
      uint32_t maj=(a&b)^(a&c)^(b&c), t2=s0+maj;
      h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    words_[0]+=a;words_[1]+=b;words_[2]+=c;words_[3]+=d;words_[4]+=e;words_[5]+=f;words_[6]+=g;words_[7]+=h;
  }
  std::array<uint32_t,8> words_{{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
  std::array<uint8_t,64> block_{};
  size_t used_ = 0;
  uint64_t total_ = 0;
};

}  // namespace

bool authorized_peer(uid_t peer_uid, uid_t satellite_uid, std::string* error) {
  if (satellite_uid == static_cast<uid_t>(-1)) return reject("update_satellite_uid_invalid", error);
  if (peer_uid != satellite_uid) return reject("update_peer_uid_rejected", error);
  return true;
}

TransactionStore::TransactionStore(std::string directory) : directory_(std::move(directory)) {}
std::string TransactionStore::state_path() const { return directory_ + "/" + kStateName; }

bool TransactionStore::save(const State& state, std::string* error) const {
  if (!ensure_private_directory(directory_, error)) return false;
  if (!valid_operation_id(state.candidate.operation_id)
      || state.candidate.package_name != "dev.sewellzhong.r1probe"
      || !safe_text(state.failure) || !safe_text(state.last_result))
    return reject("update_state_text_invalid", error);
  std::string payload = encode(state);
  if (payload.size() > kMaximumStateBytes) return reject("update_state_too_large", error);
  std::string temporary = state_path() + ".tmp";
  if (!remove_stale_temp(temporary, error)) return false;
  int fd = open(temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (fd < 0) return reject("update_state_temp_open_failed", error);
  bool okay = write_all(fd, reinterpret_cast<const uint8_t*>(payload.data()), payload.size())
      && fsync(fd) == 0 && close(fd) == 0;
  if (!okay) { close(fd); unlink(temporary.c_str()); return reject("update_state_write_failed", error); }
  if (rename(temporary.c_str(), state_path().c_str()) != 0) {
    unlink(temporary.c_str()); return reject("update_state_rename_failed", error);
  }
  if (!sync_directory(directory_)) return reject("update_state_directory_sync_failed", error);
  return true;
}

bool TransactionStore::load(State* state, std::string* error) const {
  if (!ensure_private_directory(directory_, error)) return false;
  int fd = open(state_path().c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0) return reject(errno == ENOENT ? "update_state_missing" : "update_state_open_failed", error);
  struct stat info {};
  if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size <= 0
      || static_cast<uint64_t>(info.st_size) > kMaximumStateBytes || info.st_uid != geteuid()
      || (info.st_mode & 0077) != 0) {
    close(fd); return reject("update_state_file_unsafe", error);
  }
  std::string payload(static_cast<size_t>(info.st_size), '\0');
  size_t offset = 0;
  while (offset < payload.size()) {
    ssize_t count = read(fd, &payload[offset], payload.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { close(fd); return reject("update_state_read_failed", error); }
    offset += static_cast<size_t>(count);
  }
  close(fd);
  return decode(payload, state, error);
}

TransactionController::TransactionController(std::string directory)
    : store_(std::move(directory)), policy_() {}

bool TransactionController::recover(bool* restored, std::string* error) {
  if (restored == nullptr) return reject("update_restore_output_missing", error);
  State state;
  if (!store_.load(&state, error)) {
    if (error != nullptr && *error == "update_state_missing") {
      *restored = false;
      *error = "";
      return true;
    }
    return false;
  }
  policy_ = Policy(state);
  *restored = true;
  // The Policy constructor turns an ambiguous interrupted install into rollback.
  return persist(error);
}

bool TransactionController::persist(std::string* error) {
  if (policy_.state().phase == Phase::kIdle) return store_.remove(error);
  return store_.save(policy_.state(), error);
}

bool TransactionController::stage(const Candidate& candidate, const Installed& installed,
                                  const Installed& archive, std::string* error) {
  if (!policy_.stage(candidate, installed, archive, error)) return false;
  return persist(error);
}

bool TransactionController::begin_install(uint64_t now, std::string* error) {
  if (!policy_.begin_install(now, error)) return false;
  return persist(error);
}

bool TransactionController::installed(const Installed& installed_value, std::string* error) {
  bool accepted = policy_.installed(installed_value, error);
  std::string policy_error = error == nullptr ? "" : *error;
  if (!persist(error)) return false;
  if (!accepted && error != nullptr) *error = policy_error;
  return accepted;
}

bool TransactionController::confirm_health(const Installed& installed_value,
                                           const Health& health, std::string* error) {
  bool accepted = policy_.confirm_health(installed_value, health, error);
  std::string policy_error = error == nullptr ? "" : *error;
  if (!persist(error)) return false;
  if (!accepted && error != nullptr) *error = policy_error;
  return accepted;
}

bool TransactionController::tick(uint64_t now, bool same_boot, std::string* error) {
  Phase before = policy_.state().phase;
  bool accepted = policy_.tick(now, same_boot, error);
  std::string policy_error = error == nullptr ? "" : *error;
  if (policy_.state().phase != before && !persist(error)) return false;
  if (!accepted && error != nullptr) *error = policy_error;
  return accepted;
}

bool TransactionController::rollback_finished(const Installed& installed_value,
                                              std::string* error) {
  bool accepted = policy_.rollback_finished(installed_value, error);
  std::string policy_error = error == nullptr ? "" : *error;
  if (!persist(error)) return false;
  if (!accepted && error != nullptr) *error = policy_error;
  return accepted;
}

bool TransactionStore::remove(std::string* error) const {
  if (!ensure_private_directory(directory_, error)) return false;
  if (unlink(state_path().c_str()) != 0 && errno != ENOENT)
    return reject("update_state_remove_failed", error);
  if (!sync_directory(directory_)) return reject("update_state_directory_sync_failed", error);
  return true;
}

bool stage_archive_from_fd(int source_fd, const std::string& directory,
                           const std::string& operation_id, uint64_t expected_size,
                           const std::array<uint8_t, 32>& expected_sha256,
                           StagedArchive* result, std::string* error) {
  if (source_fd < 0 || result == nullptr) return reject("update_archive_input_invalid", error);
  if (!ensure_private_directory(directory, error)) return false;
  if (!valid_operation_id(operation_id)) return reject("update_operation_id_invalid", error);
  if (expected_size < kMinimumApkBytes || expected_size > kMaximumApkBytes)
    return reject("update_apk_size_invalid", error);
  struct stat source_info {};
  if (fstat(source_fd, &source_info) != 0 || !S_ISREG(source_info.st_mode))
    return reject("update_archive_source_not_regular", error);
  if (source_info.st_size < 0 || static_cast<uint64_t>(source_info.st_size) != expected_size)
    return reject("update_archive_size_mismatch", error);
  std::string final_path = directory + "/candidate-" + operation_id + ".apk";
  std::string temp_path = final_path + ".tmp";
  if (!remove_stale_temp(temp_path, error)) return false;
  int output = open(temp_path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (output < 0) return reject("update_archive_temp_open_failed", error);
  Sha256 digest;
  std::array<uint8_t, 32768> buffer{};
  uint64_t copied = 0;
  bool okay = true;
  while (copied < expected_size) {
    size_t wanted = static_cast<size_t>(std::min<uint64_t>(buffer.size(), expected_size - copied));
    ssize_t count = pread(source_fd, buffer.data(), wanted, static_cast<off_t>(copied));
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { okay = false; break; }
    digest.update(buffer.data(), static_cast<size_t>(count));
    if (!write_all(output, buffer.data(), static_cast<size_t>(count))) { okay = false; break; }
    copied += static_cast<uint64_t>(count);
  }
  struct stat final_source_info {};
  if (fstat(source_fd, &final_source_info) != 0
      || final_source_info.st_dev != source_info.st_dev
      || final_source_info.st_ino != source_info.st_ino
      || final_source_info.st_size != source_info.st_size) okay = false;
  std::array<uint8_t, 32> actual = digest.finish();
  if (!okay || copied != expected_size || actual != expected_sha256 || fsync(output) != 0
      || close(output) != 0) {
    close(output); unlink(temp_path.c_str());
    return reject(actual != expected_sha256 ? "update_archive_hash_mismatch" : "update_archive_size_mismatch", error);
  }
  // link()+unlink() publishes atomically without replacing an existing archive.
  if (link(temp_path.c_str(), final_path.c_str()) != 0 || unlink(temp_path.c_str()) != 0) {
    unlink(temp_path.c_str()); return reject("update_archive_publish_failed", error);
  }
  if (!sync_directory(directory)) return reject("update_archive_directory_sync_failed", error);
  result->path = final_path; result->size = copied; result->sha256 = actual;
  return true;
}

}  // namespace r1_update
