package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioRecord;
import java.util.Arrays;
import org.json.JSONObject;

/** Explicit local-admin hardware check. Discards microphone samples; plays a fixed 200ms tone. */
final class NativeAudioHealth implements Runnable {
    private volatile String state = "running";
    private volatile boolean captured, played;
    private volatile int frames, peak;
    private volatile AudioRecord recorder;
    private volatile NativeAudioTrackSink sink;
    private volatile boolean stop;
    private final Thread thread;
    private final Runnable stalled;
    NativeAudioHealth(Runnable stalled) { this.stalled = stalled; thread = new Thread(this, "native-audio-health"); }
    boolean start() { if (!AudioOwner.acquire(this)) return false; thread.start(); return true; }
    boolean alive() { return thread.isAlive(); }
    synchronized void cancel() {
        if (stop) return;
        stop = true; thread.interrupt();
        Thread unblock = new Thread(() -> {
            AudioRecord current = recorder;
            if (current != null) try { current.stop(); } catch (IllegalStateException ignored) { }
            NativeAudioTrackSink output = sink;
            if (output != null) output.stop();
        }, "native-health-stop");
        unblock.setDaemon(true); unblock.start();
    }
    JSONObject snapshot() throws org.json.JSONException {
        return new JSONObject().put("state", state).put("real_capture", captured).put("real_playback", played)
                .put("capture_frames", frames).put("peak", peak).put("samples_saved", false)
                .put("audibility_verified", false).put("tone_ms", 200);
    }
    @Override public void run() {
        short[] samples = new short[320]; byte[] tone = new byte[640];
        Thread timeout = new Thread(() -> {
            try {
                Thread.sleep(10000); cancel(); thread.join(5000);
                if (thread.isAlive()) { state = "failed"; stalled.run(); }
            } catch (InterruptedException ignored) { }
        }, "native-health-timeout");
        timeout.setDaemon(true); timeout.start();
        try {
            int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("invalid_capture_buffer");
            recorder = new AudioRecord(AudioSourceSpec.VOICE_COMMUNICATION, 16000,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(6400, minimum));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("capture_unavailable");
            recorder.startRecording();
            int fill = 0;
            while (!stop && frames < 50) {
                int count = recorder.read(samples, fill, samples.length - fill);
                if (count <= 0) throw new IllegalStateException("capture_failed");
                fill += count;
                if (fill == samples.length) {
                    for (short value : samples) peak = Math.max(peak, Math.abs((int) value));
                    frames++; fill = 0; Arrays.fill(samples, (short) 0);
                }
            }
            captured = frames == 50;
            releaseRecorder();
            if (stop) throw new InterruptedException();
            sink = new NativeAudioTrackSink(); sink.start();
            for (int frame = 0; frame < 10 && !stop; frame++) {
                for (int i = 0; i < 320; i++) {
                    int value = (int) (1500 * Math.sin(2 * Math.PI * 660 * (frame * 320 + i) / 16000));
                    tone[2*i] = (byte) value; tone[2*i+1] = (byte) (value >>> 8);
                }
                int offset = 0;
                while (offset < tone.length && !stop) {
                    int accepted = sink.write(tone, offset, tone.length-offset);
                    if (accepted <= 0 || (accepted & 1) != 0) throw new IllegalStateException("playback_failed");
                    offset += accepted;
                }
            }
            while (!stop && sink.playedFrames() < 3200) Thread.sleep(10);
            played = !stop && sink.playedFrames() >= 3200;
            state = captured && played ? "passed" : "failed";
        } catch (Exception | LinkageError e) { state = "failed"; }
        finally {
            try {
                releaseRecorder();
                if (sink != null) { try { sink.stop(); } finally { sink.close(); sink = null; } }
            } finally {
                timeout.interrupt(); Arrays.fill(samples, (short) 0); Arrays.fill(tone, (byte) 0);
                AudioOwner.release(this);
            }
        }
    }
    private void releaseRecorder() {
        AudioRecord current = recorder;
        if (current != null) {
            try { current.stop(); } catch (IllegalStateException ignored) { }
            current.release(); recorder = null;
        }
    }
}
