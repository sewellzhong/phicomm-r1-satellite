#include "system_control.h"

#include <jni.h>
#include <unistd.h>

#include <string>

namespace {
void throw_io(JNIEnv* environment, const std::string& message) {
  jclass type = environment->FindClass("java/io/IOException");
  if (type != nullptr) environment->ThrowNew(type, message.c_str());
}

bool transact(const r1_system_control::Request& request,
              r1_system_control::Response* response, std::string* error) {
  int connected = -1;
  if (!r1_system_control::connect_socket(r1_system_control::kSocketPath, &connected, error))
    return false;
  const bool okay = r1_system_control::send_request(connected, request, response, error);
  close(connected);
  return okay;
}
}

extern "C" JNIEXPORT jintArray JNICALL
Java_dev_sewellzhong_r1probe_SystemControlNative_setLed(
    JNIEnv* environment, jclass, jint first, jint second) {
  r1_system_control::Response response{};
  std::string error;
  if (!transact({r1_system_control::Operation::kSetLed,
                 static_cast<uint8_t>(first), static_cast<uint8_t>(second)},
                &response, &error)) {
    throw_io(environment, error); return nullptr;
  }
  if (response.status != r1_system_control::Status::kOk) {
    throw_io(environment, "system_control_led_rejected"); return nullptr;
  }
  jint values[2] = {response.first, response.second};
  jintArray result = environment->NewIntArray(2);
  if (result != nullptr) environment->SetIntArrayRegion(result, 0, 2, values);
  return result;
}

extern "C" JNIEXPORT void JNICALL
Java_dev_sewellzhong_r1probe_SystemControlNative_reboot(JNIEnv* environment, jclass) {
  r1_system_control::Response response{};
  std::string error;
  if (!transact({r1_system_control::Operation::kReboot, 0, 0}, &response, &error)) {
    throw_io(environment, error); return;
  }
  if (response.status != r1_system_control::Status::kOk)
    throw_io(environment, "system_control_reboot_rejected");
}
