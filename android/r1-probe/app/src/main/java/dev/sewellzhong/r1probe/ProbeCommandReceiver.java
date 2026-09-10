package dev.sewellzhong.r1probe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Debug;
import android.util.Log;

import java.io.File;
import java.io.PrintWriter;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ProbeCommandReceiver extends BroadcastReceiver {
    private static final String AUDIO_TAG = "R1Audio";
    private static final AtomicBoolean BUSY = new AtomicBoolean(false);

    @Override
    public void onReceive(final Context context, final Intent intent) {
        final String action = intent.getStringExtra("probe_action");
        final String nonce = valueOrDefault(intent.getStringExtra("probe_nonce"), "manual");
        if (!"stereo_record".equals(action) && !"play".equals(action)
                && !"process_wav".equals(action) && !"processed_record".equals(action)
                && !"processed_compare".equals(action)
                && !"factory_audio_validate".equals(action)) {
            Log.e(AUDIO_TAG, "R1_COMMAND_REJECTED nonce=" + nonce + " error=unsupported_action");
            return;
        }
        if (!BUSY.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, failureMarker(action) + " nonce=" + nonce + " error=audio_busy");
            return;
        }
        final PendingResult pendingResult = goAsync();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    if ("stereo_record".equals(action)) {
                        recordStereo(context, intent, nonce);
                    } else if ("process_wav".equals(action)) {
                        processWav(context, intent, nonce);
                    } else if ("processed_record".equals(action)) {
                        recordProcessed(context, intent, nonce);
                    } else if ("processed_compare".equals(action)) {
                        recordProcessedComparison(context, intent, nonce);
                    } else if ("factory_audio_validate".equals(action)) {
                        recordFactoryAudioValidation(context, intent, nonce);
                    } else {
                        play(context, intent, nonce);
                    }
                } catch (Exception e) {
                    Log.e(AUDIO_TAG, failureMarker(action) + " nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                } finally {
                    BUSY.set(false);
                    pendingResult.finish();
                }
            }
        }, "r1-probe-command").start();
    }

    private static void recordStereo(Context context, Intent intent, String nonce) throws Exception {
        int sourceId = intent.getIntExtra("audio_source", AudioSourceSpec.VOICE_COMMUNICATION);
        int durationSeconds = clamp(intent.getIntExtra("duration_seconds", 10), 1, 30);
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_STEREO_RECORD_START nonce=" + nonce
                + " source=" + AudioSourceSpec.nameOf(sourceId)
                + " duration_seconds=" + durationSeconds);
        File diagnostics = diagnosticsDir(context);
        String cuePath = intent.getStringExtra("cue_path");
        File cueFile = cuePath == null ? null : FileNames.restrictedChild(diagnostics, cuePath);
        StereoAudioCapture.Result result = StereoAudioCapture.record(
                diagnostics, sourceId, durationSeconds, sampleId, cueFile);
        Log.i(AUDIO_TAG, "R1_STEREO_RECORD_COMPLETE nonce=" + nonce
                + " stereo_path=" + result.stereoFile.getAbsolutePath()
                + " left_path=" + result.leftFile.getAbsolutePath()
                + " right_path=" + result.rightFile.getAbsolutePath()
                + " average_path=" + result.averageFile.getAbsolutePath()
                + " difference_path=" + result.differenceFile.getAbsolutePath()
                + " metadata_path=" + result.metadataFile.getAbsolutePath()
                + " stereo_pcm_bytes=" + result.stereoBytes
                + " elapsed_ms=" + result.elapsedMillis
                + " partial_reads=" + result.partialReads);
    }

    private static void play(Context context, Intent intent, String nonce) throws Exception {
        File diagnostics = diagnosticsDir(context);
        File wavFile = FileNames.restrictedChild(diagnostics, intent.getStringExtra("file_path"));
        Log.i(AUDIO_TAG, "R1_AUDIO_PLAYBACK_START nonce=" + nonce
                + " path=" + wavFile.getAbsolutePath());
        AudioPlayback.Result result = AudioPlayback.play(wavFile);
        Log.i(AUDIO_TAG, "R1_AUDIO_PLAYBACK_COMPLETE nonce=" + nonce
                + " path=" + wavFile.getAbsolutePath()
                + " pcm_bytes=" + result.pcmBytes
                + " elapsed_ms=" + result.elapsedMillis);
    }

    private static void processWav(Context context, Intent intent, String nonce) throws Exception {
        File diagnostics = diagnosticsDir(context);
        File noiseFile = FileNames.restrictedChild(diagnostics,
                intent.getStringExtra("noise_path"));
        File inputFile = FileNames.restrictedChild(diagnostics,
                intent.getStringExtra("input_path"));
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        File outputFile = new File(diagnostics,
                System.currentTimeMillis() + "-processed-" + sampleId + ".wav");
        File metadataFile = new File(outputFile.getAbsolutePath() + ".meta.txt");
        short[] noise = MonoWavIo.read(noiseFile);
        short[] input = MonoWavIo.read(inputFile);
        long wallStarted = System.nanoTime();
        long cpuStarted = Debug.threadCpuTimeNanos();
        VoiceProcessingPipeline.Result result = VoiceProcessingPipeline.process(noise, input);
        long threadCpuNanos = Debug.threadCpuTimeNanos() - cpuStarted;
        long wallNanos = System.nanoTime() - wallStarted;
        MonoWavIo.write(outputFile, result.samples);
        PrintWriter metadata = new PrintWriter(metadataFile, "UTF-8");
        try {
            metadata.println("purpose=R1 stage1 Java voice processing benchmark");
            metadata.println("format=PCM_S16LE_16000Hz_mono");
            metadata.println("algorithm=balanced_spectral_subtraction_plus_adaptive_gain");
            metadata.println("samples=" + result.samples.length);
            metadata.println("wall_nanos=" + wallNanos);
            metadata.println("thread_cpu_nanos=" + threadCpuNanos);
            metadata.println("pipeline_elapsed_nanos=" + result.elapsedNanos);
            metadata.println("active_frames=" + result.activeFrames);
            metadata.println("maximum_gain_db=" + result.maximumGainDb);
            metadata.println("mean_gain_db=" + result.meanGainDb);
            metadata.println("clipped_samples=" + result.clippedSamples);
        } finally {
            metadata.close();
        }
        Log.i(AUDIO_TAG, "R1_PROCESSING_COMPLETE nonce=" + nonce
                + " output_path=" + outputFile.getAbsolutePath()
                + " metadata_path=" + metadataFile.getAbsolutePath()
                + " samples=" + result.samples.length
                + " wall_nanos=" + wallNanos
                + " thread_cpu_nanos=" + threadCpuNanos
                + " clipped_samples=" + result.clippedSamples);
    }

    private static void recordProcessed(Context context, Intent intent, String nonce) throws Exception {
        int durationSeconds = clamp(intent.getIntExtra("duration_seconds", 20), 5, 60);
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_PROCESSED_RECORD_START nonce=" + nonce
                + " duration_seconds=" + durationSeconds);
        ProcessedAudioCapture.Result result = ProcessedAudioCapture.record(
                diagnosticsDir(context), durationSeconds, sampleId);
        Log.i(AUDIO_TAG, "R1_PROCESSED_RECORD_COMPLETE nonce=" + nonce
                + " output_path=" + result.wavFile.getAbsolutePath()
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
                + " clipped_samples=" + result.stats.clippedSamples);
    }

    private static void recordProcessedComparison(Context context, Intent intent, String nonce)
            throws Exception {
        int durationSeconds = clamp(intent.getIntExtra("duration_seconds", 10), 5, 20);
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        File diagnostics = diagnosticsDir(context);
        String cuePath = intent.getStringExtra("cue_path");
        File cueFile = cuePath == null ? null : FileNames.restrictedChild(diagnostics, cuePath);
        Log.i(AUDIO_TAG, "R1_PROCESSED_COMPARE_START nonce=" + nonce
                + " duration_seconds=" + durationSeconds
                + " cue=" + (cueFile != null));
        ProcessedAudioCapture.Result result = ProcessedAudioCapture.recordComparison(
                diagnostics, durationSeconds, sampleId, cueFile);
        Log.i(AUDIO_TAG, "R1_PROCESSED_COMPARE_COMPLETE nonce=" + nonce
                + " raw_path=" + result.rawWavFile.getAbsolutePath()
                + " processed_path=" + result.wavFile.getAbsolutePath()
                + " metadata_path=" + result.metadataFile.getAbsolutePath()
                + " input_samples=" + result.inputSamples
                + " output_samples=" + result.outputSamples
                + " elapsed_ms=" + result.elapsedMillis
                + " partial_reads=" + result.partialReads
                + " processing_overruns=" + result.processingOverruns
                + " clipped_samples=" + result.stats.clippedSamples);
    }

    private static void recordFactoryAudioValidation(Context context, Intent intent, String nonce)
            throws Exception {
        int durationSeconds = clamp(intent.getIntExtra("duration_seconds", 10), 1, 30);
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_FACTORY_AUDIO_VALIDATION_START nonce=" + nonce
                + " duration_seconds=" + durationSeconds);
        FactoryAudioValidationCapture.Result result = FactoryAudioValidationCapture.record(
                diagnosticsDir(context), durationSeconds, sampleId);
        Log.i(AUDIO_TAG, "R1_FACTORY_AUDIO_VALIDATION_COMPLETE nonce=" + nonce
                + " wav_path=" + result.wavFile.getAbsolutePath()
                + " diagnostic_wav_path=" + (result.diagnosticWavFile == null
                        ? "unavailable" : result.diagnosticWavFile.getAbsolutePath())
                + " metadata_path=" + result.metadataFile.getAbsolutePath()
                + " frames=" + result.frames
                + " sequence_gaps=" + result.sequenceGaps
                + " doa_valid_frames=" + result.doaValidFrames);
    }

    private static File diagnosticsDir(Context context) {
        File external = context.getExternalFilesDir(null);
        if (external == null) {
            throw new IllegalStateException("external_files_unavailable");
        }
        File diagnostics = new File(external, "diagnostics");
        if (!diagnostics.isDirectory() && !diagnostics.mkdirs() && !diagnostics.isDirectory()) {
            throw new IllegalStateException("cannot_create_diagnostics_dir");
        }
        return diagnostics;
    }

    private static String failureMarker(String action) {
        if ("stereo_record".equals(action)) {
            return "R1_STEREO_RECORD_FAILED";
        }
        if ("processed_record".equals(action)) {
            return "R1_PROCESSED_RECORD_FAILED";
        }
        if ("processed_compare".equals(action)) {
            return "R1_PROCESSED_COMPARE_FAILED";
        }
        if ("factory_audio_validate".equals(action)) {
            return "R1_FACTORY_AUDIO_VALIDATION_FAILED";
        }
        return "process_wav".equals(action)
                ? "R1_PROCESSING_FAILED" : "R1_AUDIO_PLAYBACK_FAILED";
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
