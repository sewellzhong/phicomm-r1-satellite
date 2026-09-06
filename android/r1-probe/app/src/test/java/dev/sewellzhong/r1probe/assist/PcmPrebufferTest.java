package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import java.util.Arrays;
import static org.junit.Assert.*;

public final class PcmPrebufferTest {
    @Test public void wrapsAtTwoSecondsAndPreservesLittleEndianChronology() {
        PcmPrebuffer buffer = new PcmPrebuffer();
        for (short n = 0; n < 105; n++) {
            short[] frame = new short[320];
            Arrays.fill(frame, n);
            buffer.append(frame);
        }
        byte[] pcm = buffer.snapshot();
        assertEquals(64000, pcm.length);
        assertEquals(5, pcm[0]);
        assertEquals(0, pcm[1]);
        assertEquals(104, pcm[63360]);
        pcm[0] = 99;
        assertEquals(5, buffer.snapshot()[0]);
        buffer.clear();
        assertEquals(0, buffer.snapshot().length);
    }

    @Test public void selectsOnlyLatestTwoHundredMillisecondsAcrossWrap() {
        PcmPrebuffer buffer = new PcmPrebuffer();
        for (short n = 0; n < 105; n++) {
            short[] frame = new short[320]; Arrays.fill(frame, n); buffer.append(frame);
        }
        byte[] recent = buffer.snapshot(10);
        assertEquals(6400, recent.length);
        assertEquals(95, recent[0]);
        assertEquals(104, recent[5760]);
        assertEquals(64000, buffer.snapshot().length);
        assertEquals(0, buffer.snapshot(0).length);
    }

    @Test public void signedSampleEncodingIsS16le() {
        PcmPrebuffer buffer = new PcmPrebuffer();
        short[] frame = new short[320]; frame[0] = -32768; frame[1] = 32767;
        buffer.append(frame);
        byte[] pcm = buffer.snapshot();
        assertEquals(0, pcm[0]); assertEquals((byte) 128, pcm[1]);
        assertEquals((byte) 255, pcm[2]); assertEquals(127, pcm[3]);
    }
}
