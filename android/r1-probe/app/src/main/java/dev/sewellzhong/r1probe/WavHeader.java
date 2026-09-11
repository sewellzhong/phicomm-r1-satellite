package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.Charset;

final class WavHeader {
    static final int HEADER_BYTES = 44;
    static final int SAMPLE_RATE = 16000;
    static final int CHANNELS = 1;
    static final int BITS_PER_SAMPLE = 16;
    static final int BYTES_PER_SAMPLE = BITS_PER_SAMPLE / 8;
    static final int FRAME_SAMPLES = 320;
    static final int FRAME_BYTES = FRAME_SAMPLES * BYTES_PER_SAMPLE;

    private static final Charset ASCII = Charset.forName("US-ASCII");

    private WavHeader() {
    }

    static byte[] create(int pcmBytes) {
        return create(pcmBytes, CHANNELS);
    }

    static byte[] create(int pcmBytes, int channels) {
        if (channels != 1 && channels != 2 && channels != 4) {
            throw new IllegalArgumentException("unsupported_channel_count_" + channels);
        }
        int byteRate = SAMPLE_RATE * channels * BYTES_PER_SAMPLE;
        int blockAlign = channels * BYTES_PER_SAMPLE;
        ByteBuffer buffer = ByteBuffer.allocate(HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put("RIFF".getBytes(ASCII));
        buffer.putInt(36 + pcmBytes);
        buffer.put("WAVE".getBytes(ASCII));
        buffer.put("fmt ".getBytes(ASCII));
        buffer.putInt(16);
        buffer.putShort((short) 1);
        buffer.putShort((short) channels);
        buffer.putInt(SAMPLE_RATE);
        buffer.putInt(byteRate);
        buffer.putShort((short) blockAlign);
        buffer.putShort((short) BITS_PER_SAMPLE);
        buffer.put("data".getBytes(ASCII));
        buffer.putInt(pcmBytes);
        return buffer.array();
    }

    static int validate(File wavFile) throws IOException {
        return validate(wavFile, CHANNELS);
    }

    static int validate(File wavFile, int expectedChannels) throws IOException {
        if (wavFile.length() < HEADER_BYTES) {
            throw new IOException("wav_too_short");
        }
        byte[] header = new byte[HEADER_BYTES];
        RandomAccessFile input = new RandomAccessFile(wavFile, "r");
        try {
            input.readFully(header);
        } finally {
            input.close();
        }
        ByteBuffer buffer = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN);
        requireAscii(buffer, "RIFF");
        buffer.getInt();
        requireAscii(buffer, "WAVE");
        requireAscii(buffer, "fmt ");
        if (buffer.getInt() != 16 || buffer.getShort() != 1) {
            throw new IOException("unsupported_wav_encoding");
        }
        if (buffer.getShort() != expectedChannels || buffer.getInt() != SAMPLE_RATE) {
            throw new IOException("unsupported_wav_format");
        }
        buffer.getInt();
        buffer.getShort();
        if (buffer.getShort() != BITS_PER_SAMPLE) {
            throw new IOException("unsupported_wav_bit_depth");
        }
        requireAscii(buffer, "data");
        int pcmBytes = buffer.getInt();
        if (pcmBytes < 0 || wavFile.length() != HEADER_BYTES + (long) pcmBytes) {
            throw new IOException("invalid_wav_data_size");
        }
        return pcmBytes;
    }

    private static void requireAscii(ByteBuffer buffer, String expected) throws IOException {
        byte[] bytes = new byte[expected.length()];
        buffer.get(bytes);
        if (!expected.equals(new String(bytes, ASCII))) {
            throw new IOException("invalid_wav_chunk_" + expected.trim());
        }
    }
}
