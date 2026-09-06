#include <jni.h>
#include <cstdint>
#include <fvad.h>
extern "C" JNIEXPORT jlong JNICALL
Java_dev_sewellzhong_r1probe_CommandVad_nativeCreate(JNIEnv*, jclass) {
    Fvad* vad = fvad_new();
    if (!vad) return 0;
    if (fvad_set_sample_rate(vad, 16000) || fvad_set_mode(vad, 2)) {
        fvad_free(vad); return 0;
    }
    return reinterpret_cast<intptr_t>(vad);
}
extern "C" JNIEXPORT jint JNICALL
Java_dev_sewellzhong_r1probe_CommandVad_nativeProcess(JNIEnv* env, jclass, jlong ptr, jshortArray pcm) {
    if (!ptr || !pcm || env->GetArrayLength(pcm) != 320) return -1;
    int16_t frame[320];
    env->GetShortArrayRegion(pcm, 0, 320, frame);
    if (env->ExceptionCheck()) return -1;
    return fvad_process(reinterpret_cast<Fvad*>(static_cast<intptr_t>(ptr)), frame, 320);
}
extern "C" JNIEXPORT void JNICALL
Java_dev_sewellzhong_r1probe_CommandVad_nativeDestroy(JNIEnv*, jclass, jlong ptr) {
    if (ptr) fvad_free(reinterpret_cast<Fvad*>(static_cast<intptr_t>(ptr)));
}
