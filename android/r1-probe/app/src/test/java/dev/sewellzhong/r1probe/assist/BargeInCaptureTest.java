package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public final class BargeInCaptureTest {
    @Test public void preservesOnsetAndFollowingFramesInPcmOrder() {
        BargeInCapture capture = new BargeInCapture();
        byte[] onset = new byte[640]; onset[0] = 7; onset[639] = 9;
        capture.start(onset); onset[0] = 0;
        short[] frame = new short[320]; frame[0] = (short) 0x1234; frame[319] = (short) 0xabcd;
        assertTrue(capture.append(frame));
        byte[] result = capture.snapshot();
        assertEquals(1280, result.length); assertEquals(7, result[0]); assertEquals(9, result[639]);
        assertEquals(0x34, result[640] & 0xff); assertEquals(0x12, result[641] & 0xff);
        assertEquals(0xcd, result[1278] & 0xff); assertEquals(0xab, result[1279] & 0xff);
    }

    @Test public void handoffIsBoundedAtCoordinatorPrebufferLimit() {
        BargeInCapture capture = new BargeInCapture(); capture.start(new byte[640]);
        short[] frame = new short[320];
        for (int i = 1; i < 250; i++) assertTrue(capture.append(frame));
        assertEquals(160000, capture.bytes()); assertFalse(capture.append(frame));
        capture.clear(); assertEquals(0, capture.bytes()); assertEquals(0, capture.snapshot().length);
    }

    @Test(expected=IllegalArgumentException.class) public void rejectsMisalignedOnset() {
        new BargeInCapture().start(new byte[641]);
    }
}
