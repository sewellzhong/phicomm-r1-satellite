package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeAnnouncementControllerTest {
    static final class Player implements NativeVoiceSession.Playback {
        final List<String> urls = new ArrayList<>();
        boolean running, complete, stopped;
        String failure;
        public void start() { }
        public boolean startUrl(String url) throws IOException {
            if (!url.startsWith("https://")) throw new IOException("bad_url");
            urls.add(url); running = true; complete = false; return true;
        }
        public void audio(byte[] data) { }
        public void end() { }
        public boolean complete() { return complete; }
        public boolean terminated() { return !running; }
        public String failure() { return failure; }
        public void stop() { stopped = true; running = false; }
        void drain() { complete = true; running = false; }
    }
    private final Player player = new Player();
    private final List<MessageLite> sent = new ArrayList<>();
    private final NativeAnnouncementController controller = new NativeAnnouncementController(player);

    private byte[] request(String media, String preannounce, boolean conversation) {
        return EsphomeApi.VoiceAssistantAnnounceRequest.newBuilder().setMediaId(media)
                .setPreannounceMediaId(preannounce).setStartConversation(conversation)
                .build().toByteArray();
    }
    private boolean success(int index) {
        return ((EsphomeApi.VoiceAssistantAnnounceFinished) sent.get(index)).getSuccess();
    }

    @Test public void preannounceAndMediaDrainInOrderBeforeSuccess() throws Exception {
        controller.connected((id, message) -> { assertEquals(MessageIds.VoiceAssistantAnnounceFinished, id); sent.add(message); });
        assertTrue(controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("https://ha/media.wav", "https://ha/cue.wav", false), true));
        assertEquals(java.util.Arrays.asList("https://ha/cue.wav"), player.urls);
        assertTrue(controller.active()); assertTrue(sent.isEmpty());
        player.drain(); controller.tick();
        assertEquals(java.util.Arrays.asList("https://ha/cue.wav", "https://ha/media.wav"), player.urls);
        assertTrue(sent.isEmpty());
        player.drain(); controller.tick();
        assertFalse(controller.active()); assertEquals(1, sent.size()); assertTrue(success(0));
        assertEquals(1, controller.requests()); assertEquals(1, controller.completed());
        assertEquals(0, controller.failures());
    }

    @Test public void busyInvalidAndStartConversationFailClosed() throws Exception {
        controller.connected((id, message) -> sent.add(message));
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("https://ha/media.wav", "", false), false);
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("", "", false), true);
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("https://ha/media.wav", "", true), true);
        assertEquals(3, sent.size());
        assertFalse(success(0)); assertFalse(success(1)); assertFalse(success(2));
        assertTrue(player.urls.isEmpty());
        assertEquals(3, controller.requests()); assertEquals(3, controller.failures());
    }

    @Test public void sourceOrPlaybackFailureNeverReportsSuccess() throws Exception {
        controller.connected((id, message) -> sent.add(message));
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("file:///private.wav", "", false), true);
        assertEquals(1, sent.size()); assertFalse(success(0)); assertTrue(player.stopped);

        player.stopped = false;
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("https://ha/media.wav", "", false), true);
        player.failure = "playback_http_failed"; player.running = false;
        controller.tick();
        assertEquals(2, sent.size()); assertFalse(success(1));
        assertEquals(2, controller.failures());
    }

    @Test public void unrelatedMessagesAreNotConsumedAndCloseStopsWithoutReply() throws Exception {
        controller.connected((id, message) -> sent.add(message));
        assertFalse(controller.message(MessageIds.PingRequest, new byte[0], true));
        controller.message(MessageIds.VoiceAssistantAnnounceRequest,
                request("https://ha/media.wav", "", false), true);
        controller.closed();
        assertTrue(player.stopped); assertFalse(controller.active()); assertTrue(sent.isEmpty());
    }
}
