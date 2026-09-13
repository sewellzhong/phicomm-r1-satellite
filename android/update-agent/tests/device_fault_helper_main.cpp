// Temporary device-only fault helper for the two remaining v119 recovery gates.
// It has no socket or network interface and is bound to two operation ids by init.
#include <android/log.h>

#include <cerrno>
#include <climits>
#include <csignal>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace {

constexpr char kTag[] = "R1UpdateFault";
constexpr char kState[] = "/data/misc/r1_update/transaction.v1";
constexpr char kDirectory[] = "/data/misc/r1_update";
constexpr char kBridge[] = "/data/local/tmp/r1_update_install_v2";
constexpr size_t kMaximumState = 16 * 1024;

void report(const char* value) {
  __android_log_write(ANDROID_LOG_ERROR, kTag, value);
}

bool operation_id(const char* value) {
  if (value == nullptr || std::strlen(value) != 32) return false;
  for (size_t i = 0; i < 32; ++i) {
    if (!((value[i] >= '0' && value[i] <= '9')
          || (value[i] >= 'a' && value[i] <= 'f'))) return false;
  }
  return true;
}

bool read_private_file(const char* path, std::string* output) {
  int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0) return false;
  struct stat info {};
  if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_uid != 0
      || (info.st_mode & 0077) != 0 || info.st_size <= 0
      || static_cast<uint64_t>(info.st_size) > kMaximumState) {
    close(fd);
    return false;
  }
  output->assign(static_cast<size_t>(info.st_size), '\0');
  size_t offset = 0;
  while (offset < output->size()) {
    ssize_t count = read(fd, &(*output)[offset], output->size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { close(fd); return false; }
    offset += static_cast<size_t>(count);
  }
  close(fd);
  return true;
}

bool field(const std::string& state, const char* name, std::string* value) {
  const std::string prefix = std::string("\n") + name + "=";
  size_t begin = state.find(prefix);
  if (begin == std::string::npos) return false;
  begin += prefix.size();
  size_t end = state.find('\n', begin);
  if (end == std::string::npos) return false;
  *value = state.substr(begin, end - begin);
  return true;
}

bool transaction(uint32_t* phase, std::string* operation) {
  std::string state, phase_text;
  if (!read_private_file(kState, &state)
      || state.compare(0, 25, "R1_UPDATE_TRANSACTION_V2\n") != 0
      || !field(state, "phase", &phase_text)
      || !field(state, "operation_id", operation)) return false;
  if (phase_text.size() != 1 || phase_text[0] < '1' || phase_text[0] > '6'
      || !operation_id(operation->c_str())) return false;
  *phase = static_cast<uint32_t>(phase_text[0] - '0');
  return true;
}

bool create_marker(const std::string& name) {
  const std::string path = std::string(kDirectory) + "/" + name;
  int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
                0600);
  if (fd < 0) return false;
  static constexpr char payload[] = "armed\n";
  bool okay = write(fd, payload, sizeof(payload) - 1) == sizeof(payload) - 1
      && fsync(fd) == 0 && close(fd) == 0;
  if (!okay) { close(fd); unlink(path.c_str()); return false; }
  int directory = open(kDirectory, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  okay = directory >= 0 && fsync(directory) == 0;
  if (directory >= 0) close(directory);
  return okay;
}

pid_t supervisor_pid() {
  DIR* proc = opendir("/proc");
  if (proc == nullptr) return -1;
  pid_t found = -1;
  while (dirent* entry = readdir(proc)) {
    char* end = nullptr;
    errno = 0;
    long value = std::strtol(entry->d_name, &end, 10);
    if (errno != 0 || end == entry->d_name || *end != '\0'
        || value <= 1 || value > INT_MAX || value == getpid()) continue;
    const std::string path = std::string("/proc/") + entry->d_name + "/cmdline";
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) continue;
    char command[128] {};
    ssize_t count = read(fd, command, sizeof(command) - 1);
    close(fd);
    if (count > 0 && std::string(command) == "/sbin/r1-update-supervisor") {
      found = static_cast<pid_t>(value);
      break;
    }
  }
  closedir(proc);
  return found;
}

void short_pause() { usleep(50000); }

}  // namespace

int main(int argc, char** argv) {
  if (geteuid() != 0 || argc != 3 || !operation_id(argv[1])
      || !operation_id(argv[2]) || std::strcmp(argv[1], argv[2]) == 0) {
    report("update_fault_configuration_invalid");
    return 2;
  }
  const std::string crash_operation(argv[1]);
  const std::string rollback_operation(argv[2]);
  bool crash_complete = false;
  bool rollback_blocked = false;
  pid_t failed_pid = -1;
  uint32_t last_phase = 0;
  std::string last_operation;

  report("update_fault_helper_ready");
  for (;;) {
    uint32_t phase = 0;
    std::string operation;
    const bool present = transaction(&phase, &operation);
    if (present && (phase != last_phase || operation != last_operation)) {
      char message[96] {};
      std::snprintf(message, sizeof(message), "update_fault_observed:%s:%u",
                    operation.c_str(), phase);
      report(message);
      last_phase = phase;
      last_operation = operation;
    }

    if (!crash_complete && present && operation == crash_operation && phase == 3) {
      if (!create_marker("fault-crash-" + crash_operation + ".done")) {
        report("update_fault_marker_failed");
        return 2;
      }
      pid_t pid = supervisor_pid();
      if (pid <= 1 || kill(pid, SIGKILL) != 0) {
        report("update_fault_supervisor_kill_failed");
        return 2;
      }
      crash_complete = true;
      report("update_fault_supervisor_killed_installing");
    }

    if (!rollback_blocked && present && operation == rollback_operation && phase == 4) {
      if (!create_marker("fault-rollback-" + rollback_operation + ".done")
          || chmod(kBridge, 0700) != 0) {
        report("update_fault_bridge_block_failed");
        return 2;
      }
      rollback_blocked = true;
      report("update_fault_rollback_bridge_blocked");
    }

    if (rollback_blocked && failed_pid < 0 && present
        && operation == rollback_operation && phase == 6) {
      failed_pid = supervisor_pid();
      if (failed_pid <= 1 || kill(failed_pid, SIGKILL) != 0) {
        report("update_fault_failed_restart_trigger_failed");
        return 2;
      }
      report("update_fault_failed_restart_triggered");
    } else if (failed_pid > 1) {
      pid_t current = supervisor_pid();
      if (current > 1 && current != failed_pid) {
        // Keep the bridge blocked across a complete init restart attempt.
        // kill(pid, 0) is not a reliable liveness check under this old policy,
        // so use a fixed bounded interval and then re-read the durable phase.
        for (int count = 0; count < 200; ++count) short_pause();
        uint32_t retry_phase = 0;
        std::string retry_operation;
        if (!transaction(&retry_phase, &retry_operation) || retry_phase != 6
            || retry_operation != rollback_operation || chmod(kBridge, 0711) != 0) {
          report("update_fault_failed_restart_not_closed");
          return 2;
        }
        report("update_fault_rollback_bridge_restored");
        // A later init restart now owns the genuine v119 recovery.
        return 0;
      }
    }
    short_pause();
  }
}
