package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
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
        public boolean terminated() { return true; }
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
    @Test public void cancellationBeforeOwnerTickNeverStartsOrUploadsQueuedRun() throws Exception {
        subscribe(); coordinator.begin(new byte[640]);
        assertTrue(coordinator.requestCancel(NativeAudioCoordinator.CancelReason.USER_STOP));
        coordinator.tick();
        assertTrue(sent.isEmpty());
        assertEquals(NativeVoiceSession.Outcome.CANCELLED, coordinator.outcome());
        assertTrue(coordinator.ready());
    }
    @Test public void cancelStopsLocallyBeforeSingleRemoteCancelAndClearsQueuedInput() throws Exception {
        class TrackingPlayer extends Player {
            boolean stopCalled;
            @Override public void stop() { stopCalled = true; }
        }
        TrackingPlayer player = new TrackingPlayer();
        List<MessageLite> messages = new ArrayList<>();
        List<String> events = new ArrayList<>();
        NativeAudioCoordinator owner = new NativeAudioCoordinator(player, () -> 0, events::add);
        owner.connected((id,msg) -> messages.add(msg));
        owner.message(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        owner.begin(new byte[640]); owner.tick();
        assertTrue(owner.requestCancel(NativeAudioCoordinator.CancelReason.USER_STOP));
        assertTrue(player.stopCalled);
        owner.audio(new byte[640]); // Input after local cancellation is discarded.
        assertFalse(owner.requestCancel(NativeAudioCoordinator.CancelReason.NEW_WAKE));
        owner.tick();
        owner.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse.newBuilder()
                .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END).build().toByteArray());
        owner.tick();
        assertEquals(2, messages.size());
        assertTrue(((EsphomeApi.VoiceAssistantRequest)messages.get(0)).getStart());
        assertFalse(((EsphomeApi.VoiceAssistantRequest)messages.get(1)).getStart());
        assertTrue(events.stream().anyMatch(value -> value.contains("event=cancel_requested,reason=user_stop")));
        assertTrue(events.stream().anyMatch(value -> value.contains("event=remote_cancel_sent")));
    }
    @Test public void cancelledRunIgnoresLateEventsAndWaitsForPlaybackRelease() throws Exception {
        class BlockingPlayer extends Player {
            boolean released = true;
            @Override public void start() { released = false; }
            @Override public boolean terminated() { return released; }
        }
        BlockingPlayer player = new BlockingPlayer();
        List<MessageLite> messages = new ArrayList<>();
        NativeAudioCoordinator owner = new NativeAudioCoordinator(player, () -> 0);
        owner.connected((id,msg) -> messages.add(msg));
        owner.message(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        owner.begin(new byte[640]); owner.endInput(); owner.tick();
        owner.message(MessageIds.VoiceAssistantResponse, new byte[0]);
        owner.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse.newBuilder()
                .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START).build().toByteArray());
        assertFalse(player.terminated());
        assertTrue(owner.requestCancel(NativeAudioCoordinator.CancelReason.NEW_WAKE)); owner.tick();
        owner.message(MessageIds.VoiceAssistantAudio, EsphomeApi.VoiceAssistantAudio.newBuilder()
                .setData(com.google.protobuf.ByteString.copyFrom(new byte[640])).build().toByteArray());
        owner.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse.newBuilder()
                .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_ERROR).build().toByteArray());
        owner.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse.newBuilder()
                .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END).build().toByteArray());
        assertEquals(NativeVoiceSession.Outcome.CANCELLED, owner.outcome());
        assertFalse(owner.ready());
        assertEquals(NativeAudioCoordinator.RestartReason.NONE, owner.takeRestart());
        player.released = true; owner.tick();
        assertTrue(owner.ready());
        assertEquals(NativeAudioCoordinator.RestartReason.NEW_WAKE, owner.takeRestart());
        assertEquals(NativeAudioCoordinator.RestartReason.NONE, owner.takeRestart());
    }

    @Test public void ordinaryCancellationNeverRequestsWakeRestart() throws Exception {
        subscribe(); coordinator.begin(new byte[640]); coordinator.tick();
        assertTrue(coordinator.requestCancel(NativeAudioCoordinator.CancelReason.USER_STOP));
        coordinator.tick();
        coordinator.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END)
                .build().toByteArray());
        coordinator.tick();
        assertTrue(coordinator.ready());
        assertEquals(NativeAudioCoordinator.RestartReason.NONE, coordinator.takeRestart());
    }
    @Test public void directSpeechRestartsOnlyAfterCancelledPlayerReleases() throws Exception {
        subscribe(); coordinator.begin(new byte[640]); coordinator.tick();
        assertTrue(coordinator.requestCancel(NativeAudioCoordinator.CancelReason.DIRECT_SPEECH));
        assertEquals(NativeAudioCoordinator.RestartReason.NONE, coordinator.takeRestart());
        coordinator.tick();
        coordinator.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END)
                .build().toByteArray());
        coordinator.tick();
        assertEquals(NativeAudioCoordinator.RestartReason.DIRECT_SPEECH, coordinator.takeRestart());
        assertEquals(NativeAudioCoordinator.RestartReason.NONE, coordinator.takeRestart());
    }
    @Test public void concurrentCancellationHasOneWinnerAndOneOwnerDispatch() throws Exception {
        AtomicInteger localStops = new AtomicInteger();
        Player player = new Player() { @Override public void stop() { localStops.incrementAndGet(); } };
        List<MessageLite> messages = new ArrayList<>();
        List<String> events = new ArrayList<>();
        NativeAudioCoordinator owner = new NativeAudioCoordinator(player, () -> 0, events::add);
        owner.connected((id, msg) -> messages.add(msg));
        owner.message(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        owner.begin(new byte[640]); owner.tick();
        int callers = 12;
        CountDownLatch ready = new CountDownLatch(callers), go = new CountDownLatch(1);
        AtomicInteger accepted = new AtomicInteger();
        ExecutorService pool = Executors.newFixedThreadPool(callers);
        try {
            for (int i = 0; i < callers; i++) pool.submit(() -> {
                ready.countDown();
                try { go.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                if (owner.requestCancel(NativeAudioCoordinator.CancelReason.USER_STOP))
                    accepted.incrementAndGet();
            });
            assertTrue(ready.await(2, TimeUnit.SECONDS)); go.countDown();
        } finally {
            pool.shutdown(); assertTrue(pool.awaitTermination(2, TimeUnit.SECONDS));
        }
        owner.tick();
        owner.message(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse.newBuilder()
                .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END).build().toByteArray());
        owner.tick();
        assertEquals(1, accepted.get());
        assertEquals(1, localStops.get());
        assertEquals(2, messages.size());
        assertFalse(((EsphomeApi.VoiceAssistantRequest) messages.get(1)).getStart());
        assertEquals(1, events.stream().filter(value -> value.contains("event=remote_cancel_sent")).count());
        assertEquals(1, events.stream().filter(value -> value.contains("event=cancel_complete")).count());
    }
}
