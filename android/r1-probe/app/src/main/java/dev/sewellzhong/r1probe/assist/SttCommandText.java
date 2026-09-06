package dev.sewellzhong.r1probe.assist;

/** Compatibility helper for lexical-only callers without acoustic/context evidence. */
final class SttCommandText {
    static String command(String recognized) {
        return CommandInputPolicy.evaluate(recognized, true, -1, null).text;
    }
    private SttCommandText() { }
}
