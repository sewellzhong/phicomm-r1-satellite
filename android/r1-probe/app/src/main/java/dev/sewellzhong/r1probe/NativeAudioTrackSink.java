package dev.sewellzhong.r1probe;

import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import dev.sewellzhong.r1probe.esphome.NativePcmPlayback;

/** API 22 streaming sink. Only constructed by an explicitly started native runtime. */
final class NativeAudioTrackSink implements NativePcmPlayback.Sink {
    private final AudioTrack track;
    private long previousHead, wraps;
    private final NativeVolume volume;
    NativeAudioTrackSink() { this(null); }
    NativeAudioTrackSink(NativeVolume volume) {
        this.volume = volume;
        int minimum = AudioTrack.getMinBufferSize(16000, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IllegalStateException("invalid_playback_buffer");
        track = new AudioTrack(AudioManager.STREAM_MUSIC, 16000, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT, Math.max(minimum, 6400), AudioTrack.MODE_STREAM);
        if (track.getState() != AudioTrack.STATE_INITIALIZED) {
            track.release(); throw new IllegalStateException("playback_not_initialized");
        }
    }
    @Override public void start() {
        if (volume != null) { track.setVolume(volume.gain()); volume.prepareOutput(); }
        track.play();
    }
    @Override public int write(byte[] bytes, int offset, int length) { if (volume != null) track.setVolume(volume.gain());
        return track.write(bytes, offset, length); }
    @Override public long playedFrames() {
        long current = track.getPlaybackHeadPosition() & 0xffffffffL;
        if (current < previousHead) wraps++;
        previousHead = current;
        return (wraps << 32) + current;
    }
    @Override public void stop() {
        try { track.pause(); track.flush(); } catch (IllegalStateException ignored) { }
    }
    @Override public void close() { track.release(); }
}
