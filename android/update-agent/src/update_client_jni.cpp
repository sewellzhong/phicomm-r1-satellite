#include "update_protocol.h"

#include <jni.h>

#include <array>
#include <cstdint>
#include <string>

#include <unistd.h>

namespace {

constexpr char kSocketPath[] = "/dev/socket/r1_update_supervisor";
constexpr char kPackageName[] = "dev.sewellzhong.r1probe";

void throw_io(JNIEnv* environment, const std::string& error) {
  jclass type = environment->FindClass("java/io/IOException");
  if (type != nullptr) environment->ThrowNew(type, error.c_str());
}

bool copy_digest(JNIEnv* environment, jbyteArray input,
                 std::array<uint8_t, 32>* output) {
  if (input == nullptr || environment->GetArrayLength(input) != 32) return false;
  environment->GetByteArrayRegion(input, 0, 32,
      reinterpret_cast<jbyte*>(output->data()));
  return !environment->ExceptionCheck();
}

std::string copy_string(JNIEnv* environment, jstring input) {
  if (input == nullptr) return {};
  const char* bytes = environment->GetStringUTFChars(input, nullptr);
  if (bytes == nullptr) return {};
  std::string result(bytes);
  environment->ReleaseStringUTFChars(input, bytes);
  return result;
}

jobjectArray response_array(JNIEnv* environment,
                            const r1_update::ProtocolResponse& response) {
  jclass string_type = environment->FindClass("java/lang/String");
  if (string_type == nullptr) return nullptr;
  jobjectArray result = environment->NewObjectArray(3, string_type, nullptr);
  if (result == nullptr) return nullptr;
  const std::string phase = std::to_string(static_cast<uint32_t>(response.phase));
  jstring success = environment->NewStringUTF(response.success ? "1" : "0");
  jstring phase_value = environment->NewStringUTF(phase.c_str());
  jstring error = environment->NewStringUTF(response.error.c_str());
  if (success == nullptr || phase_value == nullptr || error == nullptr) return nullptr;
  environment->SetObjectArrayElement(result, 0, success);
  environment->SetObjectArrayElement(result, 1, phase_value);
  environment->SetObjectArrayElement(result, 2, error);
  return result;
}

}  // namespace

extern "C" JNIEXPORT void JNICALL
Java_dev_sewellzhong_r1probe_UpdateSupervisorNative_sendApply(
    JNIEnv* environment, jclass, jstring operation_id, jint from_version,
    jint to_version, jlong apk_size, jbyteArray apk_sha256,
    jbyteArray signer_sha256, jint health_timeout_seconds, jint archive_fd) {
  r1_update::Candidate candidate;
  candidate.operation_id = copy_string(environment, operation_id);
  candidate.package_name = kPackageName;
  candidate.from_version = static_cast<uint32_t>(from_version);
  candidate.to_version = static_cast<uint32_t>(to_version);
  candidate.apk_size = static_cast<uint64_t>(apk_size);
  candidate.health_timeout_seconds = static_cast<uint32_t>(health_timeout_seconds);
  if (environment->ExceptionCheck()) return;
  if (!copy_digest(environment, apk_sha256, &candidate.apk_sha256)
      || !copy_digest(environment, signer_sha256, &candidate.signer_sha256)) {
    throw_io(environment, "update_candidate_digest_invalid");
    return;
  }
  int connected = -1;
  std::string error;
  if (!r1_update::connect_private_update_socket(kSocketPath, &connected, &error)) {
    throw_io(environment, error);
    return;
  }
  const bool sent = r1_update::send_apply_request(connected, candidate,
                                                   archive_fd, &error);
  close(connected);
  if (!sent) throw_io(environment, error);
}

extern "C" JNIEXPORT jobjectArray JNICALL
Java_dev_sewellzhong_r1probe_UpdateSupervisorNative_sendHealth(
    JNIEnv* environment, jclass, jboolean service_ready, jboolean state_loaded,
    jboolean audio_agent_reachable, jboolean isolation_safe) {
  int connected = -1;
  std::string error;
  if (!r1_update::connect_private_update_socket(kSocketPath, &connected, &error)) {
    throw_io(environment, error);
    return nullptr;
  }
  r1_update::Health health{service_ready == JNI_TRUE, state_loaded == JNI_TRUE,
                           audio_agent_reachable == JNI_TRUE,
                           isolation_safe == JNI_TRUE};
  r1_update::ProtocolResponse response;
  bool okay = r1_update::send_health_request(connected, health, &error)
      && r1_update::receive_protocol_response(connected, &response, &error);
  close(connected);
  if (!okay) {
    throw_io(environment, error);
    return nullptr;
  }
  if (response.request_type != r1_update::ProtocolRequestType::kHealth) {
    throw_io(environment, "update_protocol_response_type_invalid");
    return nullptr;
  }
  return response_array(environment, response);
}
