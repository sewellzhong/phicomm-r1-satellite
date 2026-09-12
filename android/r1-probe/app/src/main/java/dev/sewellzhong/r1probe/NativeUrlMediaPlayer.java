package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioManager;
import android.media.MediaPlayer;
import dev.sewellzhong.r1probe.esphome.NativeMediaController;
import java.io.IOException;

/** API 22 Android media backend. Callbacks publish only observed backend state. */
final class NativeUrlMediaPlayer implements NativeMediaController.Backend {
    private final AudioManager audio;
    private MediaPlayer player;
    private NativeMediaController.State state = NativeMediaController.State.IDLE;
    private String failure = "none";
    private float volume;
    private boolean playWhenPrepared;
    private boolean prepared;
    private long generation;

    NativeUrlMediaPlayer(Context context) {
        audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
    }

    @Override public synchronized void open(String url, float volume) throws IOException {
        stopLocked();
        this.volume = volume; playWhenPrepared = true; prepared = false; failure = "none";
        final long expected = ++generation;
        final MediaPlayer created = new MediaPlayer();
        player = created; state = NativeMediaController.State.PREPARING;
        try {
            created.setAudioStreamType(AudioManager.STREAM_MUSIC);
            created.setVolume(volume, volume);
            created.setOnPreparedListener(value -> prepared(expected, value));
            created.setOnCompletionListener(value -> completed(expected, value));
            created.setOnErrorListener((value, what, extra) -> failed(expected, value));
            created.setDataSource(url);
            if (audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED)
                throw new IOException("media_audio_focus_denied");
            created.prepareAsync();
        } catch (IOException | RuntimeException error) {
            if (player == created) { failure = safe(error); state = NativeMediaController.State.FAILED; }
            release(created); player = null; audio.abandonAudioFocus(null);
            if (error instanceof IOException) throw (IOException) error;
            throw new IOException("media_backend_start_failed", error);
        }
    }

    @Override public synchronized void play() throws IOException {
        if (!prepared && player != null && (state == NativeMediaController.State.PREPARING
                || state == NativeMediaController.State.PAUSED)) {
            playWhenPrepared = true; state = NativeMediaController.State.PREPARING; return;
        }
        if (state != NativeMediaController.State.PAUSED || player == null)
            throw new IOException("media_not_resumable");
        try { player.start(); state = NativeMediaController.State.PLAYING; }
        catch (RuntimeException error) { failAndRelease(error); throw new IOException(failure, error); }
    }

    @Override public synchronized void pause() throws IOException {
        if (!prepared && player != null && (state == NativeMediaController.State.PREPARING
                || state == NativeMediaController.State.PAUSED)) {
            playWhenPrepared = false; state = NativeMediaController.State.PAUSED; return;
        }
        if (state != NativeMediaController.State.PLAYING || player == null)
            throw new IOException("media_not_playing");
        try { player.pause(); state = NativeMediaController.State.PAUSED; }
        catch (RuntimeException error) { failAndRelease(error); throw new IOException(failure, error); }
    }

    @Override public synchronized void stop() { stopLocked(); }

    @Override public synchronized void volume(float value) {
        volume = value;
        if (player != null) try { player.setVolume(value, value); }
        catch (RuntimeException error) { failAndRelease(error); }
    }

    @Override public synchronized NativeMediaController.State state() { return state; }
    @Override public synchronized String failure() { return failure; }

    private synchronized void prepared(long expected, MediaPlayer value) {
        if (expected != generation || value != player) { release(value); return; }
        prepared = true;
        if (!playWhenPrepared) { state = NativeMediaController.State.PAUSED; return; }
        try { value.start(); state = NativeMediaController.State.PLAYING; }
        catch (RuntimeException error) { failAndRelease(error); }
    }

    private synchronized void completed(long expected, MediaPlayer value) {
        if (expected != generation || value != player) { release(value); return; }
        release(value); player = null; playWhenPrepared = false; prepared = false;
        state = NativeMediaController.State.IDLE; failure = "none";
        audio.abandonAudioFocus(null);
    }

    private synchronized boolean failed(long expected, MediaPlayer value) {
        if (expected != generation || value != player) { release(value); return true; }
        failure = "media_backend_error"; state = NativeMediaController.State.FAILED;
        release(value); player = null; playWhenPrepared = false; prepared = false;
        audio.abandonAudioFocus(null);
        return true;
    }

    private void stopLocked() {
        generation++; playWhenPrepared = false; prepared = false;
        MediaPlayer current = player; player = null;
        if (current != null) release(current);
        audio.abandonAudioFocus(null); state = NativeMediaController.State.IDLE; failure = "none";
    }

    private void failAndRelease(RuntimeException error) {
        failure = safe(error); state = NativeMediaController.State.FAILED;
        MediaPlayer current = player; player = null;
        if (current != null) release(current);
        playWhenPrepared = false; prepared = false; audio.abandonAudioFocus(null);
    }

    private static void release(MediaPlayer value) {
        try { value.reset(); } catch (RuntimeException ignored) { }
        try { value.release(); } catch (RuntimeException ignored) { }
    }

    private static String safe(Exception error) {
        String value = error.getMessage();
        return value != null && value.matches("media_[a-z0-9_]{1,64}")
                ? value : "media_backend_runtime_failed";
    }
}
