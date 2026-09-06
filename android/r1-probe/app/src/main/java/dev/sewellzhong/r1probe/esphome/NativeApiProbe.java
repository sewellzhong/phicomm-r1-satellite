package dev.sewellzhong.r1probe.esphome;

import java.io.*;
import java.net.*;
import java.util.Arrays;

/** Explicit two-minute loopback-only interoperability probe. Never records audio or persists a PSK. */
public final class NativeApiProbe {
    public static void main(String[] args) throws Exception {
        byte[] key=new byte[32];
        try {
            String line=new BufferedReader(new InputStreamReader(System.in,"US-ASCII")).readLine();
            if(line==null || !line.matches("[0-9a-f]{64}"))throw new IllegalArgumentException("private_key_input_required");
            for(int i=0;i<32;i++)key[i]=(byte)Integer.parseInt(line.substring(i*2,i*2+2),16);
            line=null;
            try(ServerSocket server=new ServerSocket(6053,4,InetAddress.getByName("127.0.0.1"))) {
                server.setSoTimeout(1000);
                java.util.concurrent.atomic.AtomicReference<Socket> active = new java.util.concurrent.atomic.AtomicReference<>();
                Thread watchdog = new Thread(() -> {
                    try {
                        Thread.sleep(120000);
                        server.close();
                        Socket current=active.get(); if(current!=null)current.close();
                    } catch (Exception ignored) { }
                }, "native-probe-expiry");
                watchdog.setDaemon(true);watchdog.start();
                long deadline=System.nanoTime()+120_000_000_000L;
                System.out.println("NATIVE_API_PROBE_READY encrypted_only=true loopback_only=true audio=false");
                int clients=0;
                while(System.nanoTime()<deadline && clients<(args.length == 1 && "--satellite-metadata".equals(args[0]) ? 6 : 5)) {
                    try {
                        Socket socket=server.accept();active.set(socket);clients++;
                        socket.setSoTimeout(10000);
                        boolean metadata = args.length == 1 && "--satellite-metadata".equals(args[0]);
                        NativeApiConnection.Handler profile = new NativeApiConnection.Handler() {
                            private boolean wake = true;
                            public void connected(NativeVoiceSession.Sender sender) { }
                            public void message(int type, byte[] payload) { }
                            public void tick() { }
                            public void closed() { }
                            public boolean wakeEnabled() { return wake; }
                            public void wakeEnabled(boolean enabled) { wake = enabled; }
                        };
                        try { new NativeApiConnection(socket,"r1-native-probe","02:00:00:00:00:01",
                                args.length == 1 && ("--synthetic-voice".equals(args[0]) || "--synthetic-duplex".equals(args[0]) || "--synthetic-dialogue".equals(args[0]))
                                        ? new NativeVoiceProbeHandler(!"--synthetic-voice".equals(args[0]), "--synthetic-dialogue".equals(args[0])) : (metadata ? profile : null), metadata).run(key); }
                        catch(Exception ignored) { socket.close();System.out.println("NATIVE_CLIENT_REJECTED_OR_CLOSED"); }
                    } catch(SocketTimeoutException ignored) { }
                }
            }
        } finally { Arrays.fill(key,(byte)0); }
    }
    private NativeApiProbe() { }
}
