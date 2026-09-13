#include "system_control.h"

#include <cerrno>
#include <cstring>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace r1_system_control {
namespace {

constexpr std::array<uint8_t, 4> kRequestMagic{{'R', '1', 'S', 'C'}};
constexpr std::array<uint8_t, 4> kResponseMagic{{'R', '1', 'S', 'R'}};
constexpr uint8_t kVersion = 1;
constexpr size_t kPacketSize = 8;

void fail(std::string* error, const char* value) {
  if (error != nullptr) *error = value;
}

bool exact_packet(int fd, void* bytes, size_t size, std::string* error) {
  const ssize_t count = recv(fd, bytes, size + 1, MSG_TRUNC);
  if (count < 0) { fail(error, "system_control_receive_failed"); return false; }
  if (static_cast<size_t>(count) != size) {
    fail(error, "system_control_packet_size_invalid"); return false;
  }
  return true;
}

}  // namespace

bool receive_request(int connected, uint32_t expected_uid, Request* request,
                     Response* rejection, std::string* error) {
  if (request == nullptr || rejection == nullptr) {
    fail(error, "system_control_output_missing"); return false;
  }
  ucred credentials{};
  socklen_t length = sizeof(credentials);
  if (getsockopt(connected, SOL_SOCKET, SO_PEERCRED, &credentials, &length) != 0
      || length != sizeof(credentials)) {
    fail(error, "system_control_peer_credentials_failed"); return false;
  }
  if (static_cast<uint32_t>(credentials.uid) != expected_uid) {
    *rejection = {Status::kUnauthorized, 0, 0};
    fail(error, "system_control_peer_uid_rejected"); return false;
  }
  std::array<uint8_t, kPacketSize + 1> packet{};
  if (!exact_packet(connected, packet.data(), kPacketSize, error)) {
    *rejection = {Status::kMalformed, 0, 0}; return false;
  }
  if (!std::equal(kRequestMagic.begin(), kRequestMagic.end(), packet.begin())
      || packet[4] != kVersion || packet[7] != 0
      || (packet[5] != static_cast<uint8_t>(Operation::kSetLed)
          && packet[5] != static_cast<uint8_t>(Operation::kReboot))) {
    *rejection = {Status::kMalformed, 0, 0};
    fail(error, "system_control_request_invalid"); return false;
  }
  request->operation = static_cast<Operation>(packet[5]);
  request->first = packet[6] >> 4;
  request->second = packet[6] & 0x0f;
  if (request->operation == Operation::kReboot && packet[6] != 0) {
    *rejection = {Status::kMalformed, 0, 0};
    fail(error, "system_control_reboot_has_parameters"); return false;
  }
  return true;
}

bool send_response(int connected, const Response& response, std::string* error) {
  const std::array<uint8_t, kPacketSize> packet{{
      kResponseMagic[0], kResponseMagic[1], kResponseMagic[2], kResponseMagic[3],
      kVersion, static_cast<uint8_t>(response.status),
      static_cast<uint8_t>((response.first << 4) | response.second), 0}};
  if (send(connected, packet.data(), packet.size(), MSG_NOSIGNAL) !=
      static_cast<ssize_t>(packet.size())) {
    fail(error, "system_control_response_send_failed"); return false;
  }
  return true;
}

bool send_request(int connected, const Request& request, Response* response,
                  std::string* error) {
  if (response == nullptr || request.first > 4 || request.second > 4
      || (request.operation == Operation::kReboot
          && (request.first != 0 || request.second != 0))) {
    fail(error, "system_control_client_request_invalid"); return false;
  }
  const std::array<uint8_t, kPacketSize> packet{{
      kRequestMagic[0], kRequestMagic[1], kRequestMagic[2], kRequestMagic[3],
      kVersion, static_cast<uint8_t>(request.operation),
      static_cast<uint8_t>((request.first << 4) | request.second), 0}};
  if (send(connected, packet.data(), packet.size(), MSG_NOSIGNAL) !=
      static_cast<ssize_t>(packet.size())) {
    fail(error, "system_control_request_send_failed"); return false;
  }
  std::array<uint8_t, kPacketSize + 1> reply{};
  if (!exact_packet(connected, reply.data(), kPacketSize, error)) return false;
  if (!std::equal(kResponseMagic.begin(), kResponseMagic.end(), reply.begin())
      || reply[4] != kVersion || reply[7] != 0) {
    fail(error, "system_control_response_invalid"); return false;
  }
  response->status = static_cast<Status>(reply[5]);
  response->first = reply[6] >> 4;
  response->second = reply[6] & 0x0f;
  return true;
}

Response execute(const Request& request, Backend* backend) {
  if (request.operation == Operation::kSetLed) {
    if (request.first > 4 || request.second > 4)
      return {Status::kInvalidLevel, 0, 0};
    uint8_t first = 0, second = 0;
    if (backend == nullptr
        || !backend->set_led(request.first, request.second, &first, &second))
      return {Status::kLedIo, first, second};
    return {Status::kOk, first, second};
  }
  if (request.operation == Operation::kReboot)
    return {Status::kOk, 0, 0};
  return {Status::kMalformed, 0, 0};
}

bool connect_socket(const char* path, int* connected, std::string* error) {
  if (path == nullptr || connected == nullptr || std::strlen(path) >= sizeof(sockaddr_un::sun_path)) {
    fail(error, "system_control_socket_path_invalid"); return false;
  }
  int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  if (fd < 0) { fail(error, "system_control_socket_create_failed"); return false; }
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  std::strcpy(address.sun_path, path);
  if (connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
    close(fd); fail(error, "system_control_socket_connect_failed"); return false;
  }
  *connected = fd;
  return true;
}

}  // namespace r1_system_control
