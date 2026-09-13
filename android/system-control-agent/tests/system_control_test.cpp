#include "system_control.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <unistd.h>

namespace {
void require(bool value, const char* message) {
  if (!value) { std::cerr << message << '\n'; std::exit(1); }
}
class Backend final : public r1_system_control::Backend {
 public:
  bool okay = true;
  bool set_led(uint8_t first, uint8_t second, uint8_t* actual_first,
               uint8_t* actual_second) override {
    *actual_first = first; *actual_second = second; return okay;
  }
};
}

int main() {
  Backend backend;
  auto good = r1_system_control::execute(
      {r1_system_control::Operation::kSetLed, 4, 0}, &backend);
  require(good.status == r1_system_control::Status::kOk && good.first == 4,
          "valid LED operation failed");
  auto invalid = r1_system_control::execute(
      {r1_system_control::Operation::kSetLed, 5, 0}, &backend);
  require(invalid.status == r1_system_control::Status::kInvalidLevel,
          "invalid LED level accepted");

  int pair[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) == 0,
          "socketpair failed");
  std::thread server([&] {
    r1_system_control::Request request{};
    r1_system_control::Response rejection{};
    std::string error;
    require(r1_system_control::receive_request(pair[1], getuid(), &request,
                                                &rejection, &error),
            "request rejected");
    require(request.operation == r1_system_control::Operation::kSetLed
            && request.first == 2 && request.second == 1, "request changed");
    require(r1_system_control::send_response(pair[1],
        r1_system_control::execute(request, &backend), &error), "response failed");
    close(pair[1]);
  });
  r1_system_control::Response response{};
  std::string error;
  require(r1_system_control::send_request(pair[0],
      {r1_system_control::Operation::kSetLed, 2, 1}, &response, &error),
      "round trip failed");
  require(response.status == r1_system_control::Status::kOk
          && response.first == 2 && response.second == 1, "response changed");
  close(pair[0]); server.join();

  int rejected[2];
  require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, rejected) == 0,
          "rejection socketpair failed");
  r1_system_control::Request rejected_request{};
  r1_system_control::Response rejection{};
  require(!r1_system_control::receive_request(rejected[1], getuid() + 1,
                                               &rejected_request, &rejection, &error)
          && rejection.status == r1_system_control::Status::kUnauthorized,
          "wrong UID was not rejected");
  close(rejected[0]); close(rejected[1]);
  return 0;
}
