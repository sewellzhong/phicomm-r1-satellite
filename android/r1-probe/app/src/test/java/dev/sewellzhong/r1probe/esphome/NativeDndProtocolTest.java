package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeDndProtocolTest {
    private static final class Store implements NativeDndController.Store {
        String value = "";
        public String load() { return value; }
        public void save(String value) { this.value = value; }
    }
    private static final class Clock implements NativeDndController.Clock {
        public long wallMillis() { return 1789142400000L; }
        public boolean wallTrusted() { return true; }
        public String timeZoneId() { return "Asia/Hong_Kong"; }
    }
    private static final class Sent { final int type; final MessageLite value;
        Sent(int type, MessageLite value) { this.type=type; this.value=value; } }
    private static final class Sender implements NativeVoiceSession.Sender {
        final List<Sent> sent = new ArrayList<>();
        public void send(int type, MessageLite value) { sent.add(new Sent(type,value)); }
    }

    @Test public void advertisesGeneratedAuthenticatedServiceAndCorrelatesResponse() throws Exception {
        NativeDndProtocol protocol = new NativeDndProtocol(new NativeDndController(new Store(), new Clock()));
        Sender sender = new Sender(); protocol.list(sender);
        EsphomeApi.ListEntitiesServicesResponse listed =
                (EsphomeApi.ListEntitiesServicesResponse)sender.sent.get(0).value;
        assertEquals("do_not_disturb", listed.getName());
        assertEquals(NativeDndProtocol.SERVICE_KEY, listed.getKey());
        JSONObject request = new JSONObject().put("request_id", "aabbccddeeff00112233445566778899")
                .put("operation", "set").put("manual", true).put("schedule_enabled", true)
                .put("start_hour", 22).put("start_minute", 30).put("end_hour", 7)
                .put("end_minute", 15).put("alarms_allowed", false).put("expected_version", 0);
        EsphomeApi.ExecuteServiceRequest call = EsphomeApi.ExecuteServiceRequest.newBuilder()
                .setKey(NativeDndProtocol.SERVICE_KEY).setCallId(9).setReturnResponse(true)
                .addArgs(EsphomeApi.ExecuteServiceArgument.newBuilder().setString(request.toString())).build();
        assertTrue(protocol.message(MessageIds.ExecuteServiceRequest, call.toByteArray(), sender));
        EsphomeApi.ExecuteServiceResponse response =
                (EsphomeApi.ExecuteServiceResponse)sender.sent.get(1).value;
        assertTrue(response.getSuccess()); assertEquals(9, response.getCallId());
        JSONObject state = new JSONObject(response.getResponseData().toStringUtf8());
        assertEquals(request.getString("request_id"), state.getString("request_id"));
        assertTrue(state.getBoolean("active")); assertFalse(state.getBoolean("alarms_allowed"));
    }

    @Test public void malformedOrStaleRequestFailsWithoutLeakingException() throws Exception {
        NativeDndProtocol protocol = new NativeDndProtocol(new NativeDndController(new Store(), new Clock()));
        Sender sender = new Sender();
        EsphomeApi.ExecuteServiceRequest call = EsphomeApi.ExecuteServiceRequest.newBuilder()
                .setKey(NativeDndProtocol.SERVICE_KEY).setCallId(3).setReturnResponse(true)
                .addArgs(EsphomeApi.ExecuteServiceArgument.newBuilder().setString("{\"request_id\":\"bad\"}"))
                .build();
        assertTrue(protocol.message(MessageIds.ExecuteServiceRequest, call.toByteArray(), sender));
        EsphomeApi.ExecuteServiceResponse response = (EsphomeApi.ExecuteServiceResponse)sender.sent.get(0).value;
        assertFalse(response.getSuccess()); assertEquals("dnd_request_id_invalid", response.getErrorMessage());
    }
}
