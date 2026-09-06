package dev.sewellzhong.r1probe;

/** A detection timestamp is expressed on the input PCM timeline. */
final class KwsDetection {
    static final KwsDetection NONE = new KwsDetection(false, "", -1L, Float.NaN);

    final boolean detected;
    final String keyword;
    final long endSampleIndex;
    final float score;

    KwsDetection(boolean detected, String keyword, long endSampleIndex, float score) {
        if (detected && !KwsConfig.KEYWORD.equals(keyword)) {
            throw new IllegalArgumentException("unexpected_keyword");
        }
        if (detected && endSampleIndex < 0L) {
            throw new IllegalArgumentException("invalid_end_sample_index");
        }
        this.detected = detected;
        this.keyword = keyword;
        this.endSampleIndex = endSampleIndex;
        this.score = score;
    }
}
