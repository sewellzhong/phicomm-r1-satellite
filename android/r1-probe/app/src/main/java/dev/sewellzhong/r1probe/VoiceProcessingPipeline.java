package dev.sewellzhong.r1probe;

final class VoiceProcessingPipeline {
    static final int FFT_SIZE = 512;
    static final int HOP_SIZE = 128;
    static final int FRAME_SAMPLES = 320;
    static final double ALPHA = 1.2;
    static final double FLOOR_GAIN = 0.25;
    static final double FIXED_GAIN = 7.943282347242816; // +18 dB
    static final double ACTIVITY_RATIO = 2.0;
    static final double TARGET_RMS = 32768.0 * 0.039810717055349734; // -28 dBFS
    static final double MAXIMUM_GAIN = 7.943282347242816; // +18 dB
    static final double PEAK_LIMIT = 32768.0 * 0.8912509381337456; // -1 dBFS
    static final double INACTIVE_GAIN = 1.0 / FIXED_GAIN; // Cancel the fixed +18 dB on silence.
    static final double ATTACK_SMOOTHING = 0.65;
    static final double RELEASE_SMOOTHING = 0.25;

    private VoiceProcessingPipeline() {
    }

    static Result process(short[] noise, short[] input) {
        long startedAt = System.nanoTime();
        double[] analysisWindow = window();
        double[] noisePower = noiseProfile(noise, analysisWindow);
        short[] balancedNoise = quantize(denoise(noise, noisePower, analysisWindow), FIXED_GAIN);
        short[] balancedInput = quantize(denoise(input, noisePower, analysisWindow), FIXED_GAIN);
        AdaptiveResult adaptive = adaptiveGain(balancedNoise, balancedInput);
        long elapsedNanos = System.nanoTime() - startedAt;
        return new Result(adaptive.samples, elapsedNanos, adaptive.activeFrames,
                adaptive.maximumGainDb, adaptive.meanGainDb, adaptive.clippedSamples);
    }

    static double[] noiseProfile(short[] noise, double[] analysisWindow) {
        double[] filtered = highPass(noise);
        double[] padded = pad(filtered);
        double[] accumulated = new double[FFT_SIZE];
        int count = 0;
        for (int offset = 0; offset + FFT_SIZE <= padded.length; offset += HOP_SIZE) {
            double[] real = new double[FFT_SIZE];
            double[] imaginary = new double[FFT_SIZE];
            for (int index = 0; index < FFT_SIZE; index++) {
                real[index] = padded[offset + index] * analysisWindow[index];
            }
            fft(real, imaginary, false);
            for (int index = 0; index < FFT_SIZE; index++) {
                accumulated[index] += real[index] * real[index] + imaginary[index] * imaginary[index];
            }
            count++;
        }
        if (count == 0) {
            throw new IllegalArgumentException("noise_sample_too_short");
        }
        for (int index = 0; index < accumulated.length; index++) {
            accumulated[index] /= count;
        }
        return accumulated;
    }

    static double[] denoise(short[] input, double[] noisePower, double[] analysisWindow) {
        double[] filtered = highPass(input);
        double[] padded = pad(filtered);
        double[] output = new double[padded.length];
        double[] normalization = new double[padded.length];
        double floorPowerRatio = FLOOR_GAIN * FLOOR_GAIN;
        for (int offset = 0; offset + FFT_SIZE <= padded.length; offset += HOP_SIZE) {
            double[] real = new double[FFT_SIZE];
            double[] imaginary = new double[FFT_SIZE];
            for (int index = 0; index < FFT_SIZE; index++) {
                real[index] = padded[offset + index] * analysisWindow[index];
            }
            fft(real, imaginary, false);
            for (int index = 0; index < FFT_SIZE; index++) {
                double power = real[index] * real[index] + imaginary[index] * imaginary[index];
                if (power == 0.0) {
                    continue;
                }
                double residual = Math.max(power - ALPHA * noisePower[index],
                        floorPowerRatio * power);
                double gain = Math.sqrt(residual / power);
                real[index] *= gain;
                imaginary[index] *= gain;
            }
            fft(real, imaginary, true);
            for (int index = 0; index < FFT_SIZE; index++) {
                double weight = analysisWindow[index];
                output[offset + index] += real[index] * weight;
                normalization[offset + index] += weight * weight;
            }
        }
        double[] result = new double[filtered.length];
        int start = FFT_SIZE / 2;
        for (int index = 0; index < result.length; index++) {
            double divisor = normalization[start + index];
            result[index] = divisor > 1e-12 ? output[start + index] / divisor : 0.0;
        }
        return result;
    }

    private static AdaptiveResult adaptiveGain(short[] noise, short[] input) {
        double noiseRms = rms(noise, 0, noise.length);
        double activityThreshold = noiseRms * ACTIVITY_RATIO;
        double currentGain = INACTIVE_GAIN;
        double previousGain = INACTIVE_GAIN;
        int activeFrames = 0;
        int clippedSamples = 0;
        double maximumGain = INACTIVE_GAIN;
        double gainDbSum = 0.0;
        int gainCount = 0;
        short[] result = new short[input.length];
        for (int offset = 0; offset < input.length; offset += FRAME_SAMPLES) {
            int length = Math.min(FRAME_SAMPLES, input.length - offset);
            double frameRms = rms(input, offset, length);
            int framePeak = 0;
            for (int index = 0; index < length; index++) {
                framePeak = Math.max(framePeak, Math.abs((int) input[offset + index]));
            }
            double desiredGain = INACTIVE_GAIN;
            if (frameRms >= activityThreshold && frameRms > 0.0) {
                desiredGain = Math.min(MAXIMUM_GAIN, Math.max(1.0, TARGET_RMS / frameRms));
                activeFrames++;
            }
            if (framePeak > 0) {
                desiredGain = Math.min(desiredGain, PEAK_LIMIT / framePeak);
            }
            desiredGain = Math.max(0.0, desiredGain);
            double smoothing = desiredGain > currentGain
                    ? ATTACK_SMOOTHING : RELEASE_SMOOTHING;
            currentGain += smoothing * (desiredGain - currentGain);
            maximumGain = Math.max(maximumGain, currentGain);
            gainDbSum += 20.0 * Math.log10(currentGain);
            gainCount++;
            int denominator = Math.max(1, length - 1);
            for (int index = 0; index < length; index++) {
                double interpolation = (double) index / denominator;
                double gain = previousGain + (currentGain - previousGain) * interpolation;
                int value = (int) Math.round(input[offset + index] * gain);
                if (value > 32767) {
                    value = 32767;
                    clippedSamples++;
                } else if (value < -32768) {
                    value = -32768;
                    clippedSamples++;
                }
                result[offset + index] = (short) value;
            }
            previousGain = currentGain;
        }
        return new AdaptiveResult(result, activeFrames, 20.0 * Math.log10(maximumGain),
                gainCount == 0 ? 0.0 : gainDbSum / gainCount, clippedSamples);
    }

    private static double[] highPass(short[] input) {
        double[] output = new double[input.length];
        double previousInput = 0.0;
        double previousOutput = 0.0;
        for (int index = 0; index < input.length; index++) {
            double filtered = input[index] - previousInput + 0.995 * previousOutput;
            output[index] = filtered;
            previousInput = input[index];
            previousOutput = filtered;
        }
        return output;
    }

    private static double[] pad(double[] input) {
        double[] padded = new double[FFT_SIZE / 2 + input.length + FFT_SIZE];
        System.arraycopy(input, 0, padded, FFT_SIZE / 2, input.length);
        return padded;
    }

    static double[] window() {
        double[] result = new double[FFT_SIZE];
        for (int index = 0; index < FFT_SIZE; index++) {
            result[index] = Math.sqrt(0.5 - 0.5 * Math.cos(2.0 * Math.PI * index / FFT_SIZE));
        }
        return result;
    }

    static short[] quantize(double[] input, double gain) {
        short[] result = new short[input.length];
        for (int index = 0; index < input.length; index++) {
            int value = (int) Math.round(input[index] * gain);
            value = Math.max(-32768, Math.min(32767, value));
            result[index] = (short) value;
        }
        return result;
    }

    static double rms(short[] input, int offset, int length) {
        if (length == 0) {
            return 0.0;
        }
        double sum = 0.0;
        for (int index = 0; index < length; index++) {
            double value = input[offset + index];
            sum += value * value;
        }
        return Math.sqrt(sum / length);
    }

    static void fft(double[] real, double[] imaginary, boolean inverse) {
        int size = real.length;
        for (int source = 1, target = 0; source < size; source++) {
            int bit = size >> 1;
            while ((target & bit) != 0) {
                target ^= bit;
                bit >>= 1;
            }
            target ^= bit;
            if (source < target) {
                double temporary = real[source];
                real[source] = real[target];
                real[target] = temporary;
                temporary = imaginary[source];
                imaginary[source] = imaginary[target];
                imaginary[target] = temporary;
            }
        }
        for (int length = 2; length <= size; length <<= 1) {
            double angle = (inverse ? 2.0 : -2.0) * Math.PI / length;
            double rootReal = Math.cos(angle);
            double rootImaginary = Math.sin(angle);
            for (int start = 0; start < size; start += length) {
                double factorReal = 1.0;
                double factorImaginary = 0.0;
                int half = length / 2;
                for (int offset = 0; offset < half; offset++) {
                    int evenIndex = start + offset;
                    int oddIndex = evenIndex + half;
                    double oddReal = real[oddIndex] * factorReal
                            - imaginary[oddIndex] * factorImaginary;
                    double oddImaginary = real[oddIndex] * factorImaginary
                            + imaginary[oddIndex] * factorReal;
                    double evenReal = real[evenIndex];
                    double evenImaginary = imaginary[evenIndex];
                    real[evenIndex] = evenReal + oddReal;
                    imaginary[evenIndex] = evenImaginary + oddImaginary;
                    real[oddIndex] = evenReal - oddReal;
                    imaginary[oddIndex] = evenImaginary - oddImaginary;
                    double nextFactorReal = factorReal * rootReal - factorImaginary * rootImaginary;
                    factorImaginary = factorReal * rootImaginary + factorImaginary * rootReal;
                    factorReal = nextFactorReal;
                }
            }
        }
        if (inverse) {
            for (int index = 0; index < size; index++) {
                real[index] /= size;
                imaginary[index] /= size;
            }
        }
    }

    static final class Result {
        final short[] samples;
        final long elapsedNanos;
        final int activeFrames;
        final double maximumGainDb;
        final double meanGainDb;
        final int clippedSamples;

        Result(short[] samples, long elapsedNanos, int activeFrames, double maximumGainDb,
                double meanGainDb, int clippedSamples) {
            this.samples = samples;
            this.elapsedNanos = elapsedNanos;
            this.activeFrames = activeFrames;
            this.maximumGainDb = maximumGainDb;
            this.meanGainDb = meanGainDb;
            this.clippedSamples = clippedSamples;
        }
    }

    private static final class AdaptiveResult {
        final short[] samples;
        final int activeFrames;
        final double maximumGainDb;
        final double meanGainDb;
        final int clippedSamples;

        AdaptiveResult(short[] samples, int activeFrames, double maximumGainDb,
                double meanGainDb, int clippedSamples) {
            this.samples = samples;
            this.activeFrames = activeFrames;
            this.maximumGainDb = maximumGainDb;
            this.meanGainDb = meanGainDb;
            this.clippedSamples = clippedSamples;
        }
    }
}
