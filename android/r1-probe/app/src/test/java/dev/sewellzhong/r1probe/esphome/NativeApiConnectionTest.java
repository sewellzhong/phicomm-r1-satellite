package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.io.IOException;
import java.net.*;
import java.util.concurrent.*;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import static org.junit.Assert.*;

public final class NativeApiConnectionTest {
    @Test public void advertisesOnlyImplementedVoiceAudioTimerAndAnnouncementFeatures() {
        assertEquals(29, NativeApiConnection.SATELLITE_FEATURES);
    }
    @Test public void internalTtsEntityNegotiatesOnlyBoundedAnnouncementWav() {
        EsphomeApi.ListEntitiesMediaPlayerResponse entity = NativeApiConnection.ttsFormatEntity();
        assertEquals(0, entity.getFeatureFlags()); assertFalse(entity.getSupportsPause());
        assertEquals(1, entity.getSupportedFormatsCount());
        EsphomeApi.MediaPlayerSupportedFormat format = entity.getSupportedFormats(0);
        assertEquals("wav", format.getFormat()); assertEquals(16000, format.getSampleRate());
        assertEquals(1, format.getNumChannels()); assertEquals(2, format.getSampleBytes());
        assertEquals(EsphomeApi.MediaPlayerFormatPurpose.MEDIA_PLAYER_FORMAT_PURPOSE_ANNOUNCEMENT,
                format.getPurpose());
    }
    @Test public void plaintextIsRejectedBeforeAnyProtocolResponse() throws Exception {
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getLoopbackAddress());
            Socket client=new Socket("127.0.0.1",server.getLocalPort()); Socket accepted=server.accept()) {
            ExecutorService thread=Executors.newSingleThreadExecutor();
            try {
                Future<String> result=thread.submit(() -> {
                    try { new NativeApiConnection(accepted,"r1-test","02:00:00:00:00:01").run(new byte[32]); }
                    catch(IOException e) { return e.getMessage(); }
                    return "unexpected_accept";
                });
                client.setSoTimeout(2000);client.getOutputStream().write(0);
                assertEquals(-1,client.getInputStream().read());
                assertEquals("encrypted_frames_required",result.get(3,TimeUnit.SECONDS));
            } finally { thread.shutdownNow(); }
        }
    }
    @Test public void excessiveHelloLengthIsRejectedBeforeAllocationOrHandshake() throws Exception {
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getLoopbackAddress());
            Socket client=new Socket("127.0.0.1",server.getLocalPort()); Socket accepted=server.accept()) {
            client.getOutputStream().write(new byte[]{1,127,-1});
            try { new NativeApiConnection(accepted,"r1-test","02:00:00:00:00:01").run(new byte[32]);fail(); }
            catch(IOException e) { assertEquals("frame_too_large",e.getMessage()); }
        }
    }
    @Test public void missingPskCannotEnableServer() throws Exception {
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getLoopbackAddress());
            Socket client=new Socket("127.0.0.1",server.getLocalPort()); Socket accepted=server.accept()) {
            try { new NativeApiConnection(accepted,"r1-test","02:00:00:00:00:01").run(null);fail(); }
            catch(IllegalArgumentException e) { assertEquals("noise_psk_required",e.getMessage()); }
        }
    }
    @Test public void productionPlaintextGetsOnlyEncryptionHintThenCloses() throws Exception {
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress());
             Socket client = new Socket("127.0.0.1", server.getLocalPort()); Socket accepted = server.accept()) {
            NativeApiConnection.Handler handler = new NativeApiConnection.Handler() {
                public void connected(NativeVoiceSession.Sender sender) { fail("plaintext_authenticated"); }
                public void message(int type, byte[] payload) { fail("plaintext_dispatched"); }
                public void tick() { }
                public void closed() { }
            };
            client.getOutputStream().write(0);
            try { new NativeApiConnection(accepted, "r1-test", "02:00:00:00:00:01", handler, true).run(new byte[32]); fail(); }
            catch (IOException expected) { assertEquals("encrypted_frames_required", expected.getMessage()); }
            client.setSoTimeout(1000);
            assertEquals(1, client.getInputStream().read());
            assertEquals(0, client.getInputStream().read());
            assertEquals(0, client.getInputStream().read());
            assertEquals(-1, client.getInputStream().read());
        }
    }
    @Test public void invalidIdentityFailsExplicitly() throws Exception {
        try(Socket socket=new Socket()) {
            try { new NativeApiConnection(socket,"r1\nwrong","02:00:00:00:00:01");fail(); }
            catch(IllegalArgumentException expected) { }
        }
    }
}
