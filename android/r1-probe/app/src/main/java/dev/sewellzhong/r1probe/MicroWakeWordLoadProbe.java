package dev.sewellzhong.r1probe;

import android.content.res.AssetManager;

import org.tensorflow.lite.DataType;
import org.tensorflow.lite.Interpreter;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** API 22 smoke test for the exact microfrontend plus quantized streaming model path. */
final class MicroWakeWordLoadProbe {
    private static final String MODEL = "alexa_microwakeword.tflite";

    static final class Result {
        final String inputShape;
        final String outputShape;
        final int frontendFrames;
        final int inferenceCount;
        final int lastScore;
        final long maxInferenceMicros;

        Result(String inputShape, String outputShape, int frontendFrames,
                int inferenceCount, int lastScore, long maxInferenceMicros) {
            this.inputShape = inputShape;
            this.outputShape = outputShape;
            this.frontendFrames = frontendFrames;
            this.inferenceCount = inferenceCount;
            this.lastScore = lastScore;
            this.maxInferenceMicros = maxInferenceMicros;
        }
    }

    static final class ScoreResult {
        final int inferenceCount;
        final int maximumScore;
        final long maxInferenceMicros;

        ScoreResult(int inferenceCount, int maximumScore, long maxInferenceMicros) {
            this.inferenceCount = inferenceCount;
            this.maximumScore = maximumScore;
            this.maxInferenceMicros = maxInferenceMicros;
        }
    }

    private MicroWakeWordLoadProbe() {
    }

    static Result loadAndRun(AssetManager assets) throws Exception {
        Interpreter interpreter = null;
        MicroFrontendNative frontend = null;
        try {
            interpreter = new Interpreter(readAsset(assets, MODEL), new Interpreter.Options());
            interpreter.allocateTensors();
            int[] inputShape = interpreter.getInputTensor(0).shape();
            int[] outputShape = interpreter.getOutputTensor(0).shape();
            if (!Arrays.equals(inputShape, new int[]{1, 3, 40})
                    || interpreter.getInputTensor(0).dataType() != DataType.INT8) {
                throw new IllegalStateException("unexpected_input_tensor");
            }
            if (!Arrays.equals(outputShape, new int[]{1, 1})
                    || interpreter.getOutputTensor(0).dataType() != DataType.UINT8) {
                throw new IllegalStateException("unexpected_output_tensor");
            }

            frontend = new MicroFrontendNative();
            short[] audio = new short[160];
            byte[] feature = new byte[40];
            ByteBuffer input = ByteBuffer.allocateDirect(120).order(ByteOrder.nativeOrder());
            ByteBuffer output = ByteBuffer.allocateDirect(1).order(ByteOrder.nativeOrder());
            int frontendFrames = 0;
            int inferenceCount = 0;
            int lastScore = -1;
            long maximumNanos = 0;
            for (int chunk = 0; chunk < 40; ++chunk) {
                int count = frontend.process(audio, feature);
                if (count < 0) {
                    throw new IllegalStateException("frontend_error_" + count);
                }
                if (count == 0) {
                    continue;
                }
                input.put(feature);
                frontendFrames++;
                if (frontendFrames % 3 == 0) {
                    input.rewind();
                    output.rewind();
                    long started = System.nanoTime();
                    interpreter.run(input, output);
                    maximumNanos = Math.max(maximumNanos, System.nanoTime() - started);
                    output.rewind();
                    lastScore = output.get() & 0xff;
                    input.clear();
                    inferenceCount++;
                }
            }
            if (inferenceCount < 10) {
                throw new IllegalStateException("insufficient_streaming_inferences");
            }
            return new Result(
                    Arrays.toString(inputShape), Arrays.toString(outputShape), frontendFrames,
                    inferenceCount, lastScore, maximumNanos / 1000L);
        } finally {
            if (frontend != null) {
                frontend.close();
            }
            if (interpreter != null) {
                interpreter.close();
            }
        }
    }

    static ScoreResult score(AssetManager assets, short[] samples, int warmupInferences)
            throws Exception {
        Interpreter interpreter = null;
        MicroFrontendNative frontend = null;
        try {
            interpreter = new Interpreter(readAsset(assets, MODEL), new Interpreter.Options());
            interpreter.allocateTensors();
            if (!Arrays.equals(interpreter.getInputTensor(0).shape(), new int[]{1, 3, 40})
                    || interpreter.getInputTensor(0).dataType() != DataType.INT8
                    || !Arrays.equals(interpreter.getOutputTensor(0).shape(), new int[]{1, 1})
                    || interpreter.getOutputTensor(0).dataType() != DataType.UINT8) {
                throw new IllegalStateException("unexpected_model_tensors");
            }
            frontend = new MicroFrontendNative();
            byte[] feature = new byte[40];
            ByteBuffer input = ByteBuffer.allocateDirect(120).order(ByteOrder.nativeOrder());
            ByteBuffer output = ByteBuffer.allocateDirect(1).order(ByteOrder.nativeOrder());
            int featureFrames = 0;
            int inferences = 0;
            int maximumScore = 0;
            long maximumNanos = 0;
            for (int offset = 0; offset + 160 <= samples.length; offset += 160) {
                short[] chunk = new short[160];
                System.arraycopy(samples, offset, chunk, 0, 160);
                int count = frontend.process(chunk, feature);
                if (count < 0) {
                    throw new IllegalStateException("frontend_error_" + count);
                }
                if (count == 0) {
                    continue;
                }
                input.put(feature);
                featureFrames++;
                if (featureFrames % 3 != 0) {
                    continue;
                }
                input.rewind();
                output.rewind();
                long started = System.nanoTime();
                interpreter.run(input, output);
                maximumNanos = Math.max(maximumNanos, System.nanoTime() - started);
                output.rewind();
                int score = output.get() & 0xff;
                if (inferences >= warmupInferences) {
                    maximumScore = Math.max(maximumScore, score);
                }
                input.clear();
                inferences++;
            }
            return new ScoreResult(inferences, maximumScore, maximumNanos / 1000L);
        } finally {
            if (frontend != null) {
                frontend.close();
            }
            if (interpreter != null) {
                interpreter.close();
            }
        }
    }

    static ByteBuffer readAsset(AssetManager assets, String name) throws Exception {
        InputStream input = assets.open(name);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
        } finally {
            input.close();
        }
        byte[] bytes = output.toByteArray();
        ByteBuffer direct = ByteBuffer.allocateDirect(bytes.length).order(ByteOrder.nativeOrder());
        direct.put(bytes);
        direct.rewind();
        return direct;
    }
}
