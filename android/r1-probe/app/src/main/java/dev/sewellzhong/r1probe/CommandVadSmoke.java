package dev.sewellzhong.r1probe;

/** Explicit app_process check: synthetic zero frames only, no microphone or network. */
public final class CommandVadSmoke {
    public static void main(String[] args) {
        try (CommandVad vad = new CommandVad()) {
            short[] silence = new short[320];
            for (int i = 0; i < 400; i++) {
                if (vad.speech(silence)) { throw new IllegalStateException("silence_as_voice"); }
            }
            vad.reset();
            if (vad.speech(silence)) { throw new IllegalStateException("reset_failed"); }
            System.out.println("COMMAND_VAD_SMOKE_OK synthetic_silence_frames=401");
        }
    }
    private CommandVadSmoke() { }
}
