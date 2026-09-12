#pragma once

#include "package_orchestrator.h"

#include <cstdint>
#include <functional>
#include <string>

#include <sys/types.h>

namespace r1_update {

struct SupervisorConfig {
  int listener_fd = -1;
  uid_t satellite_uid = static_cast<uid_t>(-1);
  std::string transaction_directory;
  std::string boot_id;
  // Zero means no request limit. Tests use a finite value so the child exits
  // without relying on an asynchronous signal.
  uint32_t maximum_requests = 0;
};

using MonotonicClock = std::function<uint64_t()>;
using StopRequested = std::function<bool()>;
using SupervisorEvent = std::function<void(const std::string&)>;

// Runs the long-lived supervisor around an already secured listener. Framing
// failures are isolated to one client. Durable package/recovery failures remain
// visible through the orchestrator state and do not crash the daemon.
bool run_update_supervisor(const SupervisorConfig& config,
                           PackageOrchestrator* orchestrator,
                           const MonotonicClock& clock,
                           const StopRequested& stop_requested,
                           const SupervisorEvent& event,
                           std::string* error);

uint64_t monotonic_seconds();
bool read_kernel_boot_id(const std::string& path, std::string* boot_id,
                         std::string* error);

}  // namespace r1_update
