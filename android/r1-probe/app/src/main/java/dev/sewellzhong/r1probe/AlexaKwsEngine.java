package dev.sewellzhong.r1probe;

import android.content.res.AssetManager;
import android.os.Debug;
import org.tensorflow.lite.DataType;
import org.tensorflow.lite.Interpreter;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** Single-owner streaming engine. Holds bounded buffers and never records audio. */
final class AlexaKwsEngine implements KwsEngine {
    private final ByteBuffer model;
    private Interpreter interpreter;
    private MicroFrontendNative frontend;
    private final AlexaDecision decision = new AlexaDecision();
    private final short[] chunk = new short[160];
    private final byte[] feature = new byte[40];
    private final ByteBuffer input = ByteBuffer.allocateDirect(120).order(ByteOrder.nativeOrder());
    private final ByteBuffer output = ByteBuffer.allocateDirect(1).order(ByteOrder.nativeOrder());
    private int stride;
    private long nextSample = -1;
    private long samples;
    private long wall;
    private long cpu;
    private long maximum;
    private long inferences;
    private int maximumRawScore;
    private boolean closed;

    AlexaKwsEngine(AssetManager assets) throws Exception {
        model = MicroWakeWordLoadProbe.readAsset(assets, "alexa_microwakeword.tflite");
        initialize();
    }

    private void initialize() {
        try {
            model.rewind();
            interpreter = new Interpreter(model, new Interpreter.Options().setNumThreads(1));
            interpreter.allocateTensors();
            if (!Arrays.equals(interpreter.getInputTensor(0).shape(), new int[]{1, 3, 40})
                    || interpreter.getInputTensor(0).dataType() != DataType.INT8
                    || !Arrays.equals(interpreter.getOutputTensor(0).shape(), new int[]{1, 1})
                    || interpreter.getOutputTensor(0).dataType() != DataType.UINT8
                    || interpreter.getInputTensor(0).quantizationParams().getZeroPoint() != -128
                    || Math.abs(interpreter.getInputTensor(0).quantizationParams().getScale()
                            - 0.1019607857f) > 0.000001f
                    || interpreter.getOutputTensor(0).quantizationParams().getZeroPoint() != 0
                    || interpreter.getOutputTensor(0).quantizationParams().getScale() != 1f / 256f) {
                throw new IllegalStateException("unexpected_alexa_tensors");
            }
            frontend = new MicroFrontendNative();
        } catch (RuntimeException | LinkageError e) {
            release();
            throw e;
        }
    }

    @Override public String engineId() { return "microwakeword"; }
    @Override public String modelId() { return "alexa-v2-9011a8155b04"; }

    @Override public void reset() {
        requireOpen();
        release();
        // Recreate resource variables as well as the frontend; resetVariableTensors alone
        // is not sufficient to promise a fresh state for all resource-variable models.
        initialize();
        input.clear();
        output.clear();
        decision.reset();
        stride = 0;
        nextSample = -1;
        samples = wall = cpu = maximum = inferences = 0;
        maximumRawScore = 0;
    }

    @Override public KwsDetection acceptFrame(short[] pcm, int offset, int length,
            long firstSampleIndex) {
        requireOpen();
        if (pcm == null || length != KwsConfig.FRAME_SAMPLES || offset < 0
                || offset > pcm.length - length || firstSampleIndex < 0
                || firstSampleIndex > Long.MAX_VALUE - length
                || (nextSample >= 0 && firstSampleIndex != nextSample)) {
            throw new IllegalArgumentException("invalid_or_discontinuous_pcm_frame");
        }
        long started = System.nanoTime();
        long cpuStarted = Debug.threadCpuTimeNanos();
        KwsDetection detection = KwsDetection.NONE;
        for (int part = 0; part < 2; part++) {
            System.arraycopy(pcm, offset + part * 160, chunk, 0, 160);
            int count = frontend.process(chunk, feature);
            if (count != 0 && count != 40) {
                throw new IllegalStateException("frontend_error");
            }
            if (count == 0) {
                continue;
            }
            input.put(feature);
            boolean newOutput = ++stride == 3;
            int raw = 0;
            if (newOutput) {
                input.rewind();
                output.rewind();
                interpreter.run(input, output);
                raw = output.get(0) & 0xff;
                maximumRawScore = Math.max(maximumRawScore, raw);
                inferences++;
                input.clear();
                stride = 0;
            }
            if (decision.acceptFeature(raw, newOutput)) {
                detection = new KwsDetection(true, KwsConfig.KEYWORD,
                        firstSampleIndex + (part + 1) * 160, decision.detectedScore());
            }
        }
        long elapsed = System.nanoTime() - started;
        wall += elapsed;
        cpu += Debug.threadCpuTimeNanos() - cpuStarted;
        maximum = Math.max(maximum, elapsed);
        samples += length;
        nextSample = firstSampleIndex + length;
        return detection;
    }

    long inferenceCount() { return inferences; }
    int maximumRawScore() { return maximumRawScore; }
    @Override public KwsMetrics metrics() { return new KwsMetrics(samples, wall, cpu, maximum); }

    private void requireOpen() {
        if (closed || interpreter == null || frontend == null) {
            throw new IllegalStateException("alexa_engine_closed");
        }
    }

    private void release() {
        if (frontend != null) { frontend.close(); frontend = null; }
        if (interpreter != null) { interpreter.close(); interpreter = null; }
    }

    @Override public void close() {
        release();
        closed = true;
    }
}
