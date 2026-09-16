#include "android_package_manager_backend.h"

#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

#undef assert
#define assert(condition) do { if (!(condition)) std::abort(); } while (false)

namespace {

constexpr char kPackage[] = "dev.sewellzhong.r1probe";
constexpr char kHash[] =
    "1111111111111111111111111111111111111111111111111111111111111111";
constexpr char kSigner[] =
    "2222222222222222222222222222222222222222222222222222222222222222";

struct Fixture {
  Fixture() {
    char pattern[] = "/tmp/r1-update-backend-XXXXXX";
    char* value = mkdtemp(pattern);
    assert(value != nullptr);
    directory = value;
  }
  ~Fixture() {
    unlink((directory + "/source.apk").c_str());
    unlink((directory + "/previous-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.apk").c_str());
    rmdir(directory.c_str());
  }
  std::string identity(const std::string& path, uint32_t version = 102) const {
    return std::string("R1_PACKAGE_IDENTITY_V1\n")
        + "package_name=" + kPackage + "\nversion=" + std::to_string(version)
        + "\napk_path=" + path + "\napk_sha256=" + kHash
        + "\nsigner_sha256=" + kSigner + "\n";
  }
  std::string directory;
};

void test_reads_identity_with_fixed_helper() {
  Fixture fixture;
  bool called = false;
  r1_update::CommandRunner runner = [&](const std::vector<std::string>& arguments,
      const std::vector<std::string>& environment, const std::string& input,
      uint32_t timeout,
      r1_update::CommandResult* result, std::string*) {
    called = true;
    assert(arguments == std::vector<std::string>({
        "/system/bin/app_process", "/system/bin",
        "dev.sewellzhong.r1update.PackageIdentityHelper", "installed", kPackage}));
    assert(timeout == 30);
    assert(input.empty());
    assert(environment.end() != std::find(
        environment.begin(), environment.end(), "CLASSPATH=/sbin/helper.jar"));
    result->exit_code = 0;
    result->stdout_text = fixture.identity("/data/app/dev.sewellzhong.r1probe-1/base.apk");
    result->stderr_text = "bounded ART diagnostic\n";
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  r1_update::Installed installed;
  std::string error;
  assert(backend.read_installed(kPackage, &installed, &error));
  assert(called && installed.version == 102);
}

void test_accepts_only_bound_package_manager_output() {
  Fixture fixture;
  const std::string archive = fixture.directory
      + "/candidate-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.apk";
  {
    std::ofstream stream(archive, std::ios::binary);
    stream << std::string(4096, 'x');
  }
  bool wrong_write_result = false;
  r1_update::CommandRunner runner = [&](const std::vector<std::string>& arguments,
      const std::vector<std::string>&, const std::string& input, uint32_t,
      r1_update::CommandResult* result, std::string*) {
    result->exit_code = 1;
    if (arguments[3] == "install-create")
      result->stdout_text = "Success: created install session [123]\n";
    else if (arguments[3] == "install-write") {
      assert(arguments.size() == 8 && arguments.back() == "base.apk");
      assert(input == archive);
      result->stdout_text = wrong_write_result
          ? "Success: streamed 1 bytes\n" : "Success: streamed 4096 bytes\n";
    } else if (arguments[3] == "install-commit"
             || arguments[3] == "install-abandon")
      result->stdout_text = "Success\n";
    else
      assert(false);
    result->stderr_text = "bounded ART diagnostic\n";
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  std::string error;
  assert(backend.install_archive(archive, false, &error));
  wrong_write_result = true;
  assert(!backend.install_archive(archive, true, &error));
  assert(error == "update_package_session_write_failed");
  unlink(archive.c_str());
}

void test_accepts_android_5_silent_stdin_write_without_failure_output() {
  Fixture fixture;
  const std::string archive = fixture.directory
      + "/candidate-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.apk";
  {
    std::ofstream stream(archive, std::ios::binary);
    stream << std::string(4096, 'x');
  }
  int write_exit = 0;
  std::string write_error;
  r1_update::CommandRunner runner = [&](const std::vector<std::string>& arguments,
      const std::vector<std::string>&, const std::string&, uint32_t,
      r1_update::CommandResult* result, std::string*) {
    result->exit_code = 0;
    if (arguments[3] == "install-create")
      result->stdout_text = "Success: created install session [124]\n";
    else if (arguments[3] == "install-write") {
      result->exit_code = write_exit;
      result->stderr_text = write_error;
    } else if (arguments[3] == "install-commit"
               || arguments[3] == "install-abandon")
      result->stdout_text = "Success\n";
    else
      assert(false);
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  std::string error;
  assert(backend.install_archive(archive, false, &error));
  write_exit = 1;
  assert(backend.install_archive(archive, false, &error));
  write_error = "Failure [INSTALL_FAILED_INVALID_APK]\n";
  assert(!backend.install_archive(archive, false, &error));
  unlink(archive.c_str());
}

void test_parse_not_apk_uses_bounded_legacy_window_and_restores_modes() {
  Fixture fixture;
  const std::string bridge = fixture.directory + "_install";
  assert(mkdir(bridge.c_str(), 0711) == 0);
  // mkdir applies the process umask; make the fixture match the exact
  // init-created production bridge mode instead of depending on the host
  // user's umask.
  assert(chmod(bridge.c_str(), 0711) == 0);
  const std::string archive = fixture.directory
      + "/candidate-cccccccccccccccccccccccccccccccc.apk";
  {
    std::ofstream stream(archive, std::ios::binary);
    stream << std::string(4096, 'x');
  }
  assert(chmod(archive.c_str(), 0600) == 0);
  bool legacy_called = false;
  r1_update::CommandRunner runner = [&](const std::vector<std::string>& arguments,
      const std::vector<std::string>&, const std::string& input, uint32_t,
      r1_update::CommandResult* result, std::string*) {
    result->exit_code = 0;
    if (arguments[3] == "install-create")
      result->stdout_text = "Success: created install session [125]\n";
    else if (arguments[3] == "install-write")
      assert(input == archive);
    else if (arguments[3] == "install-commit")
      result->stdout_text = "Failure [INSTALL_PARSE_FAILED_NOT_APK]\n";
    else if (arguments[3] == "install-abandon")
      result->stdout_text = "Success\n";
    else if (arguments[3] == "install") {
      legacy_called = true;
      assert(arguments == std::vector<std::string>({
          "/system/bin/app_process", "/system/bin", "com.android.commands.pm.Pm",
          "install", "-r", bridge + "/candidate.apk"}));
      struct stat bridge_info {}, archive_info {};
      assert(stat(bridge.c_str(), &bridge_info) == 0
             && (bridge_info.st_mode & 0777) == 0711);
      assert(stat((bridge + "/candidate.apk").c_str(), &archive_info) == 0
             && (archive_info.st_mode & 0777) == 0644);
      result->stdout_text = "Success\n";
    } else
      assert(false);
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  std::string error;
  assert(backend.install_archive(archive, false, &error) && legacy_called);
  struct stat archive_info {};
  assert(stat(archive.c_str(), &archive_info) == 0
         && (archive_info.st_mode & 0777) == 0600);
  assert(access((bridge + "/candidate.apk").c_str(), F_OK) != 0);
  unlink(archive.c_str());
  assert(rmdir(bridge.c_str()) == 0);
}

void test_rejects_archive_escape_before_runner() {
  Fixture fixture;
  r1_update::CommandRunner runner = [](const std::vector<std::string>&,
      const std::vector<std::string>&, const std::string&, uint32_t,
      r1_update::CommandResult*, std::string*) {
    assert(false);
    return false;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  r1_update::Installed installed;
  std::string error;
  assert(!backend.read_archive(fixture.directory + "/../candidate-x.apk",
                               &installed, &error));
  assert(error == "update_archive_path_invalid");
}

void test_backup_is_exclusive_and_exact() {
  Fixture fixture;
  const std::string source = fixture.directory + "/source.apk";
  const std::string destination = fixture.directory
      + "/previous-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.apk";
  {
    std::ofstream stream(source, std::ios::binary);
    stream << std::string(4096, 'x');
  }
  r1_update::CommandRunner runner = [&](const std::vector<std::string>&,
      const std::vector<std::string>&, const std::string&, uint32_t,
      r1_update::CommandResult* result, std::string*) {
    result->exit_code = 0;
    result->stdout_text = fixture.identity(source);
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  std::string error;
  assert(backend.backup_installed(kPackage, destination, &error));
  struct stat info {};
  assert(stat(destination.c_str(), &info) == 0 && info.st_size == 4096);
  assert(!backend.backup_installed(kPackage, destination, &error));
  assert(error == "update_backup_destination_open_failed");
}

void test_fixed_runner_preserves_input_when_open_returns_fd_zero() {
  Fixture fixture;
  const std::string input = fixture.directory + "/stdin.apk";
  const std::string payload(4096, 'q');
  {
    std::ofstream stream(input, std::ios::binary);
    stream << payload;
  }
  assert(chmod(input.c_str(), 0600) == 0);
  const int saved_stdin = dup(STDIN_FILENO);
  assert(saved_stdin >= 0 && close(STDIN_FILENO) == 0);
  r1_update::CommandResult result;
  std::string error;
  const bool okay = r1_update::run_fixed_command(
      {"/bin/cat"}, {}, input, 5, &result, &error);
  assert(dup2(saved_stdin, STDIN_FILENO) == STDIN_FILENO);
  close(saved_stdin);
  assert(okay && result.exit_code == 0 && result.stdout_text == payload
         && result.stderr_text.empty());
  unlink(input.c_str());
}

}  // namespace

int main() {
  test_reads_identity_with_fixed_helper();
  test_accepts_only_bound_package_manager_output();
  test_accepts_android_5_silent_stdin_write_without_failure_output();
  test_parse_not_apk_uses_bounded_legacy_window_and_restores_modes();
  test_rejects_archive_escape_before_runner();
  test_backup_is_exclusive_and_exact();
  test_fixed_runner_preserves_input_when_open_returns_fd_zero();
  return 0;
}
