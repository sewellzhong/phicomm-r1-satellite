#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace r1_update {

enum class Phase : uint32_t {
  kIdle = 1,
  kStaged = 2,
  kInstalling = 3,
  kAwaitingHealth = 4,
  kRollingBack = 5,
  kFailed = 6,
};

struct Candidate {
  std::string operation_id;
  std::string package_name;
  uint32_t from_version = 0;
  uint32_t to_version = 0;
  uint64_t apk_size = 0;
  std::array<uint8_t, 32> apk_sha256{};
  std::array<uint8_t, 32> signer_sha256{};
  uint32_t health_timeout_seconds = 0;
};

struct Installed {
  std::string package_name;
  uint32_t version = 0;
  std::array<uint8_t, 32> apk_sha256{};
  std::array<uint8_t, 32> signer_sha256{};
};

struct Health {
  bool service_ready = false;
  bool state_loaded = false;
  bool audio_agent_reachable = false;
  bool isolation_safe = false;
};

struct State {
  Phase phase = Phase::kIdle;
  Candidate candidate;
  std::array<uint8_t, 32> previous_apk_sha256{};
  uint64_t deadline_monotonic_seconds = 0;
  std::string failure;
  std::string last_result = "none";
};

class Policy {
 public:
  explicit Policy(State state = {});

  const State& state() const { return state_; }
  bool stage(const Candidate& candidate, const Installed& installed,
             const Installed& archive,
             std::string* error);
  bool begin_install(uint64_t now_monotonic_seconds, std::string* error);
  bool installed(const Installed& installed, std::string* error);
  bool confirm_health(const Installed& installed, const Health& health,
                      std::string* error);
  bool tick(uint64_t now_monotonic_seconds, bool same_boot, std::string* error);
  bool rollback_finished(const Installed& installed, std::string* error);

 private:
  bool request_rollback(const std::string& reason, std::string* error);
  static bool valid_candidate(const Candidate& candidate,
                              const Installed& installed,
                              const Installed& archive, std::string* error);
  static bool matches_candidate(const Candidate& candidate,
                                const Installed& installed);
  State state_;
};

}  // namespace r1_update
