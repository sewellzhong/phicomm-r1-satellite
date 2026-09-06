package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.util.ArrayList;
import java.util.List;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import dev.sewellzhong.r1probe.assist.CommandWindow;
import static org.junit.Assert.*;

public class NativeFollowupTest {
    private long now;
    private boolean drained;
    private final List<MessageLite> sent=new ArrayList<>();
    private final NativeVoiceSession session=new NativeVoiceSession((id,msg)->sent.add(msg),()->now,
        new NativeAudioCoordinatorTest.Player() { public boolean complete() { return drained; } });
    private void event(EsphomeApi.VoiceAssistantEvent event) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse, EsphomeApi.VoiceAssistantEventResponse
            .newBuilder().setEventType(event).build().toByteArray());
    }
    private void start() throws Exception {
        session.handle(MessageIds.SubscribeVoiceAssistantRequest,EsphomeApi.SubscribeVoiceAssistantRequest
            .newBuilder().setSubscribe(true).setFlags(4).build().toByteArray());
        session.startCommand();session.handle(MessageIds.VoiceAssistantResponse,new byte[0]);
        session.sendPcmFrame(new byte[640]);session.finishInput();
    }
    private void intent(boolean follow) throws Exception {
        session.handle(MessageIds.VoiceAssistantEventResponse,EsphomeApi.VoiceAssistantEventResponse.newBuilder()
            .setEventType(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_INTENT_END)
            .addData(EsphomeApi.VoiceAssistantEventData.newBuilder().setName("conversation_id").setValue("outer-conversation"))
            .addData(EsphomeApi.VoiceAssistantEventData.newBuilder().setName("continue_conversation").setValue(follow?"1":"0"))
            .build().toByteArray());
    }
    @Test public void ordinaryReplyReopensOnlyAfterDrainAndRunEnd() throws Exception {
        start();intent(false);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_START);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_START);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_TTS_STREAM_END);
        event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertFalse(session.shouldContinue());drained=true;session.tick();
        assertTrue(session.shouldContinue());
    }
    @Test public void followupSilenceClosesWindowWithoutNewRequestOrContextReset() throws Exception {
        start();intent(true);event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertTrue(session.shouldContinue());int requests=sent.size();
        CommandWindow window=new CommandWindow();CommandWindow.Decision decision=null;
        for(int i=0;i<300;i++) decision=window.accept(false);
        assertEquals(CommandWindow.Decision.TIMEOUT,decision);
        assertEquals(requests,sent.size());assertEquals("outer-conversation",session.conversationId());
        now=90000;session.startCommand();
        assertEquals("outer-conversation",((EsphomeApi.VoiceAssistantRequest)sent.get(sent.size()-1)).getConversationId());
    }
    @Test public void clientContextExpiresAfter900Seconds() throws Exception {
        start();intent(true);event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        now=900000;session.startCommand();
        assertEquals("",((EsphomeApi.VoiceAssistantRequest)sent.get(sent.size()-1)).getConversationId());
    }
    @Test public void silentEndAndErrorsDoNotContinue() throws Exception {
        start();intent(false);event(EsphomeApi.VoiceAssistantEvent.VOICE_ASSISTANT_RUN_END);
        assertFalse(session.shouldContinue());
        session.startCommand();
        session.handle(MessageIds.VoiceAssistantResponse,EsphomeApi.VoiceAssistantResponse.newBuilder().setError(true).build().toByteArray());
        assertFalse(session.shouldContinue());
    }
}
