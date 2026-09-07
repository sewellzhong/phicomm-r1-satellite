package dev.sewellzhong.r1probe;

import android.content.Context;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import org.json.JSONObject;

/** Small local-only UI layered over the factory AP and scan endpoint. */
final class ProvisioningWebServer {
    interface Configurator { void configure(JSONObject request) throws Exception; }

    private static final int MAX_HEADERS = 8192;
    private static final int MAX_BODY = 4096;
    private final Context context;
    private final Configurator configurator;
    private volatile boolean running;
    private ServerSocket server;
    private Thread worker;

    ProvisioningWebServer(Context context, Configurator configurator) {
        this.context = context.getApplicationContext();
        this.configurator = configurator;
    }

    synchronized void start() throws IOException {
        if (running) return;
        server = new ServerSocket(8080);
        running = true;
        worker = new Thread(this::run, "r1-provisioning-page");
        worker.setDaemon(true);
        worker.start();
    }

    private void run() {
        while (running) {
            try (Socket socket = server.accept()) { handle(socket); }
            catch (IOException ignored) { /* Closing the server ends the bounded window. */ }
        }
    }

    private void handle(Socket socket) throws IOException {
        socket.setSoTimeout(4000);
        BufferedInputStream input = new BufferedInputStream(socket.getInputStream());
        String headers = readHeaders(input);
        String[] request = headers.split("\\r?\\n", 2)[0].split(" ");
        if (request.length < 2) { respond(socket, 400, "application/json", "{\"error\":\"bad_request\"}".getBytes(StandardCharsets.UTF_8)); return; }
        String method = request[0].toUpperCase(Locale.US), path = request[1].split("\\?", 2)[0];
        if ("GET".equals(method) && "/".equals(path)) {
            try (InputStream page = context.getAssets().open("provisioning.html")) {
                respond(socket, 200, "text/html; charset=utf-8", readLimited(page, 128 * 1024));
            }
        } else if ("GET".equals(method) && "/api/wifilist".equals(path)) {
            respond(socket, 200, "application/json; charset=utf-8", factoryWifiList());
        } else if ("POST".equals(method) && "/api/configwifi".equals(path)) {
            int length = contentLength(headers);
            if (length < 2 || length > MAX_BODY) { respond(socket, 400, "application/json", "{\"error\":\"bad_request\"}".getBytes(StandardCharsets.UTF_8)); return; }
            byte[] body = readExactly(input, length);
            try {
                JSONObject command = new JSONObject(new String(body, StandardCharsets.UTF_8));
                R1MessageDispatchBridge.validate(command.getString("ssid"),
                        command.optString("secure", "INSECURE"), command.optString("password", ""));
                respond(socket, 202, "application/json", "{\"accepted\":true}".getBytes(StandardCharsets.UTF_8));
                try { configurator.configure(command); } catch (Exception ignored) { }
            } catch (Exception ignored) {
                respond(socket, 400, "application/json", "{\"error\":\"invalid_wifi_configuration\"}".getBytes(StandardCharsets.UTF_8));
            }
        } else {
            respond(socket, 404, "application/json", "{\"error\":\"not_found\"}".getBytes(StandardCharsets.UTF_8));
        }
    }

    private static byte[] factoryWifiList() throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL("http://127.0.0.1:8989/api/wifilist").openConnection();
        connection.setConnectTimeout(3000); connection.setReadTimeout(5000); connection.setUseCaches(false);
        try (InputStream input = connection.getInputStream()) { return readLimited(input, 256 * 1024); }
        finally { connection.disconnect(); }
    }

    private static String readHeaders(InputStream input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int a = -1, b = -1, c = -1, d;
        while ((d = input.read()) != -1) {
            out.write(d);
            if (out.size() > MAX_HEADERS) throw new IOException("headers_too_large");
            if ((a == '\r' && b == '\n' && c == '\r' && d == '\n') || (c == '\n' && d == '\n')) break;
            a = b; b = c; c = d;
        }
        return new String(out.toByteArray(), StandardCharsets.US_ASCII);
    }

    private static int contentLength(String headers) {
        for (String line : headers.split("\\r?\\n")) {
            int colon = line.indexOf(':');
            if (colon > 0 && "content-length".equals(line.substring(0, colon).trim().toLowerCase(Locale.US)))
                try { return Integer.parseInt(line.substring(colon + 1).trim()); } catch (NumberFormatException ignored) { return -1; }
        }
        return -1;
    }

    private static byte[] readExactly(InputStream input, int length) throws IOException {
        byte[] result = new byte[length]; int offset = 0;
        while (offset < length) { int count = input.read(result, offset, length - offset); if (count < 0) throw new IOException("truncated_body"); offset += count; }
        return result;
    }

    private static byte[] readLimited(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream(); byte[] buffer = new byte[4096]; int count;
        while ((count = input.read(buffer)) != -1) { if (output.size() + count > maximum) throw new IOException("response_too_large"); output.write(buffer, 0, count); }
        return output.toByteArray();
    }

    private static void respond(Socket socket, int status, String type, byte[] body) throws IOException {
        OutputStream output = socket.getOutputStream();
        String reason = status == 200 ? "OK" : status == 202 ? "Accepted" : status == 404 ? "Not Found" : "Bad Request";
        output.write(("HTTP/1.1 " + status + " " + reason + "\r\nContent-Type: " + type
                + "\r\nContent-Length: " + body.length + "\r\nCache-Control: no-store\r\nConnection: close\r\n"
                + "Content-Security-Policy: default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
        output.write(body); output.flush();
    }

    synchronized void close() {
        running = false;
        if (server != null) try { server.close(); } catch (IOException ignored) { }
        server = null;
        if (worker != null && worker != Thread.currentThread()) worker.interrupt();
        worker = null;
    }
}
