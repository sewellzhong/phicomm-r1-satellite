#include "android_package_manager_backend.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include <fcntl.h>
#include <grp.h>
#include <poll.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __ANDROID__
#include <android/log.h>
#endif

namespace r1_update {
namespace {

constexpr char kPackageName[] = "dev.sewellzhong.r1probe";
constexpr char kHelperClass[] =
    "dev.sewellzhong.r1update.PackageIdentityHelper";
constexpr char kAppProcess[] = "/system/bin/app_process";
constexpr char kPmJar[] = "/system/framework/pm.jar";
constexpr char kPmClass[] = "com.android.commands.pm.Pm";
constexpr size_t kMaximumOutputBytes = 16 * 1024;
constexpr uint64_t kMaximumApkBytes = 64ULL * 1024ULL * 1024ULL;
constexpr uid_t kShellUid = 2000;

bool reject(const std::string& reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
}

void backend_event(const char* event) {
#ifdef __ANDROID__
  __android_log_write(ANDROID_LOG_INFO, "R1UpdateSupervisor", event);
#else
  (void) event;
#endif
}

bool append_bounded(int fd, std::string* output, bool* open_pipe,
                    std::string* error) {
  std::array<char, 4096> buffer{};
  while (true) {
    ssize_t count = read(fd, buffer.data(), buffer.size());
    if (count > 0) {
      if (output->size() + static_cast<size_t>(count) > kMaximumOutputBytes)
        return reject("update_command_output_overflow", error);
      output->append(buffer.data(), static_cast<size_t>(count));
      continue;
    }
    if (count == 0) {
      *open_pipe = false;
      return true;
    }
    if (errno == EINTR) continue;
    if (errno == EAGAIN || errno == EWOULDBLOCK) return true;
    return reject("update_command_output_read_failed", error);
  }
}

std::vector<std::string> fixed_environment(const std::string& classpath) {
  std::vector<std::string> result{
      "ANDROID_ROOT=/system", "ANDROID_DATA=/data",
      "PATH=/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin",
      "LD_LIBRARY_PATH=/vendor/lib:/system/lib", "CLASSPATH=" + classpath};
  const char* bootclasspath = getenv("BOOTCLASSPATH");
  if (bootclasspath != nullptr && bootclasspath[0] != '\0')
    result.emplace_back(std::string("BOOTCLASSPATH=") + bootclasspath);
  return result;
}

bool parse_u32(const std::string& value, uint32_t* output) {
  if (value.empty() || output == nullptr) return false;
  uint64_t result = 0;
  for (char byte : value) {
    if (byte < '0' || byte > '9') return false;
    result = result * 10 + static_cast<uint64_t>(byte - '0');
    if (result > UINT32_MAX) return false;
  }
  *output = static_cast<uint32_t>(result);
  return true;
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

bool split_lines(const std::string& text, std::vector<std::string>* lines) {
  if (lines == nullptr || text.find('\r') != std::string::npos) return false;
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string::npos) return false;
    lines->push_back(text.substr(start, end - start));
    start = end + 1;
  }
  return !lines->empty();
}

bool exact_record(const std::string& output, const std::string& record) {
  return output == record || output == record + "\n"
      || output == record + "\r\n";
}

bool parse_session_id(const std::string& output, std::string* session_id) {
  if (session_id == nullptr) return false;
  const std::string prefix = "Success: created install session [";
  std::string value = output;
  if (value.size() >= 2 && value.compare(value.size() - 2, 2, "\r\n") == 0)
    value.resize(value.size() - 2);
  else if (!value.empty() && value.back() == '\n') value.pop_back();
  if (value.compare(0, prefix.size(), prefix) != 0 || value.back() != ']')
    return false;
  std::string parsed = value.substr(prefix.size(), value.size() - prefix.size() - 1);
  if (parsed.empty() || parsed.size() > 10) return false;
  uint64_t numeric = 0;
  for (char byte : parsed) {
    if (byte < '0' || byte > '9') return false;
    numeric = numeric * 10 + static_cast<uint64_t>(byte - '0');
    if (numeric > INT32_MAX) return false;
  }
  *session_id = parsed;
  return true;
}

const char* package_manager_failure_category(const std::string& stdout_text,
                                             const std::string& stderr_text) {
  const std::string value = stdout_text + "\n" + stderr_text;
  if (value.find("INSTALL_FAILED_INVALID_APK") != std::string::npos)
    return "update_install_failure_invalid_apk";
  if (value.find("INSTALL_FAILED_INVALID_URI") != std::string::npos)
    return "update_install_failure_invalid_uri";
  if (value.find("INSTALL_PARSE_FAILED_NOT_APK") != std::string::npos)
    return "update_install_failure_parse_not_apk";
  if (value.find("INSTALL_FAILED_UPDATE_INCOMPATIBLE") != std::string::npos)
    return "update_install_failure_incompatible";
  if (value.find("INSTALL_FAILED_VERSION_DOWNGRADE") != std::string::npos)
    return "update_install_failure_version";
  if (value.find("INSTALL_FAILED_DEXOPT") != std::string::npos)
    return "update_install_failure_dexopt";
  if (value.find("INSTALL_FAILED_INSUFFICIENT_STORAGE") != std::string::npos)
    return "update_install_failure_storage";
  if (value.find("INSTALL_FAILED_INTERNAL_ERROR") != std::string::npos)
    return "update_install_failure_internal";
  if (value.find("INSTALL_FAILED_ALREADY_EXISTS") != std::string::npos)
    return "update_install_failure_already_exists";
  if (value.find("INSTALL_FAILED_DUPLICATE_PACKAGE") != std::string::npos)
    return "update_install_failure_duplicate_package";
  if (value.find("INSTALL_FAILED_OLDER_SDK") != std::string::npos
      || value.find("INSTALL_FAILED_NEWER_SDK") != std::string::npos)
    return "update_install_failure_sdk";
  if (value.find("INSTALL_FAILED_CONFLICTING_PROVIDER") != std::string::npos)
    return "update_install_failure_provider";
  if (value.find("INSTALL_FAILED_TEST_ONLY") != std::string::npos)
    return "update_install_failure_test_only";
  if (value.find("INSTALL_FAILED_CPU_ABI_INCOMPATIBLE") != std::string::npos
      || value.find("INSTALL_FAILED_NO_MATCHING_ABIS") != std::string::npos)
    return "update_install_failure_abi";
  if (value.find("INSTALL_FAILED_INVALID_INSTALL_LOCATION") != std::string::npos
      || value.find("INSTALL_FAILED_MEDIA_UNAVAILABLE") != std::string::npos)
    return "update_install_failure_location";
  if (value.find("INSTALL_FAILED_VERIFICATION_") != std::string::npos)
    return "update_install_failure_verification";
  if (value.find("INSTALL_FAILED_PACKAGE_CHANGED") != std::string::npos
      || value.find("INSTALL_FAILED_UID_CHANGED") != std::string::npos)
    return "update_install_failure_changed";
  if (value.find("SecurityException") != std::string::npos
      || value.find("Permission Denial") != std::string::npos)
    return "update_install_failure_security";
  if (value.find("Could not access the Package Manager") != std::string::npos)
    return "update_install_failure_pm_unavailable";
  if (value.find("Unknown option") != std::string::npos
      || value.find("usage:") != std::string::npos
      || value.find("Usage:") != std::string::npos)
    return "update_install_failure_usage";
  if (value.find("INSTALL_FAILED_") != std::string::npos)
    return "update_install_failure_other_install_code";
  if (value.find("Failure [") != std::string::npos)
    return "update_install_failure_other_failure";
  return "update_install_failure_unknown";
}

bool copy_regular_file(const std::string& source, const std::string& destination,
                       std::string* error) {
  int input = open(source.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (input < 0) return reject("update_backup_source_open_failed", error);
  struct stat info {};
  if (fstat(input, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < 4096
      || static_cast<uint64_t>(info.st_size) > kMaximumApkBytes) {
    close(input);
    return reject("update_backup_source_invalid", error);
  }
  int output = open(destination.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
                    0600);
  if (output < 0) {
    close(input);
    return reject("update_backup_destination_open_failed", error);
  }
  bool okay = true;
  std::array<uint8_t, 16384> buffer{};
  while (okay) {
    ssize_t count = read(input, buffer.data(), buffer.size());
    if (count < 0 && errno == EINTR) continue;
    if (count < 0) { okay = false; break; }
    if (count == 0) break;
    size_t offset = 0;
    while (offset < static_cast<size_t>(count)) {
      ssize_t written = write(output, buffer.data() + offset,
                              static_cast<size_t>(count) - offset);
      if (written < 0 && errno == EINTR) continue;
      if (written <= 0) { okay = false; break; }
      offset += static_cast<size_t>(written);
    }
  }
  if (okay) okay = fsync(output) == 0;
  close(output);
  close(input);
  if (okay) {
    const size_t slash = destination.rfind('/');
    const std::string directory = slash == std::string::npos
        ? std::string(".") : destination.substr(0, slash);
    int directory_fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    okay = directory_fd >= 0 && fsync(directory_fd) == 0;
    if (directory_fd >= 0) close(directory_fd);
  }
  if (!okay) {
    unlink(destination.c_str());
    return reject("update_backup_copy_failed", error);
  }
  return true;
}

bool sync_path_and_directory(const std::string& path,
                             const std::string& directory) {
  int file_fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  bool okay = file_fd >= 0 && fsync(file_fd) == 0;
  if (file_fd >= 0) close(file_fd);
  int directory_fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  okay = directory_fd >= 0 && fsync(directory_fd) == 0 && okay;
  if (directory_fd >= 0) close(directory_fd);
  return okay;
}

bool sync_directory(const std::string& directory) {
  int fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  const bool okay = fd >= 0 && fsync(fd) == 0;
  if (fd >= 0) close(fd);
  return okay;
}

}  // namespace

bool run_fixed_command(const std::vector<std::string>& arguments,
                       const std::vector<std::string>& environment,
                       const std::string& standard_input_path,
                       uint32_t timeout_seconds, CommandResult* result,
                       std::string* error) {
  if (result == nullptr || arguments.empty() || arguments[0].empty()
      || arguments[0][0] != '/' || timeout_seconds == 0 || timeout_seconds > 180)
    return reject("update_command_invalid", error);
  int input_fd = -1;
  if (!standard_input_path.empty()) {
    input_fd = open(standard_input_path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat input_info {};
    if (input_fd < 0 || fstat(input_fd, &input_info) != 0
        || !S_ISREG(input_info.st_mode) || input_info.st_uid != geteuid()
        || (input_info.st_mode & 0077) != 0 || input_info.st_size < 4096
        || static_cast<uint64_t>(input_info.st_size) > kMaximumApkBytes) {
      if (input_fd >= 0) close(input_fd);
      return reject("update_command_input_invalid", error);
    }
  }
  int output_pipe[2] = {-1, -1};
  int error_pipe[2] = {-1, -1};
  if (pipe2(output_pipe, O_CLOEXEC | O_NONBLOCK) != 0
      || pipe2(error_pipe, O_CLOEXEC | O_NONBLOCK) != 0) {
    if (output_pipe[0] >= 0) { close(output_pipe[0]); close(output_pipe[1]); }
    if (input_fd >= 0) close(input_fd);
    return reject("update_command_pipe_failed", error);
  }
  pid_t child = fork();
  if (child < 0) {
    if (input_fd >= 0) close(input_fd);
    close(output_pipe[0]); close(output_pipe[1]);
    close(error_pipe[0]); close(error_pipe[1]);
    return reject("update_command_fork_failed", error);
  }
  if (child == 0) {
    if (input_fd >= 0) {
      // init services commonly start with fd 0 closed, so open() may itself
      // return STDIN_FILENO. dup2(0, 0) does not clear O_CLOEXEC.
      if ((input_fd == STDIN_FILENO
              && fcntl(STDIN_FILENO, F_SETFD, 0) != 0)
          || (input_fd != STDIN_FILENO
              && dup2(input_fd, STDIN_FILENO) < 0))
        _exit(126);
    }
    dup2(output_pipe[1], STDOUT_FILENO);
    dup2(error_pipe[1], STDERR_FILENO);
    close(output_pipe[0]); close(output_pipe[1]);
    close(error_pipe[0]); close(error_pipe[1]);
    if (input_fd >= 0 && input_fd != STDIN_FILENO) close(input_fd);
    const bool package_manager_command = arguments.size() >= 4
        && arguments[0] == kAppProcess && arguments[2] == kPmClass;
    if (package_manager_command
        && (setgroups(0, nullptr) != 0 || setgid(kShellUid) != 0
            || setuid(kShellUid) != 0))
      _exit(126);
    std::vector<char*> argv;
    std::vector<char*> envp;
    for (const std::string& item : arguments)
      argv.push_back(const_cast<char*>(item.c_str()));
    argv.push_back(nullptr);
    for (const std::string& item : environment)
      envp.push_back(const_cast<char*>(item.c_str()));
    envp.push_back(nullptr);
    execve(argv[0], argv.data(), envp.data());
    _exit(127);
  }
  if (input_fd >= 0) close(input_fd);
  close(output_pipe[1]);
  close(error_pipe[1]);
  bool output_open = true, error_open = true, child_done = false, failed = false;
  int status = 0;
  const auto deadline = std::chrono::steady_clock::now()
      + std::chrono::seconds(timeout_seconds);
  while ((!child_done || output_open || error_open) && !failed) {
    const auto now = std::chrono::steady_clock::now();
    if (now >= deadline) {
      kill(child, SIGKILL);
      waitpid(child, &status, 0);
      close(output_pipe[0]); close(error_pipe[0]);
      return reject("update_command_timeout", error);
    }
    struct pollfd descriptors[2] = {
        {output_pipe[0], static_cast<short>(output_open ? POLLIN : 0), 0},
        {error_pipe[0], static_cast<short>(error_open ? POLLIN : 0), 0}};
    int wait_ms = static_cast<int>(std::min<int64_t>(
        100, std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count()));
    int poll_result;
    do { poll_result = poll(descriptors, 2, wait_ms); }
    while (poll_result < 0 && errno == EINTR);
    if (poll_result < 0) { failed = true; break; }
    if (output_open && (descriptors[0].revents & (POLLIN | POLLHUP)) != 0
        && !append_bounded(output_pipe[0], &result->stdout_text, &output_open, error))
      failed = true;
    if (error_open && (descriptors[1].revents & (POLLIN | POLLHUP)) != 0
        && !append_bounded(error_pipe[0], &result->stderr_text, &error_open, error))
      failed = true;
    pid_t waited = waitpid(child, &status, WNOHANG);
    if (waited == child) child_done = true;
    else if (waited < 0 && errno != EINTR) { failed = true; break; }
  }
  close(output_pipe[0]); close(error_pipe[0]);
  if (failed) {
    kill(child, SIGKILL);
    waitpid(child, &status, 0);
    return reject("update_command_failed", error);
  }
  result->exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 128;
  return true;
}

AndroidPackageManagerBackend::AndroidPackageManagerBackend(
    std::string transaction_directory, std::string helper_jar,
    CommandRunner runner)
    : transaction_directory_(std::move(transaction_directory)),
      install_bridge_directory_(transaction_directory_ == "/data/misc/r1_update"
          ? "/data/local/tmp/r1_update_install_v2"
          : transaction_directory_ + "_install"),
      helper_jar_(std::move(helper_jar)), runner_(std::move(runner)) {}

bool AndroidPackageManagerBackend::transaction_archive_path(
    const std::string& path) const {
  const std::string prefix = transaction_directory_ + "/";
  if (path.compare(0, prefix.size(), prefix) != 0
      || path.size() <= prefix.size() || path.find("..") != std::string::npos)
    return false;
  const std::string name = path.substr(prefix.size());
  size_t identity_start = 0;
  if (name.compare(0, 10, "candidate-") == 0) identity_start = 10;
  else if (name.compare(0, 9, "previous-") == 0) identity_start = 9;
  else return false;
  if (name.size() != identity_start + 32 + 4
      || name.compare(name.size() - 4, 4, ".apk") != 0) return false;
  for (size_t i = identity_start; i < identity_start + 32; ++i) {
    const char byte = name[i];
    if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f')))
      return false;
  }
  return true;
}

bool AndroidPackageManagerBackend::read_identity(
    const std::string& mode, const std::string& value, Installed* installed,
    std::string* apk_path, std::string* error) {
  if (installed == nullptr || (mode != "installed" && mode != "archive"))
    return reject("update_identity_request_invalid", error);
  CommandResult result;
  const std::vector<std::string> arguments{
      kAppProcess, "/system/bin", kHelperClass, mode, value};
  backend_event(mode == "installed" ? "update_read_installed_started"
                                     : "update_read_archive_started");
  if (!runner_(arguments, fixed_environment(helper_jar_), "", 30, &result, error))
    return false;
  backend_event(mode == "installed" ? "update_read_installed_finished"
                                     : "update_read_archive_finished");
  // ART and dex2oat may emit bounded diagnostics on stderr even when the
  // fixed helper exits successfully. Identity remains authoritative only when
  // the exit code and the complete, strictly parsed stdout record both pass.
  if (result.exit_code != 0)
    return reject("update_identity_helper_failed", error);
  std::vector<std::string> lines;
  if (!split_lines(result.stdout_text, &lines) || lines.size() != 6
      || lines[0] != "R1_PACKAGE_IDENTITY_V1")
    return reject("update_identity_output_invalid", error);
  const std::array<std::string, 5> prefixes{
      "package_name=", "version=", "apk_path=", "apk_sha256=", "signer_sha256="};
  std::array<std::string, 5> values{};
  for (size_t i = 0; i < values.size(); ++i) {
    if (lines[i + 1].compare(0, prefixes[i].size(), prefixes[i]) != 0)
      return reject("update_identity_output_invalid", error);
    values[i] = lines[i + 1].substr(prefixes[i].size());
  }
  Installed parsed;
  parsed.package_name = values[0];
  if (parsed.package_name != kPackageName || !parse_u32(values[1], &parsed.version)
      || values[2].empty() || values[2][0] != '/'
      || !parse_hex(values[3], &parsed.apk_sha256)
      || !parse_hex(values[4], &parsed.signer_sha256))
    return reject("update_identity_value_invalid", error);
  if ((mode == "installed" && value != kPackageName)
      || (mode == "archive" && values[2] != value))
    return reject("update_identity_binding_invalid", error);
  *installed = parsed;
  if (apk_path != nullptr) *apk_path = values[2];
  return true;
}

bool AndroidPackageManagerBackend::read_installed(
    const std::string& package_name, Installed* installed, std::string* error) {
  if (package_name != kPackageName)
    return reject("update_installed_package_invalid", error);
  return read_identity("installed", package_name, installed, nullptr, error);
}

bool AndroidPackageManagerBackend::read_archive(
    const std::string& archive_path, Installed* archive, std::string* error) {
  if (!transaction_archive_path(archive_path))
    return reject("update_archive_path_invalid", error);
  return read_identity("archive", archive_path, archive, nullptr, error);
}

bool AndroidPackageManagerBackend::backup_installed(
    const std::string& package_name, const std::string& destination_path,
    std::string* error) {
  if (package_name != kPackageName || !transaction_archive_path(destination_path)
      || destination_path.find("/previous-") == std::string::npos)
    return reject("update_backup_request_invalid", error);
  Installed installed;
  std::string source;
  if (!read_identity("installed", package_name, &installed, &source, error))
    return false;
  backend_event("update_backup_copy_started");
  const bool copied = copy_regular_file(source, destination_path, error);
  backend_event(copied ? "update_backup_copy_finished"
                       : "update_backup_copy_failed");
  return copied;
}

bool AndroidPackageManagerBackend::install_archive_legacy(
    const std::string& archive_path, bool allow_downgrade, std::string* error) {
  struct stat bridge_info {};
  if (lstat(install_bridge_directory_.c_str(), &bridge_info) != 0
      || !S_ISDIR(bridge_info.st_mode) || S_ISLNK(bridge_info.st_mode)
      || bridge_info.st_uid != geteuid()
      || (bridge_info.st_mode & 0777) != 0711)
    return reject("update_legacy_visibility_precondition_failed", error);
  const std::string bridge_path = install_bridge_directory_ + "/candidate.apk";
  struct stat stale {};
  if (lstat(bridge_path.c_str(), &stale) == 0) {
    if (!S_ISREG(stale.st_mode) || S_ISLNK(stale.st_mode)
        || stale.st_uid != geteuid() || unlink(bridge_path.c_str()) != 0)
      return reject("update_legacy_bridge_stale_unsafe", error);
  } else if (errno != ENOENT) {
    return reject("update_legacy_bridge_stat_failed", error);
  }
  if (!copy_regular_file(archive_path, bridge_path, error)
      || chmod(bridge_path.c_str(), 0644) != 0
      || !sync_path_and_directory(bridge_path, install_bridge_directory_)) {
    unlink(bridge_path.c_str());
    return reject("update_legacy_bridge_publish_failed", error);
  }
  std::vector<std::string> arguments{
      kAppProcess, "/system/bin", kPmClass, "install", "-r"};
  if (allow_downgrade) arguments.emplace_back("-d");
  arguments.emplace_back(bridge_path);
  CommandResult result;
  backend_event("update_legacy_install_started");
  const bool ran = runner_(arguments, fixed_environment(kPmJar), "", 120,
                           &result, error);
  if (unlink(bridge_path.c_str()) != 0
      || !sync_directory(install_bridge_directory_))
    return reject("update_legacy_bridge_cleanup_failed", error);
  if (!ran || !exact_record(result.stdout_text, "Success")) {
    backend_event(package_manager_failure_category(result.stdout_text,
                                                   result.stderr_text));
    return reject("update_legacy_install_failed", error);
  }
  backend_event("update_legacy_install_finished");
  return true;
}

bool AndroidPackageManagerBackend::install_archive(
    const std::string& archive_path, bool allow_downgrade, std::string* error) {
  if (!transaction_archive_path(archive_path))
    return reject("update_install_path_invalid", error);
  struct stat info {};
  if (stat(archive_path.c_str(), &info) != 0 || !S_ISREG(info.st_mode)
      || info.st_size < 4096
      || static_cast<uint64_t>(info.st_size) > kMaximumApkBytes)
    return reject("update_install_archive_invalid", error);
  const std::string size = std::to_string(static_cast<uint64_t>(info.st_size));
  std::vector<std::string> create{
      kAppProcess, "/system/bin", kPmClass, "install-create", "-r"};
  if (allow_downgrade) create.emplace_back("-d");
  create.insert(create.end(), {"-S", size});
  CommandResult created;
  backend_event(allow_downgrade ? "update_downgrade_started"
                                : "update_install_started");
  if (!runner_(create, fixed_environment(kPmJar), "", 30, &created, error))
    return false;
  std::string session;
  if (!parse_session_id(created.stdout_text, &session)) {
    backend_event(package_manager_failure_category(created.stdout_text,
                                                   created.stderr_text));
    return reject("update_package_session_create_failed", error);
  }
  backend_event("update_package_session_created");
  auto abandon = [&]() {
    CommandResult ignored;
    runner_({kAppProcess, "/system/bin", kPmClass, "install-abandon", session},
            fixed_environment(kPmJar), "", 30, &ignored, nullptr);
  };
  CommandResult written;
  const std::vector<std::string> write{
      kAppProcess, "/system/bin", kPmClass, "install-write", "-S", size,
      session, "base.apk"};
  if (!runner_(write, fixed_environment(kPmJar), archive_path, 120, &written, error)) {
    backend_event("update_package_session_write_runner_failed");
    abandon();
    return reject("update_package_session_write_failed", error);
  }
  const bool streamed_record = exact_record(
      written.stdout_text, "Success: streamed " + size + " bytes");
  // Android 5.1's Pm emits no success record when install-write consumes
  // stdin. This firmware's direct Pm exit status is not reliable, so accept
  // only empty stdout with no classified failure text; commit plus the
  // independent installed identity/hash check remain authoritative.
  const bool silent_stdin_success = written.stdout_text.empty()
      && std::string(package_manager_failure_category(
             written.stdout_text, written.stderr_text))
          == "update_install_failure_unknown";
  if (!streamed_record && !silent_stdin_success) {
    backend_event("update_package_session_write_output_rejected");
    backend_event(package_manager_failure_category(written.stdout_text,
                                                   written.stderr_text));
    abandon();
    return reject("update_package_session_write_failed", error);
  }
  backend_event("update_package_session_write_finished");
  CommandResult committed;
  backend_event("update_package_session_commit_started");
  if (!runner_({kAppProcess, "/system/bin", kPmClass, "install-commit", session},
               fixed_environment(kPmJar), "", 120, &committed, error)
      || !exact_record(committed.stdout_text, "Success")) {
    backend_event("update_package_session_commit_rejected");
    const std::string category = package_manager_failure_category(
        committed.stdout_text, committed.stderr_text);
    backend_event(category.c_str());
    abandon();
    if (category == "update_install_failure_parse_not_apk"
        && install_archive_legacy(archive_path, allow_downgrade, error)) {
      backend_event(allow_downgrade ? "update_downgrade_finished"
                                    : "update_install_finished");
      backend_event("update_install_result_accepted");
      return true;
    }
    return reject("update_package_session_commit_failed", error);
  }
  backend_event(allow_downgrade ? "update_downgrade_finished"
                                : "update_install_finished");
  backend_event("update_install_result_accepted");
  return true;
}

}  // namespace r1_update
