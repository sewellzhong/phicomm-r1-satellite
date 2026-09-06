package dev.sewellzhong.r1probe;

import java.util.Arrays;

final class StreamingVoiceProcessor {
    private final double[] analysisWindow;
    private final double[] noisePower;
    private final double noiseRms;
    private final double[] inputRing = new double[VoiceProcessingPipeline.FFT_SIZE];
    private final double[] overlap = new double[VoiceProcessingPipeline.FFT_SIZE];
    private final double[] normalization = new double[VoiceProcessingPipeline.FFT_SIZE];
    private final double[] fftReal = new double[VoiceProcessingPipeline.FFT_SIZE];
    private final double[] fftImaginary = new double[VoiceProcessingPipeline.FFT_SIZE];
    private final short[] gainFrame = new short[VoiceProcessingPipeline.FRAME_SAMPLES];
    private short[] outputBuffer;
    private int outputOffset;
    private int outputSize;
    private int outputLimit;
    private int inputHead;
    private int inputCount;
    private int gainFrameCount;
    private long totalInputSamples;
    private long spectralSamplesSeen;
    private long totalOutputSamples;
    private double currentGain = VoiceProcessingPipeline.INACTIVE_GAIN;
    private double previousGain = VoiceProcessingPipeline.INACTIVE_GAIN;
    private int activeFrames;
    private int clippedSamples;
    private double maximumGain = VoiceProcessingPipeline.INACTIVE_GAIN;
    private double gainDbSum;
    private int gainCount;
    private boolean finished;
    private double previousHighPassInput;
    private double previousHighPassOutput;

    StreamingVoiceProcessor(short[] noiseCalibration) {
        analysisWindow = VoiceProcessingPipeline.window();
        noisePower = VoiceProcessingPipeline.noiseProfile(noiseCalibration, analysisWindow);
        short[] balancedNoise = VoiceProcessingPipeline.quantize(
                VoiceProcessingPipeline.denoise(noiseCalibration, noisePower, analysisWindow),
                VoiceProcessingPipeline.FIXED_GAIN);
        noiseRms = VoiceProcessingPipeline.rms(balancedNoise, 0, balancedNoise.length);
        for (int index = 0; index < VoiceProcessingPipeline.FFT_SIZE / 2; index++) {
            addInputSample(0.0);
        }
    }

    short[] process(short[] samples, int length) {
        short[] output = new short[length + VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES];
        int written = processInto(samples, 0, length, output, 0);
        return Arrays.copyOf(output, written);
    }

    int processInto(short[] samples, int inputOffset, int length, short[] output,
            int destinationOffset) {
        if (finished) {
            throw new IllegalStateException("stream_already_finished");
        }
        if (inputOffset < 0 || length < 0 || inputOffset + length > samples.length) {
            throw new IllegalArgumentException("invalid_stream_length");
        }
        beginOutput(output, destinationOffset, length + VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES);
        for (int index = 0; index < length; index++) {
            totalInputSamples++;
            double input = samples[inputOffset + index];
            double filtered = input - previousHighPassInput
                    + 0.995 * previousHighPassOutput;
            previousHighPassInput = input;
            previousHighPassOutput = filtered;
            addInputSample(filtered);
        }
        return endOutput();
    }

    short[] finish() {
        short[] output = new short[VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES];
        int written = finishInto(output, 0);
        return Arrays.copyOf(output, written);
    }

    int finishInto(short[] output, int destinationOffset) {
        if (finished) {
            throw new IllegalStateException("stream_already_finished");
        }
        beginOutput(output, destinationOffset, VoiceProcessingPipeline.FFT_SIZE
                + VoiceProcessingPipeline.FRAME_SAMPLES);
        finished = true;
        for (int index = 0; index < VoiceProcessingPipeline.FFT_SIZE; index++) {
            addInputSample(0.0);
        }
        if (gainFrameCount > 0) {
            applyGainFrame(gainFrameCount);
            gainFrameCount = 0;
        }
        if (totalOutputSamples != totalInputSamples) {
            throw new IllegalStateException("stream_output_length_" + totalOutputSamples
                    + "_expected_" + totalInputSamples);
        }
        return endOutput();
    }

    Stats stats() {
        return new Stats(totalInputSamples, totalOutputSamples, activeFrames, clippedSamples,
                20.0 * Math.log10(maximumGain), gainCount == 0 ? 0.0 : gainDbSum / gainCount,
                VoiceProcessingPipeline.FFT_SIZE + VoiceProcessingPipeline.FRAME_SAMPLES,
                7 * VoiceProcessingPipeline.FFT_SIZE + VoiceProcessingPipeline.FRAME_SAMPLES);
    }

    private void addInputSample(double sample) {
        if (inputCount == inputRing.length) {
            throw new IllegalStateException("stream_input_ring_overflow");
        }
        int tail = (inputHead + inputCount) % inputRing.length;
        inputRing[tail] = sample;
        inputCount++;
        if (inputCount == inputRing.length) {
            processSpectralFrame();
            inputHead = (inputHead + VoiceProcessingPipeline.HOP_SIZE) % inputRing.length;
            inputCount -= VoiceProcessingPipeline.HOP_SIZE;
        }
    }

    private void processSpectralFrame() {
        Arrays.fill(fftImaginary, 0.0);
        for (int index = 0; index < fftReal.length; index++) {
            int ringIndex = (inputHead + index) % inputRing.length;
            fftReal[index] = inputRing[ringIndex] * analysisWindow[index];
        }
        VoiceProcessingPipeline.fft(fftReal, fftImaginary, false);
        double floorPowerRatio = VoiceProcessingPipeline.FLOOR_GAIN
                * VoiceProcessingPipeline.FLOOR_GAIN;
        for (int index = 0; index < fftReal.length; index++) {
            double power = fftReal[index] * fftReal[index]
                    + fftImaginary[index] * fftImaginary[index];
            if (power == 0.0) {
                continue;
            }
            double residual = Math.max(power - VoiceProcessingPipeline.ALPHA * noisePower[index],
                    floorPowerRatio * power);
            double gain = Math.sqrt(residual / power);
            fftReal[index] *= gain;
            fftImaginary[index] *= gain;
        }
        VoiceProcessingPipeline.fft(fftReal, fftImaginary, true);
        for (int index = 0; index < fftReal.length; index++) {
            double weight = analysisWindow[index];
            overlap[index] += fftReal[index] * weight;
            normalization[index] += weight * weight;
        }
        for (int index = 0; index < VoiceProcessingPipeline.HOP_SIZE; index++) {
            double divisor = normalization[index];
            double value = divisor > 1e-12 ? overlap[index] / divisor : 0.0;
            short quantized = quantizeOne(value * VoiceProcessingPipeline.FIXED_GAIN);
            spectralSamplesSeen++;
            if (spectralSamplesSeen > VoiceProcessingPipeline.FFT_SIZE / 2
                    && totalOutputSamples + gainFrameCount < totalInputSamples) {
                gainFrame[gainFrameCount++] = quantized;
                if (gainFrameCount == gainFrame.length) {
                    applyGainFrame(gainFrameCount);
                    gainFrameCount = 0;
                }
            }
        }
        System.arraycopy(overlap, VoiceProcessingPipeline.HOP_SIZE, overlap, 0,
                overlap.length - VoiceProcessingPipeline.HOP_SIZE);
        Arrays.fill(overlap, overlap.length - VoiceProcessingPipeline.HOP_SIZE,
                overlap.length, 0.0);
        System.arraycopy(normalization, VoiceProcessingPipeline.HOP_SIZE, normalization, 0,
                normalization.length - VoiceProcessingPipeline.HOP_SIZE);
        Arrays.fill(normalization, normalization.length - VoiceProcessingPipeline.HOP_SIZE,
                normalization.length, 0.0);
    }

    private void applyGainFrame(int length) {
        double frameRms = VoiceProcessingPipeline.rms(gainFrame, 0, length);
        int framePeak = 0;
        for (int index = 0; index < length; index++) {
            framePeak = Math.max(framePeak, Math.abs((int) gainFrame[index]));
        }
        double desiredGain = VoiceProcessingPipeline.INACTIVE_GAIN;
        if (frameRms >= noiseRms * VoiceProcessingPipeline.ACTIVITY_RATIO && frameRms > 0.0) {
            desiredGain = Math.min(VoiceProcessingPipeline.MAXIMUM_GAIN,
                    Math.max(1.0, VoiceProcessingPipeline.TARGET_RMS / frameRms));
            activeFrames++;
        }
        if (framePeak > 0) {
            desiredGain = Math.min(desiredGain, VoiceProcessingPipeline.PEAK_LIMIT / framePeak);
        }
        desiredGain = Math.max(0.0, desiredGain);
        double smoothing = desiredGain > currentGain
                ? VoiceProcessingPipeline.ATTACK_SMOOTHING
                : VoiceProcessingPipeline.RELEASE_SMOOTHING;
        currentGain += smoothing * (desiredGain - currentGain);
        maximumGain = Math.max(maximumGain, currentGain);
        gainDbSum += 20.0 * Math.log10(currentGain);
        gainCount++;
        int denominator = Math.max(1, length - 1);
        for (int index = 0; index < length; index++) {
            double interpolation = (double) index / denominator;
            double gain = previousGain + (currentGain - previousGain) * interpolation;
            int value = (int) Math.round(gainFrame[index] * gain);
            if (value > 32767) {
                value = 32767;
                clippedSamples++;
            } else if (value < -32768) {
                value = -32768;
                clippedSamples++;
            }
            addOutput((short) value);
            totalOutputSamples++;
        }
        previousGain = currentGain;
    }

    private static short quantizeOne(double value) {
        int rounded = (int) Math.round(value);
        rounded = Math.max(-32768, Math.min(32767, rounded));
        return (short) rounded;
    }

    private void beginOutput(short[] output, int destinationOffset, int maximumOutput) {
        if (outputBuffer != null) {
            throw new IllegalStateException("stream_output_reentrant");
        }
        if (destinationOffset < 0 || maximumOutput < 0
                || destinationOffset + maximumOutput > output.length) {
            throw new IllegalArgumentException("stream_output_too_small");
        }
        outputBuffer = output;
        outputOffset = destinationOffset;
        outputSize = 0;
        outputLimit = maximumOutput;
    }

    private void addOutput(short value) {
        if (outputSize >= outputLimit) {
            throw new IllegalStateException("stream_output_overflow");
        }
        outputBuffer[outputOffset + outputSize++] = value;
    }

    private int endOutput() {
        int written = outputSize;
        outputBuffer = null;
        outputOffset = 0;
        outputSize = 0;
        outputLimit = 0;
        return written;
    }

    static final class Stats {
        final long inputSamples;
        final long outputSamples;
        final int activeFrames;
        final int clippedSamples;
        final double maximumGainDb;
        final double meanGainDb;
        final int boundedStateSamples;
        final int workspaceElements;

        Stats(long inputSamples, long outputSamples, int activeFrames, int clippedSamples,
                double maximumGainDb, double meanGainDb, int boundedStateSamples,
                int workspaceElements) {
            this.inputSamples = inputSamples;
            this.outputSamples = outputSamples;
            this.activeFrames = activeFrames;
            this.clippedSamples = clippedSamples;
            this.maximumGainDb = maximumGainDb;
            this.meanGainDb = meanGainDb;
            this.boundedStateSamples = boundedStateSamples;
            this.workspaceElements = workspaceElements;
        }
    }
}
