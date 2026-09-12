package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import com.google.protobuf.ByteString;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import static org.junit.Assert.*;

public class NativeReplySessionTest {
    private long now;
    private final List<MessageLite> sent = new ArrayList<>();
    private boolean drained, stopped;
    private int ends;
    private String failure;
    private String url;
    private final NativeVoiceSession session = new NativeVoiceSession((id,msg)->sent.add(msg),()->now,
        new NativeAudioCoordinatorTest.Player() {
            public boolean complete() { return drained; }
            public String failure() { return failure; }
            public void stop() { stopped=true; }
            public void end() { ends++; }
            public boolean startUrl(String value) { url=value; return true; }
        });
    private void event(EsphomeApi.VoiceAssistantEvent event) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(event).build().toByteArray());
    }
    private void event(EsphomeApi.VoiceAssistantEvent event, String name, String value) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
                .newBuilder().setEventType(event).addData(EsphomeApi.VoiceAssistantEventData
                        .newBuilder().setName(name).setValue(value)).build().toByteArray());
    }
    private void start() throws Exception {
        session.handle(MessageIds.SubscribeVoiceAssistantRequest, EsphomeApi.SubscribeVoiceAssistantRequest
                .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        session.startCommand(); session.handle(MessageIds.VoiceAssistantResponse,new byte[0]);
        session.sendPcmFrame(new byte[640]); session.finishInput();
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_START);
    }
    private long acknowledgements() { return sent.stream().filter(m -> m instanceof EsphomeApi.VoiceAssistantAnnounceFinished).count(); }
    @Test public void runEndBeforeStreamDoesNotResumeOrAcknowledgeEarly() throws Exception {
        start(); event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(NativeVoiceSession.State.PROCESSING,session.state());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_END);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_END);
        assertEquals(1,ends); assertEquals(0,acknowledgements());
        assertEquals(NativeVoiceSession.State.PLAYING,session.state());
        drained=true; session.tick(); session.tick();
        assertEquals(1,acknowledgements()); assertEquals(NativeVoiceSession.State.IDLE,session.state());
    }
    @Test public void authenticatedUrlStartsAtIntentProgressBeforeRunEnd() throws Exception {
        start();
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_START,
                "url", "http://ha.local/api/tts_proxy/fixed?authSig=test");
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_INTENT_PROGRESS,
                "tts_start_streaming", "1");
        assertEquals("http://ha.local/api/tts_proxy/fixed?authSig=test", url);
        assertEquals(NativeVoiceSession.State.PLAYING, session.state());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(0, acknowledgements());
        drained=true; session.tick();
        assertEquals(1, acknowledgements());
        assertEquals(NativeVoiceSession.State.IDLE, session.state());
    }
    @Test public void drainedBeforeRunEndWaitsAndSendsOnlyOneAcknowledgement() throws Exception {
        start(); event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_END);
        drained=true; session.tick();
        assertEquals(NativeVoiceSession.State.PLAYING,session.state());
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertEquals(1,acknowledgements()); assertEquals(NativeVoiceSession.State.IDLE,session.state());
    }
    @Test public void playbackFailureAfterRunEndIsNotSuccess() throws Exception {
        start(); event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        failure="sink_error"; session.tick();
        assertTrue(stopped); assertEquals(0,acknowledgements());
        assertEquals(NativeVoiceSession.Outcome.FAILED,session.outcome());
    }
    @Test public void replyDeadlineIsNotExtendedByRepeatedEvents() throws Exception {
        start(); now=299000; event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_END);
        now=300000; session.tick();
        assertTrue(stopped); assertEquals(NativeVoiceSession.Outcome.FAILED,session.outcome());
    }
    @Test public void unsolicitedAudioClosesSession() throws Exception {
        start();
        try { session.handle(MessageIds.VoiceAssistantAudio, EsphomeApi.VoiceAssistantAudio
                .newBuilder().setData(ByteString.copyFrom(new byte[2])).build().toByteArray()); fail(); }
        catch(IOException expected) { }
        assertEquals(NativeVoiceSession.State.CLOSED,session.state()); assertTrue(stopped);
    }
    @Test public void closeDuringPlaybackStopsSinkWithoutSuccessReport() throws Exception {
        start(); event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START);
        session.close(); drained=true; session.tick();
        assertTrue(stopped); assertEquals(0,acknowledgements());
    }
    @Test public void lateDrainCannotOverrideAbsoluteTimeout() throws Exception {
        start(); event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_END);
        now=300000; drained=true; session.tick();
        assertEquals(0,acknowledgements());
        assertEquals(NativeVoiceSession.Outcome.FAILED,session.outcome());
    }

}
