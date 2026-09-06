package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioRecord;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.util.concurrent.atomic.AtomicBoolean;

final class StereoAudioCapture {
    private static final int STEREO_FRAME_BYTES = 4;

    private StereoAudioCapture() {
    }

    static Result record(File outputDirectory, int sourceId, int durationSeconds, String sampleId)
            throws Exception {
        return record(outputDirectory, sourceId, durationSeconds, sampleId, null);
    }

    static Result record(File outputDirectory, int sourceId, int durationSeconds, String sampleId,
            File startCueFile) throws Exception {
        int minimumBuffer = AudioRecord.getMinBufferSize(WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_STEREO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimumBuffer <= 0) {
            throw new IllegalStateException("invalid_stereo_min_buffer_" + minimumBuffer);
        }
        int bufferBytes = Math.max(minimumBuffer, WavHeader.FRAME_SAMPLES * STEREO_FRAME_BYTES * 10);
        bufferBytes -= bufferBytes % STEREO_FRAME_BYTES;
        int targetStereoBytes = durationSeconds * WavHeader.SAMPLE_RATE * STEREO_FRAME_BYTES;
        String baseName = System.currentTimeMillis() + "-stereo-" + sampleId;
        File stereoFile = new File(outputDirectory, baseName + "-raw.wav");
        File leftFile = new File(outputDirectory, baseName + "-left.wav");
        File rightFile = new File(outputDirectory, baseName + "-right.wav");
        File averageFile = new File(outputDirectory, baseName + "-average.wav");
        File differenceFile = new File(outputDirectory, baseName + "-difference.wav");
        File[] files = {stereoFile, leftFile, rightFile, averageFile, differenceFile};
        int[] channels = {2, 1, 1, 1, 1};
        FileOutputStream[] outputs = new FileOutputStream[files.length];
        AudioRecord recorder = new AudioRecord(sourceId, WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_STEREO, AudioFormat.ENCODING_PCM_16BIT, bufferBytes);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            recorder.release();
            throw new IllegalStateException("stereo_audio_record_not_initialized");
        }

        int stereoBytes = 0;
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
                    // Normal completion.
                }
            }
        }, "r1-stereo-watchdog");

        try {
            for (int index = 0; index < files.length; index++) {
                outputs[index] = new FileOutputStream(files[index]);
                outputs[index].write(WavHeader.create(0, channels[index]));
            }
            byte[] buffer = new byte[bufferBytes];
            if (startCueFile != null) {
                AudioPlayback.play(startCueFile);
            }
            recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                throw new IllegalStateException("stereo_audio_record_did_not_start");
            }
            watchdog.start();
            while (stereoBytes < targetStereoBytes) {
                int requested = Math.min(buffer.length, targetStereoBytes - stereoBytes);
                int read = recorder.read(buffer, 0, requested);
                if (watchdogFired.get()) {
                    throw new IllegalStateException("stereo_audio_read_timeout");
                }
                if (read < 0) {
                    throw new IllegalStateException("stereo_audio_read_error_" + read);
                }
                if (read == 0) {
                    continue;
                }
                if ((read & 3) != 0) {
                    throw new IllegalStateException("stereo_audio_unaligned_read_" + read);
                }
                if (read < requested) {
                    partialReads++;
                }
                outputs[0].write(buffer, 0, read);
                StereoPcmSplitter.Split split = StereoPcmSplitter.split(buffer, read);
                outputs[1].write(split.left);
                outputs[2].write(split.right);
                outputs[3].write(split.average);
                outputs[4].write(split.difference);
                stereoBytes += read;
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
            for (FileOutputStream output : outputs) {
                if (output != null) {
                    output.close();
                }
            }
            if (!captureComplete) {
                for (File file : files) {
                    if (file.exists() && !file.delete()) {
                        file.deleteOnExit();
                    }
                }
            }
        }

        int monoBytes = stereoBytes / 2;
        for (int index = 0; index < files.length; index++) {
            int pcmBytes = index == 0 ? stereoBytes : monoBytes;
            RandomAccessFile headerWriter = new RandomAccessFile(files[index], "rw");
            try {
                headerWriter.seek(0);
                headerWriter.write(WavHeader.create(pcmBytes, channels[index]));
            } finally {
                headerWriter.close();
            }
        }
        long elapsedMillis = (System.nanoTime() - startedAtNanos) / 1_000_000L;
        File metadataFile = new File(outputDirectory, baseName + ".meta.txt");
        writeMetadata(metadataFile, sourceId, durationSeconds, startedAtEpochMillis, stereoBytes,
                elapsedMillis, minimumBuffer, bufferBytes, partialReads, startCueFile != null);
        return new Result(stereoFile, leftFile, rightFile, averageFile, differenceFile,
                metadataFile, stereoBytes, elapsedMillis, partialReads);
    }

    private static void writeMetadata(File metadataFile, int sourceId, int durationSeconds,
            long startedAtEpochMillis, int stereoBytes, long elapsedMillis, int minimumBuffer,
            int bufferBytes, int partialReads, boolean startCuePlayed) throws Exception {
        PrintWriter metadata = new PrintWriter(metadataFile, "UTF-8");
        try {
            metadata.println("purpose=R1 stage1 diagnostic stereo channel comparison");
            metadata.println("source=" + AudioSourceSpec.nameOf(sourceId));
            metadata.println("source_id=" + sourceId);
            metadata.println("raw_format=PCM_S16LE_16000Hz_stereo");
            metadata.println("derived_format=PCM_S16LE_16000Hz_mono");
            metadata.println("production_format_changed=false");
            metadata.println("target_duration_seconds=" + durationSeconds);
            metadata.println("started_at_epoch_ms=" + startedAtEpochMillis);
            metadata.println("stereo_pcm_bytes=" + stereoBytes);
            metadata.println("elapsed_ms=" + elapsedMillis);
            metadata.println("minimum_buffer_bytes=" + minimumBuffer);
            metadata.println("capture_buffer_bytes=" + bufferBytes);
            metadata.println("partial_reads=" + partialReads);
            metadata.println("start_cue_played=" + startCuePlayed);
        } finally {
            metadata.close();
        }
    }

    static final class Result {
        final File stereoFile;
        final File leftFile;
        final File rightFile;
        final File averageFile;
        final File differenceFile;
        final File metadataFile;
        final int stereoBytes;
        final long elapsedMillis;
        final int partialReads;

        Result(File stereoFile, File leftFile, File rightFile, File averageFile,
                File differenceFile, File metadataFile, int stereoBytes, long elapsedMillis,
                int partialReads) {
            this.stereoFile = stereoFile;
            this.leftFile = leftFile;
            this.rightFile = rightFile;
            this.averageFile = averageFile;
            this.differenceFile = differenceFile;
            this.metadataFile = metadataFile;
            this.stereoBytes = stereoBytes;
            this.elapsedMillis = elapsedMillis;
            this.partialReads = partialReads;
        }
    }
}
