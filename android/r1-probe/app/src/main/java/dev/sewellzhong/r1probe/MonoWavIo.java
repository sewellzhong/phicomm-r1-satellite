package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;

final class MonoWavIo {
    private MonoWavIo() {
    }

    static short[] read(File file) throws Exception {
        int pcmBytes = WavHeader.validate(file);
        if ((pcmBytes & 1) != 0) {
            throw new IllegalStateException("odd_pcm_bytes");
        }
        byte[] bytes = new byte[pcmBytes];
        RandomAccessFile input = new RandomAccessFile(file, "r");
        try {
            input.seek(WavHeader.HEADER_BYTES);
            input.readFully(bytes);
        } finally {
            input.close();
        }
        short[] samples = new short[pcmBytes / 2];
        for (int index = 0; index < samples.length; index++) {
            int offset = index * 2;
            samples[index] = (short) ((bytes[offset] & 0xff) | (bytes[offset + 1] << 8));
        }
        return samples;
    }

    static void write(File file, short[] samples) throws Exception {
        FileOutputStream output = new FileOutputStream(file);
        try {
            output.write(WavHeader.create(samples.length * 2));
            byte[] bytes = new byte[samples.length * 2];
            for (int index = 0; index < samples.length; index++) {
                int offset = index * 2;
                bytes[offset] = (byte) (samples[index] & 0xff);
                bytes[offset + 1] = (byte) ((samples[index] >>> 8) & 0xff);
            }
            output.write(bytes);
        } finally {
            output.close();
        }
    }
}
