package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import org.junit.Test;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import static org.junit.Assert.*;

public final class NativeVoiceSessionTest {
    private long now;
    private final List<MessageLite> sent = new ArrayList<>();
    private final NativeVoiceSession session = new NativeVoiceSession((id, msg) -> sent.add(msg), () -> now);
    private void subscribe(boolean audio) throws Exception {
        session.handle(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(audio ? 1 : 0).build().toByteArray());
    }
    private void start() throws Exception {
        subscribe(true); session.startCommand();
        session.handle(MessageIds.VoiceAssistantResponse, new byte[0]);
    }
    private void event(EsphomeApi.VoiceAssistantEvent event) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(event).build().toByteArray());
    }
    private void blockedFrame() throws Exception {
        try { session.sendPcmFrame(new byte[640]); fail(); }
        catch (IllegalStateException expected) { }
    }
    @Test public void subscriptionDoesNotStartEmptyCommand() throws Exception {
        subscribe(true); now = 60000; session.tick();
        assertEquals(NativeVoiceSession.State.IDLE, session.state()); assertTrue(sent.isEmpty());
    }
    @Test public void udpSubscriptionCannotStart() throws Exception {
        subscribe(false);
        try { session.startCommand(); fail(); } catch (IllegalStateException expected) { }
        assertTrue(sent.isEmpty());
    }
    @Test public void pinnedOfficialClientSubscriptionBitIsAccepted() throws Exception {
        session.handle(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        session.startCommand();
        assertEquals(NativeVoiceSession.State.STARTING, session.state());
    }
    @Test public void closedSessionCannotBeResubscribed() throws Exception {
        session.close();
        try { subscribe(true); fail(); } catch(IOException expected) { }
        assertEquals(NativeVoiceSession.State.CLOSED,session.state());
    }
    @Test public void acceptedRunTransportsExactPcmAndNormalEnd() throws Exception {
        subscribe(true); session.startCommand(); blockedFrame();
        session.handle(MessageIds.VoiceAssistantResponse, new byte[0]);
        byte[] pcm = new byte[640]; pcm[3] = 24;
        session.sendPcmFrame(pcm); pcm[3] = 0;
        session.finishInput(); blockedFrame();
        assertArrayEquals(new byte[]{0,0,0,24}, java.util.Arrays.copyOf(
                ((EsphomeApi.VoiceAssistantAudio)sent.get(1)).getData().toByteArray(),4));
        assertTrue(((EsphomeApi.VoiceAssistantAudio)sent.get(2)).getEnd());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(NativeVoiceSession.State.IDLE,session.state());
    }
    @Test public void zeroFramesAbortInsteadOfNormalEnd() throws Exception {
        start(); session.finishInput();
        assertFalse(((EsphomeApi.VoiceAssistantRequest)sent.get(1)).getStart());
        assertEquals(NativeVoiceSession.State.CANCELLING, session.state());
    }
    @Test public void wrongFrameSizeIsRejected() throws Exception {
        start();
        try { session.sendPcmFrame(new byte[639]); fail(); } catch (IllegalArgumentException expected) { }
        assertEquals(1,sent.size());
    }
    @Test public void cancellationWaitsForOldRunEndBeforeRestart() throws Exception {
        start(); session.cancel();
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_ERROR);
        assertEquals(NativeVoiceSession.Outcome.CANCELLED, session.outcome());
        try { session.startCommand(); fail(); } catch (IllegalStateException expected) { }
        session.handle(MessageIds.VoiceAssistantResponse,new byte[0]); blockedFrame();
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        session.startCommand();
        assertEquals(NativeVoiceSession.State.STARTING,session.state());
    }
    @Test public void cancellationFromStartingSendsOneStopAndIsIdempotent() throws Exception {
        subscribe(true); session.startCommand();
        assertTrue(session.cancel()); assertFalse(session.cancel());
        assertEquals(2, sent.size());
        assertFalse(((EsphomeApi.VoiceAssistantRequest)sent.get(1)).getStart());
        assertEquals(NativeVoiceSession.Outcome.CANCELLED, session.outcome());
    }
    @Test public void cancellationFromProcessingStopsTheAcceptedRun() throws Exception {
        start(); session.sendPcmFrame(new byte[640]); session.finishInput();
        assertTrue(session.cancel());
        assertEquals(NativeVoiceSession.State.CANCELLING, session.state());
        assertFalse(((EsphomeApi.VoiceAssistantRequest)sent.get(sent.size()-1)).getStart());
    }
    @Test public void missingStartResponseCancelsThenCloses() throws Exception {
        subscribe(true); session.startCommand(); now = 10000; session.tick();
        assertEquals(NativeVoiceSession.State.CANCELLING, session.state());
        now = 15000;
        try { session.tick(); fail(); } catch (IOException expected) { }
        assertEquals(NativeVoiceSession.State.CLOSED,session.state());
    }
    @Test public void thirtySecondUploadIsNotCutAtOldTwentySecondLimit() throws Exception {
        start();
        for (int i=0; i<1500; i++) session.sendPcmFrame(new byte[640]);
        assertEquals(NativeVoiceSession.State.STREAMING, session.state());
        session.finishInput();
        assertEquals(NativeVoiceSession.State.PROCESSING, session.state());
        assertEquals(1501, sent.stream().filter(m -> m instanceof EsphomeApi.VoiceAssistantAudio).count());
    }
    @Test public void streamAndProcessingHaveAbsoluteDeadlines() throws Exception {
        start(); now = 129999; session.sendPcmFrame(new byte[640]); now = 130000; session.tick();
        assertEquals(NativeVoiceSession.State.CANCELLING,session.state());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        session.startCommand(); session.handle(MessageIds.VoiceAssistantResponse,new byte[0]);
        session.sendPcmFrame(new byte[640]); session.finishInput(); now = 190000; session.tick();
        assertEquals(NativeVoiceSession.State.CANCELLING,session.state());
    }
    @Test public void remoteVadEndStopsUploadOnce() throws Exception {
        start(); session.sendPcmFrame(new byte[640]);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_STT_VAD_END);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_STT_END);
        assertEquals(3,sent.size()); blockedFrame();
    }
    @Test public void unsupportedPortCloses() throws Exception {
        subscribe(true); session.startCommand();
        try { session.handle(MessageIds.VoiceAssistantResponse, EsphomeApi.VoiceAssistantResponse
                .newBuilder().setPort(1234).build().toByteArray()); fail(); } catch(IOException expected) { }
        assertEquals(NativeVoiceSession.State.CLOSED,session.state());
    }
    @Test public void unsubscribeActiveRunClosesConnection() throws Exception {
        start();
        try { session.handle(MessageIds.SubscribeVoiceAssistantRequest,new byte[0]); fail(); }
        catch(IOException expected) { }
        blockedFrame(); assertEquals(NativeVoiceSession.State.CLOSED,session.state());
    }
    @Test public void sendFailureAndDisconnectBlockFurtherUpload() throws Exception {
        NativeVoiceSession broken = new NativeVoiceSession((id,msg)-> { throw new IOException("offline"); }, ()->0);
        broken.handle(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(1).build().toByteArray());
        try { broken.startCommand(); fail(); } catch(IOException expected) { }
        assertEquals(NativeVoiceSession.State.CLOSED,broken.state());
        start(); session.close(); blockedFrame();
    }
    private void errorCode(String code) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_ERROR)
                .addData(EsphomeApi.VoiceAssistantEventData.newBuilder().setName("code").setValue(code))
                .build().toByteArray());
    }
    @Test public void emptySttIsQuietOutcomeAndNextCommandResetsIt() throws Exception {
        start(); errorCode("stt-no-text-recognized");
        assertEquals(NativeVoiceSession.Outcome.NO_INPUT, session.outcome());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(NativeVoiceSession.State.IDLE, session.state());
        assertEquals(NativeVoiceSession.Outcome.NO_INPUT, session.outcome());
        assertEquals(1,sent.size());
        session.startCommand();
        assertEquals(NativeVoiceSession.Outcome.NONE, session.outcome());
    }
    @Test public void serviceErrorIsNotHiddenByLaterEmptyResult() throws Exception {
        start(); errorCode("stt-stream-failed"); errorCode("stt-no-text-recognized");
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(NativeVoiceSession.Outcome.FAILED, session.outcome());
    }
    @Test public void emptyResultWithoutRunEndStillFailsDeadline() throws Exception {
        start(); errorCode("stt-no-text-recognized"); now=5000;
        try { session.tick(); fail(); } catch(IOException expected) { }
        assertEquals(NativeVoiceSession.Outcome.FAILED, session.outcome());
    }
    @Test public void disconnectBeforeTerminalEventIsFailure() throws Exception {
        start(); errorCode("stt-no-text-recognized"); session.close();
        assertEquals(NativeVoiceSession.Outcome.FAILED, session.outcome());
    }

}
