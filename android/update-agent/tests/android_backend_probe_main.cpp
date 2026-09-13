#include "android_package_manager_backend.h"

#include <cstdio>
#include <string>

int main() {
  constexpr char kDirectory[] = "/data/local/tmp/r1-update-probe";
  constexpr char kHelper[] = "/data/local/tmp/r1-update-probe/helper.jar";
  constexpr char kCandidate[] =
      "/data/local/tmp/r1-update-probe/"
      "candidate-00000000000000000000000000000000.apk";
  r1_update::AndroidPackageManagerBackend backend(kDirectory, kHelper);
  r1_update::Installed installed, archive;
  std::string error;
  if (!backend.read_installed("dev.sewellzhong.r1probe", &installed, &error)
      || !backend.read_archive(kCandidate, &archive, &error)) {
    fprintf(stderr, "%s\n", error.c_str());
    return 2;
  }
  if (installed.package_name != archive.package_name || installed.version != 102
      || archive.version != 118
      || installed.signer_sha256 != archive.signer_sha256) {
    fprintf(stderr, "update_backend_probe_identity_mismatch\n");
    return 2;
  }
  puts("R1_UPDATE_BACKEND_READ_ONLY_PASS");
  return 0;
}
