package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
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
    private final Factory factory;
    private final Gate gate;
    private final byte[] ring = new byte[32768];
    private int head, size;
    private boolean ended;
    private volatile boolean stopped, done;
    private volatile String failure;
    private volatile Sink sink;
    private Thread worker;
    private volatile Thread stopper;

    public NativePcmPlayback(Factory factory, Gate gate) { this.factory = factory; this.gate = gate; }

    @Override public synchronized void start() throws IOException {
        if (!terminated()) throw new IOException("playback_already_running");
        Arrays.fill(ring, (byte) 0);
        head = 0; size = 0; ended = false; stopped = false; done = false; failure = null;
        gate.request();
        worker = new Thread(this::play, "native-pcm-playback");
        worker.setDaemon(true);
        worker.start();
    }
    @Override public synchronized void audio(byte[] data) throws IOException {
        if (worker == null || ended || stopped || failure != null) throw new IOException("playback_not_receiving");
        if (data.length == 0 || (data.length & 1) != 0) throw new IOException("invalid_pcm_samples");
        if (size + data.length > ring.length) throw new IOException("playback_buffer_overflow");
        for (byte value : data) { ring[(head + size) % ring.length] = value; size++; }
        notifyAll();
    }
    @Override public synchronized void end() { ended = true; notifyAll(); }
    @Override public boolean complete() { return done && worker != null && !worker.isAlive(); }
    public boolean terminated() { return (worker == null || !worker.isAlive()) && (stopper == null || !stopper.isAlive()); }
    @Override public String failure() { return failure; }
    @Override public synchronized void stop() {
        stopped = true;
        Arrays.fill(ring, (byte) 0); size = 0; notifyAll();
        if (worker != null) worker.interrupt();
        Sink current = sink;
        if (current != null && (stopper == null || !stopper.isAlive())) {
            stopper = new Thread(() -> {
                try { current.stop(); } catch (RuntimeException e) { failure = "playback_stop_failed"; }
            }, "native-playback-stop");
            stopper.setDaemon(true); stopper.start();
        }
    }

    private void play() {
        byte[] frame = new byte[640];
        long deadline = System.nanoTime() + 300_000_000_000L;
        boolean drained = false;
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
            long writtenFrames = 0;
            while (!stopped) {
                if (System.nanoTime() >= deadline) throw new IOException("playback_timeout");
                int count;
                synchronized (this) {
                    // Reframe network chunks; the final partial frame contains whole samples only.
                    if (size < frame.length && !ended) { wait(10); continue; }
                    count = Math.min(size, frame.length);
                    for (int i = 0; i < count; i++) {
                        frame[i] = ring[head]; ring[head] = 0;
                        head = (head + 1) % ring.length;
                    }
                    size -= count;
                    if (count == 0 && ended) break;
                }
                int offset = 0;
                while (!stopped && offset < count) {
                    if (System.nanoTime() >= deadline) throw new IOException("playback_timeout");
                    int accepted = current.write(frame, offset, count - offset);
                    if (accepted <= 0 || accepted > count - offset || (accepted & 1) != 0)
                        throw new IOException("playback_write_failed");
                    offset += accepted; writtenFrames += accepted / 2;
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
            if (drained) gate.drained();
        } catch (Exception e) {
            if (!stopped) failure = "playback_failed";
        } finally {
            Sink current = sink;
            if (current != null) {
                try { current.stop(); }
                catch (RuntimeException e) { failure = "playback_stop_failed"; drained = false; }
                finally {
                    try { current.close(); }
                    catch (RuntimeException e) { failure = "playback_release_failed"; drained = false; }
                }
            }
            sink = null;
            Arrays.fill(frame, (byte) 0);
            synchronized (this) { Arrays.fill(ring, (byte) 0); size = 0; }
            gate.release();
            done = drained;
        }
    }
}
