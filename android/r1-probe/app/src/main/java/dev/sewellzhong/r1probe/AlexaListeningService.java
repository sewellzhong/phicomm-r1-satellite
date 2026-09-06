package dev.sewellzhong.r1probe;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

/** Explicitly started, bounded foreground listening session; no PCM storage or network. */
public final class AlexaListeningService extends Service {
    private static final String TAG = "R1Audio";
    private final Object recorderLock = new Object();
    private final Handler handler = new Handler();
    private volatile boolean stopping;
    private volatile boolean timedOut;
    private boolean running;
    private AudioRecord recorder;
    private Thread worker;
    private PowerManager.WakeLock wakeLock;
    private final Runnable watchdog = () -> {
        timedOut = true;
        stopCapture();
    };

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if ("stop".equals(intent.getAction())) {
            stopCapture();
            if (!running) { stopSelf(startId); }
            return START_NOT_STICKY;
        }
        if (running) {
            Log.w(TAG, "R1_ALEXA_REJECTED reason=already_running");
            return START_NOT_STICKY;
        }
        final String nonce = FileNames.sanitize(intent.getStringExtra("probe_nonce"));
        final int seconds = Math.max(5, Math.min(3600,
                intent.getIntExtra("duration_seconds", 60)));
        stopping = false;
        timedOut = false;
        running = true;
        try {
            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationManager manager = (NotificationManager)
                        getSystemService(NOTIFICATION_SERVICE);
                manager.createNotificationChannel(new NotificationChannel("alexa",
                        "Alexa listening", NotificationManager.IMPORTANCE_LOW));
                builder = new Notification.Builder(this, "alexa");
            } else {
                builder = new Notification.Builder(this);
            }
            startForeground(32, builder.setSmallIcon(R.drawable.ic_probe)
                    .setContentTitle("Alexa 唤醒测试")
                    .setContentText("正在本地监听，不保存录音")
                    .setOngoing(true).build());
            PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "r1probe:alexa");
            wakeLock.acquire((seconds + 15L) * 1000L);
            handler.postDelayed(watchdog, (seconds + 10L) * 1000L);
            worker = new Thread(() -> listen(nonce, seconds), "r1-alexa-listener");
            worker.start();
        } catch (RuntimeException e) {
            Log.e(TAG, "R1_ALEXA_FAILED nonce=" + nonce + " reason=start_failed", e);
            running = false;
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    private void listen(String nonce, int seconds) {
        long samples = 0;
        int events = 0;
        int partialReads = 0;
        int overruns = 0;
        int peak = 0;
        double sumSquares = 0;
        long started = System.nanoTime();
        try (AlexaKwsEngine engine = new AlexaKwsEngine(getAssets())) {
            int minimum = AudioRecord.getMinBufferSize(16000,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) {
                throw new IllegalStateException("invalid_audio_buffer");
            }
            if (stopping) { return; }
            AlexaTestCues.play(getCacheDir(), false);
            Log.i(TAG, "R1_ALEXA_CUE_COMPLETE nonce=" + nonce + " cue=start");
            Thread.sleep(200L);
            synchronized (recorderLock) {
                if (stopping) {
                    Log.i(TAG, "R1_ALEXA_STOPPED nonce=" + nonce + " samples=0");
                    return;
                }
                recorder = new AudioRecord(AudioSourceSpec.VOICE_COMMUNICATION, 16000,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                        Math.max(minimum, 6400));
                if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                    throw new IllegalStateException("audio_not_initialized");
                }
                recorder.startRecording();
                if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                    throw new IllegalStateException("audio_not_recording");
                }
            }
            Log.i(TAG, "R1_ALEXA_READY nonce=" + nonce + " model=" + engine.modelId()
                    + " source=VOICE_COMMUNICATION software_denoiser=false"
                    + " duration_seconds=" + seconds + " audio_retained=false");
            short[] frame = new short[KwsConfig.FRAME_SAMPLES];
            int filled = 0;
            long target = seconds * 16000L;
            while (!stopping && samples < target) {
                int requested = frame.length - filled;
                int read = recorder.read(frame, filled, requested);
                if (stopping) { break; }
                if (read <= 0) { throw new IllegalStateException("audio_read_" + read); }
                if (read < requested) { partialReads++; }
                filled += read;
                if (filled != frame.length) { continue; }
                for (short sample : frame) {
                    peak = Math.max(peak, Math.abs((int) sample));
                    sumSquares += (double) sample * sample;
                }
                long before = System.nanoTime();
                KwsDetection event = engine.acceptFrame(frame, 0, frame.length, samples);
                if (System.nanoTime() - before > 20_000_000L) { overruns++; }
                samples += frame.length;
                filled = 0;
                if (event.detected) {
                    events++;
                    Log.i(TAG, "R1_ALEXA_DETECTED nonce=" + nonce + " event=" + events
                            + " end_sample=" + event.endSampleIndex
                            + " score=" + event.score);
                }
            }
            if (timedOut) { throw new IllegalStateException("capture_watchdog"); }
            releaseRecorder();
            AlexaTestCues.play(getCacheDir(), true);
            Log.i(TAG, "R1_ALEXA_CUE_COMPLETE nonce=" + nonce + " cue=end");
            KwsMetrics metrics = engine.metrics();
            Log.i(TAG, (stopping ? "R1_ALEXA_STOPPED" : "R1_ALEXA_COMPLETE")
                    + " nonce=" + nonce + " samples=" + samples + " detections=" + events
                    + " peak=" + peak + " rms=" + Math.sqrt(sumSquares / Math.max(1, samples))
                    + " partial_reads=" + partialReads + " overruns=" + overruns
                    + " inference_count=" + engine.inferenceCount()
                    + " max_raw_score=" + engine.maximumRawScore()
                    + " max_frame_us=" + metrics.maximumFrameNanos / 1000
                    + " cpu_nanos=" + metrics.cpuNanos + " rtf=" + metrics.realTimeFactor()
                    + " elapsed_ms=" + (System.nanoTime() - started) / 1_000_000L
                    + " audio_retained=false");
        } catch (Exception | LinkageError e) {
            Log.e(TAG, "R1_ALEXA_FAILED nonce=" + nonce
                    + " samples=" + samples + " reason=" + e.getClass().getSimpleName(), e);
        } finally {
            handler.removeCallbacks(watchdog);
            releaseRecorder();
            handler.post(() -> {
                running = false;
                stopForeground(true);
                stopSelf();
            });
        }
    }

    private void releaseRecorder() {
        synchronized (recorderLock) {
            if (recorder != null) {
                try { recorder.stop(); } catch (IllegalStateException ignored) { }
                recorder.release();
                recorder = null;
            }
        }
    }

    private void stopCapture() {
        stopping = true;
        synchronized (recorderLock) {
            if (recorder != null) {
                try { recorder.stop(); } catch (IllegalStateException ignored) { }
            }
        }
    }

    @Override public void onDestroy() {
        stopCapture();
        handler.removeCallbacks(watchdog);
        if (worker != null) { worker.interrupt(); }
        if (wakeLock != null && wakeLock.isHeld()) { wakeLock.release(); }
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
