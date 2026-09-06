package dev.sewellzhong.r1probe.assist;

/** API22 text/Unicode compatibility check; no microphone, playback or network. */
public final class CommandInputPolicySmoke {
    public static void main(String[] args) {
        check("。", false, -1, null, CommandInputPolicy.Reason.EMPTY);
        check("[BLANK_AUDIO]", false, -1, null, CommandInputPolicy.Reason.NON_SPEECH_MARKER);
        check("ＡＬＥＸＡ", false, -1, null, CommandInputPolicy.Reason.WAKE_ONLY);
        check("嗯", true, -1, null, CommandInputPolicy.Reason.ACCEPTED);
        check("停", false, 80, null, CommandInputPolicy.Reason.ACCEPTED);
        check("说来听听。", false, 100, "说来听听。", CommandInputPolicy.Reason.ACK_ECHO);
        check("谢谢观看谢谢观看谢谢观看谢谢观看", false, 100, null, CommandInputPolicy.Reason.WEAK_REPETITION);
        System.out.println("COMMAND_INPUT_POLICY_SMOKE_OK cases=7");
    }
    private static void check(String text, boolean followup, int millis, String ack, CommandInputPolicy.Reason reason) {
        if (CommandInputPolicy.evaluate(text, followup, millis, ack).reason != reason) {
            throw new IllegalStateException("input_policy_compatibility_failed");
        }
    }
    private CommandInputPolicySmoke() { }
}
