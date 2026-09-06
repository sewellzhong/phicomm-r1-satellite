package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import static org.junit.Assert.*;

public class NativeAudioCoordinatorTest {
    static class Player implements NativeVoiceSession.Playback {
        public void start() { }
        public void audio(byte[] data) { }
        public void end() { }
        public boolean complete() { return false; }
        public String failure() { return null; }
        public void stop() { }
    }
    private final List<MessageLite> sent = new ArrayList<>();
    private final NativeAudioCoordinator coordinator = new NativeAudioCoordinator(new Player(), () -> 0);
    private void subscribe() throws Exception {
        coordinator.connected((id,msg) -> sent.add(msg));
        coordinator.message(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
    }
    @Test public void idleAndNoOpeningSpeechSendNothing() throws Exception {
        subscribe();
        dev.sewellzhong.r1probe.assist.CommandWindow window = new dev.sewellzhong.r1probe.assist.CommandWindow();
        for (int i = 0; i < 300; i++) { window.accept(false); coordinator.tick(); }
        assertTrue(coordinator.ready()); assertTrue(sent.isEmpty());
    }
    @Test public void captureQueuePreservesOnsetAndEofUntilAcceptance() throws Exception {
        subscribe(); byte[] onset = new byte[640]; onset[2] = 17;
        coordinator.begin(onset); onset[2] = 0;
        coordinator.audio(new byte[640]); coordinator.endInput(); coordinator.tick();
        assertEquals(1,sent.size());
        coordinator.message(MessageIds.VoiceAssistantResponse,new byte[0]);
        assertEquals(4,sent.size());
        assertEquals(17, ((EsphomeApi.VoiceAssistantAudio)sent.get(1)).getData().byteAt(2));
        assertTrue(((EsphomeApi.VoiceAssistantAudio)sent.get(3)).getEnd());
    }
    @Test public void queueOverflowIsFatalAndCannotReplay() throws Exception {
        subscribe(); coordinator.begin(new byte[160000]);
        try { coordinator.audio(new byte[640]); fail(); } catch(IOException expected) { }
        try { coordinator.tick(); fail(); } catch(IOException expected) { }
        assertTrue(sent.isEmpty()); assertFalse(coordinator.ready());
        coordinator.closed(); assertFalse(coordinator.ready());
    }
    @Test public void disconnectClearsUnsentCommand() throws Exception {
        subscribe(); coordinator.begin(new byte[640]); coordinator.closed(); coordinator.tick();
        assertTrue(sent.isEmpty()); assertFalse(coordinator.ready());
    }
}
