package dev.sewellzhong.r1probe.esphome;

import static org.junit.Assert.*;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.junit.Test;

public final class NativeSystemProtocolTest {
    static final class Store implements NativeSystemManager.Store {
        String value = "";
        public String load() { return value; }
        public void save(String value) { this.value = value; }
    }
    static final class Actions implements NativeSystemManager.Actions {
        String operation; NativeSystemManager.Failure failure;
        public void dispatch(String operation, NativeSystemManager.Failure failure) {
            this.operation = operation; this.failure = failure;
        }
    }
    static final class Sent { int type; MessageLite value;
        Sent(int type, MessageLite value) { this.type=type; this.value=value; } }
    static final class Sender implements NativeVoiceSession.Sender {
        List<Sent> sent = new ArrayList<>();
        public void send(int type, MessageLite value) { sent.add(new Sent(type,value)); }
    }
    private static NativeSystemManager manager(Store store, Actions actions, String instance, String boot) {
        return new NativeSystemManager(store, () -> new JSONObject()
                .put("app_version", "1.17-system-management").put("wifi_connected", true)
                .put("wifi_rssi_dbm", -48).put("service_status", "waiting_ha")
                .put("last_error", JSONObject.NULL), actions, instance, boot);
    }
    @Test public void advertisesResponseOnlyServiceAndReturnsDiagnostics() throws Exception {
        Store store=new Store(); Actions actions=new Actions();
        NativeSystemProtocol protocol=new NativeSystemProtocol(manager(store,actions,"service-a","boot-a"));
        Sender sender=new Sender(); protocol.list(sender);
        EsphomeApi.ListEntitiesServicesResponse listed=(EsphomeApi.ListEntitiesServicesResponse)sender.sent.get(0).value;
        assertEquals("system_management",listed.getName());assertEquals(2,listed.getSupportsResponseValue());
        send(protocol,sender,4,"status","aabbccddeeff00112233445566778899");
        JSONObject response=response(sender);assertEquals(-48,response.getInt("wifi_rssi_dbm"));
        assertEquals("none",response.getString("last_operation_state"));assertNull(actions.operation);
    }
    @Test public void restartIsAcceptedThenOnlyCompletesInNewServiceInstance() throws Exception {
        Store store=new Store();Actions actions=new Actions();Sender sender=new Sender();
        NativeSystemProtocol protocol=new NativeSystemProtocol(manager(store,actions,"service-a","boot-a"));
        String id="0123456789abcdef0123456789abcdef";
        send(protocol,sender,7,"restart_service",id);
        assertEquals("requested",response(sender).getString("last_operation_state"));
        assertEquals("restart_service",actions.operation);
        NativeSystemManager restarted=manager(store,new Actions(),"service-b","boot-a");
        assertEquals("completed",restarted.snapshot(repeated('b'),"status").getString("last_operation_state"));
    }
    @Test public void rebootNeedsNewBootAndDispatchFailureIsVisible() throws Exception {
        Store store=new Store();Actions actions=new Actions();NativeSystemManager first=manager(store,actions,"a","boot-a");
        first.request("reboot_device",repeated('c'));first.dispatch("reboot_device");
        NativeSystemManager sameBoot=manager(store,new Actions(),"b","boot-a");
        assertEquals("requested",sameBoot.snapshot(repeated('d'),"status").getString("last_operation_state"));
        actions.failure.failed("system_reboot_permission_denied");
        assertEquals("failed",first.snapshot(repeated('e'),"status").getString("last_operation_state"));
        first.request("reboot_device",repeated('f'));
        NativeSystemManager rebooted=manager(store,new Actions(),"c","boot-b");
        assertEquals("completed",rebooted.snapshot(repeated('1'),"status").getString("last_operation_state"));
    }
    @Test public void malformedAndConcurrentRequestsFailClosed() throws Exception {
        Store store=new Store();NativeSystemProtocol protocol=new NativeSystemProtocol(manager(store,new Actions(),"a","boot"));
        Sender sender=new Sender();send(protocol,sender,1,"restart_service",repeated('0'));sender.sent.clear();
        send(protocol,sender,2,"reboot_device",repeated('1'));
        EsphomeApi.ExecuteServiceResponse response=(EsphomeApi.ExecuteServiceResponse)sender.sent.get(0).value;
        assertFalse(response.getSuccess());assertEquals("system_operation_busy",response.getErrorMessage());
    }
    private static void send(NativeSystemProtocol protocol,Sender sender,int call,String operation,String id)throws Exception{
        JSONObject request=new JSONObject().put("request_id",id).put("operation",operation);
        EsphomeApi.ExecuteServiceRequest value=EsphomeApi.ExecuteServiceRequest.newBuilder()
                .setKey(NativeSystemProtocol.SERVICE_KEY).setCallId(call).setReturnResponse(true)
                .addArgs(EsphomeApi.ExecuteServiceArgument.newBuilder().setString(request.toString())).build();
        assertTrue(protocol.message(MessageIds.ExecuteServiceRequest,value.toByteArray(),sender));
    }
    private static JSONObject response(Sender sender)throws Exception{
        EsphomeApi.ExecuteServiceResponse value=(EsphomeApi.ExecuteServiceResponse)sender.sent.get(sender.sent.size()-1).value;
        assertTrue(value.getSuccess());return new JSONObject(value.getResponseData().toStringUtf8());
    }
    private static String repeated(char value) {
        char[] result = new char[32]; java.util.Arrays.fill(result, value); return new String(result);
    }
}
