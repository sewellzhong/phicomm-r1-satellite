package dev.sewellzhong.r1probe;

import dev.sewellzhong.r1probe.esphome.NativeTimerController;
import java.io.RandomAccessFile;
import java.util.LinkedHashMap;

/** Local API-22 alert output. Custom WAV content is app-private and never fetched at ring time. */
final class NativeTimerAlarm implements NativeTimerController.Alarm {
    interface Gate {
        void requestRelease();
        boolean released();
    }
    private final android.content.Context context;
    private final NativeSettings settings;
    private final NativeAlertAudioStore audioStore;
    private final Gate gate;
    private volatile Thread worker;
    private volatile long generation;
    private volatile String failure;
    private volatile String mode = "tone";
    private volatile long customFallbacks;
    private static final class Profile {
        final String ringtone;
        final int volumePercent;
        final String promptText;
        final String soundId;
        Profile(String ringtone, int volumePercent, String promptText, String soundId) {
            this.ringtone = ringtone; this.volumePercent = volumePercent;
            this.promptText = promptText; this.soundId = soundId;
        }
    }
    private final LinkedHashMap<String, Profile> owners = new LinkedHashMap<>();
    private volatile Profile playing;

    NativeTimerAlarm(android.content.Context context, NativeSettings settings, Gate gate) {
        this.context = context.getApplicationContext(); this.settings = settings; this.gate = gate;
        audioStore = new NativeAlertAudioStore(this.context);
    }

    @Override public synchronized void start() {
        startOwner("timer", new Profile(settings.timerRingtone(), settings.timerVolumePercent(),
                "计时器时间到了", settings.timerSoundId()));
    }
    synchronized void startAlarm() { startAlarm("classic", 100, "闹钟时间到了", ""); }
    synchronized void startAlarm(String ringtone, int volumePercent, String promptText) {
        startAlarm(ringtone, volumePercent, promptText, "");
    }
    synchronized void startAlarm(String ringtone, int volumePercent, String promptText, String soundId) {
        startOwner("alarm", new Profile(ringtone, volumePercent, promptText, soundId));
    }
    private void startOwner(String owner, Profile profile) {
        owners.put(owner, profile);
        if (workerActive()) return;
        playing = profile;
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
            Profile profile = playing;
            NativeAlertAudioStore.Audio custom = audioStore.resolve(profile.soundId);
            if (custom == null && !profile.soundId.isEmpty()) customFallbacks++;
            mode = custom == null ? "tone" : "local_audio";
            sink = new NativeAudioTrackSink(new NativeVolume(context, settings), profile.volumePercent / 100f);
            sink.start();
            byte[] frame = new byte[640];
            if (custom == null) playTone(token, sink, frame, profile);
            else playCustom(token, sink, frame, custom);
            java.util.Arrays.fill(frame, (byte) 0);
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        catch (RuntimeException error) { failure = "timer_alarm_output_failed"; }
        finally {
            if (sink != null) { sink.stop(); sink.close(); }
            new NativeVolume(context, settings).restoreOutput();
            restartAfterExit(token, Thread.currentThread());
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
    private boolean ownerActive(String owner) { return owners.containsKey(owner) && workerActive(); }
    private boolean workerActive() {
        Thread current = worker;
        return current != null && current.isAlive() && !owners.isEmpty();
    }
    private boolean running(long token) { return token == generation; }
    private synchronized void restartAfterExit(long token, Thread exited) {
        if (worker == exited) worker = null;
        if (token == generation || owners.isEmpty()) return;
        String owner = owners.keySet().iterator().next();
        startOwner(owner, owners.get(owner));
    }
    @Override public String failure() { return failure; }
    @Override public String mode() { return mode; }
    @Override public long customFallbacks() { return customFallbacks; }
    String promptText() { Profile value = playing; return value == null ? "" : value.promptText; }
    private static boolean sounding(String ringtone, long sample) {
        if ("gentle".equals(ringtone)) return sample % 24000L < 16000L;
        if ("urgent".equals(ringtone)) return sample % 8000L < 6000L;
        return (sample / 8000L) % 2 == 0;
    }
    private static double frequency(String ringtone, long sample) {
        if ("gentle".equals(ringtone)) return 660.0;
        if ("urgent".equals(ringtone)) return (sample / 2000L) % 2 == 0 ? 880.0 : 1175.0;
        return 880.0;
    }
    private void playTone(long token, NativeAudioTrackSink sink, byte[] frame, Profile profile) {
        long sample = 0;
        while (running(token)) {
            for (int i = 0; i < 320; i++, sample++) {
                boolean tone = sounding(profile.ringtone, sample);
                double frequency = frequency(profile.ringtone, sample);
                short value = tone ? (short) (Math.sin(2.0 * Math.PI * frequency * sample / 16000.0) * 9000) : 0;
                frame[i * 2] = (byte) value; frame[i * 2 + 1] = (byte) (value >> 8);
            }
            write(token, sink, frame, frame.length);
        }
    }
    private void playCustom(long token, NativeAudioTrackSink sink, byte[] frame,
            NativeAlertAudioStore.Audio audio) {
        try (RandomAccessFile input = new RandomAccessFile(audio.file, "r")) {
            while (running(token)) {
                input.seek(audio.dataOffset); int remaining = audio.dataBytes;
                while (running(token) && remaining > 0) {
                    int count = input.read(frame, 0, Math.min(frame.length, remaining));
                    if (count <= 0 || (count & 1) != 0) throw new IllegalStateException("timer_audio_read_failed");
                    write(token, sink, frame, count); remaining -= count;
                }
            }
        } catch (java.io.IOException error) { throw new IllegalStateException("timer_audio_read_failed", error); }
    }
    private void write(long token, NativeAudioTrackSink sink, byte[] frame, int length) {
        int offset = 0;
        while (running(token) && offset < length) {
            int count = sink.write(frame, offset, length - offset);
            if (count <= 0 || (count & 1) != 0) throw new IllegalStateException("timer_audio_write_failed");
            offset += count;
        }
    }
}
