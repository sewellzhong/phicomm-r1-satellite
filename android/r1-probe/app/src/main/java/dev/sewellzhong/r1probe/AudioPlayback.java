package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.util.concurrent.atomic.AtomicBoolean;

final class AudioPlayback {
    private static final String TAG = "R1Audio";

    private AudioPlayback() {
    }

    @SuppressWarnings("deprecation") // API 22 requires the legacy AudioTrack constructor.
    static Result play(File wavFile) throws Exception {
        int pcmBytes = WavHeader.validate(wavFile);
        int minimumBuffer = AudioTrack.getMinBufferSize(
                WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimumBuffer <= 0) {
            throw new IllegalStateException("invalid_playback_min_buffer_" + minimumBuffer);
        }
        int bufferBytes = Math.max(minimumBuffer, WavHeader.FRAME_BYTES * 10);
        AudioTrack track = new AudioTrack(
                AudioManager.STREAM_MUSIC,
                WavHeader.SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferBytes,
                AudioTrack.MODE_STREAM);
        if (track.getState() != AudioTrack.STATE_INITIALIZED) {
            track.release();
            throw new IllegalStateException("audio_track_not_initialized");
        }

        final AtomicBoolean playbackFinished = new AtomicBoolean(false);
        final AtomicBoolean watchdogFired = new AtomicBoolean(false);
        final AudioTrack watchdogTrack = track;
        final long pcmDurationMillis = pcmBytes * 1000L
                / (WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE);
        Thread watchdog = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep(pcmDurationMillis + 3000L);
                    if (playbackFinished.compareAndSet(false, true)) {
                        watchdogFired.set(true);
                        if (watchdogTrack.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                            watchdogTrack.stop();
                        }
                    }
                } catch (InterruptedException ignored) {
                    // Normal playback completion interrupts the watchdog.
                } catch (RuntimeException ignored) {
                    watchdogFired.set(true);
                }
            }
        }, "r1-playback-watchdog");

        long startedAtNanos = System.nanoTime();
        long playbackStartedAtNanos = 0L;
        long playbackCompletedAtNanos = 0L;
        FileInputStream input = new FileInputStream(wavFile);
        try {
            skipFully(input, WavHeader.HEADER_BYTES);
            Log.i(TAG, "R1_AUDIO_PLAYBACK_STAGE stage=track_initialized pcm_bytes=" + pcmBytes);
            playbackStartedAtNanos = System.nanoTime();
            track.play();
            watchdog.start();
            Log.i(TAG, "R1_AUDIO_PLAYBACK_STAGE stage=write_started");
            byte[] buffer = new byte[bufferBytes];
            int remaining = pcmBytes;
            while (remaining > 0) {
                int read = input.read(buffer, 0, Math.min(buffer.length, remaining));
                if (read < 0) {
                    throw new IllegalStateException("unexpected_wav_eof");
                }
                int offset = 0;
                while (offset < read) {
                    int written = track.write(buffer, offset, read - offset);
                    if (watchdogFired.get()) {
                        throw new IllegalStateException("audio_playback_timeout");
                    }
                    if (written < 0) {
                        throw new IllegalStateException("audio_track_write_error_" + written);
                    }
                    offset += written;
                }
                remaining -= read;
            }
            Log.i(TAG, "R1_AUDIO_PLAYBACK_STAGE stage=write_complete");

            int targetFrames = pcmBytes / WavHeader.BYTES_PER_SAMPLE;
            long deadline = System.currentTimeMillis() + (targetFrames * 1000L / WavHeader.SAMPLE_RATE) + 2000L;
            while (track.getPlaybackHeadPosition() < targetFrames && System.currentTimeMillis() < deadline) {
                Thread.sleep(20L);
            }
            if (track.getPlaybackHeadPosition() < targetFrames) {
                throw new IllegalStateException(watchdogFired.get()
                        ? "audio_playback_timeout" : "playback_drain_timeout");
            }
            playbackFinished.set(true);
            watchdog.interrupt();
            playbackCompletedAtNanos = System.nanoTime();
            Log.i(TAG, "R1_AUDIO_PLAYBACK_STAGE stage=drain_complete");
        } finally {
            playbackFinished.set(true);
            watchdog.interrupt();
            input.close();
            if (track.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                track.stop();
            }
            track.release();
        }

        return new Result(pcmBytes, (System.nanoTime() - startedAtNanos) / 1_000_000L,
                playbackStartedAtNanos, playbackCompletedAtNanos);
    }

    private static void skipFully(FileInputStream input, int bytes) throws Exception {
        int remaining = bytes;
        while (remaining > 0) {
            long skipped = input.skip(remaining);
            if (skipped <= 0) {
                throw new IllegalStateException("cannot_skip_wav_header");
            }
            remaining -= (int) skipped;
        }
    }

    static final class Result {
        final int pcmBytes;
        final long elapsedMillis;
        final long playbackStartedAtNanos;
        final long playbackCompletedAtNanos;

        Result(int pcmBytes, long elapsedMillis, long playbackStartedAtNanos,
                long playbackCompletedAtNanos) {
            this.pcmBytes = pcmBytes;
            this.elapsedMillis = elapsedMillis;
            this.playbackStartedAtNanos = playbackStartedAtNanos;
            this.playbackCompletedAtNanos = playbackCompletedAtNanos;
        }
    }
}
