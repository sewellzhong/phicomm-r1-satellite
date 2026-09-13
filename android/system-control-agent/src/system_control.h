#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace r1_system_control {

constexpr uint32_t kExpectedUid = 10010;
constexpr char kSocketPath[] = "/dev/socket/r1_system_control";

enum class Operation : uint8_t { kSetLed = 1, kReboot = 2 };
enum class Status : uint8_t {
  kOk = 0, kMalformed = 1, kUnauthorized = 2, kInvalidLevel = 3,
  kLedIo = 4, kRebootFailed = 5,
};

struct Request { Operation operation; uint8_t first; uint8_t second; };
struct Response { Status status; uint8_t first; uint8_t second; };

class Backend {
 public:
  virtual ~Backend() = default;
  virtual bool set_led(uint8_t first, uint8_t second,
                       uint8_t* actual_first, uint8_t* actual_second) = 0;
};

bool receive_request(int connected, uint32_t expected_uid, Request* request,
                     Response* rejection, std::string* error);
bool send_request(int connected, const Request& request, Response* response,
                  std::string* error);
Response execute(const Request& request, Backend* backend);
bool send_response(int connected, const Response& response, std::string* error);
bool connect_socket(const char* path, int* connected, std::string* error);

}  // namespace r1_system_control
