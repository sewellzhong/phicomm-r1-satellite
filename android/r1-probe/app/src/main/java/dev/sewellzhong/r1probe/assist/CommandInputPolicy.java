package dev.sewellzhong.r1probe.assist;

import java.text.Normalizer;
import java.util.Locale;
import java.util.regex.Pattern;

/** Conservative pre-intent rules. Unknown lexical input is passed to HA, not silently discarded. */
public final class CommandInputPolicy {
    public enum Reason { ACCEPTED, EMPTY, NO_SPEECH, NON_SPEECH_MARKER, WAKE_ONLY,
        FILLER_ONLY, CANCELLED, ACK_ECHO, WEAK_REPETITION, STT_NO_TEXT }
    public static final class Result {
        public final String text;
        public final Reason reason;
        Result(String text, Reason reason) { this.text = text; this.reason = reason; }
    }
    private static final Pattern MARKERS = Pattern.compile(
            "^(?:(?:\\[(?:blank_audio|no speech|silence|music|noise|applause|inaudible|静音|无语音|音乐|噪音|掌声)\\]"
            + "|【(?:静音|无语音|音乐|噪音|掌声)】|\\((?:silence|music|noise|静音|音乐|噪音)\\)"
            + "|<\\|(?:nospeech|silence)\\|>)[\\s\\p{Z}\\p{P}]*)+$", Pattern.CASE_INSENSITIVE);

    public static Result evaluate(String recognized, boolean followup, int voicedMillis, String lastAck) {
        String text = recognized == null ? "" : recognized.trim();
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFKC)
                .replaceAll("[\\p{Cf}\\p{Cc}]", "").trim().toLowerCase(Locale.ROOT);
        if (MARKERS.matcher(normalized).matches()) { return ignored(Reason.NON_SPEECH_MARKER); }
        String key = key(normalized);
        if (key.isEmpty()) { return ignored(Reason.EMPTY); }
        // No ASR confidence is supplied by HA's current Wyoming adapter. Never invent a score.
        if (voicedMillis == 0) { return ignored(Reason.NO_SPEECH); }
        if (oneOf(key, "结束对话", "取消本次对话", "取消这次对话", "不用回答了")) {
            return ignored(Reason.CANCELLED);
        }
        if (!followup) {
            if (oneOf(key, "算了", "没事了", "不说了", "不用了")) { return ignored(Reason.CANCELLED); }
            if (oneOf(key, "alexa", "奥ex斯", "欧ex萨")) { return ignored(Reason.WAKE_ONLY); }
            if (key.codePointCount(0, key.length()) <= 6 && key.matches("[嗯呃额啊唔唉哦噢]+")) {
                return ignored(Reason.FILLER_ONLY);
            }
            // Joint checks: text alone cannot distinguish an intentional quote from an ASR hallucination.
            if (voicedMillis > 0 && voicedMillis < 300) {
                if (lastAck != null && key.equals(key(lastAck))) { return ignored(Reason.ACK_ECHO); }
                if (repetitive(key)) { return ignored(Reason.WEAK_REPETITION); }
            }
        }
        return new Result(text, Reason.ACCEPTED);
    }

    private static Result ignored(Reason reason) { return new Result("", reason); }
    private static boolean oneOf(String text, String... values) {
        for (String value : values) { if (value.equals(text)) { return true; } }
        return false;
    }
    private static String key(String text) {
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        StringBuilder result = new StringBuilder();
        for (int offset = 0; offset < normalized.length();) {
            int point = normalized.codePointAt(offset);
            if (Character.isLetterOrDigit(point)) { result.appendCodePoint(point); }
            offset += Character.charCount(point);
        }
        return result.toString();
    }
    private static boolean repetitive(String key) {
        int[] points = new int[key.codePointCount(0, key.length())];
        for (int offset = 0, i = 0; offset < key.length(); i++) {
            points[i] = key.codePointAt(offset); offset += Character.charCount(points[i]);
        }
        if (points.length < 16) { return false; }
        for (int period = 1; period <= 8 && period * 4 <= points.length; period++) {
            if (points.length % period != 0) { continue; }
            boolean matches = true;
            for (int i = period; i < points.length; i++) {
                if (points[i] != points[i % period]) { matches = false; break; }
            }
            if (matches) { return true; }
        }
        return false;
    }
    private CommandInputPolicy() { }
}
