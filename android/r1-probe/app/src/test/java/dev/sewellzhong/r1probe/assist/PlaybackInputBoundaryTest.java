package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public class PlaybackInputBoundaryTest {
    @Test public void excludesPlaybackAndPreservesImmediateSpeechInOrder() {
        PlaybackInputBoundary b = new PlaybackInputBoundary();
        short[] f = new short[320], out = new short[320];
        b.start(); f[0]=1; b.accept(f);
        b.drained(); f[0]=2; b.accept(f); f[0]=3; b.accept(f); f[0]=9;
        assertTrue(b.poll(out)); assertEquals(2,out[0]);
        assertTrue(b.poll(out)); assertEquals(3,out[0]);
        assertFalse(b.poll(out)); assertFalse(b.active());
    }
    @Test public void newPlaybackAndCancellationClearPreviousReply() {
        PlaybackInputBoundary b = new PlaybackInputBoundary(); short[] f = new short[320];
        b.start(); b.drained(); b.accept(f); b.start();
        assertFalse(b.poll(f)); b.start(); b.drained(); b.accept(f); b.clear();
        assertFalse(b.active()); assertFalse(b.poll(f));
    }
    @Test(expected=IllegalStateException.class) public void handoffIsBounded() {
        PlaybackInputBoundary b = new PlaybackInputBoundary(); b.start(); b.drained();
        for(int i=0;i<101;i++) b.accept(new short[320]);
    }
}
