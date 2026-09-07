package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class LinuxInputEventReaderTest {
    @Test public void decodesFirmwareArmv7InputEvent() throws Exception {
        byte[] bytes = event(90778, 170055, 1, 195, 1);
        List<String> events = new ArrayList<>();
        new LinuxInputEventReader(new ByteArrayInputStream(bytes), (type, code, value, ms) ->
                events.add(type + ":" + code + ":" + value + ":" + ms)).run();
        assertEquals(java.util.Collections.singletonList("1:195:1:90778170"), events);
    }

    @Test public void joinsPartialReadsWithoutInventingEvents() throws Exception {
        byte[] bytes = concat(event(1, 1000, 1, 195, 1), event(1, 2000, 1, 195, 0));
        InputStream chunks = new ByteArrayInputStream(bytes) {
            @Override public synchronized int read(byte[] target, int offset, int length) {
                return super.read(target, offset, Math.min(3, length));
            }
        };
        List<Integer> values = new ArrayList<>();
        new LinuxInputEventReader(chunks, (type, code, value, ms) -> values.add(value)).run();
        assertEquals(java.util.Arrays.asList(1, 0), values);
    }

    @Test public void discardsTruncatedFinalEvent() throws Exception {
        byte[] full = event(1, 0, 3, 0, -2); byte[] truncated = java.util.Arrays.copyOf(full, 9);
        List<Integer> values = new ArrayList<>();
        new LinuxInputEventReader(new ByteArrayInputStream(truncated), (type, code, value, ms) -> values.add(value)).run();
        assertEquals(0, values.size());
    }

    private static byte[] event(int seconds, int micros, int type, int code, int value) {
        byte[] result = new byte[16]; putInt(result, 0, seconds); putInt(result, 4, micros);
        result[8] = (byte) type; result[9] = (byte) (type >>> 8);
        result[10] = (byte) code; result[11] = (byte) (code >>> 8); putInt(result, 12, value);
        return result;
    }
    private static void putInt(byte[] target, int offset, int value) {
        for (int i = 0; i < 4; i++) target[offset + i] = (byte) (value >>> (8 * i));
    }
    private static byte[] concat(byte[] first, byte[] second) {
        byte[] result = new byte[first.length + second.length];
        System.arraycopy(first, 0, result, 0, first.length); System.arraycopy(second, 0, result, first.length, second.length);
        return result;
    }
}
