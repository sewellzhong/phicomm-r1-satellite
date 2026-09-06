package dev.sewellzhong.r1probe;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;

import java.io.File;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ProcessedAudioSoakService extends Service {
    private static final String AUDIO_TAG = "R1Audio";
    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);

    @Override
    public int onStartCommand(Intent intent, int flags, final int startId) {
        final String nonce = valueOrDefault(
                intent == null ? null : intent.getStringExtra("probe_nonce"), "manual");
        if (!RUNNING.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, "R1_PROCESSED_SOAK_FAILED nonce=" + nonce
                    + " error=audio_busy");
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        final int durationSeconds = clamp(
                intent == null ? 1800 : intent.getIntExtra("duration_seconds", 1800), 20, 3600);
        final String sampleId = FileNames.sanitize(
                intent == null ? null : intent.getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_PROCESSED_SOAK_START nonce=" + nonce
                + " duration_seconds=" + durationSeconds
                + " audio_retained=false");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    ProcessedAudioCapture.Result result = ProcessedAudioCapture.soak(
                            diagnosticsDir(), durationSeconds, sampleId);
                    Log.i(AUDIO_TAG, "R1_PROCESSED_SOAK_COMPLETE nonce=" + nonce
                            + " metadata_path=" + result.metadataFile.getAbsolutePath()
                            + " input_samples=" + result.inputSamples
                            + " output_samples=" + result.outputSamples
                            + " elapsed_ms=" + result.elapsedMillis
                            + " partial_reads=" + result.partialReads
                            + " maximum_process_nanos=" + result.maximumProcessNanos
                            + " total_processing_wall_nanos=" + result.totalProcessingWallNanos
                            + " total_processing_cpu_nanos=" + result.totalProcessingCpuNanos
                            + " processing_overruns=" + result.processingOverruns
                            + " bounded_state_samples=" + result.stats.boundedStateSamples
                            + " workspace_elements=" + result.stats.workspaceElements
                            + " clipped_samples=" + result.stats.clippedSamples
                            + " audio_retained=false");
                } catch (Exception e) {
                    Log.e(AUDIO_TAG, "R1_PROCESSED_SOAK_FAILED nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                } finally {
                    RUNNING.set(false);
                    stopSelf(startId);
                }
            }
        }, "r1-processed-soak").start();
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private File diagnosticsDir() {
        File external = getExternalFilesDir(null);
        if (external == null) {
            throw new IllegalStateException("external_files_unavailable");
        }
        File diagnostics = new File(external, "diagnostics");
        if (!diagnostics.isDirectory() && !diagnostics.mkdirs() && !diagnostics.isDirectory()) {
            throw new IllegalStateException("cannot_create_diagnostics_dir");
        }
        return diagnostics;
    }

    private static int clamp(int value, int minimum, int maximum) {
        return Math.max(minimum, Math.min(maximum, value));
    }

    private static String valueOrDefault(String value, String fallback) {
        return value == null ? fallback : value;
    }

    private static String safeMessage(Throwable exception) {
        String message = exception.getMessage();
        return message == null ? "none" : message.replace(' ', '_');
    }
}
