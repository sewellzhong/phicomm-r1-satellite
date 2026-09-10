package dev.sewellzhong.r1probe;

import dev.sewellzhong.r1probe.factoryaudio.FactoryAudioClient;
import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded, explicitly unattested capture used only to collect factory-chain evidence. */
final class FactoryAudioValidationCapture {
    private static final int FRAMES_PER_SECOND = 50;
    private static final int PLAYBACK_LEAD_IN_MILLIS = 1000;
    private static final int PLAYBACK_TAIL_MILLIS = 1000;
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private FactoryAudioValidationCapture() {}

    static Result record(File outputDirectory, int durationSeconds, String sampleId)
            throws Exception {
        return record(outputDirectory, durationSeconds, sampleId, null, -1, -1);
    }

    static Result record(File outputDirectory, int durationSeconds, String sampleId,
            File playbackReferenceFile, int musicVolumeIndex, int musicVolumeMaxIndex)
            throws Exception {
        if (durationSeconds < 1 || durationSeconds > 30) {
            throw new IllegalArgumentException("factory_audio_validation_duration_out_of_range");
        }
        int playbackPcmBytes = 0;
        if (playbackReferenceFile != null) {
            playbackPcmBytes = WavHeader.validate(playbackReferenceFile);
            validatePlaybackPlan(durationSeconds, playbackPcmBytes,
                    musicVolumeIndex, musicVolumeMaxIndex);
        }
        String baseName = System.currentTimeMillis() + "-factory-audio-validation-" + sampleId;
        File wavFile = new File(outputDirectory, baseName + ".wav");
        File diagnosticWavFile = new File(outputDirectory, baseName + "-diagnostic-stereo.wav");
        File metadataFile = new File(outputDirectory, baseName + ".meta.txt");
        int targetFrames = durationSeconds * FRAMES_PER_SECOND;
        int frames = 0;
        long firstSequence = 0;
        long lastSequence = 0;
        long sequenceGaps = 0;
        long agentDroppedFrames = 0;
        int doaValidFrames = 0;
        int[] doaHistogram = new int[36];
        long startedAtEpochMillis = System.currentTimeMillis();
        long startedAtNanos = System.nanoTime();
        boolean complete = false;
        int diagnosticChannels = 0;
        int diagnosticSelectedOutputChannel = 0;
        int diagnosticPcmBytes = 0;
        FactoryAudio.Health startHealth;
        PlaybackRun playback = null;

        FileOutputStream output = new FileOutputStream(wavFile);
        FileOutputStream diagnosticOutput = null;
        try {
            output.write(WavHeader.create(0));
            FactoryAudioClient client = FactoryAudioClient.connect();
            try {
                startHealth = client.startUnattestedValidationCapture();
                if (playbackReferenceFile != null) {
                    playback = new PlaybackRun(playbackReferenceFile);
                    playback.start();
                }
                while (frames < targetFrames) {
                    FactoryAudio.AudioFrame frame = client.readFrame();
                    long sequence = frame.getSequence();
                    if (sequence <= 0 || (lastSequence != 0 && sequence <= lastSequence)) {
                        throw new IllegalStateException(
                                "factory_audio_validation_non_monotonic_sequence_" + sequence);
                    }
                    if (firstSequence == 0) firstSequence = sequence;
                    if (lastSequence != 0 && sequence > lastSequence + 1) {
                        sequenceGaps += sequence - lastSequence - 1;
                    }
                    lastSequence = sequence;
                    agentDroppedFrames = Math.max(agentDroppedFrames, frame.getDroppedFrames());
                    if (frame.getDoaValid()) {
                        int doa = frame.getDoaDegrees();
                        if (doa < 0 || doa >= 360) {
                            throw new IllegalStateException(
                                    "factory_audio_validation_invalid_doa_" + doa);
                        }
                        doaValidFrames++;
                        doaHistogram[doa / 10]++;
                    }
                    output.write(frame.getPcmS16Le().toByteArray());
                    int frameDiagnosticChannels = frame.getDiagnosticOutputChannels();
                    if (frames == 0 && frameDiagnosticChannels > 0) {
                        diagnosticChannels = frameDiagnosticChannels;
                        diagnosticSelectedOutputChannel =
                                frame.getDiagnosticSelectedOutputChannel();
                        diagnosticOutput = new FileOutputStream(diagnosticWavFile);
                        diagnosticOutput.write(WavHeader.create(0, diagnosticChannels));
                    }
                    if (frameDiagnosticChannels != diagnosticChannels) {
                        throw new IllegalStateException(
                                "factory_audio_validation_diagnostic_shape_changed_"
                                        + diagnosticChannels + "_" + frameDiagnosticChannels);
                    }
                    if (diagnosticChannels > 0
                            && frame.getDiagnosticSelectedOutputChannel()
                            != diagnosticSelectedOutputChannel) {
                        throw new IllegalStateException(
                                "factory_audio_validation_selected_channel_changed");
                    }
                    if (diagnosticOutput != null) {
                        byte[] diagnostic = frame.getDiagnosticInterleavedPcmS16Le().toByteArray();
                        diagnosticOutput.write(diagnostic);
                        diagnosticPcmBytes += diagnostic.length;
                    }
                    frames++;
                }
                if (playback != null) playback.await(playbackPcmBytes);
                client.stopCapture();
            } finally {
                client.close();
            }
            complete = true;
        } finally {
            if (playback != null) playback.cancelAndAwait();
            if (diagnosticOutput != null) diagnosticOutput.close();
            output.close();
            if (!complete) {
                if (wavFile.exists() && !wavFile.delete()) wavFile.deleteOnExit();
                if (diagnosticWavFile.exists() && !diagnosticWavFile.delete()) {
                    diagnosticWavFile.deleteOnExit();
                }
            }
        }

        int pcmBytes = frames * FactoryAudioClient.FRAME_BYTES;
        RandomAccessFile header = new RandomAccessFile(wavFile, "rw");
        try {
            header.seek(0);
            header.write(WavHeader.create(pcmBytes));
        } finally {
            header.close();
        }
        if (diagnosticChannels > 0) {
            RandomAccessFile diagnosticHeader = new RandomAccessFile(diagnosticWavFile, "rw");
            try {
                diagnosticHeader.seek(0);
                diagnosticHeader.write(WavHeader.create(diagnosticPcmBytes, diagnosticChannels));
            } finally {
                diagnosticHeader.close();
            }
        }
        long elapsedMillis = (System.nanoTime() - startedAtNanos) / 1_000_000L;
        writeMetadata(metadataFile, durationSeconds, startedAtEpochMillis, elapsedMillis,
                startHealth, frames, pcmBytes, firstSequence, lastSequence, sequenceGaps,
                agentDroppedFrames, doaValidFrames, doaHistogram, sha256(wavFile),
                diagnosticChannels, diagnosticPcmBytes,
                diagnosticSelectedOutputChannel,
                diagnosticChannels > 0 ? diagnosticWavFile.getName() : "",
                diagnosticChannels > 0 ? sha256(diagnosticWavFile) : "",
                startedAtNanos, playbackReferenceFile, playbackPcmBytes,
                musicVolumeIndex, musicVolumeMaxIndex, playback);
        return new Result(wavFile, diagnosticChannels > 0 ? diagnosticWavFile : null,
                metadataFile, frames, sequenceGaps, doaValidFrames);
    }

    private static void writeMetadata(File file, int durationSeconds, long startedAtEpochMillis,
            long elapsedMillis, FactoryAudio.Health health, int frames, int pcmBytes,
            long firstSequence, long lastSequence, long sequenceGaps, long agentDroppedFrames,
            int doaValidFrames, int[] doaHistogram, String wavSha256, int diagnosticChannels,
            int diagnosticPcmBytes, int diagnosticSelectedOutputChannel,
            String diagnosticWavName, String diagnosticWavSha256,
            long captureStartedAtNanos, File playbackReferenceFile, int playbackPcmBytes,
            int musicVolumeIndex, int musicVolumeMaxIndex, PlaybackRun playback) throws Exception {
        PrintWriter metadata = new PrintWriter(file, "UTF-8");
        try {
            metadata.println("purpose=R1 factory audio bounded validation capture");
            metadata.println("attestation=validation_only_not_production");
            metadata.println("source=factory_proxy_unattested_validation");
            metadata.println("format=PCM_S16LE_16000Hz_mono_20ms");
            metadata.println("target_duration_seconds=" + durationSeconds);
            metadata.println("started_at_epoch_ms=" + startedAtEpochMillis);
            metadata.println("elapsed_ms=" + elapsedMillis);
            metadata.println("backend=" + health.getBackendName());
            metadata.println("vendor_board_version=" + health.getVendorBoardVersion());
            metadata.println("raw_mic_channels_claimed=" + health.getRawMicChannels());
            metadata.println("aec_reference_channels_claimed=" + health.getAecReferenceChannels());
            metadata.println("aec_reference_channels_configured="
                    + health.getConfiguredAecReferenceChannels());
            metadata.println("array_processing_claimed=" + health.getArrayProcessingActive());
            metadata.println("aec_active_claimed=" + health.getAecActive());
            metadata.println("aec_configured=" + health.getAecConfigured());
            metadata.println("frames=" + frames);
            metadata.println("pcm_bytes=" + pcmBytes);
            metadata.println("first_sequence=" + firstSequence);
            metadata.println("last_sequence=" + lastSequence);
            metadata.println("sequence_gaps=" + sequenceGaps);
            metadata.println("agent_dropped_frames=" + agentDroppedFrames);
            metadata.println("doa_valid_frames=" + doaValidFrames);
            metadata.println("doa_histogram_10_degrees=" + join(doaHistogram));
            metadata.println("wav_sha256=" + wavSha256);
            metadata.println("diagnostic_output_channels=" + diagnosticChannels);
            metadata.println("diagnostic_pcm_bytes=" + diagnosticPcmBytes);
            metadata.println("diagnostic_selected_output_channel="
                    + diagnosticSelectedOutputChannel);
            metadata.println("diagnostic_wav_name=" + diagnosticWavName);
            metadata.println("diagnostic_wav_sha256=" + diagnosticWavSha256);
            metadata.println("playback_reference_present=" + (playbackReferenceFile != null));
            if (playbackReferenceFile != null) {
                metadata.println("capture_started_monotonic_ns=" + captureStartedAtNanos);
                metadata.println("playback_reference_wav_name="
                        + playbackReferenceFile.getName());
                metadata.println("playback_reference_wav_sha256="
                        + sha256(playbackReferenceFile));
                metadata.println("playback_reference_pcm_bytes=" + playbackPcmBytes);
                metadata.println("playback_reference_lead_in_ms="
                        + PLAYBACK_LEAD_IN_MILLIS);
                metadata.println("playback_started_monotonic_ns=" + playback.startedAtNanos);
                metadata.println("playback_completed_monotonic_ns=" + playback.completedAtNanos);
                metadata.println("playback_elapsed_ms=" + playback.result.elapsedMillis);
                metadata.println("music_volume_index=" + musicVolumeIndex);
                metadata.println("music_volume_max_index=" + musicVolumeMaxIndex);
                metadata.println("music_volume_percent="
                        + Math.round(100.0f * musicVolumeIndex / musicVolumeMaxIndex));
            }
        } finally {
            metadata.close();
        }
    }

    private static String join(int[] values) {
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < values.length; index++) {
            if (index > 0) result.append(',');
            result.append(values[index]);
        }
        return result.toString();
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        FileInputStream input = new FileInputStream(file);
        try {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        } finally {
            input.close();
        }
        StringBuilder value = new StringBuilder();
        for (byte item : digest.digest()) {
            int unsigned = item & 0xff;
            value.append(HEX[unsigned >>> 4]).append(HEX[unsigned & 0x0f]);
        }
        return value.toString();
    }

    static void validatePlaybackPlan(int durationSeconds, int playbackPcmBytes,
            int musicVolumeIndex, int musicVolumeMaxIndex) {
        long availableMillis = durationSeconds * 1000L
                - PLAYBACK_LEAD_IN_MILLIS - PLAYBACK_TAIL_MILLIS;
        long playbackMillis = playbackPcmBytes * 1000L
                / (WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE);
        long availablePcmBytes = availableMillis * WavHeader.SAMPLE_RATE
                * WavHeader.BYTES_PER_SAMPLE / 1000L;
        if (playbackPcmBytes <= 0 || (playbackPcmBytes & 1) != 0
                || playbackMillis <= 0 || playbackPcmBytes > availablePcmBytes) {
            throw new IllegalArgumentException("factory_audio_playback_reference_too_long");
        }
        if (musicVolumeMaxIndex <= 0 || musicVolumeIndex < 0
                || musicVolumeIndex > musicVolumeMaxIndex) {
            throw new IllegalArgumentException("factory_audio_music_volume_invalid");
        }
    }

    private static final class PlaybackRun implements Runnable {
        private final File referenceFile;
        private final AtomicReference<Throwable> failure = new AtomicReference<Throwable>();
        private final Thread thread;
        volatile long startedAtNanos;
        volatile long completedAtNanos;
        volatile AudioPlayback.Result result;

        PlaybackRun(File referenceFile) {
            this.referenceFile = referenceFile;
            thread = new Thread(this, "r1-factory-aec-reference");
        }

        void start() {
            thread.start();
        }

        @Override
        public void run() {
            try {
                Thread.sleep(PLAYBACK_LEAD_IN_MILLIS);
                result = AudioPlayback.play(referenceFile);
                startedAtNanos = result.playbackStartedAtNanos;
                completedAtNanos = result.playbackCompletedAtNanos;
            } catch (Exception error) {
                failure.set(error);
            }
        }

        void await(int pcmBytes) throws Exception {
            long playbackMillis = pcmBytes * 1000L
                    / (WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE);
            thread.join(playbackMillis + PLAYBACK_LEAD_IN_MILLIS + 4000L);
            if (thread.isAlive()) {
                throw new IllegalStateException("factory_audio_playback_reference_timeout");
            }
            Throwable error = failure.get();
            if (error != null) {
                throw new IllegalStateException("factory_audio_playback_reference_failed", error);
            }
            if (result == null || startedAtNanos <= 0 || completedAtNanos <= startedAtNanos) {
                throw new IllegalStateException("factory_audio_playback_reference_incomplete");
            }
        }

        void cancelAndAwait() {
            if (!thread.isAlive()) return;
            thread.interrupt();
            try {
                thread.join(4000L);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }
    }

    static final class Result {
        final File wavFile;
        final File diagnosticWavFile;
        final File metadataFile;
        final int frames;
        final long sequenceGaps;
        final int doaValidFrames;

        Result(File wavFile, File diagnosticWavFile, File metadataFile, int frames,
                long sequenceGaps,
                int doaValidFrames) {
            this.wavFile = wavFile;
            this.diagnosticWavFile = diagnosticWavFile;
            this.metadataFile = metadataFile;
            this.frames = frames;
            this.sequenceGaps = sequenceGaps;
            this.doaValidFrames = doaValidFrames;
        }
    }
}
