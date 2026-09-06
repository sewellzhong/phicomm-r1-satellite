package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

import org.junit.Test;

public final class WavHeaderTest {
    @Test
    public void createsCanonicalPcmHeader() {
        byte[] header = WavHeader.create(320000);
        assertEquals(44, header.length);
        assertArrayEquals("RIFF".getBytes(StandardCharsets.US_ASCII), slice(header, 0, 4));
        assertArrayEquals("WAVE".getBytes(StandardCharsets.US_ASCII), slice(header, 8, 12));
        assertEquals(320036, littleEndianInt(header, 4));
        assertEquals(16000, littleEndianInt(header, 24));
        assertEquals(320000, littleEndianInt(header, 40));
    }

    @Test
    public void createsStereoPcmHeader() {
        byte[] header = WavHeader.create(640000, 2);
        assertEquals(2, littleEndianShort(header, 22));
        assertEquals(64000, littleEndianInt(header, 28));
        assertEquals(4, littleEndianShort(header, 32));
        assertEquals(640000, littleEndianInt(header, 40));
    }

    private static byte[] slice(byte[] source, int start, int end) {
        byte[] result = new byte[end - start];
        System.arraycopy(source, start, result, 0, result.length);
        return result;
    }

    private static int littleEndianInt(byte[] bytes, int offset) {
        return ByteBuffer.wrap(bytes, offset, 4).order(ByteOrder.LITTLE_ENDIAN).getInt();
    }

    private static int littleEndianShort(byte[] bytes, int offset) {
        return ByteBuffer.wrap(bytes, offset, 2).order(ByteOrder.LITTLE_ENDIAN).getShort();
    }
}
