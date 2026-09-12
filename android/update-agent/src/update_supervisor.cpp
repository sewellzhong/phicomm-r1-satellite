#include "update_supervisor.h"

#include "update_protocol.h"

#include <cerrno>
#include <ctime>
#include <fstream>
#include <string>

#include <poll.h>

namespace r1_update {
namespace {

bool reject(const std::string& reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
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

void report(const SupervisorEvent& event, const std::string& value) {
  if (event) event(value);
}

void tick(PackageOrchestrator* orchestrator, const std::string& boot_id,
          uint64_t now, const SupervisorEvent& event) {
  if (orchestrator->state().phase != Phase::kAwaitingHealth
      && orchestrator->state().phase != Phase::kInstalling) return;
  const bool same_boot = !orchestrator->state().boot_id.empty()
      && orchestrator->state().boot_id == boot_id;
  std::string transition_error;
  if (!orchestrator->tick(now, same_boot, &transition_error))
    report(event, transition_error);
}

}  // namespace

uint64_t monotonic_seconds() {
  struct timespec value {};
  if (clock_gettime(CLOCK_BOOTTIME, &value) != 0) return 0;
  return static_cast<uint64_t>(value.tv_sec);
}

bool read_kernel_boot_id(const std::string& path, std::string* boot_id,
                         std::string* error) {
  if (boot_id == nullptr) return reject("update_boot_id_output_missing", error);
  std::ifstream input(path);
  std::string value, trailing;
  if (!input.is_open() || !std::getline(input, value) || std::getline(input, trailing))
    return reject("update_boot_id_read_failed", error);
  if (!valid_boot_id(value)) return reject("update_boot_id_invalid", error);
  *boot_id = value;
  return true;
}

bool run_update_supervisor(const SupervisorConfig& config,
                           PackageOrchestrator* orchestrator,
                           const MonotonicClock& clock,
                           const StopRequested& stop_requested,
                           const SupervisorEvent& event,
                           std::string* error) {
  if (config.listener_fd < 0 || config.satellite_uid == static_cast<uid_t>(-1)
      || config.transaction_directory.empty() || !valid_boot_id(config.boot_id)
      || orchestrator == nullptr || !clock || !stop_requested)
    return reject("update_supervisor_configuration_invalid", error);

  bool restored = false;
  if (!orchestrator->recover(&restored, error)) return false;
  if (restored) report(event, "update_transaction_recovered");
  tick(orchestrator, config.boot_id, clock(), event);

  uint32_t served = 0;
  while (!stop_requested()
         && (config.maximum_requests == 0 || served < config.maximum_requests)) {
    struct pollfd descriptor {config.listener_fd, POLLIN, 0};
    int result;
    do {
      result = poll(&descriptor, 1, 1000);
    } while (result < 0 && errno == EINTR && !stop_requested());
    if (result < 0) return reject("update_supervisor_poll_failed", error);
    if (result > 0 && (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0)
      return reject("update_supervisor_listener_failed", error);
    if (result > 0 && (descriptor.revents & POLLIN) != 0) {
      bool operation_succeeded = false;
      std::string request_error;
      if (!serve_protocol_request_once(config.listener_fd, config.satellite_uid,
                                       config.transaction_directory, orchestrator,
                                       clock(), &operation_succeeded, &request_error)) {
        report(event, request_error);
      } else if (!operation_succeeded) {
        report(event, "update_operation_failed");
      }
      ++served;
    }
    tick(orchestrator, config.boot_id, clock(), event);
  }
  if (error != nullptr) error->clear();
  return true;
}

}  // namespace r1_update
