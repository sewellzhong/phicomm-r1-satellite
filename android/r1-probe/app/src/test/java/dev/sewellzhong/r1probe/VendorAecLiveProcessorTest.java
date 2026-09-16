package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class VendorAecLiveProcessorTest {
    private static class FakeEngine implements VendorAecLiveProcessor.Engine {
        int calls;
        boolean released;
        @Override public int setOptionInt(int option, int value) { return option == 2 ? -1 : 0; }
        @Override public void reset(float microphoneGain, float referenceGain) { }
        @Override public byte[] process(byte[] input, byte[] unused) {
            calls++;
            byte[] output = new byte[VendorAecLiveProcessor.ABI_SAMPLES * 2];
            for (int i = 0; i < VendorAecLiveProcessor.ABI_SAMPLES; i++) {
                output[i * 2] = input[i * 4];
                output[i * 2 + 1] = input[i * 4 + 1];
            }
            return output;
        }
        @Override public void release() { released = true; }
    }

    @Test public void buffersAbiChunksAndReturnsFixedFrames() {
        final FakeEngine engine = new FakeEngine();
        VendorAecLiveProcessor processor = new VendorAecLiveProcessor(() -> engine);
        short[] microphone = new short[320];
        short[] reference = new short[320];
        short[] output = new short[320];
        assertFalse(processor.process(microphone, reference, output));
        assertTrue(processor.process(microphone, reference, output));
        assertEquals(2, engine.calls);
        assertEquals(280, processor.queuedSamples());
        assertEquals(640, processor.inputSamples());
        assertEquals(600, processor.outputSamples());
        assertEquals(2, processor.chunks());
        processor.close();
        assertTrue(engine.released);
    }

    @Test public void tracksInputAndOutputSaturationSeparately() {
        final FakeEngine engine = new FakeEngine() {
            @Override public byte[] process(byte[] input, byte[] unused) {
                calls++;
                byte[] output = new byte[VendorAecLiveProcessor.ABI_SAMPLES * 2];
                for (int i = 0; i < VendorAecLiveProcessor.ABI_SAMPLES; i++) {
                    output[i * 2] = (byte) 0xe8;
                    output[i * 2 + 1] = (byte) 0x03;
                }
                return output;
            }
        };
        VendorAecLiveProcessor processor = new VendorAecLiveProcessor(() -> engine);
        short[] microphone = new short[320];
        microphone[0] = Short.MIN_VALUE;
        microphone[1] = Short.MAX_VALUE;
        short[] output = new short[320];
        processor.process(microphone, new short[320], output);
        processor.process(microphone, new short[320], output);
        assertEquals(4, processor.inputSaturatedSamples());
        assertEquals(0, processor.outputSaturatedSamples());
        assertEquals(32768, processor.inputPeak());
        assertEquals(1000, processor.outputPeak());
        assertEquals(1000, processor.outputMinimum());
        assertEquals(1000, processor.outputMaximum());
        processor.close();
    }

    @Test public void resetClearsStreamingCountersAndQueue() {
        VendorAecLiveProcessor processor = new VendorAecLiveProcessor(() -> new FakeEngine());
        processor.process(new short[320], new short[320], new short[320]);
        processor.process(new short[320], new short[320], new short[320]);
        assertTrue(processor.inputSamples() > 0);
        assertTrue(processor.queuedSamples() > 0);
        processor.reset();
        assertEquals(0, processor.inputSamples());
        assertEquals(0, processor.outputSamples());
        assertEquals(0, processor.chunks());
        assertEquals(0, processor.queuedSamples());
        processor.close();
    }

    @Test public void rejectsMalformedVendorOutput() {
        VendorAecLiveProcessor processor = new VendorAecLiveProcessor(() -> new FakeEngine() {
            @Override public byte[] process(byte[] input, byte[] unused) { return new byte[] {1}; }
        });
        try {
            processor.process(new short[320], new short[320], new short[320]);
            processor.process(new short[320], new short[320], new short[320]);
            throw new AssertionError("malformed output accepted");
        } catch (IllegalStateException expected) {
            assertEquals("aec_live_output_shape", expected.getMessage());
        } finally {
            processor.close();
        }
    }

    @Test public void acceptsBoundedExpandedVendorOutput() {
        VendorAecLiveProcessor processor = new VendorAecLiveProcessor(() -> new FakeEngine() {
            @Override public byte[] process(byte[] input, byte[] unused) {
                return new byte[VendorAecLiveProcessor.ABI_SAMPLES * 4];
            }
        });
        assertTrue(processor.process(new short[320], new short[320], new short[320]));
        processor.close();
    }
}
