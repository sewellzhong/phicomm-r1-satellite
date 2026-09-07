package dev.sewellzhong.r1probe;

import java.io.IOException;
import java.io.InputStream;

/** Reader for the 16-byte, 32-bit little-endian input_event ABI used by ARMv7 firmware 3448. */
final class LinuxInputEventReader {
    interface Consumer { void event(int type, int code, int value, long eventMs); }
    private static final int EVENT_BYTES = 16;
    private final InputStream input;
    private final Consumer consumer;
    LinuxInputEventReader(InputStream input, Consumer consumer) {
        this.input = input; this.consumer = consumer;
    }
    void run() throws IOException {
        byte[] event = new byte[EVENT_BYTES];
        while (!Thread.currentThread().isInterrupted()) {
            int offset = 0;
            while (offset < event.length) {
                int count = input.read(event, offset, event.length - offset);
                if (count < 0) return;
                if (count == 0) continue;
                offset += count;
            }
            long seconds = unsignedInt(event, 0);
            long micros = unsignedInt(event, 4);
            int type = unsignedShort(event, 8), code = unsignedShort(event, 10);
            int value = signedInt(event, 12);
            consumer.event(type, code, value, seconds * 1000L + micros / 1000L);
        }
    }
    private static int unsignedShort(byte[] bytes, int offset) {
        return (bytes[offset] & 255) | ((bytes[offset + 1] & 255) << 8);
    }
    private static long unsignedInt(byte[] bytes, int offset) {
        return signedInt(bytes, offset) & 0xffffffffL;
    }
    private static int signedInt(byte[] bytes, int offset) {
        return (bytes[offset] & 255) | ((bytes[offset + 1] & 255) << 8)
                | ((bytes[offset + 2] & 255) << 16) | (bytes[offset + 3] << 24);
    }
}
