package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.io.BufferedInputStream;
import java.io.EOFException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.net.URL;
import java.util.Arrays;

/** Bounded PCM S16LE/16k mono player. Receiving bytes and draining the hardware are distinct. */
public final class NativePcmPlayback implements NativeVoiceSession.Playback {
    public interface Sink {
        void start() throws Exception;
        int write(byte[] bytes, int offset, int length) throws Exception;
        long playedFrames() throws Exception;
        void stop();
        void close();
    }
    public interface Factory { Sink create() throws Exception; }
    public interface Gate {
        void request();
        boolean microphoneReleased();
        void release();
        default void drained() { }
    }
    public interface Observer { void event(String detail); }
    private static final Observer NO_EVENTS = detail -> { };
    private final Factory factory;
    private final Gate gate;
    private final Observer observer;
    private final byte[] ring = new byte[32768];
    private int head, size;
    private boolean ended;
    private volatile boolean stopped, done;
    private volatile String failure;
    private volatile String httpFailure = "none";
    private volatile Sink sink;
    private volatile Thread worker;
    private volatile Thread stopper;
    private volatile Thread source;
    private volatile HttpURLConnection sourceConnection;
    private boolean sinkStopClaimed;
    private long generation;
    private int highWaterBytes;
    private int underruns;
    private volatile long requestedMillis;
    private volatile long firstWriteMillis;
    private volatile long drainedMillis;
    private volatile long releasedMillis;

    public synchronized int highWaterBytes() { return highWaterBytes; }
    public synchronized int underruns() { return underruns; }
    public long requestedMillis() { return requestedMillis; }
    public long firstWriteMillis() { return firstWriteMillis; }
    public long drainedMillis() { return drainedMillis; }
    public long releasedMillis() { return releasedMillis; }
    public String httpFailure() { return httpFailure; }

    public NativePcmPlayback(Factory factory, Gate gate) { this(factory, gate, NO_EVENTS); }
    public NativePcmPlayback(Factory factory, Gate gate, Observer observer) {
        this.factory = factory; this.gate = gate; this.observer = observer == null ? NO_EVENTS : observer;
    }
    private void event(String detail) {
        try { observer.event(detail); } catch (RuntimeException ignored) { /* Diagnostics never own audio. */ }
    }

    @Override public synchronized void start() throws IOException {
        if (!terminated()) throw new IOException("playback_already_running");
        Arrays.fill(ring, (byte) 0);
        head = 0; size = 0; ended = false; stopped = false; done = false; failure = null;
        httpFailure = "none";
        stopper = null; sinkStopClaimed = false;
        highWaterBytes = 0; underruns = 0; generation++;
        requestedMillis = System.nanoTime() / 1_000_000L;
        firstWriteMillis = drainedMillis = releasedMillis = 0;
        event("playback_requested,generation=" + generation);
        gate.request();
        worker = new Thread(this::play, "native-pcm-playback");
        worker.setDaemon(true);
        worker.start();
    }
    @Override public synchronized boolean startUrl(String value) throws IOException {
        if (value == null || value.length() == 0 || value.length() > 2048)
            throw new IOException("tts_url_invalid");
        URL url = new URL(value);
        String scheme = url.getProtocol();
        if (!("http".equals(scheme) || "https".equals(scheme)) || url.getHost().isEmpty()
                || url.getUserInfo() != null || url.getRef() != null)
            throw new IOException("tts_url_invalid");
        start();
        source = new Thread(() -> fetch(url), "native-http-tts");
        source.setDaemon(true); source.start();
        event("playback_http_started,generation=" + generation);
        return true;
    }
    @Override public synchronized void audio(byte[] data) throws IOException {
        if (worker == null || ended || stopped || failure != null) throw new IOException("playback_not_receiving");
        if (data.length == 0 || (data.length & 1) != 0) throw new IOException("invalid_pcm_samples");
        if (size + data.length > ring.length) throw new IOException("playback_buffer_overflow");
        for (byte value : data) { ring[(head + size) % ring.length] = value; size++; }
        highWaterBytes = Math.max(highWaterBytes, size);
        notifyAll();
    }
    @Override public synchronized void end() {
        ended = true;
        event("playback_stream_end,generation=" + generation + ",buffer_high_water_bytes="
                + highWaterBytes + ",underruns=" + underruns);
        notifyAll();
    }
    @Override public boolean complete() { return done && worker != null && !worker.isAlive(); }
    @Override public boolean terminated() { return (worker == null || !worker.isAlive())
            && (stopper == null || !stopper.isAlive()) && (source == null || !source.isAlive()); }
    @Override public String failure() { return failure; }
    @Override public synchronized void stop() {
        boolean first = !stopped;
        stopped = true;
        Arrays.fill(ring, (byte) 0); size = 0; notifyAll();
        if (first) event("playback_stop_requested,generation=" + generation);
        if (worker != null) worker.interrupt();
        Thread currentSource = source;
        if (currentSource != null) currentSource.interrupt();
        HttpURLConnection connection = sourceConnection;
        if (connection != null) connection.disconnect();
        Sink current = sink;
        if (current != null && !sinkStopClaimed) {
            sinkStopClaimed = true;
            stopper = new Thread(() -> {
                try { current.stop(); } catch (RuntimeException e) { failure = "playback_stop_failed"; }
            }, "native-playback-stop");
            stopper.setDaemon(true); stopper.start();
        }
    }

    private void fetch(URL url) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) url.openConnection();
            sourceConnection = connection;
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10000); connection.setReadTimeout(65000);
            connection.setRequestProperty("Accept", "audio/wav,audio/x-wav");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK)
                throw new IOException("tts_http_status");
            try (InputStream input = new BufferedInputStream(connection.getInputStream(), 4096)) {
                streamWav(input);
            }
        } catch (Exception error) {
            if (!stopped) { httpFailure = safeHttpFailure(error); failure = "playback_http_failed"; stop(); }
        } finally {
            sourceConnection = null;
            if (connection != null) connection.disconnect();
        }
    }
    private static String safeHttpFailure(Exception error) {
        if (error instanceof SocketTimeoutException) return "timeout";
        if (error instanceof UnknownHostException) return "unknown_host";
        if (error instanceof ConnectException) return "connect";
        String message = error.getMessage();
        if (message != null && message.matches("tts_[a-z_]+")) return message;
        return error instanceof IOException ? "io" : "runtime";
    }

    void streamWav(InputStream input) throws IOException {
        byte[] riff = readExact(input, 12);
        if (!ascii(riff, 0, "RIFF") || !ascii(riff, 8, "WAVE"))
            throw new IOException("tts_wav_header_invalid");
        boolean format = false;
        long total = 0;
        while (!stopped) {
            byte[] header = readExact(input, 8);
            long length = littleUnsigned(header, 4);
            if (ascii(header, 0, "fmt ")) {
                if (length < 16 || length > 64) throw new IOException("tts_wav_format_invalid");
                byte[] fmt = readExact(input, (int) length);
                if (little(fmt, 0) != 1 || little(fmt, 2) != 1
                        || littleUnsigned(fmt, 4) != 16000 || little(fmt, 12) != 2
                        || little(fmt, 14) != 16)
                    throw new IOException("tts_wav_format_invalid");
                format = true;
            } else if (ascii(header, 0, "data")) {
                if (!format) throw new IOException("tts_wav_data_before_format");
                long remaining = length == 0xffffffffL ? Long.MAX_VALUE : length;
                byte[] frame = new byte[640];
                while (!stopped && remaining > 0) {
                    int wanted = (int) Math.min(frame.length, remaining);
                    int count = readSome(input, frame, wanted);
                    if (count < 0) {
                        if (remaining != Long.MAX_VALUE) throw new EOFException("tts_wav_truncated");
                        break;
                    }
                    if ((count & 1) != 0 || (total += count) > 10 * 1024 * 1024L)
                        throw new IOException("tts_wav_size_invalid");
                    audioBlocking(Arrays.copyOf(frame, count));
                    if (remaining != Long.MAX_VALUE) remaining -= count;
                }
                Arrays.fill(frame, (byte) 0);
                if (!stopped) end();
                return;
            } else {
                if (length > 1024 * 1024L) throw new IOException("tts_wav_chunk_invalid");
                skipExact(input, length);
            }
            if ((length & 1) != 0) skipExact(input, 1);
        }
    }

    private synchronized void audioBlocking(byte[] data) throws IOException {
        long deadline = System.nanoTime() + 300_000_000_000L;
        while (!stopped && failure == null && size + data.length > ring.length) {
            if (System.nanoTime() >= deadline) throw new IOException("tts_http_backpressure_timeout");
            try { wait(20); }
            catch (InterruptedException e) {
                Thread.currentThread().interrupt(); throw new IOException("tts_http_interrupted", e);
            }
        }
        if (stopped || failure != null) throw new IOException("tts_http_stopped");
        audio(data);
    }

    private static byte[] readExact(InputStream input, int length) throws IOException {
        byte[] result = new byte[length]; int offset = 0;
        while (offset < length) {
            int count = input.read(result, offset, length - offset);
            if (count < 0) throw new EOFException("tts_wav_truncated");
            offset += count;
        }
        return result;
    }
    private static int readSome(InputStream input, byte[] target, int length) throws IOException {
        int offset = 0;
        while (offset < length) {
            int count = input.read(target, offset, length - offset);
            if (count < 0) return offset == 0 ? -1 : offset;
            offset += count;
        }
        return offset;
    }
    private static void skipExact(InputStream input, long length) throws IOException {
        while (length > 0) {
            long skipped = input.skip(length);
            if (skipped <= 0) { if (input.read() < 0) throw new EOFException("tts_wav_truncated"); skipped = 1; }
            length -= skipped;
        }
    }
    private static boolean ascii(byte[] bytes, int offset, String value) {
        for (int i = 0; i < value.length(); i++) if (bytes[offset + i] != (byte) value.charAt(i)) return false;
        return true;
    }
    private static int little(byte[] bytes, int offset) {
        return (bytes[offset] & 255) | ((bytes[offset + 1] & 255) << 8);
    }
    private static long littleUnsigned(byte[] bytes, int offset) {
        return (bytes[offset] & 255L) | ((bytes[offset + 1] & 255L) << 8)
                | ((bytes[offset + 2] & 255L) << 16) | ((bytes[offset + 3] & 255L) << 24);
    }

    private void play() {
        byte[] frame = new byte[640];
        long deadline = System.nanoTime() + 300_000_000_000L;
        boolean drained = false;
        boolean wrote = false, starving = false;
        try {
            while (!stopped && !gate.microphoneReleased()) {
                if (System.nanoTime() >= deadline) throw new IOException("capture_release_timeout");
                Thread.sleep(10);
            }
            if (stopped) return;
            Sink current = factory.create();
            sink = current;
            if (stopped) return;
            current.start();
            event("playback_sink_started,generation=" + generation);
            long writtenFrames = 0;
            while (!stopped) {
                if (System.nanoTime() >= deadline) throw new IOException("playback_timeout");
                int count;
                synchronized (this) {
                    // Reframe network chunks; the final partial frame contains whole samples only.
                    if (size < frame.length && !ended) {
                        if (wrote && size == 0 && !starving) { underruns++; starving = true; }
                        wait(10); continue;
                    }
                    count = Math.min(size, frame.length);
                    for (int i = 0; i < count; i++) {
                        frame[i] = ring[head]; ring[head] = 0;
                        head = (head + 1) % ring.length;
                    }
                    size -= count;
                    notifyAll();
                    if (count > 0) starving = false;
                    if (count == 0 && ended) break;
                }
                int offset = 0;
                while (!stopped && offset < count) {
                    if (System.nanoTime() >= deadline) throw new IOException("playback_timeout");
                    int accepted = current.write(frame, offset, count - offset);
                    if (accepted <= 0 || accepted > count - offset || (accepted & 1) != 0)
                        throw new IOException("playback_write_failed");
                    offset += accepted; writtenFrames += accepted / 2;
                    if (!wrote) {
                        wrote = true;
                        firstWriteMillis = System.nanoTime() / 1_000_000L;
                        event("playback_first_write,generation=" + generation);
                    }
                }
                Arrays.fill(frame, (byte) 0);
            }
            // Queue empty/write returned does not mean DAC consumed the last sample.
            while (!stopped && current.playedFrames() < writtenFrames) {
                if (System.nanoTime() >= deadline) throw new IOException("playback_drain_timeout");
                Thread.sleep(10);
            }
            if (!stopped && writtenFrames == 0) throw new IOException("empty_tts_stream");
            drained = !stopped;
            if (drained) {
                drainedMillis = System.nanoTime() / 1_000_000L;
                event("playback_drained,generation=" + generation + ",frames=" + writtenFrames);
                gate.drained();
            }
        } catch (Exception e) {
            if (!stopped) {
                failure = "playback_failed";
                event("playback_failed,generation=" + generation);
            }
        } finally {
            Sink current = sink;
            if (current != null) {
                Thread asynchronousStop;
                boolean stopHere;
                synchronized (this) {
                    stopHere = !sinkStopClaimed;
                    if (stopHere) sinkStopClaimed = true;
                    asynchronousStop = stopper;
                }
                if (stopHere) {
                    try { current.stop(); }
                    catch (RuntimeException e) { failure = "playback_stop_failed"; drained = false; }
                } else if (asynchronousStop != null) {
                    while (asynchronousStop.isAlive()) {
                        try { asynchronousStop.join(); }
                        catch (InterruptedException ignored) { /* Release still waits for native stop. */ }
                    }
                }
                try { current.close(); }
                catch (RuntimeException e) { failure = "playback_release_failed"; drained = false; }
            }
            sink = null;
            Arrays.fill(frame, (byte) 0);
            synchronized (this) { Arrays.fill(ring, (byte) 0); size = 0; }
            gate.release();
            releasedMillis = System.nanoTime() / 1_000_000L;
            done = drained;
            event("playback_released,generation=" + generation + ",drained=" + drained
                    + ",buffer_high_water_bytes=" + highWaterBytes + ",underruns=" + underruns);
        }
    }
}
