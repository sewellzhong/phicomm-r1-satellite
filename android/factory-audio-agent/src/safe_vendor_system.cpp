#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <string>

namespace {

constexpr const char* kVendorMkdirCommand = "mkdir -p /sdcard/unidata/";
constexpr const char* kVendorDebugDirectory = "/sdcard/unidata";

bool is_existing_real_directory(const char* path) {
  struct stat value {};
  return path != nullptr && lstat(path, &value) == 0 && S_ISDIR(value.st_mode);
}

bool accepted_command(const char* command, const char** directory) {
  if (command != nullptr && strcmp(command, kVendorMkdirCommand) == 0) {
    *directory = kVendorDebugDirectory;
    return true;
  }
#ifdef R1_FACTORY_AUDIO_HOST_TEST
  const char* host_directory = getenv("R1_FACTORY_AUDIO_TEST_DEBUG_DIR");
  if (host_directory != nullptr && host_directory[0] == '/') {
    const std::string expected = std::string("mkdir -p ") + host_directory + "/";
    if (expected == command) {
      *directory = host_directory;
      return true;
    }
  }
#endif
  return false;
}

}  // namespace

// Firmware 3448's vendor library calls system("mkdir -p %s") before opening
// its fixed diagnostic WAVs.  The directory is provisioned independently, so
// the agent only attests that this exact directory already exists.  It never
// starts a shell, and every other command fails closed.
extern "C" int system(const char* command) {
  const char* directory = nullptr;
  if (!accepted_command(command, &directory) || !is_existing_real_directory(directory)) {
    errno = EPERM;
    return -1;
  }
  return 0;
}
