#include "android_package_manager_backend.h"
#include "package_orchestrator.h"
#include "update_supervisor.h"

#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include <fcntl.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <android/log.h>

namespace {

constexpr char kSocketName[] = "r1_update_supervisor";
constexpr char kSocketPath[] = "/dev/socket/r1_update_supervisor";
constexpr char kTransactionDirectory[] = "/data/misc/r1_update";
constexpr char kHelperJar[] = "/sbin/r1-update-helper.jar";
constexpr uid_t kSatelliteUid = 10010;
volatile sig_atomic_t stop_requested = 0;

void log_error(const std::string& message) {
  fprintf(stderr, "%s\n", message.c_str());
  __android_log_write(ANDROID_LOG_ERROR, "R1UpdateSupervisor", message.c_str());
}

void handle_signal(int) { stop_requested = 1; }

bool parse_fd(const char* value, int* fd) {
  if (value == nullptr || value[0] == '\0' || fd == nullptr) return false;
  errno = 0;
  char* end = nullptr;
  long parsed = strtol(value, &end, 10);
  if (errno != 0 || end == value || *end != '\0' || parsed < 0 || parsed > INT_MAX)
    return false;
  *fd = static_cast<int>(parsed);
  return true;
}

bool inherited_listener(int* listener, std::string* error) {
  const std::string variable = std::string("ANDROID_SOCKET_") + kSocketName;
  int fd = -1;
  if (!parse_fd(getenv(variable.c_str()), &fd) || fcntl(fd, F_GETFD) < 0) {
    if (error != nullptr) *error = "update_init_socket_missing";
    return false;
  }
  int type = 0;
  socklen_t type_size = sizeof(type);
  struct sockaddr_un address {};
  socklen_t address_size = sizeof(address);
  if (getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_size) != 0
      || type != SOCK_SEQPACKET
      || getsockname(fd, reinterpret_cast<struct sockaddr*>(&address),
                     &address_size) != 0
      || address.sun_family != AF_UNIX || std::string(address.sun_path) != kSocketPath) {
    if (error != nullptr) *error = "update_init_socket_invalid";
    return false;
  }
  if (listen(fd, 4) != 0) {
    if (error != nullptr) *error = "update_init_socket_listen_failed";
    return false;
  }
  *listener = fd;
  return true;
}

}  // namespace

int main() {
  if (geteuid() != 0) {
    log_error("update_supervisor_root_required");
    return 2;
  }
  struct sigaction action {};
  action.sa_handler = handle_signal;
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGTERM, &action, nullptr) != 0
      || sigaction(SIGINT, &action, nullptr) != 0) {
    log_error("update_supervisor_signal_failed");
    return 2;
  }
  std::string error;
  int listener = -1;
  if (!inherited_listener(&listener, &error)) {
    log_error(error);
    return 2;
  }
  std::string boot_id;
  if (!r1_update::read_kernel_boot_id("/proc/sys/kernel/random/boot_id", &boot_id,
                                      &error)) {
    log_error(error);
    return 2;
  }
  r1_update::AndroidPackageManagerBackend backend(
      kTransactionDirectory, kHelperJar);
  r1_update::PackageOrchestrator orchestrator(
      kTransactionDirectory, boot_id, &backend);
  r1_update::SupervisorConfig config;
  config.listener_fd = listener;
  config.satellite_uid = kSatelliteUid;
  config.transaction_directory = kTransactionDirectory;
  config.boot_id = boot_id;
  const bool okay = r1_update::run_update_supervisor(
      config, &orchestrator, r1_update::monotonic_seconds,
      [] { return stop_requested != 0; },
      [](const std::string& event) { log_error(event); },
      &error);
  if (!okay) log_error(error);
  return okay ? 0 : 1;
}
