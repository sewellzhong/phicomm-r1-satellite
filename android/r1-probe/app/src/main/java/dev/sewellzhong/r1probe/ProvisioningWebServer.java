package dev.sewellzhong.r1probe;

import android.content.Context;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Locale;
import org.json.JSONObject;

/** Small local-only UI layered over the factory AP and scan endpoint. */
final class ProvisioningWebServer {
    interface Configurator { void configure(JSONObject request) throws Exception; }
    interface Scanner { byte[] scan() throws Exception; }

    private static final int MAX_HEADERS = 8192;
    private static final int MAX_BODY = 4096;
    private final Context context;
    private final Scanner scanner;
    private final Configurator configurator;
    private volatile boolean running;
    private ServerSocket server;
    private Thread worker;
    private final Owner owner = new Owner();

    ProvisioningWebServer(Context context, Scanner scanner, Configurator configurator) {
        this.context = context.getApplicationContext();
        this.scanner = scanner;
        this.configurator = configurator;
    }

    synchronized void start() throws IOException {
        if (running) return;
        ServerSocket listening = new ServerSocket(8080);
        server = listening;
        owner.reset();
        running = true;
        worker = new Thread(() -> run(listening), "r1-provisioning-page");
        worker.setDaemon(true);
        worker.start();
    }

    private void run(ServerSocket listening) {
        while (running && server == listening) {
            try (Socket socket = listening.accept()) { handle(socket); }
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
            String token = owner.claim(cookie(headers, "R1SESSION"));
            if (token == null) {
                respond(socket, 409, "text/html; charset=utf-8",
                        "<meta charset=utf-8><meta name=viewport content='width=device-width'><title>R1 正在配置</title><p style='font:18px sans-serif;margin:3rem'>已有一台手机正在配置这台 R1，请在那台手机上继续。</p>".getBytes(StandardCharsets.UTF_8));
                return;
            }
            try (InputStream page = context.getAssets().open("provisioning.html")) {
                respond(socket, 200, "text/html; charset=utf-8", readLimited(page, 128 * 1024),
                        "Set-Cookie: R1SESSION=" + token + "; Path=/; HttpOnly; SameSite=Strict\r\n");
            }
        } else if ("GET".equals(method) && "/api/wifilist".equals(path)) {
            if (!owner.authorized(cookie(headers, "R1SESSION"))) { respond(socket, 403, "application/json", "{\"error\":\"not_owner\"}".getBytes(StandardCharsets.UTF_8)); return; }
            try { respond(socket, 200, "application/json; charset=utf-8", scanner.scan()); }
            catch (Exception error) { respond(socket, 503, "application/json", "{\"error\":\"scan_unavailable\"}".getBytes(StandardCharsets.UTF_8)); }
        } else if ("POST".equals(method) && "/api/configwifi".equals(path)) {
            if (!owner.authorized(cookie(headers, "R1SESSION"))) { respond(socket, 403, "application/json", "{\"error\":\"not_owner\"}".getBytes(StandardCharsets.UTF_8)); return; }
            int length = contentLength(headers);
            if (length < 2 || length > MAX_BODY) { respond(socket, 400, "application/json", "{\"error\":\"bad_request\"}".getBytes(StandardCharsets.UTF_8)); return; }
            byte[] body = readExactly(input, length);
            try {
                JSONObject command = new JSONObject(new String(body, StandardCharsets.UTF_8));
                R1MessageDispatchBridge.validate(command.getString("ssid"),
                        command.optString("secure", "INSECURE"), command.optString("password", ""));
                if (!owner.submit()) { respond(socket, 409, "application/json", "{\"error\":\"already_submitted\"}".getBytes(StandardCharsets.UTF_8)); return; }
                respond(socket, 202, "application/json", "{\"accepted\":true}".getBytes(StandardCharsets.UTF_8));
                try { configurator.configure(command); } catch (Exception ignored) { }
            } catch (Exception ignored) {
                respond(socket, 400, "application/json", "{\"error\":\"invalid_wifi_configuration\"}".getBytes(StandardCharsets.UTF_8));
            }
        } else {
            respond(socket, 404, "application/json", "{\"error\":\"not_found\"}".getBytes(StandardCharsets.UTF_8));
        }
    }

    static final class Owner {
        private String token;
        private boolean submitted;
        synchronized void reset() { token = null; submitted = false; }
        synchronized String claim(String supplied) {
            if (token == null) {
                byte[] random = new byte[16]; new SecureRandom().nextBytes(random);
                StringBuilder value = new StringBuilder(32);
                for (byte item : random) value.append(String.format(Locale.US, "%02x", item & 255));
                token = value.toString();
                return token;
            }
            return token.equals(supplied) ? token : null;
        }
        synchronized boolean authorized(String supplied) { return token != null && token.equals(supplied); }
        synchronized boolean submit() { if (submitted) return false; submitted = true; return true; }
    }

    static String cookie(String headers, String name) {
        for (String line : headers.split("\\r?\\n")) {
            int colon = line.indexOf(':');
            if (colon <= 0 || !"cookie".equals(line.substring(0, colon).trim().toLowerCase(Locale.US))) continue;
            for (String item : line.substring(colon + 1).split(";")) {
                String value = item.trim();
                if (value.startsWith(name + "=")) return value.substring(name.length() + 1);
            }
        }
        return null;
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
        respond(socket, status, type, body, "");
    }

    private static void respond(Socket socket, int status, String type, byte[] body, String extra) throws IOException {
        OutputStream output = socket.getOutputStream();
        String reason = status == 200 ? "OK" : status == 202 ? "Accepted" : status == 403 ? "Forbidden"
                : status == 404 ? "Not Found" : status == 409 ? "Conflict" : status == 503 ? "Service Unavailable" : "Bad Request";
        output.write(("HTTP/1.1 " + status + " " + reason + "\r\nContent-Type: " + type
                + "\r\nContent-Length: " + body.length + "\r\nCache-Control: no-store\r\nConnection: close\r\n"
                + extra + "Content-Security-Policy: default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
        output.write(body); output.flush();
    }

    synchronized void close() {
        Thread previous = worker;
        running = false;
        if (server != null) try { server.close(); } catch (IOException ignored) { }
        server = null;
        if (previous != null && previous != Thread.currentThread()) {
            previous.interrupt();
            try { previous.join(1000L); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        }
        worker = null;
    }
}
