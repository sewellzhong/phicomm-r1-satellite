package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioRecord;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.util.concurrent.atomic.AtomicBoolean;

final class AudioCapture {
    private AudioCapture() {
    }

    static Result record(File outputDirectory, int sourceId, int durationSeconds, String sampleId)
            throws Exception {
        String sourceName = AudioSourceSpec.nameOf(sourceId);
        int minimumBuffer = AudioRecord.getMinBufferSize(
                WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimumBuffer <= 0) {
            throw new IllegalStateException("invalid_min_buffer_" + minimumBuffer);
        }

        int bufferBytes = Math.max(minimumBuffer, WavHeader.FRAME_BYTES * 10);
        if ((bufferBytes & 1) != 0) {
            bufferBytes++;
        }
        int targetBytes = durationSeconds * WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE;
        File wavFile = new File(outputDirectory,
                System.currentTimeMillis() + "-" + sourceName + "-" + sampleId + ".wav");

        AudioRecord recorder = new AudioRecord(
                sourceId,
                WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferBytes);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            recorder.release();
            throw new IllegalStateException("audio_record_not_initialized");
        }

        int sessionId = recorder.getAudioSessionId();
        int pcmBytes = 0;
        int partialReads = 0;
        boolean captureComplete = false;
        long startedAtEpochMillis = System.currentTimeMillis();
        long startedAtNanos = System.nanoTime();
        final AtomicBoolean captureFinished = new AtomicBoolean(false);
        final AtomicBoolean watchdogFired = new AtomicBoolean(false);
        final AudioRecord watchdogRecorder = recorder;
        Thread watchdog = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep((durationSeconds + 3L) * 1000L);
                    if (captureFinished.compareAndSet(false, true)) {
                        watchdogFired.set(true);
                        if (watchdogRecorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                            watchdogRecorder.stop();
                        }
                    }
                } catch (InterruptedException ignored) {
                    // Normal capture completion interrupts the watchdog.
                }
            }
        }, "r1-audio-watchdog");
        FileOutputStream output = new FileOutputStream(wavFile);
        try {
            output.write(WavHeader.create(0));
            byte[] buffer = new byte[bufferBytes];
            recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                throw new IllegalStateException("audio_record_did_not_start");
            }
            watchdog.start();
            while (pcmBytes < targetBytes) {
                int requested = Math.min(buffer.length, targetBytes - pcmBytes);
                int read = recorder.read(buffer, 0, requested);
                if (watchdogFired.get()) {
                    throw new IllegalStateException("audio_read_timeout");
                }
                if (read < 0) {
                    throw new IllegalStateException("audio_read_error_" + read);
                }
                if (read == 0) {
                    continue;
                }
                if (read < requested) {
                    partialReads++;
                }
                output.write(buffer, 0, read);
                pcmBytes += read;
            }
            captureComplete = true;
            captureFinished.set(true);
            watchdog.interrupt();
        } finally {
            captureFinished.set(true);
            watchdog.interrupt();
            if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                recorder.stop();
            }
            recorder.release();
            output.close();
            if (!captureComplete && wavFile.exists() && !wavFile.delete()) {
                wavFile.deleteOnExit();
            }
        }

        RandomAccessFile headerWriter = new RandomAccessFile(wavFile, "rw");
        try {
            headerWriter.seek(0);
            headerWriter.write(WavHeader.create(pcmBytes));
        } finally {
            headerWriter.close();
        }

        long elapsedMillis = (System.nanoTime() - startedAtNanos) / 1_000_000L;
        writeMetadata(wavFile, sourceId, sourceName, durationSeconds, startedAtEpochMillis,
                pcmBytes, elapsedMillis, sessionId, minimumBuffer, bufferBytes, partialReads);
        return new Result(wavFile, sourceName, pcmBytes, elapsedMillis, sessionId, partialReads);
    }

    private static void writeMetadata(File wavFile, int sourceId, String sourceName,
            int durationSeconds, long startedAtEpochMillis, int pcmBytes, long elapsedMillis,
            int sessionId, int minimumBuffer, int bufferBytes, int partialReads) throws Exception {
        PrintWriter metadata = new PrintWriter(wavFile.getAbsolutePath() + ".meta.txt", "UTF-8");
        try {
            metadata.println("purpose=R1 stage1 audio source comparison");
            metadata.println("source=" + sourceName);
            metadata.println("source_id=" + sourceId);
            metadata.println("format=PCM_S16LE_16000Hz_mono");
            metadata.println("frame_ms=20");
            metadata.println("frame_bytes=" + WavHeader.FRAME_BYTES);
            metadata.println("target_duration_seconds=" + durationSeconds);
            metadata.println("started_at_epoch_ms=" + startedAtEpochMillis);
            metadata.println("pcm_bytes=" + pcmBytes);
            metadata.println("elapsed_ms=" + elapsedMillis);
            metadata.println("audio_session_id=" + sessionId);
            metadata.println("minimum_buffer_bytes=" + minimumBuffer);
            metadata.println("capture_buffer_bytes=" + bufferBytes);
            metadata.println("partial_reads=" + partialReads);
            metadata.println("aec_available=" + AudioEffectCapabilities.aecAvailable());
            metadata.println("ns_available=" + AudioEffectCapabilities.nsAvailable());
            metadata.println("agc_available=" + AudioEffectCapabilities.agcAvailable());
        } finally {
            metadata.close();
        }
    }

    static final class Result {
        final File wavFile;
        final String sourceName;
        final int pcmBytes;
        final long elapsedMillis;
        final int audioSessionId;
        final int partialReads;

        Result(File wavFile, String sourceName, int pcmBytes, long elapsedMillis,
                int audioSessionId, int partialReads) {
            this.wavFile = wavFile;
            this.sourceName = sourceName;
            this.pcmBytes = pcmBytes;
            this.elapsedMillis = elapsedMillis;
            this.audioSessionId = audioSessionId;
            this.partialReads = partialReads;
        }
    }
}
