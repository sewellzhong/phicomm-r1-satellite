package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.ByteString;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

/** Noise-authenticated, request-correlated HA access to the complete local alarm store. */
public final class NativeAlarmProtocol {
    static final int SERVICE_KEY = 0x5231414c;
    private static final int PAGE_SIZE = 4;
    private final NativeAlarmController alarms;

    public NativeAlarmProtocol(NativeAlarmController alarms) {
        if (alarms == null) throw new IllegalArgumentException("alarm_controller_required");
        this.alarms = alarms;
    }

    public void list(NativeVoiceSession.Sender sender) throws IOException {
        sender.send(MessageIds.ListEntitiesServicesResponse,
                EsphomeApi.ListEntitiesServicesResponse.newBuilder()
                        .setName("alarm_sync").setKey(SERVICE_KEY)
                        .addArgs(EsphomeApi.ListEntitiesServicesArgument.newBuilder()
                                .setName("request").setTypeValue(3))
                        .setSupportsResponseValue(2).build());
    }

    public boolean message(int type, byte[] payload, NativeVoiceSession.Sender sender) throws IOException {
        if (type != MessageIds.ExecuteServiceRequest) return false;
        EsphomeApi.ExecuteServiceRequest call = EsphomeApi.ExecuteServiceRequest.parseFrom(payload);
        if (call.getKey() != SERVICE_KEY) return false;
        try {
            if (call.getCallId() == 0 || !call.getReturnResponse() || call.getArgsCount() != 1)
                throw new IOException("alarm_response_required");
            String encoded = call.getArgs(0).getString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > 4096)
                throw new IOException("alarm_request_too_large");
            JSONObject request = new JSONObject(encoded);
            String requestId = checkedRequestId(request.getString("request_id"));
            String operation = request.getString("operation");
            long expected = request.optLong("expected_version", -1);
            switch (operation) {
                case "status": break;
                case "put":
                    alarms.put(request.getString("id"), request.optString("name", ""),
                            request.optString("date", ""), request.getInt("hour"),
                            request.getInt("minute"), request.optInt("weekdays", 0),
                            request.optBoolean("enabled", true), request.optInt("snooze_minutes", 10),
                            request.optString("ringtone", "classic"),
                            request.optInt("volume_percent", 100), expected);
                    break;
                case "delete": alarms.delete(request.getString("id"), expected); break;
                case "enable": alarms.enable(request.getString("id"), request.getBoolean("enabled"), expected); break;
                case "stop": alarms.stopRinging(request.optString("id", "")); break;
                case "snooze": alarms.snooze(request.optString("id", ""), request.has("minutes")
                        ? Integer.valueOf(request.getInt("minutes")) : null); break;
                default: throw new IOException("alarm_operation_invalid");
            }
            JSONObject response = alarms.snapshot();
            if ("status".equals(operation) && expected >= 0 && response.getLong("version") != expected)
                throw new IOException("alarm_version_conflict");
            JSONArray all = response.getJSONArray("alarms");
            int offset = request.optInt("page_offset", 0);
            if (offset < 0 || offset > all.length()) throw new IOException("alarm_page_invalid");
            JSONArray page = new JSONArray();
            int end = Math.min(all.length(), offset + PAGE_SIZE);
            for (int i = offset; i < end; i++) page.put(all.getJSONObject(i));
            response.put("alarms", page).put("page_offset", offset).put("page_complete", end == all.length())
                    .put("request_id", requestId).put("operation", operation);
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(true)
                            .setResponseData(ByteString.copyFrom(response.toString(), StandardCharsets.UTF_8)).build());
        } catch (Exception error) {
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(false)
                            .setErrorMessage(safeReason(error)).build());
        }
        return true;
    }

    private static String checkedRequestId(String value) throws IOException {
        if (value == null || !value.matches("[a-f0-9]{32}")) throw new IOException("alarm_request_id_invalid");
        return value;
    }

    private static String safeReason(Exception error) {
        String value = error.getMessage();
        return value != null && value.matches("alarm_[a-z0-9_]{1,64}") ? value : "alarm_request_invalid";
    }
}
