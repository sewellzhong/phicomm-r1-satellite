package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioManager;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import org.json.JSONException;
import org.json.JSONObject;

/** Background, read-only listener for the R1 centre key and circular volume touch surface. */
final class HardwareInputMonitor {
    private static final String CENTRAL = "/dev/input/event0", RING = "/dev/input/event1";
    private final NativeSettings settings;
    private final AudioManager audio;
    private final HardwareInputInterpreter interpreter;
    private volatile boolean stopping;
    private volatile FileInputStream centralInput, ringInput;
    private Thread centralThread, ringThread;
    private long shortPresses, longPresses, clockwiseSteps, counterclockwiseSteps;
    private long lastDurationMs;
    private String lastEvent = "none", failure;

    HardwareInputMonitor(Context context, NativeSettings settings) {
        this.settings = settings;
        audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        interpreter = new HardwareInputInterpreter(new HardwareInputInterpreter.Listener() {
            @Override public void central(boolean longPress, long durationMs) {
                synchronized (HardwareInputMonitor.this) {
                    if (longPress) longPresses++; else shortPresses++;
                    lastDurationMs = durationMs;
                    lastEvent = longPress ? "central_long" : "central_short";
                }
            }
            @Override public void ringStep(int direction) { adjustVolume(direction); }
        });
    }

    void start() {
        if (centralThread != null || ringThread != null) return;
        centralThread = thread("r1-central-key", CENTRAL, true);
        ringThread = thread("r1-volume-ring", RING, false);
        centralThread.start(); ringThread.start();
    }

    private Thread thread(String name, String path, boolean central) {
        Thread result = new Thread(() -> {
            try (FileInputStream input = new FileInputStream(path)) {
                if (central) centralInput = input; else ringInput = input;
                new LinuxInputEventReader(input, central ? interpreter::central : interpreter::ring).run();
            } catch (IOException | RuntimeException e) {
                if (!stopping) failure = central ? "central_input_failed" : "ring_input_failed";
            } finally {
                if (central) centralInput = null; else ringInput = null;
            }
        }, name);
        result.setDaemon(true);
        return result;
    }

    private void adjustVolume(int direction) {
        synchronized (this) {
            settings.adjustVolume(direction * 5);
            if (direction > 0) clockwiseSteps++; else counterclockwiseSteps++;
            lastEvent = direction > 0 ? "ring_clockwise" : "ring_counterclockwise";
        }
        // Satellite output uses per-player gain; keep Android's shared output stage at unity.
        int maximum = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        if (audio.getStreamVolume(AudioManager.STREAM_MUSIC) != maximum)
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, maximum, 0);
    }

    synchronized void reset() {
        shortPresses = longPresses = clockwiseSteps = counterclockwiseSteps = lastDurationMs = 0;
        lastEvent = "none";
    }

    synchronized JSONObject snapshot() throws JSONException {
        return new JSONObject().put("running", centralInput != null && ringInput != null)
                .put("central_readable", new File(CENTRAL).canRead())
                .put("ring_readable", new File(RING).canRead())
                .put("short_presses", shortPresses).put("long_presses", longPresses)
                .put("last_press_ms", lastDurationMs)
                .put("clockwise_steps", clockwiseSteps).put("counterclockwise_steps", counterclockwiseSteps)
                .put("last_event", lastEvent)
                .put("failure", failure == null ? JSONObject.NULL : failure);
    }

    void stop() {
        stopping = true;
        close(centralInput); close(ringInput);
        if (centralThread != null) centralThread.interrupt();
        if (ringThread != null) ringThread.interrupt();
    }
    private static void close(FileInputStream input) {
        if (input != null) try { input.close(); } catch (IOException ignored) { }
    }
}
