package dev.sewellzhong.r1probe;

final class StereoPcmSplitter {
    private StereoPcmSplitter() {
    }

    static Split split(byte[] stereo, int length) {
        if (length < 0 || length > stereo.length || (length & 3) != 0) {
            throw new IllegalArgumentException("invalid_stereo_pcm_length_" + length);
        }
        int monoLength = length / 2;
        byte[] left = new byte[monoLength];
        byte[] right = new byte[monoLength];
        byte[] average = new byte[monoLength];
        byte[] difference = new byte[monoLength];
        int outputOffset = 0;
        for (int inputOffset = 0; inputOffset < length; inputOffset += 4) {
            short leftSample = littleEndianShort(stereo, inputOffset);
            short rightSample = littleEndianShort(stereo, inputOffset + 2);
            putLittleEndianShort(left, outputOffset, leftSample);
            putLittleEndianShort(right, outputOffset, rightSample);
            putLittleEndianShort(average, outputOffset,
                    (short) (((int) leftSample + (int) rightSample) / 2));
            putLittleEndianShort(difference, outputOffset,
                    (short) (((int) leftSample - (int) rightSample) / 2));
            outputOffset += 2;
        }
        return new Split(left, right, average, difference);
    }

    private static short littleEndianShort(byte[] bytes, int offset) {
        return (short) ((bytes[offset] & 0xff) | (bytes[offset + 1] << 8));
    }

    private static void putLittleEndianShort(byte[] bytes, int offset, short value) {
        bytes[offset] = (byte) (value & 0xff);
        bytes[offset + 1] = (byte) ((value >>> 8) & 0xff);
    }

    static final class Split {
        final byte[] left;
        final byte[] right;
        final byte[] average;
        final byte[] difference;

        Split(byte[] left, byte[] right, byte[] average, byte[] difference) {
            this.left = left;
            this.right = right;
            this.average = average;
            this.difference = difference;
        }
    }
}
