package dev.sewellzhong.r1probe;

import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.AutomaticGainControl;
import android.media.audiofx.NoiseSuppressor;

final class AudioEffectCapabilities {
    private AudioEffectCapabilities() {
    }

    static boolean aecAvailable() {
        return AcousticEchoCanceler.isAvailable();
    }

    static boolean nsAvailable() {
        return NoiseSuppressor.isAvailable();
    }

    static boolean agcAvailable() {
        return AutomaticGainControl.isAvailable();
    }

    static String describe() {
        return "aec_available=" + aecAvailable()
                + " ns_available=" + nsAvailable()
                + " agc_available=" + agcAvailable();
    }
}

