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
#include <poll.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

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

bool reject(const std::string& reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
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

}  // namespace

bool run_fixed_command(const std::vector<std::string>& arguments,
                       const std::vector<std::string>& environment,
                       uint32_t timeout_seconds, CommandResult* result,
                       std::string* error) {
  if (result == nullptr || arguments.empty() || arguments[0].empty()
      || arguments[0][0] != '/' || timeout_seconds == 0 || timeout_seconds > 180)
    return reject("update_command_invalid", error);
  int output_pipe[2] = {-1, -1};
  int error_pipe[2] = {-1, -1};
  if (pipe2(output_pipe, O_CLOEXEC | O_NONBLOCK) != 0
      || pipe2(error_pipe, O_CLOEXEC | O_NONBLOCK) != 0) {
    if (output_pipe[0] >= 0) { close(output_pipe[0]); close(output_pipe[1]); }
    return reject("update_command_pipe_failed", error);
  }
  pid_t child = fork();
  if (child < 0) {
    close(output_pipe[0]); close(output_pipe[1]);
    close(error_pipe[0]); close(error_pipe[1]);
    return reject("update_command_fork_failed", error);
  }
  if (child == 0) {
    dup2(output_pipe[1], STDOUT_FILENO);
    dup2(error_pipe[1], STDERR_FILENO);
    close(output_pipe[0]); close(output_pipe[1]);
    close(error_pipe[0]); close(error_pipe[1]);
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
  if (!runner_(arguments, fixed_environment(helper_jar_), 30, &result, error))
    return false;
  if (result.exit_code != 0 || !result.stderr_text.empty())
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
  return copy_regular_file(source, destination_path, error);
}

bool AndroidPackageManagerBackend::install_archive(
    const std::string& archive_path, bool allow_downgrade, std::string* error) {
  if (!transaction_archive_path(archive_path))
    return reject("update_install_path_invalid", error);
  std::vector<std::string> arguments{
      kAppProcess, "/system/bin", kPmClass, "install", "-r"};
  if (allow_downgrade) arguments.emplace_back("-d");
  arguments.push_back(archive_path);
  CommandResult result;
  if (!runner_(arguments, fixed_environment(kPmJar), 120, &result, error))
    return false;
  if (result.exit_code != 0 || !result.stderr_text.empty())
    return reject("update_package_manager_failed", error);
  std::vector<std::string> lines;
  if (!split_lines(result.stdout_text, &lines))
    return reject("update_package_manager_output_invalid", error);
  if (!(lines == std::vector<std::string>{"Success"}
        || lines == std::vector<std::string>{"\tpkg: " + archive_path, "Success"}
        || lines == std::vector<std::string>{"pkg: " + archive_path, "Success"}))
    return reject("update_package_manager_output_invalid", error);
  return true;
}

}  // namespace r1_update
