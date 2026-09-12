#pragma once

#include "package_orchestrator.h"

#include <cstdint>
#include <string>

#include <sys/types.h>

namespace r1_update {

constexpr uint16_t kUpdateProtocolVersion = 1;

enum class ProtocolRequestType : uint16_t {
  kApply = 1,
  kHealth = 2,
  kResponse = 3,
};

struct ProtocolResponse {
  ProtocolRequestType request_type = ProtocolRequestType::kApply;
  bool success = false;
  Phase phase = Phase::kIdle;
  std::string error;
};

struct ProtocolRequest {
  ProtocolRequestType type = ProtocolRequestType::kApply;
  Candidate candidate;
  Health health;
  // Owned by the caller after a successful receive. It is present only for an
  // apply request and must be closed even when dispatch fails.
  int archive_fd = -1;
};

// Creates an AF_UNIX SOCK_SEQPACKET listener without replacing an existing
// filesystem entry. The socket node is owned by the configured satellite UID
// and mode 0600; SO_PEERCRED remains the authoritative caller identity check.
bool open_private_update_listener(const std::string& path, uid_t satellite_uid,
                                  int* listener_fd, std::string* error);

// Opens a bounded client connection to an absolute filesystem socket and
// applies the same five-second I/O limits as the server side.
bool connect_private_update_socket(const std::string& path, int* connected_fd,
                                   std::string* error);

// Accepts one connection, verifies its kernel-supplied UID, and receives one
// complete, fixed-size version-1 packet. Apply packets require exactly one
// SCM_RIGHTS regular-file descriptor; health packets require none.
bool accept_protocol_request(int listener_fd, uid_t satellite_uid,
                             ProtocolRequest* request, std::string* error);
bool receive_protocol_request(int connected_fd, ProtocolRequest* request,
                              std::string* error);

// Client-side framing helpers. They never accept paths and send one atomic
// SEQPACKET message. The supervisor still validates every field independently.
bool send_apply_request(int connected_fd, const Candidate& candidate,
                        int archive_fd, std::string* error);
bool send_health_request(int connected_fd, const Health& health,
                         std::string* error);
bool send_protocol_response(int connected_fd, const ProtocolResponse& response,
                            std::string* error);
bool receive_protocol_response(int connected_fd, ProtocolResponse* response,
                               std::string* error);

// Connects a decoded request to U2 archive staging and U3 package orchestration.
// The function always consumes request->archive_fd.
bool dispatch_protocol_request(ProtocolRequest* request,
                               const std::string& transaction_directory,
                               PackageOrchestrator* orchestrator,
                               uint64_t now_monotonic_seconds,
                               std::string* error);

// Accepts, authenticates, decodes, dispatches, and replies to one client. A
// well-formed operation failure is reported in the fixed-size response and via
// operation_succeeded; the function itself returns false only for transport or
// framing failure.
bool serve_protocol_request_once(int listener_fd, uid_t satellite_uid,
                                 const std::string& transaction_directory,
                                 PackageOrchestrator* orchestrator,
                                 uint64_t now_monotonic_seconds,
                                 bool* operation_succeeded,
                                 std::string* error);

}  // namespace r1_update
