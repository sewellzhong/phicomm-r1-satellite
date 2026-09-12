package dev.sewellzhong.r1probe;

import dev.sewellzhong.r1probe.esphome.NativeTimerController;

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
    private volatile boolean stopping;
    private volatile String failure;

    NativeTimerAlarm(android.content.Context context, NativeSettings settings, Gate gate) {
        this.context = context.getApplicationContext(); this.settings = settings; this.gate = gate;
    }

    @Override public synchronized void start() {
        if (active()) return;
        stopping = false; failure = null;
        worker = new Thread(this::play, "native-timer-alarm");
        worker.setDaemon(true); worker.start();
    }

    private void play() {
        NativeAudioTrackSink sink = null;
        try {
            gate.requestRelease();
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (!stopping && !gate.released()) {
                if (System.nanoTime() >= deadline) throw new IllegalStateException("timer_audio_release_timeout");
                Thread.sleep(10);
            }
            if (stopping) return;
            sink = new NativeAudioTrackSink(new NativeVolume(context, settings));
            sink.start();
            byte[] frame = new byte[640];
            long sample = 0;
            while (!stopping) {
                boolean tone = (sample / 8000L) % 2 == 0;
                for (int i = 0; i < 320; i++, sample++) {
                    short value = tone ? (short) (Math.sin(2.0 * Math.PI * 880.0 * sample / 16000.0) * 9000) : 0;
                    frame[i * 2] = (byte) value;
                    frame[i * 2 + 1] = (byte) (value >> 8);
                }
                int offset = 0;
                while (!stopping && offset < frame.length) {
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

    @Override public synchronized void stop() {
        stopping = true;
        Thread current = worker;
        if (current != null) current.interrupt();
    }
    @Override public boolean active() {
        Thread current = worker;
        return current != null && current.isAlive() && !stopping;
    }
    @Override public String failure() { return failure; }
}
