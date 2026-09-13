#include "system_control.h"

#include <android/log.h>
#include <cerrno>
#include <cstdlib>
#include <fstream>
#include <string>

#include <linux/reboot.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {
constexpr char kLed0[] = "/sys/class/leds/multi_leds0/brightness";
constexpr char kLed1[] = "/sys/class/leds/multi_leds1/brightness";

bool write_and_read(const char* path, uint8_t requested, uint8_t* actual) {
  std::ofstream output(path);
  if (!output) return false;
  output << static_cast<unsigned>(requested);
  output.close();
  std::ifstream input(path);
  unsigned value = 0;
  if (!(input >> value) || value > 15) return false;
  *actual = static_cast<uint8_t>(value);
  return value == requested;
}

class SysfsBackend final : public r1_system_control::Backend {
 public:
  bool set_led(uint8_t first, uint8_t second,
               uint8_t* actual_first, uint8_t* actual_second) override {
    return write_and_read(kLed0, first, actual_first)
        && write_and_read(kLed1, second, actual_second);
  }
};
}

int main() {
  const char* inherited = std::getenv("ANDROID_SOCKET_r1_system_control");
  if (inherited == nullptr) return 64;
  char* end = nullptr;
  const long parsed = std::strtol(inherited, &end, 10);
  if (end == inherited || *end != '\0' || parsed < 0) return 64;
  const int listener = static_cast<int>(parsed);
  if (listen(listener, 4) != 0) return 70;
  SysfsBackend backend;
  for (;;) {
    int connected = accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
    if (connected < 0) { if (errno == EINTR) continue; return 70; }
    r1_system_control::Request request{};
    r1_system_control::Response rejection{};
    std::string error;
    if (!r1_system_control::receive_request(connected, r1_system_control::kExpectedUid,
                                            &request, &rejection, &error)) {
      r1_system_control::send_response(connected, rejection, nullptr);
      close(connected);
      continue;
    }
    const auto response = r1_system_control::execute(request, &backend);
    const bool sent = r1_system_control::send_response(connected, response, &error);
    close(connected);
    if (request.operation == r1_system_control::Operation::kReboot
        && response.status == r1_system_control::Status::kOk && sent) {
      sync();
      usleep(250000);
      if (reboot(RB_AUTOBOOT) != 0)
        __android_log_print(ANDROID_LOG_ERROR, "r1-system-control", "reboot failed: %d", errno);
    }
  }
}
