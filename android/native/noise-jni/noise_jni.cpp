#include <jni.h>
#include <noise/protocol.h>
#include <cstdint>
#include <cstdlib>
#include <cstring>
struct Session { NoiseHandshakeState* handshake; NoiseCipherState* send; NoiseCipherState* recv; };
static void release(Session* s) {
    if (!s) return;
    if (s->handshake) noise_handshakestate_free(s->handshake);
    if (s->send) noise_cipherstate_free(s->send);
    if (s->recv) noise_cipherstate_free(s->recv);
    free(s);
}
static void fail(JNIEnv* e) { e->ThrowNew(e->FindClass("java/lang/IllegalStateException"), "noise_operation_failed"); }
extern "C" JNIEXPORT jlong JNICALL
Java_dev_sewellzhong_r1probe_esphome_NoiseSession_create(JNIEnv* e,jclass,jbyteArray key,jbyteArray prologue) {
    if (!key || e->GetArrayLength(key)!=32 || !prologue || e->GetArrayLength(prologue)>256) { fail(e); return 0; }
    Session* s=static_cast<Session*>(calloc(1,sizeof(Session)));
    if (!s) { fail(e); return 0; }
    uint8_t k[32],p[256];
    e->GetByteArrayRegion(key,0,32,reinterpret_cast<jbyte*>(k));
    int len=e->GetArrayLength(prologue);
    e->GetByteArrayRegion(prologue,0,len,reinterpret_cast<jbyte*>(p));
    int err=noise_handshakestate_new_by_name(&s->handshake,"Noise_NNpsk0_25519_ChaChaPoly_SHA256",NOISE_ROLE_RESPONDER);
    if (!err) err=noise_handshakestate_set_pre_shared_key(s->handshake,k,32);
    volatile uint8_t* wipe=k; for(int i=0;i<32;i++) wipe[i]=0;
    if (!err) err=noise_handshakestate_set_prologue(s->handshake,p,len);
    if (!err) err=noise_handshakestate_start(s->handshake);
    if (err) { release(s); fail(e); return 0; }
    return reinterpret_cast<intptr_t>(s);
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_dev_sewellzhong_r1probe_esphome_NoiseSession_handshake(JNIEnv* e,jclass,jlong ptr,jbyteArray input) {
    auto* s=reinterpret_cast<Session*>(static_cast<intptr_t>(ptr));
    if (!s || !s->handshake || !input || e->GetArrayLength(input)>128) { fail(e); return nullptr; }
    uint8_t in[128],out[128];int len=e->GetArrayLength(input);
    e->GetByteArrayRegion(input,0,len,reinterpret_cast<jbyte*>(in));
    NoiseBuffer b;noise_buffer_set_input(b,in,len);
    int err=noise_handshakestate_read_message(s->handshake,&b,nullptr);
    noise_buffer_set_output(b,out,sizeof(out));
    if (!err) err=noise_handshakestate_write_message(s->handshake,&b,nullptr);
    if (!err) err=noise_handshakestate_split(s->handshake,&s->send,&s->recv);
    if (err) {
        if (err == NOISE_ERROR_MAC_FAILURE)
            e->ThrowNew(e->FindClass("java/lang/IllegalStateException"), "noise_handshake_mac_failed");
        else fail(e);
        return nullptr;
    }
    noise_handshakestate_free(s->handshake);s->handshake=nullptr;
    jbyteArray result=e->NewByteArray(b.size);
    if(result)e->SetByteArrayRegion(result,0,b.size,reinterpret_cast<jbyte*>(out));
    return result;
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_dev_sewellzhong_r1probe_esphome_NoiseSession_crypt(JNIEnv* e,jclass,jlong ptr,jbyteArray input,jboolean encrypt) {
    auto* s=reinterpret_cast<Session*>(static_cast<intptr_t>(ptr));
    if(!s || !s->send || !s->recv || !input || e->GetArrayLength(input)>8192) { fail(e); return nullptr; }
    uint8_t bytes[8208];int len=e->GetArrayLength(input);
    e->GetByteArrayRegion(input,0,len,reinterpret_cast<jbyte*>(bytes));
    NoiseBuffer b;noise_buffer_set_inout(b,bytes,len,sizeof(bytes));
    int err=encrypt?noise_cipherstate_encrypt(s->send,&b):noise_cipherstate_decrypt(s->recv,&b);
    if(err) { fail(e); return nullptr; }
    jbyteArray result=e->NewByteArray(b.size);
    if(result)e->SetByteArrayRegion(result,0,b.size,reinterpret_cast<jbyte*>(bytes));
    return result;
}
extern "C" JNIEXPORT void JNICALL
Java_dev_sewellzhong_r1probe_esphome_NoiseSession_destroy(JNIEnv*,jclass,jlong ptr) {
    release(reinterpret_cast<Session*>(static_cast<intptr_t>(ptr)));
}
