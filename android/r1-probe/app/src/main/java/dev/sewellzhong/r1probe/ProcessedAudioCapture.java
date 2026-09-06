package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.os.Debug;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.util.concurrent.atomic.AtomicBoolean;

final class ProcessedAudioCapture {
    private static final int CALIBRATION_SECONDS = 2;

    private ProcessedAudioCapture() {
    }

    static Result record(File outputDirectory, int durationSeconds, String sampleId) throws Exception {
        return run(outputDirectory, durationSeconds, sampleId, true, false, null);
    }

    static Result soak(File outputDirectory, int durationSeconds, String sampleId) throws Exception {
        return run(outputDirectory, durationSeconds, sampleId, false, false, null);
    }

    static Result recordComparison(File outputDirectory, int durationSeconds, String sampleId,
            File cueFile) throws Exception {
        return run(outputDirectory, durationSeconds, sampleId, true, true, cueFile);
    }

    private static Result run(File outputDirectory, int durationSeconds, String sampleId,
            boolean retainAudio, boolean retainRawAudio, File cueFile) throws Exception {
        int minimumBuffer = AudioRecord.getMinBufferSize(WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimumBuffer <= 0) {
            throw new IllegalStateException("invalid_processed_min_buffer_" + minimumBuffer);
        }
        int bufferBytes = Math.max(minimumBuffer, WavHeader.FRAME_BYTES * 10);
        if ((bufferBytes & 1) != 0) {
            bufferBytes++;
        }
        AudioRecord recorder = new AudioRecord(AudioSourceSpec.VOICE_COMMUNICATION,
                WavHeader.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, bufferBytes);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            recorder.release();
            throw new IllegalStateException("processed_audio_record_not_initialized");
        }
        long runTimestamp = System.currentTimeMillis();
        File wavFile = retainAudio ? new File(outputDirectory,
                runTimestamp + "-processed-stream-" + sampleId + ".wav") : null;
        File rawWavFile = retainRawAudio ? new File(outputDirectory,
                runTimestamp + "-raw-stream-" + sampleId + ".wav") : null;
        File metadataFile = retainAudio
                ? new File(wavFile.getAbsolutePath() + ".meta.txt")
                : new File(outputDirectory, runTimestamp + "-processed-soak-"
                        + sampleId + ".meta.txt");
        int targetSamples = durationSeconds * WavHeader.SAMPLE_RATE;
        short[] calibration = new short[CALIBRATION_SECONDS * WavHeader.SAMPLE_RATE];
        byte[] readBuffer = new byte[bufferBytes];
        short[] inputBuffer = new short[bufferBytes / 2];
        short[] processedBuffer = new short[inputBuffer.length + VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES];
        short[] tailBuffer = new short[VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES];
        byte[] writeBuffer = retainAudio ? new byte[processedBuffer.length * 2] : null;
        int calibrationSamples = 0;
        int inputSamples = 0;
        int outputSamples = 0;
        int partialReads = 0;
        long maximumProcessNanos = 0L;
        long totalProcessingWallNanos = 0L;
        long totalProcessingCpuNanos = 0L;
        int processingOverruns = 0;
        boolean complete = false;
        long startedAtEpochMillis = System.currentTimeMillis();
        long startedAtNanos = System.nanoTime();
        final AtomicBoolean captureFinished = new AtomicBoolean(false);
        final AtomicBoolean watchdogFired = new AtomicBoolean(false);
        final AudioRecord watchdogRecorder = recorder;
        Thread watchdog = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep((durationSeconds + CALIBRATION_SECONDS + 10L) * 1000L);
                    if (captureFinished.compareAndSet(false, true)) {
                        watchdogFired.set(true);
                        if (watchdogRecorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                            watchdogRecorder.stop();
                        }
                    }
                } catch (InterruptedException ignored) {
                    // Normal completion.
                }
            }
        }, "r1-processed-watchdog");
        FileOutputStream output = null;
        FileOutputStream rawOutput = null;
        StreamingVoiceProcessor processor = null;
        try {
            recorder.startRecording();
            watchdog.start();
            while (calibrationSamples < calibration.length) {
                int requestedBytes = Math.min(readBuffer.length,
                        (calibration.length - calibrationSamples) * 2);
                int read = readChecked(recorder, readBuffer, requestedBytes, watchdogFired);
                if (read < requestedBytes) {
                    partialReads++;
                }
                calibrationSamples += decode(readBuffer, read, calibration, calibrationSamples);
            }
            recorder.stop();
            long initializationWallStarted = System.nanoTime();
            long initializationCpuStarted = Debug.threadCpuTimeNanos();
            processor = new StreamingVoiceProcessor(calibration);
            totalProcessingCpuNanos += Debug.threadCpuTimeNanos() - initializationCpuStarted;
            totalProcessingWallNanos += System.nanoTime() - initializationWallStarted;
            if (retainAudio) {
                output = new FileOutputStream(wavFile);
                output.write(WavHeader.create(0));
            }
            if (retainRawAudio) {
                rawOutput = new FileOutputStream(rawWavFile);
                rawOutput.write(WavHeader.create(0));
            }
            if (cueFile != null) {
                AudioPlayback.play(cueFile);
            }
            recorder.startRecording();
            while (inputSamples < targetSamples) {
                int requestedBytes = Math.min(readBuffer.length, (targetSamples - inputSamples) * 2);
                int read = readChecked(recorder, readBuffer, requestedBytes, watchdogFired);
                if (read < requestedBytes) {
                    partialReads++;
                }
                if (retainRawAudio) {
                    rawOutput.write(readBuffer, 0, read);
                }
                int inputLength = decode(readBuffer, read, inputBuffer, 0);
                long processStarted = System.nanoTime();
                long processCpuStarted = Debug.threadCpuTimeNanos();
                int processedLength = processor.processInto(inputBuffer, 0, inputLength,
                        processedBuffer, 0);
                long processNanos = System.nanoTime() - processStarted;
                totalProcessingCpuNanos += Debug.threadCpuTimeNanos() - processCpuStarted;
                totalProcessingWallNanos += processNanos;
                maximumProcessNanos = Math.max(maximumProcessNanos, processNanos);
                long audioNanos = inputLength * 1_000_000_000L / WavHeader.SAMPLE_RATE;
                if (processNanos > audioNanos) {
                    processingOverruns++;
                }
                if (retainAudio) {
                    writeSamples(output, processedBuffer, processedLength, writeBuffer);
                }
                inputSamples += inputLength;
                outputSamples += processedLength;
            }
            long finishWallStarted = System.nanoTime();
            long finishCpuStarted = Debug.threadCpuTimeNanos();
            int tailLength = processor.finishInto(tailBuffer, 0);
            totalProcessingCpuNanos += Debug.threadCpuTimeNanos() - finishCpuStarted;
            totalProcessingWallNanos += System.nanoTime() - finishWallStarted;
            if (retainAudio) {
                writeSamples(output, tailBuffer, tailLength, writeBuffer);
            }
            outputSamples += tailLength;
            if (outputSamples != targetSamples) {
                throw new IllegalStateException("processed_output_length_" + outputSamples);
            }
            complete = true;
            captureFinished.set(true);
            watchdog.interrupt();
        } finally {
            captureFinished.set(true);
            watchdog.interrupt();
            if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                recorder.stop();
            }
            recorder.release();
            if (output != null) {
                output.close();
            }
            if (rawOutput != null) {
                rawOutput.close();
            }
            if (!complete && wavFile != null && wavFile.exists() && !wavFile.delete()) {
                wavFile.deleteOnExit();
            }
            if (!complete && rawWavFile != null && rawWavFile.exists()
                    && !rawWavFile.delete()) {
                rawWavFile.deleteOnExit();
            }
        }
        if (retainAudio) {
            RandomAccessFile header = new RandomAccessFile(wavFile, "rw");
            try {
                header.seek(0);
                header.write(WavHeader.create(outputSamples * 2));
            } finally {
                header.close();
            }
        }
        if (retainRawAudio) {
            RandomAccessFile rawHeader = new RandomAccessFile(rawWavFile, "rw");
            try {
                rawHeader.seek(0);
                rawHeader.write(WavHeader.create(inputSamples * 2));
            } finally {
                rawHeader.close();
            }
        }
        long elapsedMillis = (System.nanoTime() - startedAtNanos) / 1_000_000L;
        StreamingVoiceProcessor.Stats stats = processor.stats();
        writeMetadata(metadataFile, retainAudio, retainRawAudio, cueFile != null,
                durationSeconds, startedAtEpochMillis, elapsedMillis,
                calibrationSamples, inputSamples, outputSamples, partialReads,
                maximumProcessNanos, totalProcessingWallNanos, totalProcessingCpuNanos,
                processingOverruns, stats);
        return new Result(wavFile, rawWavFile, metadataFile, inputSamples, outputSamples, elapsedMillis,
                partialReads, maximumProcessNanos, totalProcessingWallNanos,
                totalProcessingCpuNanos, processingOverruns, stats);
    }

    private static int readChecked(AudioRecord recorder, byte[] buffer, int requested,
            AtomicBoolean watchdogFired) {
        int read = recorder.read(buffer, 0, requested);
        if (watchdogFired.get()) {
            throw new IllegalStateException("processed_audio_read_timeout");
        }
        if (read < 0) {
            throw new IllegalStateException("processed_audio_read_error_" + read);
        }
        if (read == 0) {
            throw new IllegalStateException("processed_audio_empty_read");
        }
        if ((read & 1) != 0) {
            throw new IllegalStateException("processed_audio_odd_read_" + read);
        }
        return read;
    }

    private static int decode(byte[] bytes, int length, short[] output, int outputOffset) {
        int samples = length / 2;
        for (int index = 0; index < samples; index++) {
            int offset = index * 2;
            output[outputOffset + index] = (short) ((bytes[offset] & 0xff)
                    | (bytes[offset + 1] << 8));
        }
        return samples;
    }

    private static void writeSamples(FileOutputStream output, short[] samples, int length,
            byte[] bytes) throws Exception {
        for (int index = 0; index < length; index++) {
            bytes[index * 2] = (byte) (samples[index] & 0xff);
            bytes[index * 2 + 1] = (byte) ((samples[index] >>> 8) & 0xff);
        }
        output.write(bytes, 0, length * 2);
    }

    private static void writeMetadata(File file, boolean retainAudio, boolean retainRawAudio,
            boolean startCuePlayed, int durationSeconds,
            long startedAtEpochMillis,
            long elapsedMillis, int calibrationSamples, int inputSamples, int outputSamples,
            int partialReads, long maximumProcessNanos, long totalProcessingWallNanos,
            long totalProcessingCpuNanos, int processingOverruns,
            StreamingVoiceProcessor.Stats stats) throws Exception {
        PrintWriter metadata = new PrintWriter(file, "UTF-8");
        try {
            metadata.println("purpose=R1 stage1 bounded streaming processing diagnostic");
            metadata.println("format=PCM_S16LE_16000Hz_mono");
            metadata.println("frame_ms=20");
            metadata.println("audio_retained=" + retainAudio);
            metadata.println("raw_audio_retained=" + retainRawAudio);
            metadata.println("start_cue_played=" + startCuePlayed);
            metadata.println("calibration_samples=" + calibrationSamples);
            metadata.println("target_duration_seconds=" + durationSeconds);
            metadata.println("started_at_epoch_ms=" + startedAtEpochMillis);
            metadata.println("elapsed_ms=" + elapsedMillis);
            metadata.println("input_samples=" + inputSamples);
            metadata.println("output_samples=" + outputSamples);
            metadata.println("partial_reads=" + partialReads);
            metadata.println("maximum_process_nanos=" + maximumProcessNanos);
            metadata.println("total_processing_wall_nanos=" + totalProcessingWallNanos);
            metadata.println("total_processing_cpu_nanos=" + totalProcessingCpuNanos);
            metadata.println("processing_overruns=" + processingOverruns);
            metadata.println("bounded_state_samples=" + stats.boundedStateSamples);
            metadata.println("workspace_elements=" + stats.workspaceElements);
            metadata.println("active_frames=" + stats.activeFrames);
            metadata.println("clipped_samples=" + stats.clippedSamples);
            metadata.println("maximum_gain_db=" + stats.maximumGainDb);
            metadata.println("mean_gain_db=" + stats.meanGainDb);
        } finally {
            metadata.close();
        }
    }

    static final class Result {
        final File wavFile;
        final File rawWavFile;
        final File metadataFile;
        final int inputSamples;
        final int outputSamples;
        final long elapsedMillis;
        final int partialReads;
        final long maximumProcessNanos;
        final long totalProcessingWallNanos;
        final long totalProcessingCpuNanos;
        final int processingOverruns;
        final StreamingVoiceProcessor.Stats stats;

        Result(File wavFile, File rawWavFile, File metadataFile,
                int inputSamples, int outputSamples,
                long elapsedMillis, int partialReads, long maximumProcessNanos,
                long totalProcessingWallNanos, long totalProcessingCpuNanos,
                int processingOverruns, StreamingVoiceProcessor.Stats stats) {
            this.wavFile = wavFile;
            this.rawWavFile = rawWavFile;
            this.metadataFile = metadataFile;
            this.inputSamples = inputSamples;
            this.outputSamples = outputSamples;
            this.elapsedMillis = elapsedMillis;
            this.partialReads = partialReads;
            this.maximumProcessNanos = maximumProcessNanos;
            this.totalProcessingWallNanos = totalProcessingWallNanos;
            this.totalProcessingCpuNanos = totalProcessingCpuNanos;
            this.processingOverruns = processingOverruns;
            this.stats = stats;
        }
    }
}
