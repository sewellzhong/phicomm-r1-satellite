package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.ByteString;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Noise-authenticated system diagnostics and response-before-action restart requests. */
public final class NativeSystemProtocol {
    static final int SERVICE_KEY = 0x52315359;
    private final NativeSystemManager system;

    public NativeSystemProtocol(NativeSystemManager system) {
        if (system == null) throw new IllegalArgumentException("system_manager_required");
        this.system = system;
    }
    public void list(NativeVoiceSession.Sender sender) throws IOException {
        sender.send(MessageIds.ListEntitiesServicesResponse,
                EsphomeApi.ListEntitiesServicesResponse.newBuilder()
                        .setName("system_management").setKey(SERVICE_KEY)
                        .addArgs(EsphomeApi.ListEntitiesServicesArgument.newBuilder()
                                .setName("request").setTypeValue(3))
                        .setSupportsResponseValue(2).build());
    }
    public boolean message(int type, byte[] payload, NativeVoiceSession.Sender sender) throws IOException {
        if (type != MessageIds.ExecuteServiceRequest) return false;
        EsphomeApi.ExecuteServiceRequest call = EsphomeApi.ExecuteServiceRequest.parseFrom(payload);
        if (call.getKey() != SERVICE_KEY) return false;
        String operation = null;
        boolean responded = false;
        try {
            if (call.getCallId() == 0 || !call.getReturnResponse() || call.getArgsCount() != 1)
                throw new IOException("system_response_required");
            String encoded = call.getArgs(0).getString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > 1024)
                throw new IOException("system_request_too_large");
            JSONObject request = new JSONObject(encoded);
            String requestId = request.getString("request_id");
            operation = request.getString("operation");
            JSONObject response = system.request(operation, requestId);
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(true)
                            .setResponseData(ByteString.copyFrom(response.toString(), StandardCharsets.UTF_8)).build());
            responded = true;
            if (!"status".equals(operation)) system.dispatch(operation);
        } catch (Exception error) {
            if (responded) {
                if (operation != null && !"status".equals(operation))
                    system.failed(operation, safeReason(error));
                return true;
            }
            sender.send(MessageIds.ExecuteServiceResponse,
                    EsphomeApi.ExecuteServiceResponse.newBuilder().setCallId(call.getCallId()).setSuccess(false)
                            .setErrorMessage(safeReason(error)).build());
            if (operation != null && !"status".equals(operation))
                system.failed(operation, safeReason(error));
        }
        return true;
    }
    private static String safeReason(Exception error) {
        String value = error.getMessage();
        return value != null && value.matches("system_[a-z0-9_]{1,64}")
                ? value : "system_request_invalid";
    }
}
