package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public final class TtsRuntimeStatsTest {
    @Test public void streamingResponseIsCountedOnceAndCompletes() {
        TtsRuntimeStats stats = new TtsRuntimeStats();
        stats.beginRun(); stats.response(true); stats.response(true);
        stats.finish(true);
        assertEquals(1, stats.responses());
        assertEquals(1, stats.streams());
        assertEquals(1, stats.playbackCompleted());
        assertEquals(0, stats.playbackFailed());
    }

    @Test public void nonStreamingUrlResponseCompletesWithoutStreamCount() {
        TtsRuntimeStats stats = new TtsRuntimeStats();
        stats.beginRun(); stats.response(false); stats.finish(true);
        assertEquals(1, stats.responses());
        assertEquals(0, stats.streams());
        assertEquals(1, stats.playbackCompleted());
    }

    @Test public void localPromptWithoutAssistTtsDoesNotCount() {
        TtsRuntimeStats stats = new TtsRuntimeStats();
        stats.beginRun(); stats.finish(true);
        assertEquals(0, stats.responses());
        assertEquals(0, stats.playbackCompleted());
    }

    @Test public void failedPlaybackDoesNotComplete() {
        TtsRuntimeStats stats = new TtsRuntimeStats();
        stats.beginRun(); stats.response(false); stats.finish(false);
        assertEquals(1, stats.responses());
        assertEquals(0, stats.playbackCompleted());
        assertEquals(1, stats.playbackFailed());
    }

    @Test public void beginRunSeparatesCancelledOldRunFromNextRun() {
        TtsRuntimeStats stats = new TtsRuntimeStats();
        stats.beginRun(); stats.response(false); stats.beginRun(); stats.response(true);
        stats.finish(true);
        assertEquals(2, stats.responses());
        assertEquals(1, stats.streams());
        assertEquals(1, stats.playbackCompleted());
        assertEquals(0, stats.playbackFailed());
    }
}
