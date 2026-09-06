package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.RandomAccessFile;
import java.util.concurrent.atomic.AtomicBoolean;

final class FourMicCapture {
    static final int NATIVE_BUFFER_BYTES = 2400;
    private static final int INIT_MODE = 1;
    private static final int AUDIO_SOURCE = 2;

    private FourMicCapture() {
    }

    static Result record(File outputDirectory, int durationSeconds, String sampleId,
            FourMicBackend backend) throws Exception {
        int targetBytes = durationSeconds * WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE;
        File wavFile = new File(outputDirectory,
                System.currentTimeMillis() + "-vendor_four_mic-" + sampleId + ".wav");
        long startedAtEpochMillis = System.currentTimeMillis();
        long startedAtNanos = System.nanoTime();
        Session session = new Session(backend);
        FileOutputStream output = null;
        boolean captureComplete = false;
        int pcmBytes = 0;
        int partialReads = 0;
        int readCalls = 0;
        String boardVersion = "unknown";
        Throwable failure = null;
        try {
            boardVersion = sanitizeValue(backend.boardVersion());
            session.initialize();
            output = new FileOutputStream(wavFile);
            output.write(WavHeader.create(0));
            byte[] buffer = new byte[NATIVE_BUFFER_BYTES];
            session.startWatchdog(durationSeconds);
            while (pcmBytes < targetBytes) {
                int requested = Math.min(buffer.length, targetBytes - pcmBytes);
                int read = backend.readData(session.handle(), buffer, requested);
                readCalls++;
                if (session.watchdogFired()) {
                    throw new IllegalStateException("four_mic_read_timeout");
                }
                if (read < 0) {
                    throw new IllegalStateException("four_mic_read_error_" + read);
                }
                if (read > requested) {
                    throw new IllegalStateException("four_mic_read_overflow_" + read);
                }
                if ((read & 1) != 0) {
                    throw new IllegalStateException("four_mic_odd_pcm_bytes_" + read);
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
        } catch (Exception | LinkageError e) {
            failure = e;
            throw e;
        } finally {
            session.cancelWatchdog();
            if (output != null) {
                output.close();
            }
            try {
                session.close();
            } catch (Exception cleanupError) {
                if (failure != null) {
                    failure.addSuppressed(cleanupError);
                } else {
                    throw cleanupError;
                }
            } finally {
                if (!captureComplete && wavFile.exists() && !wavFile.delete()) {
                    wavFile.deleteOnExit();
                }
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
        writeMetadata(wavFile, durationSeconds, startedAtEpochMillis, pcmBytes, elapsedMillis,
                partialReads, readCalls, boardVersion);
        return new Result(wavFile, pcmBytes, elapsedMillis, partialReads, readCalls, boardVersion);
    }

    private static void writeMetadata(File wavFile, int durationSeconds,
            long startedAtEpochMillis, int pcmBytes, long elapsedMillis, int partialReads,
            int readCalls, String boardVersion) throws Exception {
        PrintWriter metadata = new PrintWriter(wavFile.getAbsolutePath() + ".meta.txt", "UTF-8");
        try {
            metadata.println("purpose=R1 stage1 vendor four microphone comparison");
            metadata.println("source=vendor_four_mic");
            metadata.println("format=PCM_S16LE_16000Hz_mono");
            metadata.println("frame_ms=20");
            metadata.println("frame_bytes=" + WavHeader.FRAME_BYTES);
            metadata.println("native_buffer_bytes=" + NATIVE_BUFFER_BYTES);
            metadata.println("target_duration_seconds=" + durationSeconds);
            metadata.println("started_at_epoch_ms=" + startedAtEpochMillis);
            metadata.println("pcm_bytes=" + pcmBytes);
            metadata.println("elapsed_ms=" + elapsedMillis);
            metadata.println("partial_reads=" + partialReads);
            metadata.println("read_calls=" + readCalls);
            metadata.println("board_version=" + boardVersion);
            metadata.println("native_library_source=system");
            metadata.println("native_library_bundled=false");
        } finally {
            metadata.close();
        }
    }

    private static String sanitizeValue(String value) {
        if (value == null || value.length() == 0) {
            return "unknown";
        }
        return value.replace('\n', '_').replace('\r', '_').replace(' ', '_');
    }

    static final class Result {
        final File wavFile;
        final int pcmBytes;
        final long elapsedMillis;
        final int partialReads;
        final int readCalls;
        final String boardVersion;

        Result(File wavFile, int pcmBytes, long elapsedMillis, int partialReads, int readCalls,
                String boardVersion) {
            this.wavFile = wavFile;
            this.pcmBytes = pcmBytes;
            this.elapsedMillis = elapsedMillis;
            this.partialReads = partialReads;
            this.readCalls = readCalls;
            this.boardVersion = boardVersion;
        }
    }

    private static final class Session {
        private final FourMicBackend backend;
        private final AtomicBoolean stopIssued = new AtomicBoolean(false);
        private final AtomicBoolean watchdogFired = new AtomicBoolean(false);
        private long handle;
        private boolean initialized;
        private boolean opened;
        private boolean started;
        private Thread watchdog;

        Session(FourMicBackend backend) {
            this.backend = backend;
        }

        void initialize() {
            requireSuccess("init", backend.init(INIT_MODE));
            initialized = true;
            requireSuccess("set_debug_mode", backend.setDebugMode(1));
            requireSuccess("close_algorithm", backend.closeAlgorithm(0));
            requireSuccess("set_wakeup_status", backend.setWakeUpStatus(0));
            handle = backend.openAudioIn(AUDIO_SOURCE);
            if (handle == 0L) {
                throw new IllegalStateException("four_mic_open_failed_0");
            }
            opened = true;
            requireSuccess("start", backend.startRecorder(handle));
            started = true;
        }

        long handle() {
            return handle;
        }

        void startWatchdog(final int durationSeconds) {
            watchdog = new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        Thread.sleep((durationSeconds + 3L) * 1000L);
                        watchdogFired.set(true);
                        stopOnce();
                    } catch (InterruptedException ignored) {
                        // Normal capture completion interrupts the watchdog.
                    }
                }
            }, "r1-four-mic-watchdog");
            watchdog.start();
        }

        boolean watchdogFired() {
            return watchdogFired.get();
        }

        void cancelWatchdog() {
            if (watchdog != null) {
                watchdog.interrupt();
            }
        }

        void close() throws Exception {
            Exception first = null;
            if (started) {
                try {
                    stopOnce();
                } catch (RuntimeException e) {
                    first = e;
                }
            }
            if (opened) {
                try {
                    requireSuccess("close", backend.closeAudioIn(handle));
                } catch (RuntimeException e) {
                    if (first == null) {
                        first = e;
                    } else {
                        first.addSuppressed(e);
                    }
                }
            }
            if (initialized) {
                try {
                    requireSuccess("release", backend.release());
                } catch (RuntimeException e) {
                    if (first == null) {
                        first = e;
                    } else {
                        first.addSuppressed(e);
                    }
                }
            }
            if (first != null) {
                throw first;
            }
        }

        private void stopOnce() {
            if (stopIssued.compareAndSet(false, true)) {
                requireSuccess("stop", backend.stopRecorder(handle));
            }
        }
    }

    private static void requireSuccess(String stage, int result) {
        if (result != 0) {
            throw new IllegalStateException("four_mic_" + stage + "_error_" + result);
        }
    }
}
