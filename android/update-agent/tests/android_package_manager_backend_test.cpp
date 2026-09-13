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
      const std::vector<std::string>& environment, uint32_t timeout,
      r1_update::CommandResult* result, std::string*) {
    called = true;
    assert(arguments == std::vector<std::string>({
        "/system/bin/app_process", "/system/bin",
        "dev.sewellzhong.r1update.PackageIdentityHelper", "installed", kPackage}));
    assert(timeout == 30);
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
  bool wrong_path = false;
  r1_update::CommandRunner runner = [&](const std::vector<std::string>&,
      const std::vector<std::string>&, uint32_t,
      r1_update::CommandResult* result, std::string*) {
    result->exit_code = 0;
    result->stdout_text = std::string("\tpkg: ")
        + (wrong_path ? "/data/local/tmp/other.apk" : archive) + "\nSuccess\n";
    return true;
  };
  r1_update::AndroidPackageManagerBackend backend(
      fixture.directory, "/sbin/helper.jar", runner);
  std::string error;
  assert(backend.install_archive(archive, false, &error));
  wrong_path = true;
  assert(!backend.install_archive(archive, true, &error));
  assert(error == "update_package_manager_output_invalid");
}

void test_rejects_archive_escape_before_runner() {
  Fixture fixture;
  r1_update::CommandRunner runner = [](const std::vector<std::string>&,
      const std::vector<std::string>&, uint32_t,
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
      const std::vector<std::string>&, uint32_t,
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

}  // namespace

int main() {
  test_reads_identity_with_fixed_helper();
  test_accepts_only_bound_package_manager_output();
  test_rejects_archive_escape_before_runner();
  test_backup_is_exclusive_and_exact();
  return 0;
}
