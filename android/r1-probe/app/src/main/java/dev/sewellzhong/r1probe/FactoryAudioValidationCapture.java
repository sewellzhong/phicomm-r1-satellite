package dev.sewellzhong.r1probe;

import dev.sewellzhong.r1probe.factoryaudio.FactoryAudioClient;
import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.security.MessageDigest;

/** Bounded, explicitly unattested capture used only to collect factory-chain evidence. */
final class FactoryAudioValidationCapture {
    private static final int FRAMES_PER_SECOND = 50;
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private FactoryAudioValidationCapture() {}

    static Result record(File outputDirectory, int durationSeconds, String sampleId)
            throws Exception {
        if (durationSeconds < 1 || durationSeconds > 30) {
            throw new IllegalArgumentException("factory_audio_validation_duration_out_of_range");
        }
        String baseName = System.currentTimeMillis() + "-factory-audio-validation-" + sampleId;
        File wavFile = new File(outputDirectory, baseName + ".wav");
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
        FactoryAudio.Health startHealth;

        FileOutputStream output = new FileOutputStream(wavFile);
        try {
            output.write(WavHeader.create(0));
            FactoryAudioClient client = FactoryAudioClient.connect();
            try {
                startHealth = client.startUnattestedValidationCapture();
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
                    frames++;
                }
                client.stopCapture();
            } finally {
                client.close();
            }
            complete = true;
        } finally {
            output.close();
            if (!complete && wavFile.exists() && !wavFile.delete()) wavFile.deleteOnExit();
        }

        int pcmBytes = frames * FactoryAudioClient.FRAME_BYTES;
        RandomAccessFile header = new RandomAccessFile(wavFile, "rw");
        try {
            header.seek(0);
            header.write(WavHeader.create(pcmBytes));
        } finally {
            header.close();
        }
        long elapsedMillis = (System.nanoTime() - startedAtNanos) / 1_000_000L;
        writeMetadata(metadataFile, durationSeconds, startedAtEpochMillis, elapsedMillis,
                startHealth, frames, pcmBytes, firstSequence, lastSequence, sequenceGaps,
                agentDroppedFrames, doaValidFrames, doaHistogram, sha256(wavFile));
        return new Result(wavFile, metadataFile, frames, sequenceGaps, doaValidFrames);
    }

    private static void writeMetadata(File file, int durationSeconds, long startedAtEpochMillis,
            long elapsedMillis, FactoryAudio.Health health, int frames, int pcmBytes,
            long firstSequence, long lastSequence, long sequenceGaps, long agentDroppedFrames,
            int doaValidFrames, int[] doaHistogram, String wavSha256) throws Exception {
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
            metadata.println("array_processing_claimed=" + health.getArrayProcessingActive());
            metadata.println("aec_active_claimed=" + health.getAecActive());
            metadata.println("frames=" + frames);
            metadata.println("pcm_bytes=" + pcmBytes);
            metadata.println("first_sequence=" + firstSequence);
            metadata.println("last_sequence=" + lastSequence);
            metadata.println("sequence_gaps=" + sequenceGaps);
            metadata.println("agent_dropped_frames=" + agentDroppedFrames);
            metadata.println("doa_valid_frames=" + doaValidFrames);
            metadata.println("doa_histogram_10_degrees=" + join(doaHistogram));
            metadata.println("wav_sha256=" + wavSha256);
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

    static final class Result {
        final File wavFile;
        final File metadataFile;
        final int frames;
        final long sequenceGaps;
        final int doaValidFrames;

        Result(File wavFile, File metadataFile, int frames, long sequenceGaps,
                int doaValidFrames) {
            this.wavFile = wavFile;
            this.metadataFile = metadataFile;
            this.frames = frames;
            this.sequenceGaps = sequenceGaps;
            this.doaValidFrames = doaValidFrames;
        }
    }
}
