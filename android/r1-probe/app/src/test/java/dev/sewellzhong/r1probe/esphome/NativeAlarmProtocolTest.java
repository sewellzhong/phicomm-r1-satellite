package dev.sewellzhong.r1probe.esphome;

import static org.junit.Assert.*;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;

public class NativeAlarmProtocolTest {
    static final class Clock implements NativeAlarmController.Clock {
        public long wallMillis() { return 1789171200000L; }
        public boolean wallTrusted() { return true; }
        public String timeZoneId() { return "Asia/Hong_Kong"; }
    }
    static final class Ringer implements NativeAlarmController.Ringer {
        public void start() { }
        public void stop() { }
        public boolean active() { return false; }
        public String failure() { return null; }
    }
    static final class Sent {
        final int type; final MessageLite value;
        Sent(int type, MessageLite value) { this.type = type; this.value = value; }
    }
    private final List<Sent> sent = new ArrayList<>();
    private final NativeAlarmController alarms = new NativeAlarmController(new NativeAlarmController.Store() {
        private String value;
        public String load() { return value; }
        public void save(String next) { value = next; }
    }, new Clock(), new Ringer());
    private final NativeAlarmProtocol protocol = new NativeAlarmProtocol(alarms);
    private final NativeVoiceSession.Sender sender = (type, value) -> sent.add(new Sent(type, value));

    @Test public void advertisesOneResponseOnlyStringService() throws Exception {
        protocol.list(sender);
        assertEquals(MessageIds.ListEntitiesServicesResponse, sent.get(0).type);
        EsphomeApi.ListEntitiesServicesResponse value = (EsphomeApi.ListEntitiesServicesResponse) sent.get(0).value;
        assertEquals("alarm_sync", value.getName());
        assertEquals(NativeAlarmProtocol.SERVICE_KEY, value.getKey());
        assertEquals(2, value.getSupportsResponseValue());
        assertEquals("request", value.getArgs(0).getName());
        assertEquals(3, value.getArgs(0).getTypeValue());
    }

    @Test public void putReturnsCorrelatedCompleteReadback() throws Exception {
        JSONObject request = new JSONObject().put("request_id", "0123456789abcdef0123456789abcdef")
                .put("operation", "put").put("id", "wake").put("name", "起床")
                .put("date", "2026-09-13").put("hour", 7).put("minute", 30)
                .put("expected_version", 0);
        assertTrue(send(41, request));
        EsphomeApi.ExecuteServiceResponse response = response();
        assertTrue(response.getSuccess()); assertEquals(41, response.getCallId());
        JSONObject state = new JSONObject(response.getResponseData().toStringUtf8());
        assertEquals(request.getString("request_id"), state.getString("request_id"));
        assertEquals(1, state.getLong("version")); assertEquals(1, state.getInt("alarm_count"));
        assertEquals(0, state.getInt("page_offset")); assertTrue(state.getBoolean("page_complete"));
        assertEquals("wake", state.getJSONArray("alarms").getJSONObject(0).getString("id"));
    }

    @Test public void staleWriteFailsWithoutClosingProtocolOrMutatingState() throws Exception {
        JSONObject first = new JSONObject().put("request_id", "0123456789abcdef0123456789abcdef")
                .put("operation", "put").put("id", "wake").put("date", "2026-09-13")
                .put("hour", 7).put("minute", 30).put("expected_version", 0);
        send(1, first); sent.clear();
        first.put("request_id", "fedcba9876543210fedcba9876543210").put("name", "旧写入")
                .put("expected_version", 0);
        assertTrue(send(2, first));
        assertFalse(response().getSuccess()); assertEquals("alarm_version_conflict", response().getErrorMessage());
        sent.clear();
        assertTrue(send(3, new JSONObject().put("request_id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                .put("operation", "status")));
        JSONObject state = new JSONObject(response().getResponseData().toStringUtf8());
        assertEquals(1, state.getLong("version"));
        assertEquals("", state.getJSONArray("alarms").getJSONObject(0).getString("name"));
    }

    @Test public void malformedRequestGetsFixedFailureAndUnknownKeyIsNotConsumed() throws Exception {
        assertTrue(send(7, new JSONObject().put("request_id", "bad").put("operation", "status")));
        assertEquals("alarm_request_id_invalid", response().getErrorMessage());
        EsphomeApi.ExecuteServiceRequest other = EsphomeApi.ExecuteServiceRequest.newBuilder()
                .setKey(123).setCallId(8).setReturnResponse(true).build();
        assertFalse(protocol.message(MessageIds.ExecuteServiceRequest, other.toByteArray(), sender));
    }

    @Test public void fullCapacityReadbackIsPagedAndVersionLocked() throws Exception {
        for (int i = 0; i < 9; i++) alarms.put("a" + i, "闹钟" + i, "", 7, i, 127, true, 10, -1);
        send(20, new JSONObject().put("request_id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                .put("operation", "status"));
        JSONObject first = new JSONObject(response().getResponseData().toStringUtf8());
        assertEquals(4, first.getJSONArray("alarms").length()); assertFalse(first.getBoolean("page_complete"));
        sent.clear();
        send(21, new JSONObject().put("request_id", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
                .put("operation", "status").put("expected_version", 9).put("page_offset", 8));
        JSONObject last = new JSONObject(response().getResponseData().toStringUtf8());
        assertEquals(1, last.getJSONArray("alarms").length()); assertTrue(last.getBoolean("page_complete"));
    }

    private boolean send(int callId, JSONObject request) throws Exception {
        EsphomeApi.ExecuteServiceRequest call = EsphomeApi.ExecuteServiceRequest.newBuilder()
                .setKey(NativeAlarmProtocol.SERVICE_KEY).setCallId(callId).setReturnResponse(true)
                .addArgs(EsphomeApi.ExecuteServiceArgument.newBuilder().setString(request.toString())).build();
        return protocol.message(MessageIds.ExecuteServiceRequest, call.toByteArray(), sender);
    }
    private EsphomeApi.ExecuteServiceResponse response() {
        Sent value = sent.get(sent.size() - 1);
        assertEquals(MessageIds.ExecuteServiceResponse, value.type);
        return (EsphomeApi.ExecuteServiceResponse) value.value;
    }
}
