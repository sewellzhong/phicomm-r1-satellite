package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioManager;

/** Logical percentage shared by all satellite playback, independent of the 15 system steps. */
final class NativeVolume {
    private final NativeSettings settings;
    private final AudioManager audio;
    NativeVolume(Context context, NativeSettings settings) {
        this.settings = settings;
        audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        settings.initializeVolume(Math.round(100f * audio.getStreamVolume(AudioManager.STREAM_MUSIC)
                / audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)));
    }
    float gain() { return settings.volumePercent() / 100f; }
    // Call only after setting the per-player gain, before starting that player.
    void restoreOutput() {
        audio.setStreamVolume(AudioManager.STREAM_MUSIC,
            Math.round(settings.volumePercent() * audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC) / 100f), 0);
    }
    void prepareOutput() {
        int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        if (audio.getStreamVolume(AudioManager.STREAM_MUSIC) != max)
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, max, 0);
    }
}
