package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.ByteString;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Noise-authenticated, request-correlated access to the local DND policy. */
public final class NativeDndProtocol {
    static final int SERVICE_KEY = 0x5231444e;
    private final NativeDndController dnd;

    public NativeDndProtocol(NativeDndController dnd) {
        if (dnd == null) throw new IllegalArgumentException("dnd_controller_required");
        this.dnd = dnd;
    }

    public void list(NativeVoiceSession.Sender sender) throws IOException {
        sender.send(MessageIds.ListEntitiesServicesResponse,
                EsphomeApi.ListEntitiesServicesResponse.newBuilder()
                        .setName("do_not_disturb").setKey(SERVICE_KEY)
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
                throw new IOException("dnd_response_required");
            String encoded = call.getArgs(0).getString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > 2048)
                throw new IOException("dnd_request_too_large");
            JSONObject request = new JSONObject(encoded);
            String requestId = request.getString("request_id");
            if (!requestId.matches("[a-f0-9]{32}")) throw new IOException("dnd_request_id_invalid");
            String operation = request.getString("operation");
            if ("set".equals(operation)) {
                dnd.configure(request.getBoolean("manual"), request.getBoolean("schedule_enabled"),
                        request.getInt("start_hour"), request.getInt("start_minute"),
                        request.getInt("end_hour"), request.getInt("end_minute"),
                        request.getBoolean("alarms_allowed"), request.optLong("expected_version", -1));
            } else if (!"status".equals(operation)) throw new IOException("dnd_operation_invalid");
            JSONObject response = dnd.snapshot().put("request_id", requestId).put("operation", operation);
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

    private static String safeReason(Exception error) {
        String value = error.getMessage();
        return value != null && value.matches("dnd_[a-z0-9_]{1,64}") ? value : "dnd_request_invalid";
    }
}
