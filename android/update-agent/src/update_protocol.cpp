#include "update_protocol.h"

#include <array>
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <string>

#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

namespace r1_update {
namespace {

constexpr size_t kHeaderBytes = 12;
constexpr size_t kApplyBodyBytes = 116;
constexpr size_t kHealthBodyBytes = 4;
constexpr size_t kResponseBodyBytes = 116;
constexpr size_t kMaximumPacketBytes = kHeaderBytes + kApplyBodyBytes;
constexpr size_t kResponseErrorBytes = 104;
constexpr char kMagic[] = {'R', '1', 'U', 'P'};
constexpr char kPackageName[] = "dev.sewellzhong.r1probe";

bool reject(const std::string& reason, std::string* error) {
  if (error != nullptr) *error = reason;
  return false;
}

void put_u16(uint8_t* output, uint16_t value) {
  output[0] = static_cast<uint8_t>(value >> 8);
  output[1] = static_cast<uint8_t>(value);
}

void put_u32(uint8_t* output, uint32_t value) {
  for (size_t i = 0; i < 4; ++i)
    output[i] = static_cast<uint8_t>(value >> (24 - i * 8));
}

void put_u64(uint8_t* output, uint64_t value) {
  for (size_t i = 0; i < 8; ++i)
    output[i] = static_cast<uint8_t>(value >> (56 - i * 8));
}

uint16_t get_u16(const uint8_t* input) {
  return static_cast<uint16_t>((static_cast<uint16_t>(input[0]) << 8) | input[1]);
}

uint32_t get_u32(const uint8_t* input) {
  uint32_t value = 0;
  for (size_t i = 0; i < 4; ++i) value = (value << 8) | input[i];
  return value;
}

uint64_t get_u64(const uint8_t* input) {
  uint64_t value = 0;
  for (size_t i = 0; i < 8; ++i) value = (value << 8) | input[i];
  return value;
}

bool valid_operation_id(const std::string& value) {
  if (value.size() != 32) return false;
  for (char byte : value) {
    if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'))) return false;
  }
  return true;
}

bool secure_socket_parent(const std::string& path, std::string* error) {
  const size_t separator = path.rfind('/');
  if (separator == std::string::npos || separator + 1 == path.size())
    return reject("update_socket_path_invalid", error);
  const std::string parent = separator == 0 ? "/" : path.substr(0, separator);
  struct stat info {};
  if (lstat(parent.c_str(), &info) != 0 || !S_ISDIR(info.st_mode)
      || S_ISLNK(info.st_mode))
    return reject("update_socket_parent_unsafe", error);
  if (info.st_uid != geteuid() || (info.st_mode & 0022) != 0)
    return reject("update_socket_parent_permissions", error);
  return true;
}

void encode_header(uint8_t* output, ProtocolRequestType type, uint32_t body_size) {
  std::memcpy(output, kMagic, sizeof(kMagic));
  put_u16(output + 4, kUpdateProtocolVersion);
  put_u16(output + 6, static_cast<uint16_t>(type));
  put_u32(output + 8, body_size);
}

bool send_packet(int fd, const uint8_t* packet, size_t size, int archive_fd,
                 std::string* error) {
  struct iovec io {const_cast<uint8_t*>(packet), size};
  std::array<uint8_t, CMSG_SPACE(sizeof(int))> control{};
  struct msghdr message {};
  message.msg_iov = &io;
  message.msg_iovlen = 1;
  if (archive_fd >= 0) {
    message.msg_control = control.data();
    message.msg_controllen = control.size();
    struct cmsghdr* header = CMSG_FIRSTHDR(&message);
    header->cmsg_level = SOL_SOCKET;
    header->cmsg_type = SCM_RIGHTS;
    header->cmsg_len = CMSG_LEN(sizeof(int));
    std::memcpy(CMSG_DATA(header), &archive_fd, sizeof(archive_fd));
  }
  ssize_t sent;
  do {
    sent = sendmsg(fd, &message, MSG_NOSIGNAL);
  } while (sent < 0 && errno == EINTR);
  if (sent != static_cast<ssize_t>(size)) return reject("update_protocol_send_failed", error);
  return true;
}

bool valid_phase(uint32_t raw) {
  return raw >= static_cast<uint32_t>(Phase::kIdle)
      && raw <= static_cast<uint32_t>(Phase::kFailed);
}

bool valid_response_error(const std::string& value) {
  if (value.size() > kResponseErrorBytes) return false;
  for (char byte : value) {
    if (!((byte >= 'a' && byte <= 'z') || (byte >= '0' && byte <= '9')
          || byte == '_')) return false;
  }
  return true;
}

bool accept_authorized_connection(int listener_fd, uid_t satellite_uid,
                                  int* connected_fd, std::string* error) {
  int connected;
  do {
    connected = accept4(listener_fd, nullptr, nullptr, SOCK_CLOEXEC);
  } while (connected < 0 && errno == EINTR);
  if (connected < 0) return reject("update_socket_accept_failed", error);
  struct ucred credentials {};
  socklen_t length = sizeof(credentials);
  if (getsockopt(connected, SOL_SOCKET, SO_PEERCRED, &credentials, &length) != 0
      || length != sizeof(credentials)) {
    close(connected);
    return reject("update_peer_credentials_failed", error);
  }
  if (!authorized_peer(credentials.uid, satellite_uid, error)) {
    close(connected);
    return false;
  }
  struct timeval timeout {5, 0};
  if (setsockopt(connected, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                 sizeof(timeout)) != 0
      || setsockopt(connected, SOL_SOCKET, SO_SNDTIMEO, &timeout,
                    sizeof(timeout)) != 0) {
    close(connected);
    return reject("update_socket_timeout_failed", error);
  }
  *connected_fd = connected;
  return true;
}

void close_received_fds(struct msghdr* message, int keep_fd) {
  for (struct cmsghdr* header = CMSG_FIRSTHDR(message); header != nullptr;
       header = CMSG_NXTHDR(message, header)) {
    if (header->cmsg_level != SOL_SOCKET || header->cmsg_type != SCM_RIGHTS
        || header->cmsg_len < CMSG_LEN(0)) continue;
    size_t bytes = header->cmsg_len - CMSG_LEN(0);
    const int* descriptors = reinterpret_cast<const int*>(CMSG_DATA(header));
    for (size_t i = 0; i < bytes / sizeof(int); ++i)
      if (descriptors[i] >= 0 && descriptors[i] != keep_fd) close(descriptors[i]);
  }
}

}  // namespace

bool open_private_update_listener(const std::string& path, uid_t satellite_uid,
                                  int* listener_fd, std::string* error) {
  if (listener_fd == nullptr) return reject("update_listener_output_missing", error);
  *listener_fd = -1;
  if (satellite_uid == static_cast<uid_t>(-1))
    return reject("update_satellite_uid_invalid", error);
  if (path.empty() || path.size() >= sizeof(sockaddr_un::sun_path)
      || path.find('\0') != std::string::npos || path[0] != '/')
    return reject("update_socket_path_invalid", error);
  if (!secure_socket_parent(path, error)) return false;
  struct stat existing {};
  if (lstat(path.c_str(), &existing) == 0 || errno != ENOENT)
    return reject("update_socket_path_exists", error);

  int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  if (fd < 0) return reject("update_socket_create_failed", error);
  struct sockaddr_un address {};
  address.sun_family = AF_UNIX;
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  const socklen_t address_size = static_cast<socklen_t>(
      offsetof(struct sockaddr_un, sun_path) + path.size() + 1);
  if (bind(fd, reinterpret_cast<const struct sockaddr*>(&address), address_size) != 0) {
    close(fd);
    return reject("update_socket_bind_failed", error);
  }
  if (chown(path.c_str(), satellite_uid, static_cast<gid_t>(-1)) != 0
      || chmod(path.c_str(), 0600) != 0 || listen(fd, 4) != 0) {
    close(fd);
    unlink(path.c_str());
    return reject("update_socket_secure_failed", error);
  }
  *listener_fd = fd;
  return true;
}

bool receive_protocol_request(int connected_fd, ProtocolRequest* request,
                              std::string* error) {
  if (request == nullptr) return reject("update_protocol_output_missing", error);
  if (request->archive_fd >= 0)
    return reject("update_protocol_output_not_empty", error);
  std::array<uint8_t, kMaximumPacketBytes> packet{};
  struct iovec io {packet.data(), packet.size()};
  std::array<uint8_t, CMSG_SPACE(sizeof(int) * 2)> control{};
  struct msghdr message {};
  message.msg_iov = &io;
  message.msg_iovlen = 1;
  message.msg_control = control.data();
  message.msg_controllen = control.size();
  ssize_t received;
  do {
    received = recvmsg(connected_fd, &message, 0);
  } while (received < 0 && errno == EINTR);
  if (received < 0 || (message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0) {
    close_received_fds(&message, -1);
    return reject("update_protocol_receive_failed", error);
  }

  int received_fd = -1;
  size_t descriptor_count = 0;
  bool invalid_control = false;
  for (struct cmsghdr* header = CMSG_FIRSTHDR(&message); header != nullptr;
       header = CMSG_NXTHDR(&message, header)) {
    if (header->cmsg_level != SOL_SOCKET || header->cmsg_type != SCM_RIGHTS
        || header->cmsg_len < CMSG_LEN(sizeof(int))) {
      invalid_control = true;
      continue;
    }
    size_t count = (header->cmsg_len - CMSG_LEN(0)) / sizeof(int);
    const int* descriptors = reinterpret_cast<const int*>(CMSG_DATA(header));
    for (size_t i = 0; i < count; ++i) {
      ++descriptor_count;
      if (received_fd < 0) received_fd = descriptors[i];
    }
  }
  if (received < static_cast<ssize_t>(kHeaderBytes)
      || std::memcmp(packet.data(), kMagic, sizeof(kMagic)) != 0
      || get_u16(packet.data() + 4) != kUpdateProtocolVersion) {
    close_received_fds(&message, -1);
    return reject("update_protocol_header_invalid", error);
  }
  const uint16_t raw_type = get_u16(packet.data() + 6);
  const uint32_t body_size = get_u32(packet.data() + 8);
  if (static_cast<uint64_t>(body_size) + kHeaderBytes
      != static_cast<uint64_t>(received)) {
    close_received_fds(&message, -1);
    return reject("update_protocol_size_invalid", error);
  }
  if (invalid_control || descriptor_count > 1) {
    close_received_fds(&message, -1);
    return reject("update_protocol_descriptor_invalid", error);
  }

  if (raw_type == static_cast<uint16_t>(ProtocolRequestType::kApply)) {
    if (body_size != kApplyBodyBytes || descriptor_count != 1) {
      close_received_fds(&message, -1);
      return reject("update_protocol_apply_invalid", error);
    }
    const uint8_t* body = packet.data() + kHeaderBytes;
    Candidate candidate;
    candidate.operation_id.assign(reinterpret_cast<const char*>(body), 32);
    candidate.package_name = kPackageName;
    candidate.from_version = get_u32(body + 32);
    candidate.to_version = get_u32(body + 36);
    candidate.apk_size = get_u64(body + 40);
    std::memcpy(candidate.apk_sha256.data(), body + 48, 32);
    std::memcpy(candidate.signer_sha256.data(), body + 80, 32);
    candidate.health_timeout_seconds = get_u32(body + 112);
    if (!valid_operation_id(candidate.operation_id)) {
      close_received_fds(&message, -1);
      return reject("update_protocol_operation_invalid", error);
    }
    int flags = fcntl(received_fd, F_GETFD);
    if (flags < 0 || fcntl(received_fd, F_SETFD, flags | FD_CLOEXEC) != 0) {
      close_received_fds(&message, -1);
      return reject("update_protocol_descriptor_flags_failed", error);
    }
    request->type = ProtocolRequestType::kApply;
    request->candidate = candidate;
    request->archive_fd = received_fd;
    close_received_fds(&message, received_fd);
    return true;
  }

  if (raw_type == static_cast<uint16_t>(ProtocolRequestType::kHealth)) {
    if (body_size != kHealthBodyBytes || descriptor_count != 0) {
      close_received_fds(&message, -1);
      return reject("update_protocol_health_invalid", error);
    }
    const uint8_t* body = packet.data() + kHeaderBytes;
    for (size_t i = 0; i < kHealthBodyBytes; ++i) {
      if (body[i] > 1) return reject("update_protocol_health_value_invalid", error);
    }
    request->type = ProtocolRequestType::kHealth;
    request->health = {body[0] == 1, body[1] == 1, body[2] == 1, body[3] == 1};
    return true;
  }
  close_received_fds(&message, -1);
  return reject("update_protocol_type_invalid", error);
}

bool accept_protocol_request(int listener_fd, uid_t satellite_uid,
                             ProtocolRequest* request, std::string* error) {
  int connected = -1;
  if (!accept_authorized_connection(listener_fd, satellite_uid, &connected, error))
    return false;
  bool okay = receive_protocol_request(connected, request, error);
  close(connected);
  return okay;
}

bool send_apply_request(int connected_fd, const Candidate& candidate,
                        int archive_fd, std::string* error) {
  if (!valid_operation_id(candidate.operation_id) || candidate.package_name != kPackageName
      || archive_fd < 0) return reject("update_protocol_apply_invalid", error);
  std::array<uint8_t, kMaximumPacketBytes> packet{};
  encode_header(packet.data(), ProtocolRequestType::kApply, kApplyBodyBytes);
  uint8_t* body = packet.data() + kHeaderBytes;
  std::memcpy(body, candidate.operation_id.data(), 32);
  put_u32(body + 32, candidate.from_version);
  put_u32(body + 36, candidate.to_version);
  put_u64(body + 40, candidate.apk_size);
  std::memcpy(body + 48, candidate.apk_sha256.data(), 32);
  std::memcpy(body + 80, candidate.signer_sha256.data(), 32);
  put_u32(body + 112, candidate.health_timeout_seconds);
  return send_packet(connected_fd, packet.data(), packet.size(), archive_fd, error);
}

bool send_health_request(int connected_fd, const Health& health,
                         std::string* error) {
  std::array<uint8_t, kHeaderBytes + kHealthBodyBytes> packet{};
  encode_header(packet.data(), ProtocolRequestType::kHealth, kHealthBodyBytes);
  uint8_t* body = packet.data() + kHeaderBytes;
  body[0] = health.service_ready;
  body[1] = health.state_loaded;
  body[2] = health.audio_agent_reachable;
  body[3] = health.isolation_safe;
  return send_packet(connected_fd, packet.data(), packet.size(), -1, error);
}

bool send_protocol_response(int connected_fd, const ProtocolResponse& response,
                            std::string* error) {
  const uint16_t raw_type = static_cast<uint16_t>(response.request_type);
  if ((raw_type != static_cast<uint16_t>(ProtocolRequestType::kApply)
       && raw_type != static_cast<uint16_t>(ProtocolRequestType::kHealth))
      || response.error.size() > kResponseErrorBytes
      || !valid_phase(static_cast<uint32_t>(response.phase))
      || !valid_response_error(response.error)
      || (!response.success && response.error.empty())
      || (response.success && !response.error.empty()))
    return reject("update_protocol_response_invalid", error);
  std::array<uint8_t, kHeaderBytes + kResponseBodyBytes> packet{};
  encode_header(packet.data(), ProtocolRequestType::kResponse,
                kResponseBodyBytes);
  uint8_t* body = packet.data() + kHeaderBytes;
  put_u16(body, raw_type);
  body[2] = response.success ? 1 : 0;
  put_u32(body + 4, static_cast<uint32_t>(response.phase));
  put_u16(body + 8, static_cast<uint16_t>(response.error.size()));
  std::memcpy(body + 12, response.error.data(), response.error.size());
  return send_packet(connected_fd, packet.data(), packet.size(), -1, error);
}

bool receive_protocol_response(int connected_fd, ProtocolResponse* response,
                               std::string* error) {
  if (response == nullptr) return reject("update_protocol_response_output_missing", error);
  std::array<uint8_t, kHeaderBytes + kResponseBodyBytes> packet{};
  struct iovec io {packet.data(), packet.size()};
  std::array<uint8_t, CMSG_SPACE(sizeof(int))> control{};
  struct msghdr message {};
  message.msg_iov = &io;
  message.msg_iovlen = 1;
  message.msg_control = control.data();
  message.msg_controllen = control.size();
  ssize_t received;
  do {
    received = recvmsg(connected_fd, &message, 0);
  } while (received < 0 && errno == EINTR);
  if ((message.msg_flags & MSG_CTRUNC) != 0 || CMSG_FIRSTHDR(&message) != nullptr) {
    close_received_fds(&message, -1);
    return reject("update_protocol_response_descriptor_invalid", error);
  }
  if (received != static_cast<ssize_t>(packet.size())
      || (message.msg_flags & MSG_TRUNC) != 0
      || std::memcmp(packet.data(), kMagic, sizeof(kMagic)) != 0
      || get_u16(packet.data() + 4) != kUpdateProtocolVersion
      || get_u16(packet.data() + 6)
          != static_cast<uint16_t>(ProtocolRequestType::kResponse)
      || get_u32(packet.data() + 8) != kResponseBodyBytes)
    return reject("update_protocol_response_header_invalid", error);
  const uint8_t* body = packet.data() + kHeaderBytes;
  const uint16_t raw_type = get_u16(body);
  const uint8_t success = body[2];
  const uint32_t raw_phase = get_u32(body + 4);
  const uint16_t error_size = get_u16(body + 8);
  if ((raw_type != static_cast<uint16_t>(ProtocolRequestType::kApply)
       && raw_type != static_cast<uint16_t>(ProtocolRequestType::kHealth))
      || success > 1 || !valid_phase(raw_phase) || error_size > kResponseErrorBytes
      || (success == 1 && error_size != 0) || (success == 0 && error_size == 0))
    return reject("update_protocol_response_value_invalid", error);
  if (body[3] != 0) return reject("update_protocol_response_reserved_invalid", error);
  for (size_t i = 10; i < 12; ++i)
    if (body[i] != 0) return reject("update_protocol_response_reserved_invalid", error);
  for (size_t i = 12 + error_size; i < kResponseBodyBytes; ++i)
    if (body[i] != 0) return reject("update_protocol_response_padding_invalid", error);
  response->request_type = static_cast<ProtocolRequestType>(raw_type);
  response->success = success == 1;
  response->phase = static_cast<Phase>(raw_phase);
  response->error.assign(reinterpret_cast<const char*>(body + 12), error_size);
  if (!valid_response_error(response->error))
    return reject("update_protocol_response_error_invalid", error);
  return true;
}

bool dispatch_protocol_request(ProtocolRequest* request,
                               const std::string& transaction_directory,
                               PackageOrchestrator* orchestrator,
                               uint64_t now, std::string* error) {
  if (request == nullptr || orchestrator == nullptr)
    return reject("update_protocol_dispatch_missing", error);
  if (request->type == ProtocolRequestType::kHealth) {
    if (request->archive_fd >= 0) {
      close(request->archive_fd);
      request->archive_fd = -1;
      return reject("update_protocol_health_descriptor_present", error);
    }
    return orchestrator->confirm_health(request->health, error);
  }
  if (request->type != ProtocolRequestType::kApply) {
    if (request->archive_fd >= 0) close(request->archive_fd);
    request->archive_fd = -1;
    return reject("update_protocol_dispatch_type_invalid", error);
  }
  const int archive_fd = request->archive_fd;
  request->archive_fd = -1;
  if (archive_fd < 0) return reject("update_protocol_apply_descriptor_missing", error);
  StagedArchive archive;
  bool staged = stage_archive_from_fd(archive_fd, transaction_directory,
                                      request->candidate.operation_id,
                                      request->candidate.apk_size,
                                      request->candidate.apk_sha256,
                                      &archive, error);
  close(archive_fd);
  if (!staged) return false;
  return orchestrator->apply(request->candidate, archive, now, error);
}

bool serve_protocol_request_once(int listener_fd, uid_t satellite_uid,
                                 const std::string& transaction_directory,
                                 PackageOrchestrator* orchestrator,
                                 uint64_t now, bool* operation_succeeded,
                                 std::string* error) {
  if (operation_succeeded == nullptr)
    return reject("update_protocol_result_output_missing", error);
  if (orchestrator == nullptr)
    return reject("update_protocol_dispatch_missing", error);
  *operation_succeeded = false;
  int connected = -1;
  if (!accept_authorized_connection(listener_fd, satellite_uid, &connected, error))
    return false;
  ProtocolRequest request;
  if (!receive_protocol_request(connected, &request, error)) {
    close(connected);
    return false;
  }
  const ProtocolRequestType request_type = request.type;
  std::string operation_error;
  const bool success = dispatch_protocol_request(&request, transaction_directory,
                                                 orchestrator, now,
                                                 &operation_error);
  if (!success && !valid_response_error(operation_error))
    operation_error = "update_internal_error";
  ProtocolResponse response{request_type, success, orchestrator->state().phase,
                            success ? "" : operation_error};
  bool replied = send_protocol_response(connected, response, error);
  close(connected);
  if (!replied) return false;
  *operation_succeeded = success;
  return true;
}

}  // namespace r1_update
