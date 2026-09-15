package dev.sewellzhong.r1probe;

import com.unisound.jni.AEC;

import java.io.ByteArrayOutputStream;
import java.io.File;

/** Bounded offline use of the firmware's original mono AEC. Never used by production capture. */
final class VendorAecOfflineProcessor {
    static final int CHUNK_BYTES = 1200;
    static final int MONO_CHUNK_BYTES = CHUNK_BYTES / 2;
    static final int MAX_PCM_BYTES = 60 * WavHeader.SAMPLE_RATE * WavHeader.BYTES_PER_SAMPLE;

    interface Engine {
        int setOptionInt(int option, int value);
        void reset(float microphoneGain, float referenceGain);
        byte[] process(byte[] microphone, byte[] reference);
        byte[] getLast();
        void release();
    }

    interface EngineFactory {
        Engine create();
    }

    static final class Result {
        final int microphoneBytes;
        final int referenceBytes;
        final int outputBytes;
        final int chunks;
        final int referenceOffsetSamples;
        final long elapsedNanos;
        final int option0Result;
        final int option2Result;
        final int option3Result;

        Result(int microphoneBytes, int referenceBytes, int outputBytes, int chunks,
                int referenceOffsetSamples, long elapsedNanos, int option0Result,
                int option2Result, int option3Result) {
            this.microphoneBytes = microphoneBytes;
            this.referenceBytes = referenceBytes;
            this.outputBytes = outputBytes;
            this.chunks = chunks;
            this.referenceOffsetSamples = referenceOffsetSamples;
            this.elapsedNanos = elapsedNanos;
            this.option0Result = option0Result;
            this.option2Result = option2Result;
            this.option3Result = option3Result;
        }
    }

    private VendorAecOfflineProcessor() {
    }

    static Result process(File microphoneWav, File referenceWav, File outputWav,
            int referenceOffsetSamples) throws Exception {
        return process(microphoneWav, referenceWav, outputWav, referenceOffsetSamples,
                new EngineFactory() {
                    @Override public Engine create() {
                        return new NativeEngine(new AEC(WavHeader.SAMPLE_RATE, 1));
                    }
                });
    }

    static Result process(File microphoneWav, File referenceWav, File outputWav,
            int referenceOffsetSamples, EngineFactory factory) throws Exception {
        short[] microphone = MonoWavIo.read(microphoneWav);
        short[] reference = MonoWavIo.read(referenceWav);
        if (microphone.length == 0 || microphone.length * 2 > MAX_PCM_BYTES) {
            throw new IllegalArgumentException("microphone_duration_out_of_range");
        }
        if (reference.length == 0 || reference.length * 2 > MAX_PCM_BYTES) {
            throw new IllegalArgumentException("reference_duration_out_of_range");
        }
        if (referenceOffsetSamples < -WavHeader.SAMPLE_RATE * 10
                || referenceOffsetSamples > WavHeader.SAMPLE_RATE * 10) {
            throw new IllegalArgumentException("reference_offset_out_of_range");
        }
        byte[] microphoneBytes = littleEndianBytes(microphone);
        byte[] referenceBytes = littleEndianBytes(reference);
        ByteArrayOutputStream output = new ByteArrayOutputStream(microphoneBytes.length);
        Engine engine = factory.create();
        int chunks = 0;
        int option0Result;
        int option2Result;
        int option3Result;
        long started = System.nanoTime();
        try {
            // The original IAudioSourceAEC invokes these in this order and ignores their
            // return values. Preserve and report those values; a 3448 device returns -1 for
            // option 2 even though the original caller proceeds.
            option0Result = engine.setOptionInt(0, 600);
            option2Result = engine.setOptionInt(2, 1);
            option3Result = engine.setOptionInt(3, 0);
            engine.reset(0.0f, 0.0f);
            for (int offset = 0; offset < microphoneBytes.length; offset += MONO_CHUNK_BYTES) {
                int length = Math.min(MONO_CHUNK_BYTES, microphoneBytes.length - offset);
                // bargeinProcess divides its first input by nmic+1 and, with the original
                // AEC(16000, 1), deinterleaves each [mic, echo] pair. DWARF names the
                // corresponding buffers mcdata and echodata. The original Java
                // caller also passes null as process()'s second argument.
                byte[] interleaved = interleaveMicrophoneAndReference(referenceBytes,
                        microphoneBytes, offset, length,
                        referenceOffsetSamples * WavHeader.BYTES_PER_SAMPLE);
                appendBounded(output, engine.process(interleaved, null));
                chunks++;
            }
            appendBounded(output, engine.getLast());
        } finally {
            engine.release();
        }
        byte[] outputBytes = output.toByteArray();
        if ((outputBytes.length & 1) != 0 || outputBytes.length == 0
                || outputBytes.length > microphoneBytes.length + CHUNK_BYTES) {
            throw new IllegalStateException("vendor_aec_output_size_invalid");
        }
        MonoWavIo.write(outputWav, littleEndianSamples(outputBytes));
        return new Result(microphoneBytes.length, referenceBytes.length, outputBytes.length,
                chunks, referenceOffsetSamples, System.nanoTime() - started,
                option0Result, option2Result, option3Result);
    }

    private static void appendBounded(ByteArrayOutputStream output, byte[] bytes) {
        if (bytes == null || bytes.length == 0) {
            return;
        }
        if (output.size() + bytes.length > MAX_PCM_BYTES + CHUNK_BYTES) {
            throw new IllegalStateException("vendor_aec_output_unbounded");
        }
        output.write(bytes, 0, bytes.length);
    }

    private static byte[] interleaveMicrophoneAndReference(byte[] reference, byte[] microphone,
            int microphoneOffset, int length,
            int referenceOffsetBytes) {
        byte[] chunk = new byte[length * 2];
        for (int offset = 0; offset < length; offset += 2) {
            int referenceOffset = microphoneOffset + offset - referenceOffsetBytes;
            int destination = offset * 2;
            chunk[destination] = microphone[microphoneOffset + offset];
            chunk[destination + 1] = microphone[microphoneOffset + offset + 1];
            if (referenceOffset >= 0 && referenceOffset + 1 < reference.length) {
                chunk[destination + 2] = reference[referenceOffset];
                chunk[destination + 3] = reference[referenceOffset + 1];
            }
        }
        return chunk;
    }

    private static byte[] littleEndianBytes(short[] samples) {
        byte[] bytes = new byte[samples.length * 2];
        for (int index = 0; index < samples.length; index++) {
            bytes[index * 2] = (byte) (samples[index] & 0xff);
            bytes[index * 2 + 1] = (byte) ((samples[index] >>> 8) & 0xff);
        }
        return bytes;
    }

    private static short[] littleEndianSamples(byte[] bytes) {
        short[] samples = new short[bytes.length / 2];
        for (int index = 0; index < samples.length; index++) {
            samples[index] = (short) ((bytes[index * 2] & 0xff) | (bytes[index * 2 + 1] << 8));
        }
        return samples;
    }

    private static final class NativeEngine implements Engine {
        private final AEC delegate;

        NativeEngine(AEC delegate) {
            this.delegate = delegate;
        }

        @Override public int setOptionInt(int option, int value) {
            return delegate.setOptionInt(option, value);
        }

        @Override public void reset(float microphoneGain, float referenceGain) {
            delegate.reset(microphoneGain, referenceGain);
        }

        @Override public byte[] process(byte[] microphone, byte[] reference) {
            return delegate.process(microphone, reference);
        }

        @Override public byte[] getLast() {
            return delegate.getlast();
        }

        @Override public void release() {
            delegate.release();
        }
    }
}
