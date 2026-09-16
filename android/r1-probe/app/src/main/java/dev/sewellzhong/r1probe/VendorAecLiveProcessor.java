package dev.sewellzhong.r1probe;

import com.unisound.jni.AEC;

import java.util.ArrayDeque;

/**
 * Bounded live adapter for the firmware AEC ABI. It is used only for playback-time
 * observation until the device proves the complete production factory chain.
 *
 * The 3448 ABI consumes 300 mono samples as [mic, echo] interleaved S16LE. The
 * satellite still runs at 320 samples/20 ms, so this class carries a small bounded
 * input/output queue and never owns AudioRecord or playback.
 */
final class VendorAecLiveProcessor implements AutoCloseable {
    static final int FRAME_SAMPLES = 320;
    static final int ABI_SAMPLES = 300;
    // Firmware 3448 can return up to 600 samples for one 300-sample ABI call;
    // two calls arrive before a 320-sample satellite frame is drained.
    private static final int MAX_QUEUED_SAMPLES = 32768;

    interface Engine {
        int setOptionInt(int option, int value);
        void reset(float microphoneGain, float referenceGain);
        byte[] process(byte[] interleavedMicEcho, byte[] unusedReference);
        void release();
    }

    interface Factory { Engine create(); }

    private final Engine engine;
    private final short[] microphones = new short[ABI_SAMPLES];
    private final short[] references = new short[ABI_SAMPLES];
    private int buffered;
    private final ArrayDeque<Short> output = new ArrayDeque<>();
    private long inputSamples;
    private long outputSamples;
    private long inputSaturatedSamples;
    private long outputSaturatedSamples;
    private long chunks;
    private int inputPeak;
    private int outputPeak;
    private int outputMinimum = 32767;
    private int outputMaximum = -32768;
    private boolean closed;

    static VendorAecLiveProcessor tryCreate() {
        try {
            return new VendorAecLiveProcessor(new Factory() {
                @Override public Engine create() {
                    return new NativeEngine(new AEC(WavHeader.SAMPLE_RATE, 1));
                }
            });
        } catch (Throwable error) {
            return null;
        }
    }

    VendorAecLiveProcessor(Factory factory) {
        if (factory == null) throw new IllegalArgumentException("aec_factory_required");
        engine = factory.create();
        if (engine == null) throw new IllegalStateException("aec_engine_missing");
        engine.setOptionInt(0, 600);
        // The original caller proceeds when this returns -1 on firmware 3448.
        engine.setOptionInt(2, 1);
        engine.setOptionInt(3, 0);
        engine.reset(0.0f, 0.0f);
    }

    /** Returns true only when a complete 320-sample AEC-clean frame is available. */
    boolean process(short[] microphone, short[] reference, short[] cleaned) {
        if (closed || microphone == null || reference == null || cleaned == null
                || microphone.length != FRAME_SAMPLES || reference.length != FRAME_SAMPLES
                || cleaned.length != FRAME_SAMPLES) {
            throw new IllegalArgumentException("aec_live_frame_size");
        }
        for (int i = 0; i < FRAME_SAMPLES; i++) {
            inputSamples++;
            int mic = Math.abs((int) microphone[i]);
            inputPeak = Math.max(inputPeak, mic);
            if (microphone[i] == Short.MIN_VALUE || microphone[i] == Short.MAX_VALUE) {
                inputSaturatedSamples++;
            }
            microphones[buffered++] = microphone[i];
            references[buffered - 1] = reference[i];
            if (buffered == ABI_SAMPLES) {
                processChunk();
                buffered = 0;
            }
        }
        if (output.size() < FRAME_SAMPLES) return false;
        for (int i = 0; i < FRAME_SAMPLES; i++) {
            short sample = output.removeFirst();
            cleaned[i] = sample;
        }
        return true;
    }

    int queuedSamples() { return output.size(); }
    long inputSamples() { return inputSamples; }
    long outputSamples() { return outputSamples; }
    long inputSaturatedSamples() { return inputSaturatedSamples; }
    long outputSaturatedSamples() { return outputSaturatedSamples; }
    long chunks() { return chunks; }
    int inputPeak() { return inputPeak; }
    int outputPeak() { return outputPeak; }
    int outputMinimum() { return outputSamples == 0 ? 0 : outputMinimum; }
    int outputMaximum() { return outputSamples == 0 ? 0 : outputMaximum; }

    void reset() {
        buffered = 0;
        output.clear();
        engine.reset(0.0f, 0.0f);
        inputSamples = outputSamples = inputSaturatedSamples = outputSaturatedSamples = 0;
        chunks = 0;
        inputPeak = outputPeak = 0;
        outputMinimum = 32767;
        outputMaximum = -32768;
    }

    private void processChunk() {
        chunks++;
        byte[] interleaved = new byte[ABI_SAMPLES * 4];
        for (int i = 0; i < ABI_SAMPLES; i++) {
            int destination = i * 4;
            interleaved[destination] = (byte) microphones[i];
            interleaved[destination + 1] = (byte) (microphones[i] >>> 8);
            interleaved[destination + 2] = (byte) references[i];
            interleaved[destination + 3] = (byte) (references[i] >>> 8);
        }
        byte[] bytes = engine.process(interleaved, null);
        // The original offline caller ignores null/empty process output and flushes
        // the engine later. Live observation must preserve that ABI behavior rather
        // than disabling the adapter on the first warm-up chunk.
        if (bytes != null && ((bytes.length & 1) != 0 || bytes.length > 8192)) {
            throw new IllegalStateException("aec_live_output_shape");
        }
        if (bytes == null || bytes.length == 0) return;
        if (output.size() + bytes.length / 2 > MAX_QUEUED_SAMPLES) {
            throw new IllegalStateException("aec_live_queue_overflow");
        }
        for (int i = 0; i < bytes.length; i += 2) {
            short sample = (short)((bytes[i] & 0xff) | (bytes[i + 1] << 8));
            output.add(sample);
            int absolute = Math.abs((int) sample);
            outputPeak = Math.max(outputPeak, absolute);
            outputMinimum = Math.min(outputMinimum, sample);
            outputMaximum = Math.max(outputMaximum, sample);
            if (sample == Short.MIN_VALUE || sample == Short.MAX_VALUE) {
                outputSaturatedSamples++;
            }
            outputSamples++;
        }
    }

    @Override public void close() {
        if (!closed) {
            closed = true;
            output.clear();
            engine.release();
        }
    }

    private static final class NativeEngine implements Engine {
        private final AEC delegate;
        NativeEngine(AEC delegate) { this.delegate = delegate; }
        @Override public int setOptionInt(int option, int value) { return delegate.setOptionInt(option, value); }
        @Override public void reset(float microphoneGain, float referenceGain) { delegate.reset(microphoneGain, referenceGain); }
        @Override public byte[] process(byte[] interleavedMicEcho, byte[] unusedReference) {
            return delegate.process(interleavedMicEcho, unusedReference);
        }
        @Override public void release() { delegate.release(); }
    }
}
