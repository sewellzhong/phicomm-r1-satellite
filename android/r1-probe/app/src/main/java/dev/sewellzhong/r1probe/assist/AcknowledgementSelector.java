package dev.sewellzhong.r1probe.assist;

import java.util.Random;

/** Six daily phrases and four occasional ones; no immediate repeats or consecutive occasional turns. */
public final class AcknowledgementSelector {
    private static final String[] PHRASES = {"诶，叫我啦？", "来了来了。", "好嘞，什么安排？", "说来听听。",
        "你说，我接着。", "好，接下来听你的。", "我就知道你会叫我。", "终于轮到我啦。", "好巧，我正等着呢。", "小助手到位。"};
    public static final int COUNT = PHRASES.length;
    public static String phrase(int index) { return PHRASES[index]; }
    private final Random random;
    private int previous = -1;
    public AcknowledgementSelector(Random random) { this.random = random; }
    public int next() {
        // With an obligatory daily turn after each occasional turn, 3/17 gives
        // a long-run occasional share of (3/17)/(1+3/17) = 15 percent.
        boolean occasional = previous < 6 && random.nextInt(17) < 3;
        int value;
        if (occasional) {
            value = 6 + random.nextInt(4);
        } else {
            boolean excludePrevious = previous >= 0 && previous < 6;
            value = random.nextInt(excludePrevious ? 5 : 6);
            if (excludePrevious && value >= previous) { value++; }
        }
        previous = value;
        return value;
    }
}
