package dev.sewellzhong.r1probe;

final class AudioSourceSpec {
    static final int MIC = 1;
    static final int VOICE_COMMUNICATION = 7;
    static final int VOICE_RECOGNITION = 6;

    private AudioSourceSpec() {
    }

    static String nameOf(int sourceId) {
        switch (sourceId) {
            case VOICE_COMMUNICATION:
                return "voice_communication";
            case VOICE_RECOGNITION:
                return "voice_recognition";
            case MIC:
                return "mic";
            default:
                throw new IllegalArgumentException("unsupported_audio_source_" + sourceId);
        }
    }
}

