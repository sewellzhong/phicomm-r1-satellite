package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

import org.junit.Test;

public final class VendorAecOfflineProcessorTest {
    @Test public void usesOriginalOptionsChunksAndDelayedReference() throws Exception {
        File directory = Files.createTempDirectory("vendor-aec-test").toFile();
        File microphone = new File(directory, "microphone.wav");
        File reference = new File(directory, "reference.wav");
        File output = new File(directory, "output.wav");
        short[] microphoneSamples = new short[900];
        short[] referenceSamples = new short[900];
        for (int index = 0; index < 900; index++) {
            microphoneSamples[index] = (short) (index + 1);
            referenceSamples[index] = (short) (1000 + index);
        }
        MonoWavIo.write(microphone, microphoneSamples);
        MonoWavIo.write(reference, referenceSamples);
        final FakeEngine engine = new FakeEngine();
        VendorAecOfflineProcessor.Result result = VendorAecOfflineProcessor.process(
                microphone, reference, output, 100, new VendorAecOfflineProcessor.EngineFactory() {
                    @Override public VendorAecOfflineProcessor.Engine create() { return engine; }
                });
        assertEquals(3, result.chunks);
        assertEquals(1800, result.outputBytes);
        assertEquals("0:600", engine.options.get(0));
        assertEquals("2:1", engine.options.get(1));
        assertEquals("3:0", engine.options.get(2));
        assertEquals(0, result.option0Result);
        assertEquals(-1, result.option2Result);
        assertEquals(0, result.option3Result);
        assertTrue(engine.reset);
        assertTrue(engine.released);
        assertEquals(1, sample(engine.inputs.get(0), 0));
        assertEquals(0, sample(engine.inputs.get(0), 1));
        assertEquals(100, sample(engine.inputs.get(0), 198));
        assertEquals(0, sample(engine.inputs.get(0), 199));
        assertEquals(101, sample(engine.inputs.get(0), 200));
        assertEquals(1000, sample(engine.inputs.get(0), 201));
        assertEquals(301, sample(engine.inputs.get(1), 0));
        assertEquals(1200, sample(engine.inputs.get(1), 1));
        assertTrue(engine.referencesAreNull);
        assertEquals(900, MonoWavIo.read(output).length);
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsUnboundedReferenceOffset() throws Exception {
        File directory = Files.createTempDirectory("vendor-aec-offset-test").toFile();
        File microphone = new File(directory, "microphone.wav");
        File reference = new File(directory, "reference.wav");
        MonoWavIo.write(microphone, new short[] {1});
        MonoWavIo.write(reference, new short[] {1});
        VendorAecOfflineProcessor.process(microphone, reference,
                new File(directory, "output.wav"), 160001, null);
    }

    private static int sample(byte[] bytes, int sample) {
        int offset = sample * 2;
        return (short) ((bytes[offset] & 0xff) | (bytes[offset + 1] << 8));
    }

    private static final class FakeEngine implements VendorAecOfflineProcessor.Engine {
        final List<String> options = new ArrayList<>();
        final List<byte[]> inputs = new ArrayList<>();
        boolean reset;
        boolean released;
        boolean referencesAreNull = true;

        @Override public int setOptionInt(int option, int value) {
            options.add(option + ":" + value);
            return option == 2 ? -1 : 0;
        }

        @Override public void reset(float microphoneGain, float referenceGain) { reset = true; }

        @Override public byte[] process(byte[] microphone, byte[] reference) {
            inputs.add(microphone);
            referencesAreNull &= reference == null;
            byte[] mono = new byte[microphone.length / 2];
            for (int source = 0, destination = 0; source < microphone.length;
                    source += 4, destination += 2) {
                mono[destination] = microphone[source];
                mono[destination + 1] = microphone[source + 1];
            }
            return mono;
        }

        @Override public byte[] getLast() { return new byte[0]; }
        @Override public void release() { released = true; }
    }
}
