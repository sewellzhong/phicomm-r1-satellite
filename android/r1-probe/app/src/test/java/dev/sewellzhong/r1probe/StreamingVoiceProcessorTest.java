package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import org.junit.Test;

public final class StreamingVoiceProcessorTest {
    @Test
    public void matchesBatchPipelineAcrossIrregularChunks() {
        Random random = new Random(19L);
        short[] noise = new short[16000];
        short[] input = new short[32123];
        fill(random, noise, false);
        fill(random, input, true);
        short[] expected = VoiceProcessingPipeline.process(noise, input).samples;
        StreamingVoiceProcessor processor = new StreamingVoiceProcessor(noise);
        List<Short> actualValues = new ArrayList<>();
        int offset = 0;
        int[] chunks = {1, 319, 640, 17, 2048, 127};
        int chunkIndex = 0;
        while (offset < input.length) {
            int length = Math.min(chunks[chunkIndex++ % chunks.length], input.length - offset);
            short[] chunk = new short[length];
            System.arraycopy(input, offset, chunk, 0, length);
            append(actualValues, processor.process(chunk, length));
            offset += length;
        }
        append(actualValues, processor.finish());
        short[] actual = new short[actualValues.size()];
        for (int index = 0; index < actual.length; index++) {
            actual[index] = actualValues.get(index);
        }

        assertEquals(input.length, actual.length);
        assertArrayEquals(expected, actual);
        assertEquals(VoiceProcessingPipeline.FFT_SIZE + VoiceProcessingPipeline.FRAME_SAMPLES,
                processor.stats().boundedStateSamples);
    }

    @Test
    public void reusableBuffersMatchBatchPipelineAndPreserveOffsets() {
        Random random = new Random(23L);
        short[] noise = new short[16000];
        short[] input = new short[33333];
        fill(random, noise, false);
        fill(random, input, true);
        short[] expected = VoiceProcessingPipeline.process(noise, input).samples;
        StreamingVoiceProcessor processor = new StreamingVoiceProcessor(noise);
        short[] inputWorkspace = new short[2048];
        short[] outputWorkspace = new short[inputWorkspace.length + VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES + 4];
        short[] actual = new short[input.length];
        int inputOffset = 0;
        int outputOffset = 0;
        int[] chunks = {1, 319, 320, 511, 2048, 17};
        int chunkIndex = 0;
        while (inputOffset < input.length) {
            int length = Math.min(chunks[chunkIndex++ % chunks.length],
                    input.length - inputOffset);
            System.arraycopy(input, inputOffset, inputWorkspace, 0, length);
            int written = processor.processInto(inputWorkspace, 0, length,
                    outputWorkspace, 2);
            System.arraycopy(outputWorkspace, 2, actual, outputOffset, written);
            inputOffset += length;
            outputOffset += written;
        }
        short[] tailWorkspace = new short[VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES + 3];
        int tailLength = processor.finishInto(tailWorkspace, 3);
        System.arraycopy(tailWorkspace, 3, actual, outputOffset, tailLength);
        outputOffset += tailLength;

        assertEquals(input.length, outputOffset);
        assertArrayEquals(expected, actual);
        assertEquals(3904, processor.stats().workspaceElements);
        assertThrows(IllegalStateException.class,
                () -> processor.processInto(inputWorkspace, 0, 1, outputWorkspace, 2));
    }

    @Test
    public void rejectsUndersizedOutputWithoutFinishingStream() {
        short[] noise = new short[16000];
        StreamingVoiceProcessor processor = new StreamingVoiceProcessor(noise);
        short[] tooSmall = new short[VoiceProcessingPipeline.FFT_SIZE];
        assertThrows(IllegalArgumentException.class, () -> processor.finishInto(tooSmall, 0));
        short[] enough = new short[VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES];
        assertEquals(0, processor.finishInto(enough, 0));
    }

    private static void fill(Random random, short[] samples, boolean speech) {
        for (int index = 0; index < samples.length; index++) {
            int value = random.nextInt(41) - 20;
            if (speech && index > 4000) {
                value += (int) Math.round(50.0 * Math.sin(2.0 * Math.PI * 330.0 * index / 16000.0));
            }
            samples[index] = (short) value;
        }
    }

    private static void append(List<Short> destination, short[] values) {
        for (short value : values) {
            destination.add(value);
        }
    }
}
