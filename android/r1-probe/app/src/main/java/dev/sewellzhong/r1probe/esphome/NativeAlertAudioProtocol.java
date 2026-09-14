package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.ByteString;
import dev.sewellzhong.r1probe.NativeAlertAudioStore;
import dev.sewellzhong.r1probe.NativeSettings;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Bounded authenticated chunk transport for offline alarm music and timer prompts. */
public final class NativeAlertAudioProtocol {
    static final int SERVICE_KEY = 0x52314155;
    private final NativeAlertAudioStore store;
    private final NativeSettings settings;
    private final NativeAlarmController alarms;

    public NativeAlertAudioProtocol(NativeAlertAudioStore store, NativeSettings settings,
            NativeAlarmController alarms) {
        if (store == null || settings == null) throw new IllegalArgumentException("alert_audio_dependencies_required");
        this.store = store; this.settings = settings; this.alarms = alarms;
    }
    public void list(NativeVoiceSession.Sender sender) throws IOException {
        sender.send(MessageIds.ListEntitiesServicesResponse,
                EsphomeApi.ListEntitiesServicesResponse.newBuilder()
                        .setName("alert_audio").setKey(SERVICE_KEY)
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
                throw new IOException("alert_audio_response_required");
            String encoded = call.getArgs(0).getString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > 40 * 1024)
                throw new IOException("alert_audio_request_too_large");
            JSONObject request = new JSONObject(encoded);
            String requestId = request.getString("request_id");
            if (!requestId.matches("[a-f0-9]{32}")) throw new IOException("alert_audio_request_id_invalid");
            JSONObject response = store.operation(request, settings, alarms)
                    .put("request_id", requestId).put("operation", request.getString("operation"));
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(true)
                            .setResponseData(ByteString.copyFrom(response.toString(), StandardCharsets.UTF_8)).build());
        } catch (Exception error) {
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(false)
                            .setErrorMessage(safe(error)).build());
        }
        return true;
    }
    private static String safe(Exception error) {
        String value = error.getMessage();
        return value != null && value.matches("alert_audio_[a-z0-9_]{1,64}")
                ? value : "alert_audio_request_invalid";
    }
}
