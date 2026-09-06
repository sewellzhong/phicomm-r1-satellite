package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertArrayEquals;

import org.junit.Test;

public final class StereoPcmSplitterTest {
    @Test
    public void splitsAndDerivesChannelsWithoutOverflow() {
        byte[] stereo = {
                0x10, 0x27, (byte) 0xf0, (byte) 0xd8,
                0x00, (byte) 0x80, (byte) 0xff, 0x7f
        };

        StereoPcmSplitter.Split split = StereoPcmSplitter.split(stereo, stereo.length);

        assertArrayEquals(new byte[] {0x10, 0x27, 0x00, (byte) 0x80}, split.left);
        assertArrayEquals(new byte[] {(byte) 0xf0, (byte) 0xd8, (byte) 0xff, 0x7f}, split.right);
        assertArrayEquals(new byte[] {0x00, 0x00, 0x00, 0x00}, split.average);
        assertArrayEquals(new byte[] {0x10, 0x27, 0x01, (byte) 0x80}, split.difference);
    }
}
