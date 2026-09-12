package dev.sewellzhong.r1probe.esphome;

import java.io.*;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;

/** Encrypted endpoint; the opt-in satellite profile advertises only implemented voice capabilities. */
public final class NativeApiConnection {
    public interface Handler {
        void connected(NativeVoiceSession.Sender sender);
        default void listEntities(NativeVoiceSession.Sender sender) throws IOException { }
        void message(int type, byte[] payload) throws IOException;
        void tick() throws IOException;
        void closed();
        default boolean wakeEnabled() { return true; }
        default void wakeEnabled(boolean enabled) { }
    }
    private static final int MAX_FRAME = 8192;
    private final Socket socket;
    private final DataInputStream in;
    private final DataOutputStream out;
    private final String name;
    private final String mac;
    private NoiseSession noise;
    private final Handler handler;
    private final boolean satellite;
    // aioesphomeapi 45.6.1 model.py: VOICE_ASSISTANT | API_AUDIO | TIMERS | ANNOUNCE. SPEAKER is
    // intentionally absent: this client consumes HA's authenticated early TTS URL, so HA must
    // not also push the same stream through VoiceAssistantAudio at TTS_END.
    public static final int SATELLITE_FEATURES = 29;
    private boolean ready;
    private volatile long writeStarted;
    private Thread watchdog;
    public NativeApiConnection(Socket socket, String name, String mac) throws IOException {
        this(socket, name, mac, null);
    }
    public NativeApiConnection(Socket socket, String name, String mac, Handler handler) throws IOException {
        this(socket, name, mac, handler, false);
    }
    public NativeApiConnection(Socket socket, String name, String mac, Handler handler, boolean satellite) throws IOException {
        if (satellite && handler == null) throw new IllegalArgumentException("satellite_handler_required");
        this.satellite = satellite;
        if (!name.matches("[a-z][a-z0-9-]{0,30}") || !mac.matches("[0-9A-F]{2}(:[0-9A-F]{2}){5}")) {
            throw new IllegalArgumentException("invalid_device_identity");
        }
        this.socket=socket; this.name=name; this.mac=mac; this.handler=handler;
        in=new DataInputStream(socket.getInputStream());out=new DataOutputStream(socket.getOutputStream());
    }
    public void run(byte[] key) throws IOException {
        if (key == null || key.length != 32) { throw new IllegalArgumentException("noise_psk_required"); }
        try {
            socket.setSoTimeout(10000); socket.setTcpNoDelay(true);
            watchdog = new Thread(() -> {
                try {
                    while (!socket.isClosed()) {
                        long began = writeStarted;
                        if (began != 0 && System.nanoTime() - began > 5_000_000_000L) {
                            socket.close(); return;
                        }
                        Thread.sleep(100);
                    }
                } catch (InterruptedException | IOException ignored) { }
            }, "native-write-watchdog");
            watchdog.setDaemon(true); watchdog.start();
            byte[] hello=readFrame(128);
            ByteArrayOutputStream prologue=new ByteArrayOutputStream();
            prologue.write("NoiseAPIInit".getBytes(StandardCharsets.US_ASCII));
            prologue.write(hello.length >> 8);prologue.write(hello.length);prologue.write(hello);
            noise=new NoiseSession(key,prologue.toByteArray());
            ByteArrayOutputStream serverHello=new ByteArrayOutputStream();
            serverHello.write(1);serverHello.write(name.getBytes(StandardCharsets.US_ASCII));serverHello.write(0);
            serverHello.write(mac.getBytes(StandardCharsets.US_ASCII));serverHello.write(0);
            frame(serverHello.toByteArray());
            byte[] handshake=readFrame(129);
            if (handshake.length < 2 || handshake[0]!=0) { throw new IOException("bad_handshake"); }
            byte[] reply;
            try { reply = noise.respond(Arrays.copyOfRange(handshake, 1, handshake.length)); }
            catch (IllegalStateException e) {
                if (satellite && "noise_handshake_mac_failed".equals(e.getMessage())) {
                    byte[] explanation = "Handshake MAC failure".getBytes(StandardCharsets.US_ASCII);
                    byte[] rejected = new byte[explanation.length + 1]; rejected[0] = 1;
                    System.arraycopy(explanation, 0, rejected, 1, explanation.length); frame(rejected);
                }
                throw e;
            }
            byte[] response=new byte[reply.length+1];System.arraycopy(reply,0,response,1,reply.length);frame(response);
            socket.setSoTimeout(90000);
            boolean initialized=false;
            while (!socket.isClosed()) {
                byte[] plain=noise.decrypt(readFrame(MAX_FRAME));
                if (plain.length < 4) { throw new IOException("invalid_payload"); }
                int type=((plain[0]&255)<<8)|(plain[1]&255);
                int size=((plain[2]&255)<<8)|(plain[3]&255);
                if (size != plain.length-4) { throw new IOException("invalid_payload_length"); }
                byte[] payload=Arrays.copyOfRange(plain,4,plain.length);
                if (!initialized && type!=MessageIds.HelloRequest) { throw new IOException("hello_required"); }
                if (type==MessageIds.HelloRequest) {
                    if(initialized) throw new IOException("duplicate_hello");
                    EsphomeApi.HelloRequest request=EsphomeApi.HelloRequest.parseFrom(payload);
                    if(request.getApiVersionMajor()!=1) throw new IOException("unsupported_api_major");
                    send(MessageIds.HelloResponse,EsphomeApi.HelloResponse.newBuilder().setApiVersionMajor(1)
                            .setApiVersionMinor(15).setName(name).setServerInfo("R1 native foundation").build());
                    initialized=true;
                    if (handler != null) {
                        handler.connected(this::send);
                        ready=true;
                        socket.setSoTimeout(1000);
                    }
                } else if(type==MessageIds.PingRequest) {
                    send(MessageIds.PingResponse,EsphomeApi.PingResponse.getDefaultInstance());
                } else if(type==MessageIds.DeviceInfoRequest) {
                    send(MessageIds.DeviceInfoResponse,EsphomeApi.DeviceInfoResponse.newBuilder().setName(name)
                            .setFriendlyName(satellite ? "R1 原生语音" : "R1 Native Foundation").setMacAddress(mac).setManufacturer("Phicomm")
                            .setModel("R1 API22").setEsphomeVersion("2026.8.0").setProjectName("sewellzhong.r1-satellite")
                            .setProjectVersion(satellite ? "1.17-system-management" : "0.43-foundation")
                            .setVoiceAssistantFeatureFlags(satellite ? SATELLITE_FEATURES : 0).build());
                } else if(type==MessageIds.DeviceCapabilitiesRequest) {
                    send(MessageIds.DeviceCapabilitiesResponse,satellite ? EsphomeApi.DeviceCapabilitiesResponse.newBuilder()
                            .setVoiceAssistant(EsphomeApi.VoiceAssistantCapabilities.newBuilder().setFeatureFlags(SATELLITE_FEATURES)).build()
                            : EsphomeApi.DeviceCapabilitiesResponse.getDefaultInstance());
                } else if(type==MessageIds.ListEntitiesRequest) {
                    if (satellite) handler.listEntities(this::send);
                    send(MessageIds.ListEntitiesDoneResponse,EsphomeApi.ListEntitiesDoneResponse.getDefaultInstance());
                } else if(satellite && type==MessageIds.VoiceAssistantConfigurationRequest) {
                    sendWakeConfiguration();
                } else if(satellite && type==MessageIds.VoiceAssistantSetConfiguration) {
                    EsphomeApi.VoiceAssistantSetConfiguration config = EsphomeApi.VoiceAssistantSetConfiguration.parseFrom(payload);
                    if (config.getActiveWakeWordsCount() > 1 || (config.getActiveWakeWordsCount() == 1
                            && !"alexa".equals(config.getActiveWakeWords(0)))) throw new IOException("unsupported_wake_word");
                    handler.wakeEnabled(config.getActiveWakeWordsCount() == 1);
                } else if(type==MessageIds.DisconnectRequest) {
                    send(MessageIds.DisconnectResponse,EsphomeApi.DisconnectResponse.getDefaultInstance());return;
                } else if(handler != null) {
                    handler.message(type, payload);
                }
                if (ready) handler.tick();
                // Unknown messages safely ignored; no unsupported voice/media feature bits are advertised.
            }
        } catch (IllegalStateException e) { throw new IOException("noise_authentication_or_frame_failed"); }
        finally {
            try { if(handler!=null)handler.closed(); }
            finally {
                if (watchdog != null) watchdog.interrupt();
                if(noise!=null)noise.close();socket.close();
            }
        }
    }
    private void sendWakeConfiguration() throws IOException {
        EsphomeApi.VoiceAssistantConfigurationResponse.Builder config = EsphomeApi.VoiceAssistantConfigurationResponse.newBuilder()
                .addAvailableWakeWords(EsphomeApi.VoiceAssistantWakeWord.newBuilder().setId("alexa").setWakeWord("Alexa").addTrainedLanguages("en"))
                .setMaxActiveWakeWords(1);
        if (handler.wakeEnabled()) config.addActiveWakeWords("alexa");
        send(MessageIds.VoiceAssistantConfigurationResponse, config.build());
    }
    private byte[] readFrame(int max) throws IOException {
        if (ready) socket.setSoTimeout(20);
        int marker;
        long idleDeadline=System.nanoTime()+90_000_000_000L;
        // Only an idle frame boundary is retryable; a timeout inside a frame closes the stream.
        while (true) {
            try { marker=in.readUnsignedByte(); break; }
            catch (SocketTimeoutException e) {
                if (!ready || System.nanoTime() >= idleDeadline) throw e;
                handler.tick();
            }
        }
        if (marker != 1) {
            // HA's manual pairing first probes plaintext. Return only the Noise framing marker,
            // so its pinned client raises RequiresEncryptionAPIError and asks for the PSK.
            // No plaintext protobuf, identity, authentication or audio is processed.
            if (satellite && noise == null && marker == 0) frame(new byte[0]);
            throw new IOException("encrypted_frames_required");
        }
        if (ready) socket.setSoTimeout(1000);
        int size=in.readUnsignedShort();if(size>max)throw new IOException("frame_too_large");
        byte[] data=new byte[size];in.readFully(data);return data;
    }
    private void frame(byte[] data) throws IOException {
        if(data.length>MAX_FRAME)throw new IOException("frame_too_large");
        writeStarted = System.nanoTime();
        try { out.writeByte(1);out.writeShort(data.length);out.write(data);out.flush(); }
        finally { writeStarted = 0; }
    }
    private void send(int type, MessageLite message) throws IOException {
        byte[] payload=message.toByteArray();ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        DataOutputStream writer=new DataOutputStream(bytes);writer.writeShort(type);writer.writeShort(payload.length);writer.write(payload);
        frame(noise.encrypt(bytes.toByteArray()));
    }
}
