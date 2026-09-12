package dev.sewellzhong.r1probe;

import dev.sewellzhong.r1probe.esphome.NativeTimerController;
import java.util.LinkedHashSet;

/** Local API-22 alarm tone. It never needs HA, a URL, or a private audio asset. */
final class NativeTimerAlarm implements NativeTimerController.Alarm {
    interface Gate {
        void requestRelease();
        boolean released();
    }
    private final android.content.Context context;
    private final NativeSettings settings;
    private final Gate gate;
    private volatile Thread worker;
    private volatile long generation;
    private volatile String failure;
    private final LinkedHashSet<String> owners = new LinkedHashSet<>();

    NativeTimerAlarm(android.content.Context context, NativeSettings settings, Gate gate) {
        this.context = context.getApplicationContext(); this.settings = settings; this.gate = gate;
    }

    @Override public synchronized void start() { startOwner("timer"); }
    synchronized void startAlarm() { startOwner("alarm"); }
    private void startOwner(String owner) {
        owners.add(owner);
        if (workerActive()) return;
        failure = null;
        final long token = ++generation;
        worker = new Thread(() -> play(token), "native-timer-alarm");
        worker.setDaemon(true); worker.start();
    }

    private void play(long token) {
        NativeAudioTrackSink sink = null;
        try {
            gate.requestRelease();
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (running(token) && !gate.released()) {
                if (System.nanoTime() >= deadline) throw new IllegalStateException("timer_audio_release_timeout");
                Thread.sleep(10);
            }
            if (!running(token)) return;
            sink = new NativeAudioTrackSink(new NativeVolume(context, settings));
            sink.start();
            byte[] frame = new byte[640];
            long sample = 0;
            while (running(token)) {
                boolean tone = (sample / 8000L) % 2 == 0;
                for (int i = 0; i < 320; i++, sample++) {
                    short value = tone ? (short) (Math.sin(2.0 * Math.PI * 880.0 * sample / 16000.0) * 9000) : 0;
                    frame[i * 2] = (byte) value;
                    frame[i * 2 + 1] = (byte) (value >> 8);
                }
                int offset = 0;
                while (running(token) && offset < frame.length) {
                    int count = sink.write(frame, offset, frame.length - offset);
                    if (count <= 0) throw new IllegalStateException("timer_audio_write_failed");
                    offset += count;
                }
            }
            java.util.Arrays.fill(frame, (byte) 0);
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        catch (RuntimeException error) { failure = "timer_alarm_output_failed"; }
        finally {
            if (sink != null) { sink.stop(); sink.close(); }
            new NativeVolume(context, settings).restoreOutput();
        }
    }

    @Override public synchronized void stop() { stopOwner("timer"); }
    synchronized void stopAlarm() { stopOwner("alarm"); }
    private void stopOwner(String owner) {
        owners.remove(owner);
        if (!owners.isEmpty()) return;
        generation++;
        Thread current = worker;
        if (current != null) current.interrupt();
    }
    @Override public synchronized boolean active() { return ownerActive("timer"); }
    synchronized boolean alarmActive() { return ownerActive("alarm"); }
    private boolean ownerActive(String owner) { return owners.contains(owner) && workerActive(); }
    private boolean workerActive() {
        Thread current = worker;
        return current != null && current.isAlive() && !owners.isEmpty();
    }
    private boolean running(long token) { return token == generation; }
    @Override public String failure() { return failure; }
}
